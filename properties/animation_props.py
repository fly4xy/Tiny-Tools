import bpy
from bpy.props import StringProperty, EnumProperty, BoolProperty, IntProperty, CollectionProperty, FloatProperty
from bpy.types import PropertyGroup
from .main_props import AnimationItem

# pyright: reportInvalidTypeForm=false

def update_select_all_animations(self, context):
    """Update function for select_all_animations"""
    for action in bpy.data.actions:
        if hasattr(action, "select"):
            action.select = self.select_all_animations

def update_select_all_loaded_animations(self, context):
    """Update function for select_all_loaded_animations"""
    for item in self.loaded_animations_list:
        item.select = self.select_all_loaded_animations

class TinyToolsAnimationProps(PropertyGroup):
    animation_list: CollectionProperty(type=AnimationItem)
    animation_rename_new_name: StringProperty(name="New Name", default="")
    animation_search: StringProperty(name="Search", default="")

    animation_columns: EnumProperty(
        name="Columns",
        description="Number of columns for animations display",
        items=[
            ('1', "1 Column", "Display in 1 column"),
            ('2', "2 Columns", "Display in 2 columns"), 
            ('3', "3 Columns", "Display in 3 columns"),
            ('4', "4 Columns", "Display in 4 columns"),
        ],
        default='2'
    )
    
    select_all_loaded_animations: BoolProperty(
        name="Select All",
        description="Select or deselect all loaded animations",
        default=False,
        update=update_select_all_loaded_animations
    )

    select_all_animations: BoolProperty(
        name="Select All Animations",
        description="Select or deselect all animations",
        default=False,
        update=update_select_all_animations
    )

    loaded_animations_list: CollectionProperty(type=AnimationItem)
    loaded_animations_list_index: IntProperty(name="Loaded Animation Index", default=0)
    show_loaded_animations: BoolProperty(default=False)
    
    animation_import_mode: EnumProperty(
        name="Import Mode",
        items=[
            ('REPLACE', "Import Replaced", "Replace existing actions with same names"),
            ('NEW_ONLY', "Import Only New", "Import only animations that don't exist"),
            ('COPY', "Import as Copy", "Copy selected animations with _COPY suffix"),
        ],
        default='NEW_ONLY'
    )
    
    animation_json_path: StringProperty(name="Animation JSON File", subtype='FILE_PATH', default="")

    # ---------- Экспорт анимаций: бэкап или FBX для движков ----------
    anim_export_format: EnumProperty(
        name="Export As",
        items=[('BACKUP', "Backup (GZIP)", "Tiny Tools backup: exact curves, re-import into Blender"),
               ('FBX', "Animations (FBX)", "Skeleton + animation without meshes, one file per animation — for game engines")],
        default='BACKUP')

    fbx_preset: EnumProperty(
        name="Preset",
        items=[('UE5', "Unreal Engine 5", "Deform bones only, no leaf bones, exact (unsimplified) curves, FBX units"),
               ('BLENDER', "Blender", "All bones, Blender scale, light curve simplification")],
        default='UE5',
        update=lambda self, context: apply_fbx_preset(self))
    fbx_add_root: BoolProperty(
        name="Add Root", default=False,
        description="Keep the armature object as an extra root bone. Off: the armature is exported as 'Armature', "
                    "which Unreal skips, so no new root bone is added")
    fbx_prefix: StringProperty(name="Prefix", default="SA_", description="Added to every file name (empty — none)")
    fbx_deform_only: BoolProperty(name="Deform Bones Only", default=True,
                                  description="Skip control/IK/helper bones that do not deform meshes")
    fbx_leaf_bones: BoolProperty(name="Add Leaf Bones", default=False,
                                 description="Extra end bones at chain tips (not needed for Unreal)")
    fbx_simplify: FloatProperty(name="Simplify", default=0.0, min=0.0, max=100.0,
                                description="Curve simplification: 0 — key on every frame (exact, recommended for UE5)")
    fbx_apply_scale: EnumProperty(
        name="Apply Scalings",
        items=[('FBX_SCALE_NONE', "All Local", ""), ('FBX_SCALE_UNITS', "FBX Units Scale", ""),
               ('FBX_SCALE_CUSTOM', "FBX Custom Scale", ""), ('FBX_SCALE_ALL', "FBX All", "")],
        default='FBX_SCALE_UNITS')
    fbx_global_scale: FloatProperty(name="Scale", default=1.0, min=0.001, max=1000.0)
    fbx_force_startend: BoolProperty(name="Key Start/End", default=True,
                                     description="Always key the first and last frame of the animation")
    fbx_export_dir: StringProperty(name="Folder", subtype='DIR_PATH', default="",
                                   description="Where to save FBX files (empty — BACKUP_<file>/FBX next to the .blend)")


def apply_fbx_preset(p):
    if p.fbx_preset == 'UE5':
        p.fbx_deform_only, p.fbx_leaf_bones, p.fbx_simplify, p.fbx_apply_scale = True, False, 0.0, 'FBX_SCALE_UNITS'
    else:
        p.fbx_deform_only, p.fbx_leaf_bones, p.fbx_simplify, p.fbx_apply_scale = False, False, 1.0, 'FBX_SCALE_NONE'
    p.fbx_global_scale, p.fbx_force_startend = 1.0, True
