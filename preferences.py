import bpy
from bpy.types import AddonPreferences, Operator

# pyright: reportInvalidTypeForm=false

ADDON_NAME = __package__  # полное имя пакета: у расширения включает репозиторий

class TT_OT_ResetSettings(Operator):
    """Reset all Tiny Tools settings to default values"""
    bl_idname = "tiny_tools.reset_settings"
    bl_label = "Reset Settings to Defaults"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    def execute(self, context):
        addon_prefs = context.preferences.addons[ADDON_NAME].preferences
        
        # Сбрасываем все свойства
        addon_prefs.show_tooltips = True
        addon_prefs.tooltip_language = 'EN'
        addon_prefs.bone_select_link = True
        
        addon_prefs.show_export_box = False
        addon_prefs.show_import_box = False
        addon_prefs.show_armature_tools = False
        addon_prefs.show_animation_tools = False
        addon_prefs.show_animator_tools = False
        addon_prefs.show_cleanup_tools = False
        addon_prefs.show_mirror_tools = False
        
        self.report({'INFO'}, "Settings reset to defaults")
        return {'FINISHED'}

class TT_AddonPreferences(AddonPreferences):
    bl_idname = ADDON_NAME

    # Глобальные настройки
    show_tooltips: bpy.props.BoolProperty(
        name="Show Tooltips",
        description="Show tooltips for UI elements",
        default=True
    )

    tooltip_language: bpy.props.EnumProperty(
        name="Tooltip Language",
        items=[
            ('EN', "English", "Show tooltips in English"),
            ('RU', "Russian", "Show tooltips in Russian"),
            ('ZH', "Chinese", "Show tooltips in Chinese"),
        ],
        default='EN'
    )

    bone_select_link: bpy.props.BoolProperty(
        name="Bone Select Link",
        description="Sync bone selection between 3D View and Outliner",
        default=True
    )
    
    # Состояния вкладок
    show_export_box: bpy.props.BoolProperty(default=False)
    show_import_box: bpy.props.BoolProperty(default=False)
    show_armature_tools: bpy.props.BoolProperty(default=False)
    show_animation_tools: bpy.props.BoolProperty(default=False)
    show_animator_tools: bpy.props.BoolProperty(default=False)
    show_cleanup_tools: bpy.props.BoolProperty(default=False)
    show_mirror_tools: bpy.props.BoolProperty(default=False)

    def draw(self, context):
        layout = self.layout
        
        # Основные настройки
        box = layout.box()
        box.label(text="General Settings", icon='PREFERENCES')
        box.prop(self, "show_tooltips")
        box.prop(self, "tooltip_language")
        box.prop(self, "bone_select_link")
        
        # Состояния вкладок
        box = layout.box()
        box.label(text="Panels open by default (applies after restart)", icon='TOOL_SETTINGS')
        
        col = box.column(align=True)
        col.prop(self, "show_export_box", text="Export", icon='EXPORT')
        col.prop(self, "show_import_box", text="Import", icon='IMPORT')
        col.prop(self, "show_armature_tools", text="Armature Tools", icon='ARMATURE_DATA')
        col.prop(self, "show_animation_tools", text="Animation Tools", icon='ANIM')
        col.prop(self, "show_animator_tools", text="Animator", icon='ACTION_TWEAK')
        col.prop(self, "show_mirror_tools", text="Weights", icon='MOD_VERTEX_WEIGHT')
        col.prop(self, "show_cleanup_tools", text="Cleanup Tools", icon='BRUSH_DATA')
        
        # Ссылки
        box = layout.box()
        row = box.row(align=True)
        row.operator("wm.url_open", text="Project Page", icon='URL').url = "https://lis-carter.site/tiny-tools/"
        row.operator("wm.url_open", text="Documentation", icon='HELP').url = "https://lis-carter.site/tiny-tools/docs"
        row.operator("wm.url_open", text="Report a Bug", icon='ERROR').url = "https://github.com/fly4xy/Tiny-Tools/issues"

        # Кнопка сброса
        layout.separator()
        row = layout.row()
        row.operator("tiny_tools.reset_settings", icon='FILE_REFRESH')

def register():    
    bpy.utils.register_class(TT_OT_ResetSettings)
    bpy.utils.register_class(TT_AddonPreferences)


def unregister():
    bpy.utils.unregister_class(TT_AddonPreferences)
    bpy.utils.unregister_class(TT_OT_ResetSettings)