import bpy

from .main_panel import PANELS, TT_UL_LoadedAnimationsList
from ..preferences import ADDON_NAME


def register():
    bpy.utils.register_class(TT_UL_LoadedAnimationsList)
    try:
        prefs = bpy.context.preferences.addons[ADDON_NAME].preferences
    except KeyError:  # первое включение: настройки ещё не созданы — все секции закрыты
        prefs = None
    for cls in PANELS:
        if getattr(cls, "pref_prop", ""):
            cls.bl_options = set() if prefs and getattr(prefs, cls.pref_prop) else {'DEFAULT_CLOSED'}
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(PANELS):
        bpy.utils.unregister_class(cls)
    bpy.utils.unregister_class(TT_UL_LoadedAnimationsList)
