import bpy
from .anim_compat import get_fcurves, get_groups, new_fcurve

_keyframe_cache = {}

def is_action_compatible(action, obj):
    """Проверяет совместимость экшена с объектом по костям (минимум 50% костей должны совпадать)"""
    # 1. Извлекаем ВСЕ уникальные имена костей из экшена
    action_bones = extract_bones_from_action(action)
    
    if not action_bones:
        return False  # В экшене нет костей
    
    # 2. Проверяем тип объекта
    if obj.type != 'ARMATURE':
        return False
        
    # 3. Получаем кости арматуры
    armature_bones = {bone.name for bone in obj.data.bones}
    
    # 4. Считаем совпадения
    matched_bones = action_bones.intersection(armature_bones)
    match_percentage = len(matched_bones) / len(action_bones)
    
    return match_percentage >= 0.5

def extract_bones_from_action(action):
    """Извлекает все уникальные имена костей из экшена"""
    bone_names = set()
    for fcurve in get_fcurves(action):
        bone_name = extract_bone_name(fcurve.data_path)
        if bone_name:
            bone_names.add(bone_name)
    return bone_names

def extract_bone_name(data_path):
    """Извлекает имя кости из data_path"""
    if 'pose.bones["' in data_path:
        return data_path.split('pose.bones["')[1].split('"]')[0]
    return None

def find_target_object_for_action(action, context):
    """Находит подходящий объект для применения экшена по приоритетам"""
    # 1. Проверяем активный объект
    active_obj = context.active_object
    if active_obj and is_action_compatible(action, active_obj):
        return active_obj
    
    # 2. Для мешей проверяем арматуру из модификаторов
    if active_obj and active_obj.type == 'MESH':
        armature_obj = find_armature_from_modifiers(active_obj)
        if armature_obj and is_action_compatible(action, armature_obj):
            return armature_obj
        
        # Проверяем сам меш (если экшен для меша, а не для костей)
        if is_action_compatible(action, active_obj):
            return active_obj
    
    # 3. Ищем единственный скелет в сцене
    armatures = [obj for obj in context.scene.objects if obj.type == 'ARMATURE']
    if len(armatures) == 1:
        single_armature = armatures[0]
        if is_action_compatible(action, single_armature):
            return single_armature
    
    return None

def find_armature_from_modifiers(mesh_obj):
    """Находит арматуру из модификаторов меша"""
    for mod in mesh_obj.modifiers:
        if mod.type == 'ARMATURE' and mod.object:
            return mod.object
    return None

def soft_copy_keyframes(action, frame, tolerance=0.001):
    """Копирует только существующие ключи в указанном кадре"""
    keyframe_data = {}
    
    for fcurve in get_fcurves(action):
        # Ищем ключ в указанном кадре
        for keyframe in fcurve.keyframe_points:
            if abs(keyframe.co.x - frame) < tolerance:
                # СОСТАВНОЙ КЛЮЧ: data_path + array_index
                key_id = f"{fcurve.data_path}|{fcurve.array_index}"
                keyframe_data[key_id] = {
                    'data_path': fcurve.data_path,
                    'array_index': fcurve.array_index,
                    'value': keyframe.co.y,
                    # хэндлы — смещением от ключа: при вставке на другой кадр они переезжают вместе с ним
                    'handle_left': keyframe.handle_left - keyframe.co,
                    'handle_right': keyframe.handle_right - keyframe.co,
                    'handle_types': (keyframe.handle_left_type, keyframe.handle_right_type),
                    'interpolation': keyframe.interpolation,
                    'type': keyframe.type
                }
                break
    
    return keyframe_data

def hard_copy_keyframes(action, frame):
    """Вычисляет значения всех параметров в указанном кадре (виртуальные ключи)"""
    keyframe_data = {}
    
    for fcurve in get_fcurves(action):
        try:
            value = fcurve.evaluate(frame)
            # СОСТАВНОЙ КЛЮЧ
            key_id = f"{fcurve.data_path}|{fcurve.array_index}"
            keyframe_data[key_id] = {
                'data_path': fcurve.data_path,
                'array_index': fcurve.array_index,
                'value': value,
                'interpolation': 'BEZIER'
            }
        except:
            continue
    
    return keyframe_data

def paste_keyframes(action, frame, keyframe_data):
    """Вставляет ключевые кадры в указанный кадр только для незаблокированных костей"""
    pasted_count = 0
    
    for key_id, key_data in keyframe_data.items():
        data_path = key_data['data_path']
        
        # ПРОВЕРЯЕМ БЛОКИРОВКУ КОСТИ ЧЕРЕЗ ГРУППЫ ДЕЙСТВИЙ
        if is_bone_locked(data_path, action):
            print(f"Skipping locked bone: {data_path}")
            continue
        
        # Находим или создаем fcurve
        fcurve = None
        for fc in get_fcurves(action):
            if (fc.data_path == data_path and 
                fc.array_index == key_data['array_index']):
                fcurve = fc
                break
        
        if not fcurve:
            fcurve = new_fcurve(action, data_path, index=key_data['array_index'])
        
        # Добавляем ключевой кадр
        keyframe = fcurve.keyframe_points.insert(frame, key_data['value'])
        keyframe.interpolation = key_data.get('interpolation', 'BEZIER')
        
        if 'handle_types' in key_data:
            keyframe.handle_left_type, keyframe.handle_right_type = key_data['handle_types']
        if 'handle_left' in key_data:
            keyframe.handle_left = keyframe.co + key_data['handle_left']
            keyframe.handle_right = keyframe.co + key_data['handle_right']
        if 'type' in key_data:
            keyframe.type = key_data['type']
        
        pasted_count += 1
    
    # Обновляем fcurves
    for fcurve in get_fcurves(action):
        fcurve.update()
    
    print(f"Pasted {pasted_count} keys (skipped {len(keyframe_data) - pasted_count} locked bones)")
    return pasted_count

def is_bone_locked(data_path, action):
    """Проверяет заблокирована ли кость через группы действий"""
    if 'pose.bones[' not in data_path:
        return False
    
    try:
        # Извлекаем имя кости из data_path
        bone_name = data_path.split('pose.bones["')[1].split('"]')[0]
        
        # Ищем группу с именем кости в действии
        for group in get_groups(action):
            if group.name == bone_name and group.lock:
                print(f"Bone {bone_name} is locked via action group")
                return True
                
    except (IndexError, KeyError, AttributeError) as e:
        print(f"Error checking bone lock: {e}")
    
    return False


def cache_keyframes(keyframe_data, cache_key="default"):
    _keyframe_cache[cache_key] = keyframe_data

def get_cached_keyframes(cache_key="default"):
    return _keyframe_cache.get(cache_key)

def clear_keyframe_cache(cache_key=None):
    global _keyframe_cache
    if cache_key:
        if cache_key in _keyframe_cache:
            del _keyframe_cache[cache_key]
    else:
        _keyframe_cache.clear()
