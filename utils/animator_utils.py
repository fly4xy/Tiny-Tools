"""Общие помощники инструментов аниматора: цели, ключи, матрицы, повороты, отражение."""
import bpy
from mathutils import Matrix, Quaternion, Euler
from .anim_compat import get_fcurves
from .action_utils import extract_bone_name


# ---------- Цели ----------

def animated_targets(context):
    """[(владелец, имя кости | None)]: выделенные кости в Pose Mode, иначе выделенные объекты (None = весь объект)."""
    if context.mode == 'POSE':
        return [(pb.id_data, pb.name) for pb in (context.selected_pose_bones or [])]
    return [(o, None) for o in context.selected_objects]


def owner_fcurves(owner, bone=None):
    """F-кривые активного экшена владельца; для кости — только её каналы."""
    ad = owner.animation_data
    if not ad or not ad.action:
        return []
    return [fc for fc in get_fcurves(ad.action) if bone is None or extract_bone_name(fc.data_path) == bone]


def target_fcurves(context):
    """Все F-кривые выделенных костей/объектов (без повторов)."""
    seen, out = set(), []
    for owner, bone in animated_targets(context):
        for fc in owner_fcurves(owner, bone):
            if fc.as_pointer() not in seen:
                seen.add(fc.as_pointer())
                out.append(fc)
    return out


def edit_keys(fcurves, frame):
    """{fcurve: [x ключей]}: выделенные ключи, а если ни один не выделен — ключи на текущем кадре."""
    sel = {fc: [k.co.x for k in fc.keyframe_points if k.select_control_point] for fc in fcurves}
    sel = {fc: xs for fc, xs in sel.items() if xs}
    if sel:
        return sel, True
    at = {fc: [k.co.x for k in fc.keyframe_points if abs(k.co.x - frame) < 0.5] for fc in fcurves}
    return {fc: xs for fc, xs in at.items() if xs}, False


def scene_range(scene):
    """Preview range, если он включён, иначе диапазон сцены."""
    if scene.use_preview_range:
        return scene.frame_preview_start, scene.frame_preview_end
    return scene.frame_start, scene.frame_end


def shift_key(k, dx):
    k.co.x += dx
    k.handle_left.x += dx
    k.handle_right.x += dx


def neighbor_keys(fcurves, frame):
    """(ближайший ключ слева, справа) по всем кривым или None."""
    xs = [k.co.x for fc in fcurves for k in fc.keyframe_points]
    prev = max((x for x in xs if x < frame - 0.5), default=None)
    nxt = min((x for x in xs if x > frame + 0.5), default=None)
    return prev, nxt


# ---------- Повороты и матрицы ----------

def get_rot_quat(t):
    """Поворот кости/объекта в любом режиме вращения как Quaternion."""
    mode = t.rotation_mode
    if mode == 'QUATERNION':
        return t.rotation_quaternion.copy()
    if mode == 'AXIS_ANGLE':
        a = t.rotation_axis_angle
        return Quaternion((a[1], a[2], a[3]), a[0])
    return t.rotation_euler.to_quaternion()


def set_rot_quat(t, q):
    """Записывает Quaternion в канал вращения в режиме кости/объекта (Euler без скачков на ±180°)."""
    mode = t.rotation_mode
    if mode == 'QUATERNION':
        t.rotation_quaternion = q
    elif mode == 'AXIS_ANGLE':
        axis, angle = q.to_axis_angle()
        t.rotation_axis_angle = (angle, *axis)
    else:
        t.rotation_euler = q.to_euler(mode, t.rotation_euler)


def rot_data_path(t):
    return {'QUATERNION': "rotation_quaternion", 'AXIS_ANGLE': "rotation_axis_angle"}.get(t.rotation_mode, "rotation_euler")


def lerp_matrix(a, b, f):
    la, ra, sa = a.decompose()
    lb, rb, sb = b.decompose()
    return Matrix.LocRotScale(la.lerp(lb, f), ra.slerp(rb, f), sa.lerp(sb, f))


def world_matrix(owner, bone):
    return owner.matrix_world @ owner.pose.bones[bone].matrix if bone else owner.matrix_world.copy()


def set_world_matrix(owner, bone, m):
    if bone:
        owner.pose.bones[bone].matrix = owner.matrix_world.inverted() @ m
    else:
        owner.matrix_world = m


def transform_target(owner, bone):
    return owner.pose.bones[bone] if bone else owner


def autokey(context, owner, bone, paths=None):
    """Ставит ключи на изменённые каналы, если в сцене включён Auto Keying."""
    if not context.scene.tool_settings.use_keyframe_insert_auto:
        return
    t = transform_target(owner, bone)
    for path in paths or ("location", rot_data_path(t), "scale"):
        t.keyframe_insert(path)


def depth(owner, bone):
    """Глубина в иерархии — чтобы родителей обрабатывать раньше детей."""
    if bone:
        return len(owner.pose.bones[bone].parent_recursive)
    d, o = 0, owner
    while o.parent:
        o, d = o.parent, d + 1
    return d


def set_bone_selected(pb, value):
    """В 4.x выделение живёт на Bone, в 5.x — на PoseBone."""
    (pb if hasattr(pb, "select") else pb.bone).select = value


# ---------- Отражение L/R ----------

# Каналы, которые меняют знак при зеркалировании по X в локальном пространстве кости (как Paste Flipped в Blender)
FLIP_SIGN = {"location": {0}, "rotation_quaternion": {2, 3}, "rotation_euler": {1, 2}, "rotation_axis_angle": {2, 3}}


def flip_sign(prop, index):
    return -1.0 if index in FLIP_SIGN.get(prop, ()) else 1.0


def flipped_pose(loc, q, scale):
    """Отражённые по X (location, rotation Quaternion, scale) — как Paste Flipped в Blender."""
    return (loc.x * -1, loc.y, loc.z), Quaternion((q.w, q.x, -q.y, -q.z)), scale.copy()
