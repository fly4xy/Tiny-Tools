"""Инструменты аниматора: ключи, касательные, поза, наборы костей, чистый вид при проигрывании."""
import bpy
from bpy.types import Operator
from bpy.props import IntProperty, FloatProperty, EnumProperty, StringProperty, BoolProperty
from bpy.app.handlers import persistent
from mathutils import Vector, Quaternion, Euler

from ..utils.anim_compat import get_fcurves, new_fcurve, remove_fcurve
from ..utils.action_utils import extract_bone_name
from ..utils.vertex_utils import get_mirror_group_name, group_side
from ..utils.file_utils import _pose_cache
from ..utils.animator_utils import (
    animated_targets, owner_fcurves, target_fcurves, edit_keys, scene_range, shift_key,
    get_rot_quat, set_rot_quat, lerp_matrix, world_matrix, set_world_matrix, transform_target,
    autokey, depth, set_bone_selected, flip_sign, flipped_pose,
)


def _no_curves(op):
    op.report({'WARNING'}, "No animated bones/objects selected")
    return {'CANCELLED'}


# ======================= Модальный слайдер =======================

class _BlendSlider:
    """Слайдер для блендов: клик — 100%, тянуть мышь влево/вправо — меньше/больше, ЛКМ/Enter — принять, ПКМ/Esc — отмена.
    Наследник реализует capture(context) -> bool и apply(context, factor); factor 0 должен давать исходное состояние."""
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    factor: FloatProperty(name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR')

    def execute(self, context):
        if not self.capture(context):
            return {'CANCELLED'}
        self.apply(context, self.factor)
        self.finish(context)
        return {'FINISHED'}

    def invoke(self, context, event):
        if not self.capture(context):
            return {'CANCELLED'}
        self._x0, self._f0 = event.mouse_x, self.factor
        self.apply(context, self.factor)
        self._header(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self.factor = max(0.0, min(1.0, self._f0 + (event.mouse_x - self._x0) / 300))
            self.apply(context, self.factor)
            self._header(context)
        elif event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            self._header(context, clear=True)
            self.finish(context)
            return {'FINISHED'}
        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self.apply(context, 0.0)
            self._header(context, clear=True)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _header(self, context, clear=False):
        if context.area:
            context.area.header_text_set(None if clear else
                                         f"{self.bl_label}: {round(self.factor * 100)}%   (LMB/Enter — apply, RMB/Esc — cancel)")

    def finish(self, context):
        pass


# ======================= Ключи =======================

class TT_OT_NudgeKeys(Operator):
    bl_idname = "tiny_tools.nudge_keys"
    bl_label = "Nudge Keys"
    bl_description = ("Move selected keys (or keys on the current frame) of the selected bones/objects by N frames. "
                      "Keys already sitting at the destination are overwritten")
    bl_options = {'REGISTER', 'UNDO'}

    frames: IntProperty(name="Frames", default=1)

    def execute(self, context):
        curves = target_fcurves(context)
        moving, by_selection = edit_keys(curves, context.scene.frame_current)
        if not moving:
            self.report({'WARNING'}, "No keys to move")
            return {'CANCELLED'}
        dx = self.frames
        for fc, xs in moving.items():
            dest = {round(x + dx) for x in xs}
            # ключи-препятствия удаляем по индексу с конца: удаление инвалидирует ссылки на keyframe_points
            for i in reversed(range(len(fc.keyframe_points))):
                k = fc.keyframe_points[i]
                if round(k.co.x) in dest and not any(abs(k.co.x - x) < 1e-4 for x in xs):
                    fc.keyframe_points.remove(k)
            for k in fc.keyframe_points:
                if any(abs(k.co.x - x) < 1e-4 for x in xs):
                    shift_key(k, dx)
            fc.update()
        if not by_selection:
            context.scene.frame_current += dx
        return {'FINISHED'}


class TT_OT_BakeStep(Operator):
    bl_idname = "tiny_tools.bake_step"
    bl_label = "Bake on Step"
    bl_description = ("Bake the visual motion of the selected bones/objects with a key every N frames over the scene "
                      "(or preview) range. Baked keys are marked as 'Generated' (own color in the Dope Sheet)")
    bl_options = {'REGISTER', 'UNDO'}

    step: IntProperty(name="Step", default=2, min=1, max=100)
    stepped: BoolProperty(name="Stepped", default=True)

    def execute(self, context):
        targets = animated_targets(context)
        if not targets:
            return _no_curves(self)
        start, end = scene_range(context.scene)
        pose = context.mode == 'POSE'
        bpy.ops.nla.bake(frame_start=start, frame_end=end, step=self.step, only_selected=True,
                         visual_keying=True, clear_constraints=False, clear_parents=False,
                         use_current_action=True, clean_curves=False,
                         bake_types={'POSE'} if pose else {'OBJECT'})
        grid = set(range(start, end + 1, self.step))
        for fc in target_fcurves(context):
            # между шагами не должно остаться старых ключей
            for i in reversed(range(len(fc.keyframe_points))):
                k = fc.keyframe_points[i]
                if start <= k.co.x <= end and round(k.co.x) not in grid:
                    fc.keyframe_points.remove(k)
            for k in fc.keyframe_points:
                if start <= k.co.x <= end:
                    k.type = 'GENERATED'
                    if self.stepped:
                        k.interpolation = 'CONSTANT'
            fc.update()
        self.report({'INFO'}, f"Baked {start}-{end} every {self.step} frame(s)")
        return {'FINISHED'}


class TT_OT_ShareKeyTimes(Operator):
    bl_idname = "tiny_tools.share_key_times"
    bl_label = "Share Key Times"
    bl_description = ("Key the other selected bones/objects on the key times of the active one, keeping their motion. "
                      "Optionally remove their other keys")
    bl_options = {'REGISTER', 'UNDO'}

    remove_others: BoolProperty(name="Remove Other Keys", default=False)

    def execute(self, context):
        if context.mode == 'POSE':
            act = context.active_pose_bone
            src = (act.id_data, act.name) if act else None
        else:
            src = (context.active_object, None) if context.active_object else None
        others = [t for t in animated_targets(context) if t != src]
        if not src or not others:
            self.report({'WARNING'}, "Select targets and make the source active")
            return {'CANCELLED'}
        times = sorted({round(k.co.x) for fc in owner_fcurves(*src) for k in fc.keyframe_points})
        if not times:
            self.report({'WARNING'}, "Active item has no keys")
            return {'CANCELLED'}
        for owner, bone in others:
            for fc in owner_fcurves(owner, bone):
                values = {t: fc.evaluate(t) for t in times}  # до вставки: новые ключи меняют кривую
                existing = {round(k.co.x) for k in fc.keyframe_points}
                for t in times:
                    if t not in existing:
                        fc.keyframe_points.insert(t, values[t])
                if self.remove_others:
                    for i in reversed(range(len(fc.keyframe_points))):
                        if round(fc.keyframe_points[i].co.x) not in values:
                            fc.keyframe_points.remove(fc.keyframe_points[i])
                fc.update()
        self.report({'INFO'}, f"Shared {len(times)} key times to {len(others)} item(s)")
        return {'FINISHED'}


class TT_OT_TimeOffset(Operator):
    bl_idname = "tiny_tools.time_offset"
    bl_label = "Time Offset"
    bl_description = ("Shift the animation of each selected bone/object in time. With Cascade every next item in the "
                      "hierarchy (parent to child) is shifted more — overlap for tails, chains, crowds")
    bl_options = {'REGISTER', 'UNDO'}

    offset: IntProperty(name="Offset", default=0)
    cascade: IntProperty(name="Cascade", default=2)

    def execute(self, context):
        targets = sorted(animated_targets(context), key=lambda t: (depth(*t), t[1] or t[0].name))
        if not targets:
            return _no_curves(self)
        for i, (owner, bone) in enumerate(targets):
            dx = self.offset + i * self.cascade
            if dx:
                for fc in owner_fcurves(owner, bone):
                    for k in fc.keyframe_points:
                        shift_key(k, dx)
                    fc.update()
        return {'FINISHED'}


class TT_OT_ReverseAnimation(Operator):
    bl_idname = "tiny_tools.reverse_animation"
    bl_label = "Reverse Animation"
    bl_description = "Play the keys of the selected bones/objects backwards inside the scene (or preview) range"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        curves = target_fcurves(context)
        if not curves:
            return _no_curves(self)
        start, end = scene_range(context.scene)
        pivot = start + end
        ease_flip = {'EASE_IN': 'EASE_OUT', 'EASE_OUT': 'EASE_IN'}
        for fc in curves:
            keys = sorted((k for k in fc.keyframe_points if start <= k.co.x <= end), key=lambda k: k.co.x)
            if not keys:
                continue
            if all(k.interpolation == 'CONSTANT' for k in keys):
                # Ступенчатая кривая: ключ держит значение до следующего, поэтому он переезжает на кадр
                # pivot + 1 - (кадр следующего ключа) — каждая ступенька точно ложится на свои кадры
                times = [k.co.x for k in keys] + [end + 1]
                for i, k in enumerate(keys):
                    shift_key(k, pivot + 1 - times[i + 1] - k.co.x)
                fc.update()
                continue
            # интерполяция живёт на левом ключе сегмента: после разворота сегмент (i, i+1) начинается с ключа i+1
            seg = [(k.interpolation, ease_flip.get(k.easing, k.easing)) for k in keys]
            data = [(k.co.copy(), k.handle_left.copy(), k.handle_right.copy(), k.handle_left_type, k.handle_right_type)
                    for k in keys]
            for i, k in enumerate(keys):
                co, hl, hr, tl, tr = data[i]
                k.handle_left_type, k.handle_right_type = 'FREE', 'FREE'
                k.co.x = pivot - co.x
                k.handle_left = (pivot - hr.x, hr.y)
                k.handle_right = (pivot - hl.x, hl.y)
                k.handle_left_type, k.handle_right_type = tr, tl
                k.interpolation, k.easing = seg[i - 1] if i > 0 else seg[-1]
            fc.update()
        return {'FINISHED'}


# ======================= Касательные =======================

def flow_slopes(xs, ys):
    """Наклоны естественного кубического сплайна (непрерывна 2-я производная) — самая плавная кривая через ключи."""
    n = len(xs)
    if n < 2:
        return [0.0] * n
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    if n == 2:
        return [d[0], d[0]]
    # прогонка для вторых производных M, M0 = Mn = 0
    a, b, c, r = [0.0] * n, [1.0] * n, [0.0] * n, [0.0] * n
    for i in range(1, n - 1):
        a[i], b[i], c[i], r[i] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i], 6 * (d[i] - d[i - 1])
    for i in range(1, n):
        m = a[i] / b[i - 1]
        b[i] -= m * c[i - 1]
        r[i] -= m * r[i - 1]
    M = [0.0] * n
    M[-1] = r[-1] / b[-1]
    for i in range(n - 2, -1, -1):
        M[i] = (r[i] - c[i] * M[i + 1]) / b[i]
    slopes = [d[i] - h[i] * (2 * M[i] + M[i + 1]) / 6 for i in range(n - 1)]
    slopes.append(d[-1] + h[-1] * (M[-2] + 2 * M[-1]) / 6)
    return slopes


TANGENTS = [('AUTO', "Auto", "Blender Auto (spline)"),
            ('AUTO_CLAMPED', "Clamped", "Auto Clamped: no overshoot"),
            ('LINEAR', "Linear", "Straight lines to the neighbor keys"),
            ('FLAT', "Flat", "Horizontal tangents"),
            ('FLOW', "Flow", "Smoothest curve through the keys: inherits momentum from neighbor poses")]


class TT_OT_BlendTangents(_BlendSlider, Operator):
    bl_idname = "tiny_tools.blend_tangents"
    bl_label = "Blend Tangents"
    bl_description = ("Blend the tangents of the selected keys (or keys on the current frame) towards a tangent type. "
                      "Click = 100%, drag the mouse to blend, LMB to apply")

    tangent: EnumProperty(name="Tangent", items=TANGENTS, default='FLOW')

    def capture(self, context):
        curves = target_fcurves(context)
        sel, _ = edit_keys(curves, context.scene.frame_current)
        self._data = []
        for fc, xs in sel.items():
            kps = fc.keyframe_points
            orig = [(k.handle_left_type, k.handle_right_type, k.handle_left.copy(), k.handle_right.copy(), k.interpolation)
                    for k in kps]
            idx = [i for i, k in enumerate(kps) if any(abs(k.co.x - x) < 1e-4 for x in xs)]
            target = self._targets(fc, idx, orig)
            self._data.append((fc, orig, idx, target))
        if not self._data:
            self.report({'WARNING'}, "No keys selected")
        return bool(self._data)

    def _targets(self, fc, idx, orig):
        kps = fc.keyframe_points
        co = [k.co.copy() for k in kps]
        if self.tangent in {'AUTO', 'AUTO_CLAMPED'}:
            for i in idx:
                kps[i].handle_left_type = kps[i].handle_right_type = self.tangent
            fc.update()
            target = {i: (kps[i].handle_left.copy(), kps[i].handle_right.copy()) for i in idx}
            for k, (tl, tr, hl, hr, _) in zip(kps, orig):
                k.handle_left_type, k.handle_right_type = tl, tr
                k.handle_left, k.handle_right = hl, hr
            return target
        slopes = flow_slopes([c.x for c in co], [c.y for c in co]) if self.tangent == 'FLOW' else None
        target = {}
        for i in idx:
            p = co[i]
            dl = (p.x - co[i - 1].x) / 3 if i > 0 else (orig[i][3].x - p.x or 1.0)
            dr = (co[i + 1].x - p.x) / 3 if i < len(co) - 1 else (p.x - orig[i][2].x or 1.0)
            if self.tangent == 'FLAT':
                sl = sr = 0.0
            elif self.tangent == 'FLOW':
                sl = sr = slopes[i]
            else:  # LINEAR: прямо на соседей, крайние — продолжают единственный сегмент
                sl = (p.y - co[i - 1].y) / (p.x - co[i - 1].x) if i > 0 else None
                sr = (co[i + 1].y - p.y) / (co[i + 1].x - p.x) if i < len(co) - 1 else None
                sl = sr if sl is None else sl
                sr = sl if sr is None else sr
                sl, sr = sl or 0.0, sr or 0.0
            target[i] = (Vector((p.x - dl, p.y - sl * dl)), Vector((p.x + dr, p.y + sr * dr)))
        return target

    def apply(self, context, f):
        for fc, orig, idx, target in self._data:
            kps = fc.keyframe_points
            for i in idx:
                tl, tr, hl, hr, interp = orig[i]
                k = kps[i]
                if f == 0.0:
                    k.handle_left_type, k.handle_right_type, k.interpolation = tl, tr, interp
                    k.handle_left, k.handle_right = hl, hr
                    continue
                k.interpolation = 'BEZIER'
                k.handle_left_type = k.handle_right_type = 'FREE'
                k.handle_left = hl.lerp(target[i][0], f)
                k.handle_right = hr.lerp(target[i][1], f)
            fc.update()


# ======================= Поза =======================

def _selected_or_all_bones(context):
    arm = context.active_object
    if not arm or arm.type != 'ARMATURE':
        return None, []
    names = [pb.name for pb in (context.selected_pose_bones or []) if pb.id_data == arm] if context.mode == 'POSE' else []
    return arm, names or [pb.name for pb in arm.pose.bones]


class TT_OT_ResetPose(Operator):
    bl_idname = "tiny_tools.reset_pose"
    bl_label = "Reset Pose"
    bl_description = ("Reset the selected bones (all bones if none selected) of the active armature to the rest pose, "
                      "including custom properties with a default value")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm, names = _selected_or_all_bones(context)
        if not arm:
            self.report({'WARNING'}, "Active object is not an armature")
            return {'CANCELLED'}
        for name in names:
            pb = arm.pose.bones[name]
            pb.location = (0, 0, 0)
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.rotation_euler = (0, 0, 0)
            pb.rotation_axis_angle = (0, 0, 1, 0)
            pb.scale = (1, 1, 1)
            props = []
            for key in list(pb.keys()):
                try:
                    default = pb.id_properties_ui(key).as_dict().get("default")
                except TypeError:  # не числовое свойство — без UI-данных
                    continue
                if default is not None:
                    pb[key] = default
                    props.append(f'["{key}"]')
            autokey(context, arm, name)
            if props:
                autokey(context, arm, name, props)
        return {'FINISHED'}


class TT_OT_MirrorPose(Operator):
    bl_idname = "tiny_tools.mirror_pose"
    bl_label = "Mirror Pose"
    bl_description = ("Mirror the pose between the L/R bones of the active armature (selected pairs, or all). "
                      "Swap also flips the center bones")
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(name="Direction", items=[('L_TO_R', "L > R", ""), ('R_TO_L', "R > L", ""), ('SWAP', "Swap", "")])

    def execute(self, context):
        arm, names = _selected_or_all_bones(context)
        if not arm:
            self.report({'WARNING'}, "Active object is not an armature")
            return {'CANCELLED'}
        pairs = _bone_pairs(arm, names, self.direction)
        # для Swap обе стороны читаем до записи
        saved = {n: (pb.location.copy(), get_rot_quat(pb), pb.scale.copy())
                 for n, pb in ((n, arm.pose.bones[n]) for pair in pairs for n in pair)}
        for src, dst in pairs:
            loc, q, scale = flipped_pose(*saved[src])
            pb = arm.pose.bones[dst]
            pb.location, pb.scale = loc, scale
            set_rot_quat(pb, q)
            autokey(context, arm, dst)
        self.report({'INFO'}, f"Mirrored {len(pairs)} bone(s)")
        return {'FINISHED'}


def _bone_pairs(arm, names, direction):
    """[(источник, приёмник)] по L/R-суффиксам; Swap даёт обе стороны и центральные кости сами в себя."""
    pairs, seen = [], set()
    for n in names:
        mirror = get_mirror_group_name(n)
        if not mirror:
            if direction == 'SWAP':
                pairs.append((n, n))
            continue
        if mirror not in arm.pose.bones:
            continue
        side = group_side(n)
        left, right = (n, mirror) if side == 'L' else (mirror, n)
        if (left, right) in seen:
            continue
        seen.add((left, right))
        if direction == 'L_TO_R':
            pairs.append((left, right))
        elif direction == 'R_TO_L':
            pairs.append((right, left))
        else:
            pairs += [(left, right), (right, left)]
    return pairs


class TT_OT_MirrorAnimation(Operator):
    bl_idname = "tiny_tools.mirror_animation"
    bl_label = "Mirror Animation"
    bl_description = ("Mirror the animation curves between L/R bones of the active armature's action "
                      "(selected pairs, or all). Swap also flips the center bones — e.g. turn a left turn into a right one")
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(name="Direction", items=[('L_TO_R', "L > R", ""), ('R_TO_L', "R > L", ""), ('SWAP', "Swap", "")])

    def execute(self, context):
        arm, names = _selected_or_all_bones(context)
        action = arm.animation_data.action if arm and arm.animation_data else None
        if not action:
            self.report({'WARNING'}, "Active armature has no animation")
            return {'CANCELLED'}
        pairs = _bone_pairs(arm, names, self.direction)
        by_bone = {}
        for fc in get_fcurves(action):
            by_bone.setdefault(extract_bone_name(fc.data_path), []).append(fc)
        # сначала копируем исходные данные (для Swap источник и приёмник — одни и те же кривые)
        copies = []
        for src, dst in pairs:
            for fc in by_bone.get(src, []):
                prop = fc.data_path.rsplit(".", 1)[-1]
                sign = flip_sign(prop, fc.array_index)
                keys = [(k.co.copy(), k.handle_left.copy(), k.handle_right.copy(), k.handle_left_type,
                         k.handle_right_type, k.interpolation, k.easing, k.type) for k in fc.keyframe_points]
                path = fc.data_path.replace(f'pose.bones["{src}"]', f'pose.bones["{dst}"]', 1)
                copies.append((path, fc.array_index, dst, sign, keys, fc.extrapolation))
        dst_bones = {dst for _, dst in pairs}
        for fc in [fc for b in dst_bones for fc in by_bone.get(b, [])]:
            remove_fcurve(action, fc)
        for path, index, dst, sign, keys, extrap in copies:
            fc = new_fcurve(action, path, index=index, group=dst)
            fc.extrapolation = extrap
            fc.keyframe_points.add(len(keys))
            for k, (co, hl, hr, tl, tr, interp, easing, ktype) in zip(fc.keyframe_points, keys):
                k.co = (co.x, co.y * sign)
                k.handle_left_type, k.handle_right_type = tl, tr
                k.handle_left = (hl.x, hl.y * sign)
                k.handle_right = (hr.x, hr.y * sign)
                k.interpolation, k.easing, k.type = interp, easing, ktype
            fc.update()
        self.report({'INFO'}, f"Mirrored animation of {len(pairs)} bone(s)")
        return {'FINISHED'}


class TT_OT_BlendToBuffer(_BlendSlider, Operator):
    bl_idname = "tiny_tools.blend_to_buffer"
    bl_label = "Blend to Buffer"
    bl_description = ("Blend the selected bones (all if none selected) of the active armature towards the pose saved "
                      "with Copy Pose. Click = 100%, drag to blend")

    def capture(self, context):
        arm, names = _selected_or_all_bones(context)
        buf = _pose_cache.get("copied_pose", {}).get("bones", {})
        self._arm, self._data = arm, []
        for n in names if arm else []:
            if n not in buf:
                continue
            pb, b = arm.pose.bones[n], buf[n]
            if b.get("rotation_quaternion"):
                tq = Quaternion(b["rotation_quaternion"])
            else:
                tq = Euler(b["rotation_euler"], b["rotation_mode"] if b["rotation_mode"] in
                           {'XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'} else 'XYZ').to_quaternion()
            self._data.append((n, (pb.location.copy(), get_rot_quat(pb), pb.scale.copy()),
                               (Vector(b["location"]), tq, Vector(b["scale"]))))
        if not self._data:
            self.report({'WARNING'}, "Pose buffer is empty — use Copy Pose first")
        return bool(self._data)

    def apply(self, context, f):
        for n, (l0, q0, s0), (l1, q1, s1) in self._data:
            pb = self._arm.pose.bones[n]
            pb.location = l0.lerp(l1, f)
            set_rot_quat(pb, q0.slerp(q1, f))
            pb.scale = s0.lerp(s1, f)

    def finish(self, context):
        for n, *_ in self._data:
            autokey(context, self._arm, n)


class TT_OT_BlendToActive(_BlendSlider, Operator):
    bl_idname = "tiny_tools.blend_to_active"
    bl_label = "Blend to Active"
    bl_description = ("Blend the selected bones/objects towards the active one: World — match its world transform "
                      "(align), Local — copy its transform channels. Click = 100%, drag to blend")

    space: EnumProperty(name="Space", items=[('WORLD', "World", "Align in world space"),
                                             ('LOCAL', "Local", "Copy local transform channels")])

    def capture(self, context):
        if context.mode == 'POSE':
            act = context.active_pose_bone
            src = (act.id_data, act.name) if act else None
        else:
            src = (context.active_object, None) if context.active_object else None
        others = sorted((t for t in animated_targets(context) if t != src), key=lambda t: depth(*t))
        if not src or not others:
            self.report({'WARNING'}, "Select targets and make the source active")
            return False
        self._others = others
        if self.space == 'WORLD':
            self._target = world_matrix(*src)
            self._orig = [world_matrix(*t) for t in others]
        else:
            s = transform_target(*src)
            self._target = (s.location.copy(), get_rot_quat(s), s.scale.copy())
            self._orig = [(transform_target(*t).location.copy(), get_rot_quat(transform_target(*t)),
                           transform_target(*t).scale.copy()) for t in others]
        return True

    def apply(self, context, f):
        for t, orig in zip(self._others, self._orig):
            if self.space == 'WORLD':
                set_world_matrix(*t, lerp_matrix(orig, self._target, f))
                context.view_layer.update()  # дети считаются от уже сдвинутого родителя
            else:
                tt = transform_target(*t)
                tt.location = orig[0].lerp(self._target[0], f)
                set_rot_quat(tt, orig[1].slerp(self._target[1], f))
                tt.scale = orig[2].lerp(self._target[2], f)

    def finish(self, context):
        for t in self._others:
            autokey(context, *t)


class TT_OT_TempPivot(Operator):
    bl_idname = "tiny_tools.temp_pivot"
    bl_label = "Temp Pivot"
    bl_description = ("Toggle a temporary pivot: the 3D Cursor is placed at the active bone/object and becomes the "
                      "transform pivot. Move the cursor (Shift+RMB) to rotate around any point. Click again to restore")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ap = context.scene.tiny_tools_props.animator
        ts = context.scene.tool_settings
        if ap.temp_pivot_prev:
            ts.transform_pivot_point, ap.temp_pivot_prev = ap.temp_pivot_prev, ""
            return {'FINISHED'}
        if context.mode == 'POSE' and context.active_pose_bone:
            pb = context.active_pose_bone
            context.scene.cursor.location = pb.id_data.matrix_world @ pb.head
        elif context.active_object:
            context.scene.cursor.location = context.active_object.matrix_world.translation
        ap.temp_pivot_prev = ts.transform_pivot_point
        ts.transform_pivot_point = 'CURSOR'
        return {'FINISHED'}


# ======================= Наборы костей =======================

class TT_OT_SelectBoneSet(Operator):
    bl_idname = "tiny_tools.select_bone_set"
    bl_label = "Select Bone Set"
    bl_description = "Select the bones of this bone collection (Shift — add to selection)"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty()
    extend: BoolProperty(default=False, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        arm = context.active_object
        coll = arm.data.collections_all.get(self.name) if arm and arm.type == 'ARMATURE' else None
        if not coll:
            return {'CANCELLED'}
        members = {b.name for b in coll.bones}
        for pb in arm.pose.bones:
            if pb.name in members:
                set_bone_selected(pb, True)
            elif not self.extend:
                set_bone_selected(pb, False)
        return {'FINISHED'}


class TT_OT_NewBoneSet(Operator):
    bl_idname = "tiny_tools.new_bone_set"
    bl_label = "New Bone Set"
    bl_description = "Create a bone collection from the selected bones"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Name", default="Set")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        arm = context.active_object
        bones = [pb for pb in (context.selected_pose_bones or []) if pb.id_data == arm]
        if not bones:
            self.report({'WARNING'}, "Select bones in Pose Mode")
            return {'CANCELLED'}
        coll = arm.data.collections.new(self.name)
        for pb in bones:
            coll.assign(pb)
        return {'FINISHED'}


# ======================= Чистый вид при проигрывании =======================

_hidden_spaces = {}


@persistent
def _playback_pre(scene, *args):
    props = getattr(scene, "tiny_tools_props", None)
    if not props or not props.animator.clean_playback:
        return
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                sp = area.spaces.active
                _hidden_spaces[sp.as_pointer()] = (sp, sp.overlay.show_overlays, sp.show_gizmo)
                sp.overlay.show_overlays = sp.show_gizmo = False


@persistent
def _playback_post(scene, *args):
    for sp, overlays, gizmo in _hidden_spaces.values():
        try:
            sp.overlay.show_overlays, sp.show_gizmo = overlays, gizmo
        except ReferenceError:  # окно закрыли во время проигрывания
            pass
    _hidden_spaces.clear()


HANDLERS = ((bpy.app.handlers.animation_playback_pre, _playback_pre),
            (bpy.app.handlers.animation_playback_post, _playback_post))

classes = (
    TT_OT_NudgeKeys, TT_OT_BakeStep, TT_OT_ShareKeyTimes, TT_OT_TimeOffset, TT_OT_ReverseAnimation,
    TT_OT_BlendTangents, TT_OT_ResetPose, TT_OT_MirrorPose, TT_OT_MirrorAnimation, TT_OT_BlendToBuffer,
    TT_OT_BlendToActive, TT_OT_TempPivot, TT_OT_SelectBoneSet, TT_OT_NewBoneSet,
)
