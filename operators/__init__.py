import bpy
from bpy.app.handlers import persistent 
from . import armature_ops, cleanup_ops, verification_ops, vertex_ops, animator_ops

_bone_select_auto_started = False

classes = (
    *armature_ops.classes,
    *cleanup_ops.classes, 
    *verification_ops.classes,
    *vertex_ops.classes,
    *animator_ops.classes,
)

@persistent
def start_bone_select_link_if_needed(dummy):
    """Persistent handler: schedule a delayed check to auto-start bone-select link if enabled."""
    # Reset flag and schedule delayed starter
    global _bone_select_auto_started
    _bone_select_auto_started = False
    bpy.app.timers.register(start_bone_select_delayed, first_interval=1.0)


def start_bone_select_delayed():
    """Delayed starter called by timer: checks props and starts operator if needed."""
    global _bone_select_auto_started
    try:
        if not bpy.context.scene:
            return 2.0

        props = getattr(bpy.context.scene, 'tiny_tools_props', None)
        if not props:
            return 2.0

        # Запускаем только если опция включена и еще не запускали
        if props.bone_select_link and not _bone_select_auto_started:
            from .armature_ops import TT_OT_BoneSelectLink
            if not TT_OT_BoneSelectLink._running:
                print("Auto-starting Bone Select Link")
                bpy.ops.tiny_tools.bone_select_link('EXEC_DEFAULT')
                _bone_select_auto_started = True

        return None

    except Exception as e:
        print(f"Error auto-starting bone select: {e}")
        return 2.0
    
def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Только ОДИН обработчик - load_post
    if start_bone_select_link_if_needed not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(start_bone_select_link_if_needed)
    for handlers, fn in animator_ops.HANDLERS:
        if fn not in handlers:
            handlers.append(fn)

def unregister():
    for handlers, fn in animator_ops.HANDLERS:
        if fn in handlers:
            handlers.remove(fn)
    if start_bone_select_link_if_needed in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(start_bone_select_link_if_needed)
    if bpy.app.timers.is_registered(start_bone_select_delayed):
        bpy.app.timers.unregister(start_bone_select_delayed)
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)