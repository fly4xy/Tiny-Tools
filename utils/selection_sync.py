import bpy

def focus_on_selected_bone_in_outliner():
    """Фокусирует аутлайнер на выделенной кости в Pose Mode или Edit Mode"""
    
    # Проверяем оба режима
    if bpy.context.mode not in ['POSE', 'EDIT_ARMATURE']:
        return False
    
    # Получаем активную кость в зависимости от режима
    active_bone = None
    armature_obj = None
    bone_name = None
    
    if bpy.context.mode == 'POSE':
        if bpy.context.active_pose_bone:
            active_bone = bpy.context.active_pose_bone
            armature_obj = active_bone.id_data
            bone_name = active_bone.name
        elif bpy.context.selected_pose_bones:
            active_bone = bpy.context.selected_pose_bones[0]
            armature_obj = active_bone.id_data
            bone_name = active_bone.name
    
    elif bpy.context.mode == 'EDIT_ARMATURE':
        if bpy.context.active_bone:
            active_bone = bpy.context.active_bone
            armature_obj = bpy.context.active_object
            bone_name = active_bone.name
        elif bpy.context.selected_bones:
            active_bone = bpy.context.selected_bones[0]
            armature_obj = bpy.context.active_object
            bone_name = active_bone.name
    
    if not bone_name or not armature_obj:
        return False
    
    # Ищем аутлайнер для переопределения контекста
    override = None
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'OUTLINER':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        override = {
                            'window': window,
                            'area': area, 
                            'region': region,
                            'scene': bpy.context.scene,
                            'view_layer': bpy.context.view_layer
                        }
                        break
                if override:
                    break
        if override:
            break
    
    if not override:
        return False
    
    # Устанавливаем активный объект (арматуру)
    bpy.context.view_layer.objects.active = armature_obj
    
    # Устанавливаем активную кость по имени (работает в любом режиме)
    if bone_name in armature_obj.data.bones:
        armature_obj.data.bones.active = armature_obj.data.bones[bone_name]
    
    # Фокусируем аутлайнер на активной кости
    try:
        with bpy.context.temp_override(**override):
            bpy.ops.outliner.show_active()
        return True
    except Exception as e:
        print(f"Error due Focusing: {e}")
        return False