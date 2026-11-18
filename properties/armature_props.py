import bpy
from bpy.props import StringProperty, EnumProperty, BoolProperty
from bpy.types import PropertyGroup
from ..utils.armature_utils import list_armatures

# pyright: reportInvalidTypeForm=false

class TinyToolsArmatureProps(PropertyGroup):
    source_armature: EnumProperty(
        name="Source Armature",
        description="Armature to backup from",
        items=list_armatures
    )
    
    target_armature: EnumProperty(
        name="Target Armature", 
        description="Armature to restore to (only armatures shown)",
        items=list_armatures
    )

    json_path: StringProperty(name="JSON File", subtype='FILE_PATH', default="")
