import bpy
from bpy.props import StringProperty, EnumProperty, BoolProperty, IntProperty, CollectionProperty
from bpy.types import PropertyGroup

# pyright: reportInvalidTypeForm=false

from ..preferences import ADDON_NAME

class AnimationItem(PropertyGroup):
    name: StringProperty(name="Animation Name", default="")
    frame_start: IntProperty(name="Start Frame", default=0)
    frame_end: IntProperty(name="End Frame", default=0)
    exists_in_blend: BoolProperty(default=False)
    select: BoolProperty(name="Select", default=False)

class TinyToolsProps(PropertyGroup):
    # Основные UI свойства
    show_verification_results: BoolProperty(default=False)
    bone_select_link: BoolProperty(
        name="Bone Select Link",
        description="Sync bone selection between 3D View and Outliner",
        default=True
    )

    # Общие свойства
    show_tooltips: BoolProperty(
        name="Show Tooltips",
        description="Show tooltips for UI elements",
        default=True
    )

    tooltip_language: EnumProperty(
        name="Tooltip Language",
        items=[
            ('EN', "English", "Show tooltips in English"),
            ('RU', "Russian", "Show tooltips in Russian"),
            ('ZH', "Chinese", "Show tooltips in Chinese"),
        ],
        default='EN'
    )

    # Флаг для отслеживания применения глобальных настроек
    global_settings_applied: BoolProperty(default=False)

    def _get_addon_prefs(self):
        """Безопасное получение настроек аддона"""
        try:
            return bpy.context.preferences.addons[ADDON_NAME].preferences
        except:
            return None

    def apply_global_settings(self):
        """Применяет глобальные настройки для нового проекта"""
        if self.global_settings_applied:
            return
        addon_prefs = self._get_addon_prefs()
        if addon_prefs and not bpy.data.filepath:  # Только для новых проектов
            # Основные UI свойства
            self.bone_select_link = addon_prefs.bone_select_link
            
            # Общие свойства
            self.show_tooltips = addon_prefs.show_tooltips
            self.tooltip_language = addon_prefs.tooltip_language
            
            self.global_settings_applied = True