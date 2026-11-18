import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty
from bpy.types import PropertyGroup

# pyright: reportInvalidTypeForm=false

class TinyToolsVerificationProps(PropertyGroup):
    def get_verification_scroll(self):
        return min(self.verification_scroll_raw, self.verification_scroll_max)

    def set_verification_scroll(self, value):
        self.verification_scroll_raw = max(0, min(value, self.verification_scroll_max))

    verification_scroll_max: IntProperty(default=0)
    verification_scroll_raw: IntProperty(default=0)

    verification_scroll: IntProperty(
        name="Verification Scroll", 
        description="Scroll position for verification results",
        default=0,
        min=0,
        get=get_verification_scroll,
        set=set_verification_scroll
    )

    verification_result: StringProperty(
        name="Verification Result",
        description="Results of JSON verification", 
        default="",
        subtype='NONE'
    )
    
    show_verification_results: BoolProperty(
        name="Show Verification Results",
        description="Show or hide verification results",
        default=True
    )
    
    verification_max_lines: IntProperty(
        name="Max Lines",
        description="Maximum lines to show",
        default=15,
        min=1,
        max=100
    )