from bpy.types import Operator
from ..utils.armature_utils import clean_unused_fcurves
from ..utils.vertex_utils import clean_vertex_groups_across_scene

class HT_OT_CleanAnimations(Operator):
    bl_idname = "tiny_tools.clean_animations"
    bl_label = "Clean Unused Animation Data"
    bl_description = "Remove F-curves that reference non-existing bones"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        removed = clean_unused_fcurves()
        self.report({'INFO'}, f"Removed {removed} unused fcurves")
        return {'FINISHED'}

class HT_OT_CleanVertexGroups(Operator):
    bl_idname = "tiny_tools.clean_vertex_groups"
    bl_label = "Clean Vertex Groups"
    bl_description = "Remove vertex groups that don't match bones in armature modifiers (except TEMP_ groups)"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        try:
            cleaned_count = clean_vertex_groups_across_scene()
            self.report({'INFO'}, f"Cleaned {cleaned_count} vertex groups across scene")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to clean vertex groups: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

classes = (
    HT_OT_CleanAnimations,
    HT_OT_CleanVertexGroups,
)
