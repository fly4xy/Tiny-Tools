import bpy
from bpy.types import Panel, UIList
from ..utils.ui_utils import draw_tooltip
from ..properties.tooltip_data import (POSE_MASTER_TOOLTIPS, IMPORT_TOOLTIPS, EXPORT_TOOLTIPS, ANIMATION_TOOLS_TOOLTIPS,
                                       SYMMETRIZE_WEIGHTS_TOOLTIPS, ANIMATOR_TOOLTIPS, SKINNING_TOOLTIPS)
from ..utils.anim_compat import get_groups
from ..utils.vertex_utils import group_side, get_mirror_group_name
from ..utils.action_utils import find_armature_from_modifiers, get_cached_keyframes
from ..utils.file_utils import get_backup_directory, has_cached_pose
from ..utils.animator_utils import target_fcurves, neighbor_keys
from ..operators.animator_ops import TANGENTS
from ..utils.modal_job import JOB


class TT_UL_LoadedAnimationsList(UIList):
    bl_idname = "TT_UL_loaded_animations_list"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            split = layout.split(factor=0.75)
            left_row = split.row(align=True)
            left_row.prop(item, "select", text="")
            # Иконка: уже есть в файле / новая
            left_row.label(text=item.name, icon='CHECKMARK' if item.exists_in_blend else 'FILE_NEW')
            right_row = split.row(align=True)
            right_row.alignment = 'RIGHT'
            right_row.label(text=f"{int(item.frame_start)}-{int(item.frame_end)}")
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'LEFT'
            layout.label(text="", icon_value=icon)


# ---------- Оформление ----------

def props_col(layout):
    """Колонка с подписями слева, как в нативных панелях Blender"""
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = False
    return col


def big(layout, alert=False):
    """Крупная кнопка главного действия; alert — красная (меняет данные необратимо или сразу во всём файле)"""
    row = layout.row(align=True)
    row.scale_y = 1.4
    row.alert = alert
    return row


def heading(layout, text, icon):
    row = layout.row()
    row.label(text=text, icon=icon)


def tips(context):
    return context.scene.tiny_tools_props.show_tooltips


class _TTPanel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tiny Tools"


class _TTSection(_TTPanel):
    """Верхняя панель вкладки: иконка в заголовке; закрыта по умолчанию, если так задано в настройках аддона"""
    bl_options = {'DEFAULT_CLOSED'}
    pref_prop = ""  # show_* в настройках аддона
    header_icon = 'NONE'

    def draw_header(self, context):
        self.layout.label(text="", icon=self.header_icon)


# ---------- Шапка ----------

class TT_PT_MainPanel(_TTPanel, Panel):
    bl_label = "Tiny Tools"
    bl_idname = "TT_PT_main_panel"
    bl_options = {'HIDE_HEADER'}
    bl_order = 0

    def draw(self, context):
        props = context.scene.tiny_tools_props
        row = self.layout.row(align=True)
        row.scale_y = 1.2
        if props.bone_select_link:
            row.operator("tiny_tools.stop_bone_select_link", text="Bone Select Link", icon='LINKED', depress=True)
        else:
            row.operator("tiny_tools.bone_select_link", text="Bone Select Link", icon='UNLINKED')
        row.prop(props, "show_tooltips", text="", icon='QUESTION')
        if JOB:
            pct = JOB["done"] / JOB["total"]
            col = self.layout.column(align=True)
            col.progress(factor=pct, type='BAR', text=f"{JOB['label']}: {JOB['text']}  {round(pct * 100)}%")
            col.label(text="Esc — cancel", icon='CANCEL')


# ---------- Export ----------

class TT_PT_Export(_TTSection, Panel):
    bl_label = "Export"
    bl_idname = "TT_PT_export"
    bl_order = 1
    pref_prop = "show_export_box"
    header_icon = 'EXPORT'

    def draw(self, context):
        layout = self.layout
        props = context.scene.tiny_tools_props
        if tips(context):
            draw_tooltip(layout, EXPORT_TOOLTIPS, "export.main_help")

        heading(layout, "Armature", 'ARMATURE_DATA')
        props_col(layout).prop(props.armature, "source_armature", text="Source")
        big(layout).operator("tiny_tools.backup_armature", icon='EXPORT')

        layout.separator()
        heading(layout, "Animation", 'ANIM')
        a = props.animation
        layout.row(align=True).prop(a, "anim_export_format", expand=True)
        if a.anim_export_format == 'BACKUP':
            row = big(layout)
            row.operator("tiny_tools.export_active_animation", text="Active", icon='ACTION')
            row.operator("tiny_tools.export_all_animations", text="All", icon='RENDER_ANIMATION')
            row.operator("tiny_tools.export_each_animation", text="Each", icon='LINENUMBERS_ON')
            folder_path = ""
        else:
            if tips(context):
                draw_tooltip(layout, EXPORT_TOOLTIPS, "export.fbx_help")
            col = props_col(layout)
            col.prop(a, "fbx_preset")
            col.prop(a, "fbx_prefix")
            col.prop(a, "fbx_export_dir")
            box = layout.box()
            col = box.column(align=True)
            col.prop(a, "fbx_add_root")
            col.prop(a, "fbx_deform_only")
            col.prop(a, "fbx_leaf_bones")
            col.prop(a, "fbx_force_startend")
            col = props_col(box)
            col.prop(a, "fbx_simplify")
            col.prop(a, "fbx_apply_scale")
            col.prop(a, "fbx_global_scale")
            row = big(layout)
            row.operator("tiny_tools.export_animations_fbx", text="Active", icon='ACTION').mode = 'ACTIVE'
            row.operator("tiny_tools.export_animations_fbx", text="All (separate files)", icon='RENDER_ANIMATION').mode = 'ALL'
            folder_path = a.fbx_export_dir

        layout.separator()
        row = layout.row(align=True)
        if folder_path:
            folder = bpy.path.basename(bpy.path.abspath(folder_path).rstrip("\\/"))
        else:
            folder = bpy.path.basename(get_backup_directory(create=False).rstrip("\\/"))
            if a.anim_export_format == 'FBX':
                folder += " / FBX"
        row.label(text=folder, icon='FILE_FOLDER')
        op = row.operator("tiny_tools.open_backup_folder", text="", icon='FOLDER_REDIRECT')
        if a.anim_export_format == 'FBX':
            op.path = folder_path or get_backup_directory('FBX', create=False)


# ---------- Import ----------

class TT_PT_Import(_TTSection, Panel):
    bl_label = "Import"
    bl_idname = "TT_PT_import"
    bl_order = 2
    pref_prop = "show_import_box"
    header_icon = 'IMPORT'

    def draw(self, context):
        layout = self.layout
        props = context.scene.tiny_tools_props
        if tips(context):
            draw_tooltip(layout, IMPORT_TOOLTIPS, "import.main_help")

        heading(layout, "Armature", 'ARMATURE_DATA')
        col = props_col(layout)
        col.prop(props.armature, "json_path", text="JSON")
        col.prop(props.armature, "target_armature", text="Target")
        big(layout).operator("tiny_tools.restore_armature", text="Restore All", icon='IMPORT')
        row = layout.row(align=True)
        row.operator("tiny_tools.restore_bones_only", text="Bones Only", icon='BONE_DATA')
        row.operator("tiny_tools.restore_constraints_only", text="Constraints Only", icon='CONSTRAINT_BONE')
        layout.operator("tiny_tools.verify_with_json", icon='VIEWZOOM')

        if props.verification.verification_result:
            res = layout.box()
            row = res.row()
            row.prop(props.verification, "show_verification_results",
                     icon='TRIA_DOWN' if props.verification.show_verification_results else 'TRIA_RIGHT',
                     icon_only=True, emboss=False)
            row.label(text="Verification Results", icon='TEXT')
            row.operator("tiny_tools.clear_verification_log", icon='TRASH', text="")
            if props.verification.show_verification_results:
                draw_scrollable_verification(res, props)

        layout.separator()
        heading(layout, "Animation", 'ANIM')
        row = layout.row(align=True)
        row.prop(props.animation, "animation_json_path", text="")
        row.operator("tiny_tools.load_animation_list", text="", icon='FILE_REFRESH')

        anim = props.animation
        if anim.show_loaded_animations and anim.loaded_animations_list:
            selected = sum(1 for i in anim.loaded_animations_list if i.select)
            row = layout.row()
            row.label(text=f"In file: {len(anim.loaded_animations_list)}  ·  selected: {selected}", icon='ANIM_DATA')
            row.operator("tiny_tools.clear_loaded_animations", text="", icon='X')
            layout.row(align=True).prop(anim, "animation_import_mode", expand=True)
            layout.template_list("TT_UL_loaded_animations_list", "", anim, "loaded_animations_list",
                                 anim, "loaded_animations_list_index", rows=6)
            row = big(layout)
            row.prop(anim, "select_all_loaded_animations", text="All", toggle=True)
            sub = row.row(align=True)
            sub.enabled = selected > 0
            sub.alert = anim.animation_import_mode == 'REPLACE'  # перезапишет существующие анимации
            sub.operator("tiny_tools.import_selected_animations", text=f"Import {selected}", icon='IMPORT')


# ---------- Armature Tools ----------

class TT_PT_ArmatureTools(_TTSection, Panel):
    bl_label = "Armature Tools"
    bl_idname = "TT_PT_armature_tools"
    bl_order = 3
    pref_prop = "show_armature_tools"
    header_icon = 'ARMATURE_DATA'

    def draw(self, context):
        row = self.layout.row(align=True)
        row.operator("tiny_tools.copy_pose", text="Copy Pose", icon='COPYDOWN')
        sub = row.row(align=True)
        sub.enabled = has_cached_pose()
        sub.operator("tiny_tools.paste_pose", text="Paste Pose", icon='PASTEDOWN')


class TT_PT_PoseMaster(_TTPanel, Panel):
    bl_label = "Pose Master"
    bl_idname = "TT_PT_pose_master"
    bl_parent_id = "TT_PT_armature_tools"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='POSE_HLT')

    def draw(self, context):
        layout = self.layout
        props = context.scene.tiny_tools_props
        pm = props.pose_master
        if tips(context):
            draw_tooltip(layout, POSE_MASTER_TOOLTIPS, "pose_master.main_help")

        col = props_col(layout)
        col.prop_search(pm, "pose_target_armature", context.scene, "objects", text="Target")
        target = bpy.data.objects.get(pm.pose_target_armature)
        is_arm = bool(target and target.type == 'ARMATURE')
        if pm.pose_target_armature and not is_arm:
            row = layout.row()
            row.alert = True
            row.label(text="Target is not an armature", icon='ERROR')

        col = layout.column(align=True)
        col.prop(pm, "ignore_constraints")
        col.prop(pm, "adapt_selected_animations")
        if pm.adapt_selected_animations:
            selected = sum(1 for a in bpy.data.actions if getattr(a, "select", False))
            box = col.box()
            box.label(text=f"Selected animations: {selected}", icon='ANIM_DATA')
            if not selected:
                box.label(text="Tick them in Animation Tools → Animations", icon='INFO')
        col.prop(pm, "apply_to_linked_meshes")
        if pm.apply_to_linked_meshes:
            linked = []
            if is_arm:
                linked = [o for o in bpy.data.objects if o.type == 'MESH' and
                          any(m.type == 'ARMATURE' and m.object == target for m in o.modifiers)]
                if pm.apply_only_to_selected_meshes:
                    linked = [o for o in linked if o.select_get()]
            box = col.box()
            box.prop(pm, "apply_only_to_selected_meshes")
            box.label(text=f"Meshes to process: {len(linked)}", icon='MESH_DATA')

        row = big(layout, alert=True)
        row.enabled = is_arm
        row.operator("tiny_tools.apply_pose_master", text="Apply Pose as Rest", icon='PLAY')


# ---------- Animation Tools ----------

class TT_PT_AnimationTools(_TTSection, Panel):
    bl_label = "Animation Tools"
    bl_idname = "TT_PT_animation_tools"
    bl_order = 4
    pref_prop = "show_animation_tools"
    header_icon = 'ANIM'

    def draw(self, context):
        layout = self.layout
        if tips(context):
            draw_tooltip(layout, ANIMATION_TOOLS_TOOLTIPS, "animation_tools.main_help")
        row = layout.row()
        row.label(text="Keyframes", icon='KEYINGSET')
        cached = get_cached_keyframes("copied_keys")
        if cached:
            row.label(text=f"Buffer: {len(cached)}")
        row = layout.row(align=True)
        row.operator("tiny_tools.soft_copy_keyframes", text="Soft Copy", icon='COPYDOWN')
        row.operator("tiny_tools.hard_copy_keyframes", text="Hard Copy", icon='GHOST_ENABLED')
        sub = row.row(align=True)
        sub.enabled = bool(cached)
        sub.operator("tiny_tools.paste_keyframes", text="Paste", icon='PASTEDOWN')


class TT_PT_AnimationsList(_TTPanel, Panel):
    bl_label = "Animations"
    bl_idname = "TT_PT_animations_list"
    bl_parent_id = "TT_PT_animation_tools"

    def draw_header(self, context):
        total = len(bpy.data.actions)
        selected = sum(1 for a in bpy.data.actions if getattr(a, "select", False))
        self.layout.label(text=f"({selected}/{total})", icon='LINENUMBERS_ON')

    def draw(self, context):
        layout = self.layout
        props = context.scene.tiny_tools_props
        row = layout.row(align=True)
        row.prop(props.animation, "select_all_animations", text="All", toggle=True)
        row.separator()
        row.operator("tiny_tools.add_animation", text="", icon='ADD')
        row.operator("tiny_tools.rename_animation", text="", icon='GREASEPENCIL')
        sub = row.row(align=True)
        sub.alert = True
        sub.operator("tiny_tools.delete_animations", text="", icon='TRASH')
        row.separator()
        row.operator("tiny_tools.set_frame_range_from_action", text="", icon='PREVIEW_RANGE')
        row.separator()
        row.operator("tiny_tools.toggle_all_animations_lock", text="", icon='UNLOCKED').lock_all = False
        row.operator("tiny_tools.toggle_all_animations_lock", text="", icon='LOCKED').lock_all = True

        row = layout.row(align=True)
        row.prop(props.animation, "animation_search", text="", icon='VIEWZOOM')
        if props.animation.animation_search:
            row.operator("tiny_tools.clear_search_field", text="", icon='X').search_field = "animation.animation_search"
        sub = row.row(align=True)
        sub.scale_x = 0.7
        for n in "1234":
            sub.prop_enum(props.animation, "animation_columns", n, text=n)

        draw_animations_grid(layout, context, props)


# ---------- Animator ----------

class TT_PT_Animator(_TTSection, Panel):
    bl_label = "Animator"
    bl_idname = "TT_PT_animator"
    bl_order = 5
    pref_prop = "show_animator_tools"
    header_icon = 'ACTION_TWEAK'

    def draw(self, context):
        layout = self.layout
        if tips(context):
            draw_tooltip(layout, ANIMATOR_TOOLTIPS, "animator.main_help")
        layout.prop(context.scene.tiny_tools_props.animator, "clean_playback", icon='HIDE_ON')


class TT_PT_AnimatorKeys(_TTPanel, Panel):
    bl_label = "Keys"
    bl_idname = "TT_PT_animator_keys"
    bl_parent_id = "TT_PT_animator"

    def draw_header(self, context):
        self.layout.label(text="", icon='KEYFRAME')

    def draw(self, context):
        layout = self.layout
        ap = context.scene.tiny_tools_props.animator
        frame = context.scene.frame_current

        row = layout.row(align=True)
        row.operator("tiny_tools.nudge_keys", text="", icon='TRIA_LEFT').frames = -ap.nudge_step
        row.prop(ap, "nudge_step", text="Nudge")
        row.operator("tiny_tools.nudge_keys", text="", icon='TRIA_RIGHT').frames = ap.nudge_step
        prev, nxt = neighbor_keys(target_fcurves(context), frame)
        if prev is not None or nxt is not None:
            left = f"◀ {frame - prev:g}" if prev is not None else "◀ —"
            right = f"{nxt - frame:g} ▶" if nxt is not None else "— ▶"
            row = layout.row()
            row.alignment = 'CENTER'
            row.label(text=f"Neighbor keys:  {left}   |   {right}")

        layout.separator()
        row = layout.row(align=True)
        row.prop(ap, "bake_step", text="Bake on")
        row.prop(ap, "bake_stepped", text="", icon='IPO_CONSTANT')
        op = row.operator("tiny_tools.bake_step", text="Bake", icon='REC')
        op.step, op.stepped = ap.bake_step, ap.bake_stepped

        row = layout.row(align=True)
        row.operator("tiny_tools.share_key_times", icon='KEYFRAME_HLT').remove_others = ap.share_remove_others
        row.prop(ap, "share_remove_others", text="", icon='TRASH')

        row = layout.row(align=True)
        row.prop(ap, "offset_frames", text="Offset")
        row.prop(ap, "offset_cascade", text="Cascade")
        op = row.operator("tiny_tools.time_offset", text="", icon='NLA_PUSHDOWN')
        op.offset, op.cascade = ap.offset_frames, ap.offset_cascade

        layout.operator("tiny_tools.reverse_animation", icon='LOOP_BACK')

        layout.separator()
        heading(layout, "Tangents · click, drag to blend", 'IPO_BEZIER')
        row = layout.row(align=True)
        for ident, name, _ in TANGENTS:
            row.operator("tiny_tools.blend_tangents", text=name).tangent = ident


class TT_PT_AnimatorPose(_TTPanel, Panel):
    bl_label = "Pose"
    bl_idname = "TT_PT_animator_pose"
    bl_parent_id = "TT_PT_animator"

    def draw_header(self, context):
        self.layout.label(text="", icon='POSE_HLT')

    def draw(self, context):
        layout = self.layout
        ap = context.scene.tiny_tools_props.animator
        row = layout.row(align=True)
        row.operator("tiny_tools.reset_pose", icon='LOOP_BACK')
        row.operator("tiny_tools.temp_pivot", icon='PIVOT_CURSOR', depress=bool(ap.temp_pivot_prev))

        layout.separator()
        heading(layout, "Buffer · click, drag to blend", 'PASTEDOWN')
        row = layout.row(align=True)
        row.operator("tiny_tools.copy_pose", text="Copy to Buffer", icon='COPYDOWN')
        sub = row.row(align=True)
        sub.enabled = has_cached_pose()
        sub.operator("tiny_tools.blend_to_buffer", text="Blend", icon='PASTEDOWN')

        heading(layout, "Blend to Active", 'PIVOT_ACTIVE')
        row = layout.row(align=True)
        row.operator("tiny_tools.blend_to_active", text="World").space = 'WORLD'
        row.operator("tiny_tools.blend_to_active", text="Local").space = 'LOCAL'

        layout.separator()
        heading(layout, "Mirror", 'MOD_MIRROR')
        layout.row(align=True).prop(ap, "mirror_direction", expand=True)
        row = layout.row(align=True)
        row.operator("tiny_tools.mirror_pose", text="Pose", icon='ARMATURE_DATA').direction = ap.mirror_direction
        row.operator("tiny_tools.mirror_animation", text="Animation", icon='ACTION').direction = ap.mirror_direction
        arm = context.active_object
        if arm and arm.type == 'ARMATURE':
            layout.prop(arm.pose, "use_mirror_x", text="Auto Mirror (edit both sides)")


class TT_PT_AnimatorSets(_TTPanel, Panel):
    bl_label = "Bone Sets"
    bl_idname = "TT_PT_animator_sets"
    bl_parent_id = "TT_PT_animator"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='BONE_DATA')

    def draw(self, context):
        layout = self.layout
        arm = context.active_object
        if not arm or arm.type != 'ARMATURE':
            layout.label(text="Select an armature", icon='INFO')
            return
        flow = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        for coll in arm.data.collections_all:
            flow.operator("tiny_tools.select_bone_set", text=coll.name).name = coll.name
        layout.operator("tiny_tools.new_bone_set", text="New Set from Selection", icon='ADD')


# ---------- Cleanup ----------

class TT_PT_Cleanup(_TTSection, Panel):
    bl_label = "Cleanup"
    bl_idname = "TT_PT_cleanup"
    bl_order = 6
    pref_prop = "show_cleanup_tools"
    header_icon = 'BRUSH_DATA'

    def draw(self, context):
        col = self.layout.column(align=True)
        col.alert = True
        col.operator("tiny_tools.clean_animations", icon='TRASH')
        col.operator("tiny_tools.clean_vertex_groups", icon='GROUP_VERTEX')


# ---------- Symmetrize Weights ----------

class TT_PT_Weights(_TTSection, Panel):
    bl_label = "Weights"
    bl_idname = "TT_PT_weights"
    bl_order = 7
    pref_prop = "show_mirror_tools"
    header_icon = 'MOD_VERTEX_WEIGHT'

    def draw(self, context):
        obj = context.active_object
        if obj and obj.type == 'MESH':
            self.layout.label(text=f"{obj.name}: {len(obj.vertex_groups)} groups", icon='MESH_DATA')
        else:
            self.layout.label(text="Select a mesh object", icon='INFO')


class TT_PT_Symmetrize(_TTPanel, Panel):
    bl_label = "Symmetrize"
    bl_idname = "TT_PT_symmetrize"
    bl_parent_id = "TT_PT_weights"

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_MIRROR')

    def draw(self, context):
        layout = self.layout
        props = context.scene.tiny_tools_props
        if tips(context):
            draw_tooltip(layout, SYMMETRIZE_WEIGHTS_TOOLTIPS, "symmetrize_weights.main_help")

        v = props.vertex
        layout.row(align=True).prop(v, "mirror_method", expand=True)
        layout.row(align=True).prop(v, "mirror_direction", expand=True)

        if v.mirror_method == 'CUSTOM':
            col = props_col(layout)
            col.prop(v, "mirror_projection_method", text="Projection")
            col.prop(v, "mirror_search_radius", text="Search Radius")
            col.prop(v, "mirror_weight_mode", text="Weights")

            box = layout.box()
            box.label(text="Checks", icon='CHECKMARK')
            row = box.row(align=True)
            row.prop(v, "mirror_check_topology", text="Topology", toggle=True)
            row.prop(v, "mirror_check_normals", text="Normals", toggle=True)
            if v.mirror_check_normals:
                box.prop(v, "mirror_normal_threshold", text="Normal Threshold")

            box = layout.box()
            smooth_prop = {'DIRECT': "smooth_direct", 'GRADIENT': "smooth_gradient",
                           'INTERPOLATION': "smooth_interpolation"}[v.mirror_projection_method]
            box.prop(v, smooth_prop, text="Smooth After Mirroring")
            if getattr(v, smooth_prop):
                row = box.row(align=True)
                row.prop(v, "smooth_iterations", text="Iterations")
                row.prop(v, "smooth_intensity", text="Intensity")

            if v.mirror_projection_method != 'DIRECT':
                box = layout.box()
                box.label(text="Hole Filling", icon='MOD_SMOOTH')
                box.prop(v, "edge_length_mult", text="Fill Radius ×")
                box.prop(v, "project_weights", text="Project Along Normals")
                if v.project_weights:
                    col = box.column(align=True)
                    col.prop(v, "projection_distance", text="Distance")
                    col.prop(v, "projection_steps", text="Steps")
                    col.prop(v, "smooth_after_projection_steps", text="Smooth Steps")

            layout.label(text="First run builds the vertex pairs cache", icon='TIME')
        else:
            layout.prop(v, "use_topology", text="Use Topology")

        obj = context.active_object
        col = layout.column(align=True)
        col.enabled = bool(obj and obj.type == 'MESH')
        col.scale_y = 1.4
        col.operator("tiny_tools.mirror_vertex_groups", text="Symmetrize All", icon='MOD_MIRROR').mirror_mode = 'ALL'
        col.operator("tiny_tools.mirror_vertex_groups", text="Symmetrize Selected Pair",
                     icon='LAYER_ACTIVE').mirror_mode = 'SELECTED'


class TT_PT_WeightsTransfer(_TTPanel, Panel):
    bl_label = "Transfer"
    bl_idname = "TT_PT_weights_transfer"
    bl_parent_id = "TT_PT_weights"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_DATA_TRANSFER')

    def draw(self, context):
        layout = self.layout
        v = context.scene.tiny_tools_props.vertex
        if tips(context):
            draw_tooltip(layout, SKINNING_TOOLTIPS, "skinning.transfer_help")
        row = layout.row(align=True)
        row.scale_y = 1.2
        row.operator("tiny_tools.transfer_pick", text="Selected → Active", icon='FORWARD').mode = 'SELECTED'
        row.operator("tiny_tools.transfer_pick", text="", icon='UV_SYNC_SELECT').mode = 'SWAP'
        for prop, label, mode in (("transfer_source", "From", 'SOURCE'), ("transfer_target", "To", 'TARGET')):
            row = props_col(layout).row(align=True)
            row.prop(v, prop, text=label)
            row.operator("tiny_tools.transfer_pick", text="", icon='RESTRICT_SELECT_OFF').mode = mode
        layout.row(align=True).prop(v, "transfer_groups", expand=True)
        col = props_col(layout)
        col.prop(v, "transfer_max_distance", text="Max Distance")
        col.prop(v, "transfer_weight_mode", text="Weights")
        row = layout.row(align=True)
        row.prop(v, "transfer_check_normals", text="Check Normals", toggle=True)
        sub = row.row(align=True)
        sub.active = v.transfer_check_normals
        sub.prop(v, "transfer_normal_threshold", text="Angle")
        row = layout.row(align=True)
        row.prop(v, "transfer_smooth", text="Smooth After", toggle=True)
        sub = row.row(align=True)
        sub.active = v.transfer_smooth
        sub.prop(v, "smooth_weights_iterations", text="Iterations")
        row = big(layout)
        row.enabled = bool(v.transfer_source and v.transfer_target and v.transfer_source != v.transfer_target)
        row.operator("tiny_tools.transfer_weights", icon='MOD_DATA_TRANSFER')


class TT_PT_WeightsSmooth(_TTPanel, Panel):
    bl_label = "Smooth"
    bl_idname = "TT_PT_weights_smooth"
    bl_parent_id = "TT_PT_weights"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_SMOOTH')

    def draw(self, context):
        layout = self.layout
        v = context.scene.tiny_tools_props.vertex
        if tips(context):
            draw_tooltip(layout, SKINNING_TOOLTIPS, "skinning.smooth_help")
        layout.row(align=True).prop(v, "smooth_groups_mode", expand=True)
        row = layout.row(align=True)
        row.prop(v, "smooth_weights_iterations", text="Iterations")
        row.prop(v, "smooth_weights_factor", text="Factor")
        obj = context.active_object
        row = big(layout)
        row.enabled = bool(obj and obj.type == 'MESH' and obj.vertex_groups)
        row.operator("tiny_tools.smooth_weights", icon='MOD_SMOOTH')


class TT_PT_VertexGroups(_TTPanel, Panel):
    bl_label = "Vertex Groups"
    bl_idname = "TT_PT_vertex_groups"
    bl_parent_id = "TT_PT_weights"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        obj = context.active_object
        count = len(obj.vertex_groups) if obj and obj.type == 'MESH' else 0
        self.layout.label(text=f"({count})", icon='GROUP_VERTEX')

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            layout.label(text="Select a mesh object", icon='ERROR')
            return
        v = context.scene.tiny_tools_props.vertex
        row = layout.row(align=True)
        row.prop(v, "vertex_group_search", text="", icon='VIEWZOOM')
        if v.vertex_group_search:
            row.operator("tiny_tools.clear_search_field", text="", icon='X').search_field = "vertex.vertex_group_search"
        row.prop(v, "show_only_mirror_groups", text="", icon='MOD_MIRROR', toggle=True)
        row.operator("tiny_tools.select_mirror_group", text="", icon='ARROW_LEFTRIGHT')

        row = layout.row(align=True)
        row.prop(v, "vertex_groups_sort", expand=True)
        sub = row.row(align=True)
        sub.scale_x = 0.7
        for n in "1234":
            sub.prop_enum(v, "vertex_groups_columns", n, text=n)

        active_vg = obj.vertex_groups.active
        mirror_name = get_mirror_group_name(active_vg.name) if active_vg else None
        search = v.vertex_group_search.lower()
        groups = [vg for vg in obj.vertex_groups
                  if (not v.show_only_mirror_groups or group_side(vg.name))
                  and (not search or search in vg.name.lower())]
        if v.vertex_groups_sort == 'ALPHABETICAL':
            groups.sort(key=lambda x: x.name.lower())
        else:
            groups = sort_by_bone_hierarchy(obj, groups)
        if not groups:
            layout.label(text="No vertex groups found", icon='INFO')
            return
        flow = layout.grid_flow(row_major=True, columns=int(v.vertex_groups_columns),
                                even_columns=True, even_rows=False, align=True)
        for vg in groups:
            is_active = vg == active_vg
            icon = 'LAYER_ACTIVE' if is_active else 'ARROW_LEFTRIGHT' if vg.name == mirror_name else 'NONE'
            flow.operator("tiny_tools.select_vertex_group", text=vg.name, depress=is_active, icon=icon).group_name = vg.name


# ---------- Вспомогательное ----------

def sort_by_bone_hierarchy(obj, vertex_groups):
    """Сортирует вертекс-группы по порядку костей арматуры из модификатора"""
    armature_obj = find_armature_from_modifiers(obj)
    if not armature_obj or armature_obj.type != 'ARMATURE':
        return sorted(vertex_groups, key=lambda x: x.name.lower())
    bones = armature_obj.data.edit_bones if armature_obj.mode == 'EDIT' else armature_obj.data.bones
    bone_order = {bone.name: i for i, bone in enumerate(bones)}
    return sorted(vertex_groups, key=lambda vg: bone_order.get(vg.name, 9999))  # группы без костей — в конце


def draw_scrollable_verification(layout, props):
    """Рисует скроллируемую область с результатами верификации"""
    lines = props.verification.verification_result.split('\n')
    total_lines = len(lines)
    max_visible = props.verification.verification_max_lines
    if total_lines == 0:
        return
    max_scroll = max(0, total_lines - max_visible)
    current_scroll = min(props.verification.verification_scroll, max_scroll)
    if props.verification.verification_scroll != current_scroll:
        layout.operator("tiny_tools.correct_scroll", text="Correct Scroll Position", icon='FILE_REFRESH')
        return
    start_line = current_scroll
    end_line = min(start_line + max_visible, total_lines)
    col = layout.box().column()
    col.scale_y = 0.8
    for i in range(start_line, end_line):
        draw_wrapped_label(col, lines[i])
    if total_lines > max_visible:
        row = layout.row(align=True)
        up = row.row(align=True)
        up.enabled = current_scroll > 0
        up.operator("tiny_tools.scroll_verification_up", icon='TRIA_UP', text="")
        row.prop(props.verification, "verification_scroll", text=f"Lines {start_line + 1}-{end_line} of {total_lines}")
        down = row.row(align=True)
        down.enabled = current_scroll < max_scroll
        down.operator("tiny_tools.scroll_verification_down", icon='TRIA_DOWN', text="")


def draw_wrapped_label(layout, text):
    """Рисует текст с переносом по словам (80 символов)"""
    if len(text) <= 80:
        layout.label(text=text)
        return
    current_line = ""
    for word in text.split(' '):
        if len(current_line + word) <= 80:
            current_line += word + " "
        else:
            if current_line:
                layout.label(text=current_line.strip())
            current_line = word + " "
    if current_line:
        layout.label(text=current_line.strip())


def draw_animations_grid(layout, context, props):
    """Сетка анимаций: выбор, fake user, замок"""
    active_action = get_active_action_with_priority(context)
    search = props.animation.animation_search.lower()
    animations = [a for a in bpy.data.actions if not search or search in a.name.lower()]
    if not animations:
        layout.label(text="No animations found", icon='INFO')
        return
    flow = layout.grid_flow(row_major=True, columns=int(props.animation.animation_columns),
                            even_columns=True, even_rows=False, align=False)
    for action in animations:
        row = flow.row(align=True)
        row.prop(action, "select", text="", icon='CHECKBOX_HLT' if action.select else 'CHECKBOX_DEHLT')
        row.operator("tiny_tools.select_animation", text=action.name,
                     depress=(action == active_action)).action_name = action.name
        row.prop(action, "use_fake_user", text="", icon='FAKE_USER_OFF', toggle=True)
        lock_state = get_action_lock_state(action)
        lock_icon = {'ALL_UNLOCKED': 'UNLOCKED', 'ALL_LOCKED': 'LOCKED'}.get(lock_state, 'KEYINGSET')
        row.operator("tiny_tools.toggle_action_lock", text="", depress=lock_state != 'ALL_UNLOCKED',
                     icon=lock_icon).action_name = action.name


def get_action_lock_state(action):
    """ALL_UNLOCKED / ALL_LOCKED / PARTLY_LOCKED по группам каналов экшена"""
    groups = get_groups(action)
    locked = sum(1 for g in groups if g.lock)
    if locked == 0:
        return 'ALL_UNLOCKED'
    return 'ALL_LOCKED' if locked == len(groups) else 'PARTLY_LOCKED'


def get_active_action_with_priority(context):
    """Активный экшен: объекта, а для меша — его арматуры из модификатора"""
    obj = context.active_object
    if not obj:
        return None
    if obj.animation_data and obj.animation_data.action:
        return obj.animation_data.action
    if obj.type == 'MESH':
        arm = find_armature_from_modifiers(obj)
        if arm and arm.animation_data and arm.animation_data.action:
            return arm.animation_data.action
    return None


# Родительские панели раньше дочерних
PANELS = (
    TT_PT_MainPanel, TT_PT_Export, TT_PT_Import, TT_PT_ArmatureTools, TT_PT_PoseMaster,
    TT_PT_AnimationTools, TT_PT_AnimationsList, TT_PT_Animator, TT_PT_AnimatorKeys, TT_PT_AnimatorPose,
    TT_PT_AnimatorSets, TT_PT_Cleanup, TT_PT_Weights, TT_PT_Symmetrize, TT_PT_WeightsTransfer,
    TT_PT_WeightsSmooth, TT_PT_VertexGroups,
)
