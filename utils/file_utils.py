import bpy, json, mathutils, os, gzip
from .modal_job import run
from datetime import datetime
from pathlib import Path
from .anim_compat import get_fcurves, new_fcurve, remove_fcurve

_pose_cache = {}

#Работа с джейсоном скелета

def save_skeleton_to_json(arm_obj: bpy.types.Object, filepath: str):
    """Сохраняет иерархию, трансформы и констрейнты в JSON"""
    # ПРЕОБРАЗУЕМ ПУТЬ В АБСОЛЮТНЫЙ
    abs_filepath = bpy.path.abspath(filepath)
    
    data = {"bones": {}, "constraints": {}}

    # READ Rest Pose (Edit Bones)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')

    for bone in arm_obj.data.edit_bones:
        bone_info = {
            "head": list(bone.head),
            "tail": list(bone.tail),
            "roll": float(bone.roll),
            "length": float((bone.tail - bone.head).length),
            "parent": bone.parent.name if bone.parent else None,
        }
        data["bones"][bone.name] = bone_info

    # READ Constraints from Pose bones
    bpy.ops.object.mode_set(mode='POSE')

    for pb in arm_obj.pose.bones:
        clist = []
        for c in pb.constraints:
            c_data = {"type": c.type, "properties": {}}
            for prop in dir(c):
                if prop.startswith("_"):
                    continue
                if prop in {"bl_rna", "rna_type"}:
                    continue
                try:
                    val = getattr(c, prop)
                except Exception:
                    continue
                if isinstance(val, (int, float, str, bool)):
                    c_data["properties"][prop] = val
                elif isinstance(val, (list, tuple)):
                    try:
                        c_data["properties"][prop] = list(val)
                    except Exception:
                        pass
                elif hasattr(val, "name"):
                    c_data["properties"][prop] = {"__name__": val.name}
            clist.append(c_data)
        data["constraints"][pb.name] = clist

    # Запись в файл с АБСОЛЮТНЫМ путем
    with open(abs_filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    bpy.ops.object.mode_set(mode='OBJECT')

def save_pose_to_cache(arm_obj, cache_key="default"):
    """Сохраняет позу арматуры в кэш (память)"""
    global _pose_cache
    data = {"bones": {}}
    
    # Сохраняем позу костей (аналогично JSON бэкапу)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='POSE')
    
    for bone in arm_obj.pose.bones:
        bone_data = {
            "location": list(bone.location),
            "rotation_quaternion": list(bone.rotation_quaternion) if bone.rotation_mode == 'QUATERNION' else None,
            "rotation_euler": list(bone.rotation_euler) if bone.rotation_mode != 'QUATERNION' else None,
            "scale": list(bone.scale),
            "rotation_mode": bone.rotation_mode
        }
        data["bones"][bone.name] = bone_data
    
    _pose_cache[cache_key] = data
    return True

def load_skeleton_bones_from_json(arm_obj: bpy.types.Object, filepath: str):
    """Восстанавливает только иерархию и положение костей из JSON"""
    abs_filepath = bpy.path.abspath(filepath)

    with open(abs_filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Сохраняем текущие настройки симметрии
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')
    
    original_use_mirror_x = arm_obj.data.use_mirror_x
    arm_obj.data.use_mirror_x = False

    bones = arm_obj.data.edit_bones

    # Разорвём родителей сначала, чтобы безопасно устанавливать
    json_bones = data.get("bones", {})
    for name in json_bones:
        if name in bones:
            bones[name].parent = None

    for name, info in data.get("bones", {}).items():
        if name not in bones:
            continue
        b = bones[name]
        try:
            b.head = info["head"]
            b.tail = info["tail"]
            b.roll = info.get("roll", 0.0)
        except Exception as e:
            print(f"Не удалось установить head/tail/roll для {name}: {e}")

    # Восстанавливаем родителей
    for name, info in data.get("bones", {}).items():
        parent_name = info.get("parent")
        if not parent_name:
            continue
        if name in bones and parent_name in bones:
            bones[name].parent = bones[parent_name]

    # ВОЗВРАЩАЕМ настройки симметрии
    bpy.ops.object.mode_set(mode='EDIT')
    arm_obj.data.use_mirror_x = original_use_mirror_x
    bpy.ops.object.mode_set(mode='OBJECT')

def load_pose_from_cache(arm_obj, cache_key="default"):
    """Восстанавливает позу арматуры из кэша"""
    global _pose_cache
    
    if cache_key not in _pose_cache:
        return False
    
    data = _pose_cache[cache_key]
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='POSE')
    
    for bone_name, bone_data in data["bones"].items():
        if bone_name in arm_obj.pose.bones:
            bone = arm_obj.pose.bones[bone_name]
            
            # Восстанавливаем трансформации
            bone.location = bone_data["location"]
            bone.scale = bone_data["scale"]
            
            # Восстанавливаем вращение в зависимости от режима
            if bone_data["rotation_mode"] == 'QUATERNION' and bone_data["rotation_quaternion"]:
                bone.rotation_quaternion = bone_data["rotation_quaternion"]
            elif bone_data["rotation_euler"]:
                bone.rotation_euler = bone_data["rotation_euler"]
    
    return True

def load_skeleton_constraints_from_json(arm_obj: bpy.types.Object, filepath: str, source_arm_name: str = None):
    """Восстанавливает только констрейнты из JSON"""
    abs_filepath = bpy.path.abspath(filepath)
    with open(abs_filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='POSE')

    # Восстановление констрейнтов
    for pb_name, clist in data.get("constraints", {}).items():
        if pb_name not in arm_obj.pose.bones:
            continue
        pb = arm_obj.pose.bones[pb_name]
        # удалим существующие
        for c in list(pb.constraints):
            pb.constraints.remove(c)

        for c_info in clist:
            c_type = c_info.get("type")
            c_new = pb.constraints.new(type=c_type)
            props = c_info.get("properties", {})
            for k, v in props.items():
                try:
                    if isinstance(v, dict) and "__name__" in v:
                        obj_name = v["__name__"]
                        if source_arm_name and obj_name == source_arm_name:
                            if hasattr(c_new, k):
                                try:
                                    setattr(c_new, k, arm_obj)
                                except Exception:
                                    pass
                        else:
                            obj = bpy.data.objects.get(obj_name)
                            if obj and hasattr(c_new, k):
                                try:
                                    setattr(c_new, k, obj)
                                except Exception:
                                    pass
                    else:
                        if hasattr(c_new, k):
                            try:
                                setattr(c_new, k, v)
                            except Exception:
                                pass
                except Exception:
                    pass

    bpy.ops.object.mode_set(mode='OBJECT')

def load_skeleton_from_json(arm_obj: bpy.types.Object, filepath: str, source_arm_name: str = None):
    """Восстанавливает полный скелет из JSON (кости + констрейнты)"""
    load_skeleton_bones_from_json(arm_obj, filepath)
    load_skeleton_constraints_from_json(arm_obj, filepath, source_arm_name)

def has_cached_pose(cache_key="copied_pose"):
    return cache_key in _pose_cache

def clear_pose_cache(cache_key=None):
    """Очищает кэш поз"""
    global _pose_cache
    if cache_key:
        if cache_key in _pose_cache:
            del _pose_cache[cache_key]
    else:
        _pose_cache.clear()

def format_vector_for_display(vec):
    """Форматирует вектор для красивого отображения"""
    if hasattr(vec, 'x') and hasattr(vec, 'y') and hasattr(vec, 'z'):
        return f"({vec.x:.4f}, {vec.y:.4f}, {vec.z:.4f})"
    elif isinstance(vec, (list, tuple)) and len(vec) == 3:
        return f"({vec[0]:.4f}, {vec[1]:.4f}, {vec[2]:.4f})"
    return str(vec)

def verify_skeleton_with_json(arm_obj, filepath):
    """Сравнивает текущий скелет с JSON файлом и возвращает различия"""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    from .armature_utils import almost_equal
    bone_errors = {}
    constraint_errors = {}

    # Сохраняем текущий активный объект и режим
    original_active = bpy.context.view_layer.objects.active
    original_mode = original_active.mode if original_active else 'OBJECT'
    
    try:
        # Устанавливаем наш армачур активным
        bpy.context.view_layer.objects.active = arm_obj
        
        # Проверка костей
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.mode_set(mode='EDIT')
        
        for bone_name, json_data in data.get("bones", {}).items():
            if bone_name not in arm_obj.data.edit_bones:
                bone_errors[bone_name] = ["Bone not found in armature"]
                continue
                
            bone = arm_obj.data.edit_bones[bone_name]
            errors = []
            
            # Проверка head
            json_head = mathutils.Vector(json_data["head"])
            if not almost_equal(bone.head, json_head):
                errors.append(f"Head: {format_vector_for_display(bone.head)} vs {format_vector_for_display(json_head)}")
            
            # Проверка tail
            json_tail = mathutils.Vector(json_data["tail"])
            if not almost_equal(bone.tail, json_tail):
                errors.append(f"Tail: {format_vector_for_display(bone.tail)} vs {format_vector_for_display(json_tail)}")
            
            # Проверка roll
            json_roll = json_data.get("roll", 0.0)
            if abs(bone.roll - json_roll) > 1e-4:
                errors.append(f"Roll: {bone.roll:.4f} vs {json_roll:.4f}")
            
            # Проверка родителя
            json_parent = json_data.get("parent")
            current_parent = bone.parent.name if bone.parent else None
            if json_parent != current_parent:
                errors.append(f"Parent mismatch: {current_parent} vs {json_parent}")
            
            if errors:
                bone_errors[bone_name] = errors
        
        # Проверка констрейнтов
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.mode_set(mode='POSE')
        
        for bone_name, json_constraints in data.get("constraints", {}).items():
            if bone_name not in arm_obj.pose.bones:
                constraint_errors[bone_name] = ["Bone not found for constraint check"]
                continue
                
            pose_bone = arm_obj.pose.bones[bone_name]
            current_constraints = {c.name: c for c in pose_bone.constraints}
            json_constraints_by_name = {c.get('properties', {}).get('name', f"constraint_{i}"): c 
                                      for i, c in enumerate(json_constraints)}
            
            errors = []
            
            # Проверяем отсутствующие констрейнты
            for const_name, json_const in json_constraints_by_name.items():
                if const_name not in current_constraints:
                    errors.append(f"Missing constraint: {json_const['type']} ({const_name})")
            
            # Проверяем лишние констрейнты
            for const_name, current_const in current_constraints.items():
                if const_name not in json_constraints_by_name:
                    errors.append(f"Extra constraint: {current_const.type} ({const_name})")
            
            # Проверяем свойства констрейнтов
            for const_name, json_const in json_constraints_by_name.items():
                if const_name in current_constraints:
                    current_const = current_constraints[const_name]
                    
                    # Проверка типа
                    if current_const.type != json_const['type']:
                        errors.append(f"Constraint type mismatch for {const_name}: {current_const.type} vs {json_const['type']}")
            
            if errors:
                constraint_errors[bone_name] = errors
        
        # Возвращаемся в исходный режим
        bpy.ops.object.mode_set(mode='OBJECT')
        
    except Exception as e:
        # Восстанавливаем оригинальное состояние при ошибке
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
            if original_active:
                bpy.context.view_layer.objects.active = original_active
                if original_mode != 'OBJECT':
                    try:
                        bpy.ops.object.mode_set(mode=original_mode)
                    except Exception:
                        pass
        except Exception:
            pass
        raise e
    
    finally:
        # Всегда пытаемся восстановить оригинальное состояние
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
            if original_active and original_active != arm_obj:
                bpy.context.view_layer.objects.active = original_active
        except Exception:
            pass
    
    total_errors = len(bone_errors) + len(constraint_errors)
    
    return {
        "bone_errors": bone_errors,
        "constraint_errors": constraint_errors,
        "total_errors": total_errors
    }

#Работа с джейсоном анимаций

def export_animations_to_json(arm_obj, filepath, action_names=None):
    return run(export_animations_to_json_iter(arm_obj, filepath, action_names))


def export_animations_to_json_iter(arm_obj: bpy.types.Object, filepath: str, action_names=None):
    """Экспортирует анимации скелета в JSON со сжатием GZIP"""
    abs_filepath = bpy.path.abspath(filepath)
    
    data = {
        "armature_name": arm_obj.name if arm_obj else "No Armature",
        "export_date": datetime.now().isoformat(),
        "blender_version": bpy.app.version_string,
        "animations": {}
    }
    
    if action_names is None:
        action_names = [action.name for action in bpy.data.actions]
    
    for i, action_name in enumerate(action_names):
        yield i, len(action_names), action_name
        action = bpy.data.actions.get(action_name)
        if not action:
            continue
            
        animation_data = {
            "name": action.name,
            "frame_range": [action.frame_range[0], action.frame_range[1]],
            "fcurves": []
        }
        
        for fcurve in get_fcurves(action):
            fcurve_data = {
                "data_path": fcurve.data_path,
                "array_index": fcurve.array_index,
                "group": fcurve.group.name if fcurve.group else None,
                "extrapolation": fcurve.extrapolation,
                "keyframe_points": []
            }
            
            for keyframe in fcurve.keyframe_points:
                keyframe_data = {
                    "co": list(keyframe.co),
                    "handle_left": list(keyframe.handle_left),
                    "handle_right": list(keyframe.handle_right),
                    "handle_left_type": keyframe.handle_left_type,
                    "handle_right_type": keyframe.handle_right_type,
                    "interpolation": keyframe.interpolation,
                    "easing": keyframe.easing,
                    "type": keyframe.type
                }
                fcurve_data["keyframe_points"].append(keyframe_data)
            
            animation_data["fcurves"].append(fcurve_data)
        
        data["animations"][action.name] = animation_data
    
    # СОХРАНЕНИЕ СО СЖАТИЕМ GZIP
    try:
        with gzip.open(abs_filepath, 'wt', encoding='utf-8') as f:
            json.dump(data, f, indent=None, separators=(',', ':'))
        print(f"Successfully exported with GZIP compression: {abs_filepath}")
    except Exception as e:
        print(f"GZIP compression failed, falling back to normal JSON: {e}")
        # РЕЗЕРВНЫЙ ВАРИАНТ БЕЗ СЖАТИЯ
        with open(abs_filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=None, separators=(',', ':'))
    
    return True

def load_animations_from_json(filepath: str):
    """Загружает список анимаций из JSON файла (поддерживает GZIP и обычный JSON)"""
    abs_filepath = bpy.path.abspath(filepath)
    
    try:
        # ПРОБУЕМ GZIP СНАЧАЛА
        try:
            with gzip.open(abs_filepath, 'rt', encoding='utf-8') as f:
                data = json.load(f)
            print("Loaded GZIP compressed file")
        except (gzip.BadGzipFile, OSError):
            # ЕСЛИ НЕ GZIP, ПРОБУЕМ ОБЫЧНЫЙ JSON
            with open(abs_filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            print("Loaded normal JSON file")
        
        animations = []
        for action_name, action_data in data.get("animations", {}).items():
            frame_range = action_data.get("frame_range", [0, 0])
            animations.append({
                "name": action_data.get("name", action_name),
                "frame_start": int(frame_range[0]),
                "frame_end": int(frame_range[1]),
                "exists_in_blend": action_name in bpy.data.actions
            })
        
        return animations
    except Exception as e:
        print(f"Error loading animations from JSON: {e}")
        return []

def get_backup_directory(subfolder=None, create=True):
    """Возвращает путь к папке для бэкапов"""
    blend_filepath = bpy.data.filepath
    if not blend_filepath:
        # Файл не сохранён: "//" указывал бы в рабочую папку Blender (может быть только для чтения)
        try:
            base_dir = bpy.utils.extension_path_user(__package__.rsplit(".", 1)[0], path="BACKUP_unsaved_project", create=create)
        except (ValueError, TypeError):  # установлен как старый аддон, не расширение
            import tempfile
            base_dir = os.path.join(tempfile.gettempdir(), "TinyTools_BACKUP_unsaved_project")
    else:
        blend_name = Path(blend_filepath).stem
        base_dir = f"//BACKUP_{blend_name}"
    
    # Добавляем подпапку если указана
    if subfolder:
        full_path = os.path.join(base_dir, subfolder)
    else:
        full_path = base_dir
    
    # Создаем папку если её нет и возвращаем АБСОЛЮТНЫЙ путь
    abs_path = bpy.path.abspath(full_path)
    if create:
        Path(abs_path).mkdir(parents=True, exist_ok=True)
    
    return abs_path

def import_animations_from_json(filepath, animation_indices=None, import_mode='NEW_ONLY', armature_obj=None):
    return run(import_animations_from_json_iter(filepath, animation_indices, import_mode, armature_obj))


def import_animations_from_json_iter(filepath: str, animation_indices=None, import_mode='NEW_ONLY', armature_obj=None):
    """Импортирует анимации из JSON файла (поддерживает GZIP и обычный JSON)"""
    abs_filepath = bpy.path.abspath(filepath)
    
    try:
        # ПРОБУЕМ GZIP СНАЧАЛА
        try:
            with gzip.open(abs_filepath, 'rt', encoding='utf-8') as f:
                data = json.load(f)
        except (gzip.BadGzipFile, OSError):
            # ЕСЛИ НЕ GZIP, ПРОБУЕМ ОБЫЧНЫЙ JSON
            with open(abs_filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        
        imported_count = 0
        skipped_count = 0
        
        animations_data = data.get("animations", {})
        animation_names = list(animations_data.keys())
        
        if animation_indices is None:
            animation_indices = range(len(animation_names))
        
        animation_indices = list(animation_indices)
        for step, idx in enumerate(animation_indices):
            yield step, len(animation_indices), animation_names[idx] if idx < len(animation_names) else ""
            if idx >= len(animation_names):
                continue
                
            action_name = animation_names[idx]
            action_data = animations_data[action_name]
            
            new_action_name = action_name
            if import_mode == 'COPY':
                new_action_name = f"{action_name}_COPY"
            
            existing_action = bpy.data.actions.get(new_action_name)
            if existing_action and import_mode == 'NEW_ONLY':
                skipped_count += 1
                continue
            
            if existing_action and import_mode == 'REPLACE':
                action = existing_action
                for fcurve in list(get_fcurves(action)):
                    remove_fcurve(action, fcurve)
            else:
                action = bpy.data.actions.new(name=new_action_name)
            
            for fcurve_data in action_data.get("fcurves", []):
                fcurve = new_fcurve(action, fcurve_data["data_path"],
                                    index=fcurve_data["array_index"],
                                    group=fcurve_data.get("group") or "")
                if "extrapolation" in fcurve_data:
                    fcurve.extrapolation = fcurve_data["extrapolation"]

                for keyframe_data in fcurve_data.get("keyframe_points", []):
                    keyframe = fcurve.keyframe_points.insert(
                        keyframe_data["co"][0],
                        keyframe_data["co"][1]
                    )
                    # Типы ставим ДО координат хэндлов: AUTO-хэндлы иначе пересчитают их. Старые файлы типов не содержат.
                    if "handle_left_type" in keyframe_data:
                        keyframe.handle_left_type = keyframe_data["handle_left_type"]
                        keyframe.handle_right_type = keyframe_data["handle_right_type"]
                    if "type" in keyframe_data:
                        keyframe.type = keyframe_data["type"]
                        keyframe.easing = keyframe_data["easing"]
                    keyframe.handle_left = keyframe_data["handle_left"]
                    keyframe.handle_right = keyframe_data["handle_right"]
                    keyframe.interpolation = keyframe_data["interpolation"]
            
            frame_range = action_data.get("frame_range", [0, 0])
            action.frame_range = (frame_range[0], frame_range[1])
            
            imported_count += 1
        
        return imported_count, skipped_count
        
    except Exception as e:
        print(f"Error importing animations: {e}")
        raise

def import_selected_animation(arm_obj: bpy.types.Object, filepath: str, animation_index: int):
    """Импортирует выбранную анимацию (заглушка)"""
    # TODO: Реализовать импорт конкретной анимации
    print(f"Importing animation {animation_index} from {filepath}")
    return True

def import_all_animations(arm_obj: bpy.types.Object, filepath: str):
    """Импортирует все анимации (заглушка)"""
    # TODO: Реализовать импорт всех анимаций
    print(f"Importing all animations from {filepath}")
    return True

