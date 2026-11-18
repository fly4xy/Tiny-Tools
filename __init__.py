# ====================== BEGIN GPL LICENSE BLOCK ============================
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	 See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.	 If not, see <http://www.gnu.org/licenses/>.
#  All rights reserved.
#
# ======================= END GPL LICENSE BLOCK =============================

bl_info = {
    "name": "Tiny Tools",
    "author": "Lis Carter", 
    "version": (1, 5, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Tiny Tools",
    "description": "Professional rigging and animation toolkit with armature management, pose mastering, animation tools, and vertex weight symmetrizing",
    "category": "Rigging",
    "tracker_url": "https://github.com/fly4xy/Tiny-Tools/issues",
    "doc_url": "https://lis-carter.site/tiny-tools/docs"
}

import bpy, traceback

# import sys
# sys.dont_write_bytecode = True #Дебажная шняга. Отключаем сборку бинарников

from . import operators, panels, properties, utils, preferences

modules = (
    properties,
    utils,
    operators,
    preferences,
    panels,
)

@bpy.app.handlers.persistent
def load_handler(dummy):
    """Initialize properties after file load"""
    try:
        if hasattr(bpy.context.scene, 'tiny_tools_props'):
            bpy.context.scene.tiny_tools_props.is_initialized = True
    except Exception as e:
        print(f"Tiny Tools load handler error: {e}")

@bpy.app.handlers.persistent
def apply_global_settings_on_load(dummy):
    """Применяет глобальные настройки при загрузке нового файла"""
    if hasattr(bpy.context.scene, 'tiny_tools_props') and not bpy.data.filepath:
        props = bpy.context.scene.tiny_tools_props
        props.apply_global_settings()

def register():
    """Register all modules"""
    if load_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_handler)
    
    try:
        for module in modules:
            if hasattr(module, 'register'):
                module.register()
        print("✅ Tiny Tools registered successfully")
                
    except Exception as e:
        print(f"❌ Tiny Tools registration failed: {e}")
        traceback.print_exc()
        unregister()
        raise
    
    if apply_global_settings_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(apply_global_settings_on_load)

def unregister():
    """Unregister all modules"""
    if apply_global_settings_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(apply_global_settings_on_load)

    if load_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_handler)
    
    for module in reversed(modules):
        if hasattr(module, 'unregister'):
            try:
                module.unregister()
            except Exception as e:
                print(f"Warning: Failed to unregister {module.__name__}: {e}")

if __name__ == "__main__":
    register()