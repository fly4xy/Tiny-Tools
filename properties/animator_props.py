from bpy.props import IntProperty, BoolProperty, StringProperty, EnumProperty
from bpy.types import PropertyGroup

# pyright: reportInvalidTypeForm=false


class TinyToolsAnimatorProps(PropertyGroup):
    nudge_step: IntProperty(name="Step", default=1, min=1, description="Frames to move keys per click")

    bake_step: IntProperty(name="Bake Step", default=2, min=1, max=100,
                           description="Key every N frames: 1 = on ones, 2 = on twos...")
    bake_stepped: BoolProperty(name="Stepped", default=True,
                               description="Constant interpolation between baked keys (stop-motion look)")

    share_remove_others: BoolProperty(name="Remove Other Keys", default=False,
                                      description="Also delete target keys that are not on the source key times")

    offset_frames: IntProperty(name="Offset", default=0, description="Frames to shift every selected bone/object")
    offset_cascade: IntProperty(name="Cascade", default=2,
                                description="Extra frames per next item in the chain (parent to child)")

    mirror_direction: EnumProperty(
        name="Mirror Direction",
        items=[('L_TO_R', "L > R", "Left side drives the right side"),
               ('R_TO_L', "R > L", "Right side drives the left side"),
               ('SWAP', "Swap", "Exchange sides; center bones are flipped")],
        default='L_TO_R')

    clean_playback: BoolProperty(name="Clean Playback", default=False,
                                 description="Hide overlays and gizmos in 3D views while the animation plays")

    temp_pivot_prev: StringProperty(default="")  # pivot point до включения Temp Pivot ("" = выключен)

