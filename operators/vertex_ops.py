import bpy
from bpy.types import Operator
from ..utils.modal_job import ModalJob
from ..utils.vertex_utils import mirror_vertex_weights, get_cached_vertex_pairs, mirror_weights_blender, get_mirror_group_name

class TT_OT_MirrorVertexGroups(ModalJob, Operator):
    bl_idname = "tiny_tools.mirror_vertex_groups"
    bl_label = "Symmetrize Weights"
    bl_description = "Mirror vertex group weights (Esc cancels and reverts)"
    bl_options = {'REGISTER', 'UNDO'}

    mirror_mode: bpy.props.EnumProperty(
        name="Mode",
        items=[
            ('ALL', "All", "Mirror all groups"),
            ('SELECTED', "Selected", "Mirror selected group only")
        ],
        default='ALL'
    ) # type: ignore

    def job(self, context, state):
        from ..utils.vertex_utils import (get_cached_vertex_pairs_iter, mirror_vertex_weights_iter,
                                          mirror_weights_blender_iter, get_source_groups, get_opposite_group_name,
                                          get_mirrored_group_names, smooth_multiple_vertex_groups_iter, snapshot_groups)
        v = context.scene.tiny_tools_props.vertex
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            return ('ERROR', "Please select a mesh object")
        if self.mirror_mode == 'SELECTED' and not obj.vertex_groups.active:
            return ('ERROR', "No vertex group selected")
        sources = get_source_groups(obj, v.mirror_direction, self.mirror_mode)
        if not sources:
            return ('WARNING', "No source groups for this direction")
        state["obj"] = obj
        state["edit"] = _leave_edit_mode(context)
        state["snap"] = snapshot_groups(obj, [get_opposite_group_name(s, v.mirror_direction) for s in sources])
        try:
            if v.mirror_method == 'BLENDER':
                count = yield from mirror_weights_blender_iter(obj, v.mirror_direction, self.mirror_mode, v.use_topology)
                return ('INFO', f"Symmetrized {count} group(s) with Blender method")

            pairs = yield from get_cached_vertex_pairs_iter(obj, v.mirror_search_radius, 'SPATIAL_HASH',
                                                            v.mirror_check_topology, v.mirror_check_normals,
                                                            v.mirror_normal_threshold)
            count = yield from mirror_vertex_weights_iter(
                obj, v.mirror_direction, v.mirror_weight_mode, pairs, v.mirror_projection_method, self.mirror_mode,
                v.mirror_check_normals, v.mirror_normal_threshold, v.mirror_search_radius, v.project_weights,
                v.projection_distance, v.projection_steps, v.smooth_after_projection_steps, v.edge_length_mult)
            smooth = {'DIRECT': v.smooth_direct, 'GRADIENT': v.smooth_gradient,
                      'INTERPOLATION': v.smooth_interpolation}[v.mirror_projection_method]
            if smooth and count:
                if self.mirror_mode == 'ALL':
                    targets = get_mirrored_group_names(obj, v.mirror_direction, 'ALL')
                else:
                    targets = [get_opposite_group_name(sources[0], v.mirror_direction)]
                smoothed = yield from smooth_multiple_vertex_groups_iter(obj, targets, v.smooth_iterations, v.smooth_intensity)
                return ('INFO', f"Mirrored {count} group(s), smoothed {smoothed}")
            return ('INFO', f"Mirrored {count} vertex group(s)")
        finally:
            if state.pop("edit", False):
                bpy.ops.object.mode_set(mode='EDIT')

    def cancel_job(self, context, state):
        from ..utils.vertex_utils import restore_groups
        if "snap" not in state:
            return False
        restore_groups(state["obj"], state["snap"])
        return True


class TT_OT_TransferWeights(ModalJob, Operator):
    bl_idname = "tiny_tools.transfer_weights"
    bl_label = "Transfer Weights"
    bl_description = ("Project vertex weights from one mesh to another (different topology and density): "
                      "interpolation on the nearest source surface, normal check, hole filling from neighbors. "
                      "Esc cancels and reverts")
    bl_options = {'REGISTER', 'UNDO'}

    def job(self, context, state):
        from ..utils.vertex_utils import transfer_weights_iter, smooth_groups_iter, snapshot_groups
        v = context.scene.tiny_tools_props.vertex
        src, dst = v.transfer_source, v.transfer_target
        if not src or not dst or src == dst:
            return ('ERROR', "Pick two different meshes: From and To")
        if v.transfer_groups == 'ACTIVE':
            if not src.vertex_groups.active:
                return ('ERROR', f"'{src.name}' has no active vertex group")
            names = [src.vertex_groups.active.name]
        else:
            names = [vg.name for vg in src.vertex_groups]
        if not names:
            return ('ERROR', f"'{src.name}' has no vertex groups")
        state["obj"] = dst
        state["edit"] = _leave_edit_mode(context)
        state["snap"] = snapshot_groups(dst, names)
        try:
            count, filled = yield from transfer_weights_iter(
                src, dst, names, v.transfer_max_distance, v.transfer_check_normals,
                v.transfer_normal_threshold, v.transfer_weight_mode == 'REPLACE_ALL')
            if v.transfer_smooth:
                yield from smooth_groups_iter(dst, names, v.smooth_weights_iterations, v.smooth_weights_factor)
        finally:
            if state.pop("edit", False):
                bpy.ops.object.mode_set(mode='EDIT')
        msg = f"Transferred {count} group(s) to '{dst.name}'"
        return ('INFO', msg + (f", {filled} vertices filled from neighbors" if filled else ""))

    def cancel_job(self, context, state):
        from ..utils.vertex_utils import restore_groups
        if "snap" not in state:
            return False
        restore_groups(state["obj"], state["snap"])
        return True


class TT_OT_SmoothWeights(ModalJob, Operator):
    bl_idname = "tiny_tools.smooth_weights"
    bl_label = "Smooth Weights"
    bl_description = ("Smooth the active vertex group (or all unlocked groups) of the active mesh along its edges. "
                      "Esc cancels and reverts")
    bl_options = {'REGISTER', 'UNDO'}

    def job(self, context, state):
        from ..utils.vertex_utils import smooth_groups_iter, snapshot_groups
        v = context.scene.tiny_tools_props.vertex
        obj = context.active_object
        if not obj or obj.type != 'MESH' or not obj.vertex_groups:
            return ('ERROR', "Select a mesh with vertex groups")
        if v.smooth_groups_mode == 'ACTIVE':
            names = [obj.vertex_groups.active.name] if obj.vertex_groups.active else []
        else:
            names = [vg.name for vg in obj.vertex_groups]
        state["obj"] = obj
        state["edit"] = _leave_edit_mode(context)
        state["snap"] = snapshot_groups(obj, names)
        try:
            count = yield from smooth_groups_iter(obj, names, v.smooth_weights_iterations, v.smooth_weights_factor)
        finally:
            if state.pop("edit", False):
                bpy.ops.object.mode_set(mode='EDIT')
        if not count:
            return ('WARNING', "Nothing to smooth (group locked or missing)")
        return ('INFO', f"Smoothed {count} group(s)")

    def cancel_job(self, context, state):
        from ..utils.vertex_utils import restore_groups
        if "snap" not in state:
            return False
        restore_groups(state["obj"], state["snap"])
        return True


class TT_OT_SelectMirrorGroup(Operator):
    bl_idname = "tiny_tools.select_mirror_group"
    bl_label = "Select Mirror Group"
    bl_description = "Select the mirror counterpart of the active vertex group"
    
    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH' or not obj.vertex_groups.active:
            return {'CANCELLED'}
            
        active_vg = obj.vertex_groups.active
        active_name = active_vg.name
        
        mirror_name = get_mirror_group_name(active_name)
        if not mirror_name:
            self.report({'WARNING'}, "Active group doesn't have L/R suffix")
            return {'CANCELLED'}
        
        # Ищем и выбираем зеркальную группу
        mirror_vg = obj.vertex_groups.get(mirror_name)
        if mirror_vg:
            obj.vertex_groups.active = mirror_vg
            self.report({'INFO'}, f"Selected {mirror_name}")
        else:
            self.report({'WARNING'}, f"Mirror group {mirror_name} not found")
            
        return {'FINISHED'}

class TT_OT_SelectVertexGroup(Operator):
    bl_idname = "tiny_tools.select_vertex_group"
    bl_label = "Select Vertex Group"
    bl_description = "Select this vertex group"
    
    group_name: bpy.props.StringProperty() # type: ignore
    
    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            return {'CANCELLED'}
            
        vg = obj.vertex_groups.get(self.group_name)
        if vg:
            obj.vertex_groups.active = vg
            
        return {'FINISHED'}

class TT_OT_SwapMirrorDirection(Operator):
    bl_idname = "tiny_tools.swap_mirror_direction"
    bl_label = "Swap Mirror Direction"
    bl_description = "Swap mirror direction (L↔R)"
    
    def execute(self, context):
        props = context.scene.tiny_tools_props
        
        if props.vertex.mirror_direction == 'L_TO_R':
            props.vertex.mirror_direction = 'R_TO_L'
        else:
            props.vertex.mirror_direction = 'L_TO_R'
        
        return {'FINISHED'}

def _leave_edit_mode(context):
    """Веса читаются/пишутся из данных меша: из Edit Mode выходим на время операции. Возвращает, надо ли вернуться."""
    if context.mode == 'EDIT_MESH':
        bpy.ops.object.mode_set(mode='OBJECT')
        return True
    return False


class TT_OT_TransferPick(Operator):
    bl_idname = "tiny_tools.transfer_pick"
    bl_label = "Pick Meshes"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    mode: bpy.props.EnumProperty(items=[
        ('SELECTED', "Selected → Active", "From = the other selected mesh, To = the active mesh"),
        ('SOURCE', "Active as From", "Use the active mesh as From"),
        ('TARGET', "Active as To", "Use the active mesh as To"),
        ('SWAP', "Swap", "Swap From and To")])

    @classmethod
    def description(cls, context, properties):
        return {'SELECTED': "From = the other selected mesh, To = the active mesh (select the source, then the target)",
                'SOURCE': "Use the active mesh as From", 'TARGET': "Use the active mesh as To",
                'SWAP': "Swap From and To"}[properties.mode]

    def execute(self, context):
        v = context.scene.tiny_tools_props.vertex
        if self.mode == 'SWAP':
            v.transfer_source, v.transfer_target = v.transfer_target, v.transfer_source
            return {'FINISHED'}
        act = context.active_object
        if not act or act.type != 'MESH':
            self.report({'WARNING'}, "Active object is not a mesh")
            return {'CANCELLED'}
        if self.mode == 'SOURCE':
            v.transfer_source = act
        elif self.mode == 'TARGET':
            v.transfer_target = act
        else:
            others = [o for o in context.selected_objects if o.type == 'MESH' and o != act]
            if len(others) != 1:
                self.report({'WARNING'}, "Select exactly two meshes: the source, then the target (active)")
                return {'CANCELLED'}
            v.transfer_source, v.transfer_target = others[0], act
        return {'FINISHED'}


classes = (
    TT_OT_TransferWeights,
    TT_OT_TransferPick,
    TT_OT_SmoothWeights,
    TT_OT_MirrorVertexGroups,
    TT_OT_SelectMirrorGroup,
    TT_OT_SelectVertexGroup,
    TT_OT_SwapMirrorDirection,
)
