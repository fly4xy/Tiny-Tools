import bpy
from bpy.types import Operator
from ..utils.file_utils import verify_skeleton_with_json

class TT_OT_VerifyWithJson(Operator):
    bl_idname = "tiny_tools.verify_with_json"
    bl_label = "Verify with JSON"
    bl_description = "Compare current armature with JSON file and show differences"

    def execute(self, context):
        props = context.scene.tiny_tools_props
        json_path = props.armature.json_path

        if not json_path:
            self.report({'ERROR'}, "JSON файл не выбран")
            return {'CANCELLED'}

        target_name = props.armature.target_armature
        if not target_name or target_name == "NONE" or target_name not in bpy.data.objects:
            self.report({'ERROR'}, "Target armature not selected or not found")
            return {'CANCELLED'}

        try:
            arm_obj = bpy.data.objects[target_name]
            result = verify_skeleton_with_json(arm_obj, bpy.path.abspath(json_path))
            
            # Форматируем результат как простой текст
            result_text = self.format_verification_result(result)
            props.verification.verification_result = result_text
            bpy.ops.tiny_tools.update_scroll_max()
            
            # Автоматически корректируем скролл
            lines = result_text.split('\n')
            max_scroll = max(0, len(lines) - props.verification.verification_max_lines)
            props.verification.verification_scroll_max = max_scroll
            props.verification.verification_scroll = 0
            
            self.report({'INFO'}, f"Verification complete: {result['total_errors']} errors found")
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed to verify: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

    def format_verification_result(self, result):
        """Форматирует результаты проверки для отображения в UI"""
        lines = []
        total_errors = result['total_errors']
        
        if total_errors == 0:
            lines.append("✓ Perfect match! No errors found.")
            return "\n".join(lines)
        
        lines.append(f"Found {total_errors} errors:")
        lines.append("")
        
        # Ошибки костей
        if result["bone_errors"]:
            lines.append("BONE ERRORS:")
            for bone_name, errors in result["bone_errors"].items():
                lines.append(f"  {bone_name}:")
                for error in errors:
                    lines.append(f"    - {error}")
            lines.append("")
        
        # Ошибки констрейнтов
        if result["constraint_errors"]:
            lines.append("CONSTRAINT ERRORS:")
            for bone_name, errors in result["constraint_errors"].items():
                lines.append(f"  {bone_name}:")
                for error in errors:
                    lines.append(f"    - {error}")
        
        return "\n".join(lines)

class TT_OT_ClearVerificationLog(Operator):
    bl_idname = "tiny_tools.clear_verification_log"
    bl_label = "Clear Verification Log"
    bl_description = "Clear verification results"

    def execute(self, context):
        props = context.scene.tiny_tools_props
        props.verification.verification_result = ""
        bpy.ops.tiny_tools.update_scroll_max()
        props.verification.verification_scroll = 0
        return {'FINISHED'}

class TT_OT_ScrollVerificationUp(Operator):
    bl_idname = "tiny_tools.scroll_verification_up"
    bl_label = "Scroll Up"
    bl_description = "Scroll verification results up"

    def execute(self, context):
        props = context.scene.tiny_tools_props
        if props.verification.verification_scroll > 0:
            props.verification.verification_scroll -= 1
        return {'FINISHED'}

class TT_OT_ScrollVerificationDown(Operator):
    bl_idname = "tiny_tools.scroll_verification_down"
    bl_label = "Scroll Down"
    bl_description = "Scroll verification results down"

    def execute(self, context):
        props = context.scene.tiny_tools_props
        lines = props.verification.verification_result.split('\n')
        max_scroll = max(0, len(lines) - props.verification.verification_max_lines)
        if props.verification.verification_scroll < max_scroll:
            props.verification.verification_scroll += 1
        return {'FINISHED'}

class TT_OT_CorrectScroll(Operator):
    """Оператор для коррекции скролла"""
    bl_idname = "tiny_tools.correct_scroll"
    bl_label = "Correct Scroll"
    bl_description = "Correct scroll position"
    
    def execute(self, context):
        props = context.scene.tiny_tools_props
        if props.verification.verification_result:
            lines = props.verification.verification_result.split('\n')
            max_scroll = max(0, len(lines) - props.verification.verification_max_lines)
            props.verification.verification_scroll = min(props.verification.verification_scroll, max_scroll)
        return {'FINISHED'}
    
class TT_OT_UpdateScrollMax(Operator):
    bl_idname = "tiny_tools.update_scroll_max"
    bl_label = "Update Scroll Max"
    
    def execute(self, context):
        props = context.scene.tiny_tools_props
        if props.verification.verification_result:
            lines = props.verification.verification_result.split('\n')
            max_scroll = max(0, len(lines) - props.verification.verification_max_lines)
            props.verification.verification_scroll_max = max_scroll
        return {'FINISHED'}

classes = (
    TT_OT_VerifyWithJson,
    TT_OT_ClearVerificationLog,
    TT_OT_ScrollVerificationUp,
    TT_OT_ScrollVerificationDown,
    TT_OT_CorrectScroll,
    TT_OT_UpdateScrollMax,
)