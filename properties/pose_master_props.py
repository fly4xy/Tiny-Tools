
from bpy.props import StringProperty, EnumProperty, BoolProperty, IntProperty, CollectionProperty
from bpy.types import PropertyGroup

# pyright: reportInvalidTypeForm=false

class TinyToolsPoseMasterProps(PropertyGroup):
    """Properties for Pose Master tool"""
    
    pose_target_armature: StringProperty(
        name="Target Armature",
        default="",
        description="Armature to apply pose to"
    )
    
    pose_verification_status: EnumProperty(
        name="Verification Status",
        items=[
            ('NOT_CHECKED', "Not Checked", "Armature not verified yet"),
            ('VALID', "Valid", "Armature matches JSON structure"),
            ('INVALID', "Invalid", "Armature doesn't match JSON structure"),
        ],
        default='NOT_CHECKED'
    )

    ignore_constraints: BoolProperty(
        name="Ignore Constraints",
        default=True,
        description="Temporarily remove constraints during pose application"
    )
    
    pose_verification_message: StringProperty(
        name="Verification Message",
        default="",
        description="Verification result message"
    )
    
    adapt_selected_animations: BoolProperty(
        name="Adapt Selected Animations to Pose",
        default=False,
        description="Adapt selected animations to the new pose"
    )
    
    selected_animations_count: IntProperty(
        name="Selected Animations Count",
        default=0,
        description="Number of selected animations"
    )
    
    apply_to_linked_meshes: BoolProperty(
        name="Apply Pose to Linked Meshes",
        default=False,
        description="Apply pose to meshes with armature modifier"
    )
    
    linked_meshes_count: IntProperty(
        name="Linked Meshes Count",
        default=0,
        description="Number of linked meshes"
    )
    
    apply_only_to_selected_meshes: BoolProperty(
        name="Apply Only to Selected Meshes",
        default=False,
        description="Apply pose only to selected meshes"
    )
