from . import main_props, armature_props, animation_props, vertex_props, verification_props, pose_master_props, animator_props
import bpy

classes = (
    main_props.AnimationItem,
    armature_props.TinyToolsArmatureProps,
    animation_props.TinyToolsAnimationProps,
    vertex_props.TinyToolsVertexProps,
    verification_props.TinyToolsVerificationProps,
    main_props.TinyToolsProps,
    pose_master_props.TinyToolsPoseMasterProps,
    animator_props.TinyToolsAnimatorProps,
)

def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    from ..utils.ui_utils import TT_OT_SetTooltipLanguage, TT_OT_ToggleTooltip
    register_class(TT_OT_SetTooltipLanguage)
    register_class(TT_OT_ToggleTooltip)
    
    from bpy.types import Scene
    Scene.tiny_tools_props = bpy.props.PointerProperty(type=main_props.TinyToolsProps)

    main_props.TinyToolsProps.armature = bpy.props.PointerProperty(
        type=armature_props.TinyToolsArmatureProps
    )
    main_props.TinyToolsProps.animation = bpy.props.PointerProperty(
        type=animation_props.TinyToolsAnimationProps
    )
    main_props.TinyToolsProps.vertex = bpy.props.PointerProperty(
        type=vertex_props.TinyToolsVertexProps
    )
    main_props.TinyToolsProps.verification = bpy.props.PointerProperty(
        type=verification_props.TinyToolsVerificationProps
    )
    main_props.TinyToolsProps.pose_master = bpy.props.PointerProperty(
        type=pose_master_props.TinyToolsPoseMasterProps
    )
    main_props.TinyToolsProps.animator = bpy.props.PointerProperty(
        type=animator_props.TinyToolsAnimatorProps
    )

    if not hasattr(bpy.types.Action, "select"):
        bpy.types.Action.select = bpy.props.BoolProperty(
            name="Select Action",
            description="Select action for batch operations",
            default=False
        )

def unregister():
    from bpy.utils import unregister_class
    from bpy.types import Scene

    from ..utils.ui_utils import TT_OT_SetTooltipLanguage, TT_OT_ToggleTooltip
    unregister_class(TT_OT_ToggleTooltip)
    unregister_class(TT_OT_SetTooltipLanguage)
    
    if hasattr(Scene, "tiny_tools_props"):
        del Scene.tiny_tools_props

    try:
        del main_props.TinyToolsProps.armature
    except Exception:
        pass
    try:
        del main_props.TinyToolsProps.animation
    except Exception:
        pass
    try:
        del main_props.TinyToolsProps.vertex
    except Exception:
        pass
    try:
        del main_props.TinyToolsProps.verification
    except Exception:
        pass
    for name in ("pose_master", "animator"):
        try:
            delattr(main_props.TinyToolsProps, name)
        except Exception:
            pass
    
    if hasattr(bpy.types.Action, "select"):
        del bpy.types.Action.select
    
    for cls in reversed(classes):
        unregister_class(cls)