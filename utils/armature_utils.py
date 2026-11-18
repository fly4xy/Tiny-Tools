import bpy
from typing import List, Tuple
from mathutils import Vector, Quaternion, Euler
from .anim_compat import get_fcurves, remove_fcurve, new_fcurve

_armature_enum_items = []  # Blender не копирует строки dynamic enum — держим ссылку, иначе мусор в UI

def list_armatures(self, context) -> List[Tuple[str, str, str]]:
    """Возвращает список объектов-арматур в сцене для EnumProperty"""
    items = [(obj.name, obj.name, "Armature object") for obj in bpy.data.objects if obj.type == 'ARMATURE']
    if not items:
        items.append(("NONE", "No Armatures", "No armature objects found"))
    _armature_enum_items[:] = items
    return _armature_enum_items

def clean_unused_fcurves() -> int:
    """Удаляет анимационные каналы, ссылающиеся на несуществующие кости в действиях."""
    removed = 0
    for action in bpy.data.actions:
        fcurves = list(get_fcurves(action))
        for fc in fcurves:
            data_path = fc.data_path
            if 'pose.bones' in data_path:
                parts = data_path.split('pose.bones["')
                if len(parts) > 1:
                    bone_name = parts[1].split('"]')[0]
                    found = False
                    for obj in bpy.data.objects:
                        if obj.type == 'ARMATURE' and bone_name in obj.data.bones:
                            found = True
                            break
                    if not found:
                        try:
                            remove_fcurve(action, fc)
                            removed += 1
                        except Exception:
                            pass
    return removed

def almost_equal(v1, v2, eps=1e-4):
    return (v1 - v2).length < eps

def clear_pose(armature_obj):
    """Сбрасывает позу в рест-позицию"""
    original_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = armature_obj
    
    try:
        # Переходим в режим позы если нужно
        if bpy.context.object.mode != 'POSE':
            bpy.ops.object.mode_set(mode='POSE')
        
        # Выделяем все кости
        bpy.ops.pose.select_all(action='SELECT')
        
        # Очищаем все трансформы
        bpy.ops.pose.transforms_clear()
        
        # Снимаем выделение
        bpy.ops.pose.select_all(action='DESELECT')
        
        # Принудительно обновляем сцену
        bpy.context.view_layer.update()
        
    finally:
        # Восстанавливаем оригинальный активный объект
        if original_active:
            bpy.context.view_layer.objects.active = original_active

def get_current_pose_data(armature_obj):
    """Получает данные текущей позы"""
    pose_data = {}
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')
    
    for bone in armature_obj.pose.bones:
        pose_data[bone.name] = {
            'matrix': bone.matrix.copy(),
            'location': bone.location.copy(),
            'rotation_mode': bone.rotation_mode,
            'scale': bone.scale.copy()
        }
        if bone.rotation_mode == 'QUATERNION':
            pose_data[bone.name]['rotation'] = bone.rotation_quaternion.copy()
        else:
            pose_data[bone.name]['rotation'] = bone.rotation_euler.copy()
    
    return pose_data

def process_mesh_with_pose(mesh_obj, armature_obj):
    """Запекает текущую позу арматуры в меш и в КАЖДЫЙ его shape key.

    Каждый ключ вычисляется отдельно (show_only_shape_key) через depsgraph только с модификатором этой арматуры,
    поэтому после смены rest-позы меш и все ключи выглядят ровно как в позе. Меш должен быть в View Layer.
    """
    import numpy as np
    arm_mods = [m for m in mesh_obj.modifiers if m.type == 'ARMATURE' and m.object == armature_obj]
    if not arm_mods:
        print(f"No armature modifier found for {mesh_obj.name}")
        return False

    mesh = mesh_obj.data
    n = len(mesh.vertices)
    keys = mesh.shape_keys
    viewport_states = [(m, m.show_viewport) for m in mesh_obj.modifiers]
    saved_only, saved_index = mesh_obj.show_only_shape_key, mesh_obj.active_shape_key_index

    def evaluated_co():
        ev = mesh_obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        me = ev.to_mesh()
        try:
            if len(me.vertices) != n:
                raise RuntimeError(f"{mesh_obj.name}: modifiers change vertex count")
            co = np.empty(n * 3, dtype=np.float32)
            me.vertices.foreach_get("co", co)
            return co
        finally:
            ev.to_mesh_clear()

    try:
        for m, _ in viewport_states:
            m.show_viewport = m in arm_mods  # прочие модификаторы (subsurf, triangulate...) не запекаем
        if keys:
            mesh_obj.show_only_shape_key = True
            baked = []
            for i in range(len(keys.key_blocks)):
                mesh_obj.active_shape_key_index = i
                baked.append(evaluated_co())
            for kb, co in zip(keys.key_blocks, baked):
                kb.data.foreach_set("co", co)
            mesh.vertices.foreach_set("co", baked[0])
        else:
            mesh.vertices.foreach_set("co", evaluated_co())
        mesh.update()
        return True
    except Exception:
        import traceback
        traceback.print_exc()
        return False
    finally:
        for m, state in viewport_states:
            m.show_viewport = state
        mesh_obj.show_only_shape_key, mesh_obj.active_shape_key_index = saved_only, saved_index
    
EULER_ORDERS = {'XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'}


def adjust_animation_for_pose(action, transform_diff):
    """Пересчитывает анимацию под новую rest-позу, чтобы в мире она выглядела ровно как раньше.

    Для кости с позой P (которая станет rest) новый basis = P⁻¹ · basis:
    loc' = qp⁻¹·(loc − lp) / sp,  rot' = qp⁻¹·rot,  scale' = scale / sp.
    """
    for bone, d in transform_diff.items():
        qinv = d['rotation'].inverted()
        lp = d['location']
        inv_s = [1.0 / s if s else 1.0 for s in d['scale']]
        path = f'pose.bones["{bone}"].'

        def loc(v, prev):
            w = qinv @ (Vector(v) - lp)
            return tuple(x * k for x, k in zip(w, inv_s))

        _remap_channel(action, path + "location", (0.0, 0.0, 0.0), bone, loc)
        _remap_channel(action, path + "scale", (1.0, 1.0, 1.0), bone,
                       lambda v, prev: tuple(x * k for x, k in zip(v, inv_s)))
        mode = d['rotation_mode']
        if mode == 'QUATERNION':
            _remap_channel(action, path + "rotation_quaternion", (1.0, 0.0, 0.0, 0.0), bone,
                           lambda v, prev: tuple(qinv @ Quaternion(v)))
        elif mode in EULER_ORDERS:
            def eul(v, prev, mode=mode):
                e = (qinv @ Euler(v, mode).to_quaternion()).to_euler(mode, Euler(prev, mode)) if prev else                     (qinv @ Euler(v, mode).to_quaternion()).to_euler(mode)
                return tuple(e)
            _remap_channel(action, path + "rotation_euler", (0.0, 0.0, 0.0), bone, eul)
        # shortcut: AXIS_ANGLE не пересчитывается — редкий режим; при необходимости по аналогии с кватернионом


def _find_fcurve(action, data_path, index):
    return next((fc for fc in get_fcurves(action) if fc.data_path == data_path and fc.array_index == index), None)


def _remap_channel(action, data_path, default, group, func):
    """Применяет func(вектор, предыдущий_результат) -> вектор к векторному каналу (location / rotation / scale).

    Компоненты канала сначала получают ключи на общих кадрах: поворот смешивает x/y/z, поэтому каждую точку
    считаем по всему вектору. Для аффинных func (location, кватернион, scale) ключи и хэндлы переводятся точно.
    """
    size = len(default)
    fcs = [_find_fcurve(action, data_path, i) for i in range(size)]
    if not any(fcs):
        new = func(default, None)
        if max(abs(a - b) for a, b in zip(new, default)) < 1e-6:
            return
        frame = action.frame_range[0]  # канал не анимирован: постоянный ключ, иначе после смены rest он «поедет»
        for i in range(size):
            new_fcurve(action, data_path, index=i, group=group).keyframe_points.insert(frame, new[i])
        return

    first = min(k.co.x for fc in fcs if fc for k in fc.keyframe_points)
    for i in range(size):
        if fcs[i] is None:
            fcs[i] = new_fcurve(action, data_path, index=i, group=group)
            fcs[i].keyframe_points.insert(first, default[i])
    times = sorted({round(k.co.x, 4) for fc in fcs for k in fc.keyframe_points})
    for fc in fcs:
        have = {round(k.co.x, 4) for k in fc.keyframe_points}
        missing = {t: fc.evaluate(t) for t in times if t not in have}
        for t, v in missing.items():
            fc.keyframe_points.insert(t, v, options={'FAST'})
        fc.update()

    # считаем всё до записи: evaluate должен видеть исходные кривые
    pts = [[(k.co.copy(), k.handle_left.copy(), k.handle_right.copy()) for k in fc.keyframe_points] for fc in fcs]

    def vec_at(j, side):
        ref = pts[0][j][side].x
        return [pts[i][j][side].y if abs(pts[i][j][side].x - ref) < 1e-4 else fcs[i].evaluate(ref) for i in range(size)]

    out, prev = [], None
    for j in range(len(times)):
        key = func([pts[i][j][0].y for i in range(size)], prev)
        prev = key
        out.append((key, func(vec_at(j, 1), key), func(vec_at(j, 2), key)))

    for i, fc in enumerate(fcs):
        for j, k in enumerate(fc.keyframe_points):
            key, hl, hr = out[j]
            k.co.y = key[i]
            k.handle_left = (pts[i][j][1].x, hl[i])
            k.handle_right = (pts[i][j][2].x, hr[i])
        fc.update()

def restore_pose_from_data(armature_obj, pose_data):
    """Восстанавливает позу из данных, полученных через get_current_pose_data"""
    original_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')
    
    try:
        for bone_name, bone_data in pose_data.items():
            if bone_name in armature_obj.pose.bones:
                bone = armature_obj.pose.bones[bone_name]
                bone.location = bone_data['location']
                bone.scale = bone_data['scale']
                
                if bone_data['rotation_mode'] == 'QUATERNION' and bone_data.get('rotation'):
                    bone.rotation_quaternion = bone_data['rotation']
                elif bone_data.get('rotation'):
                    bone.rotation_euler = bone_data['rotation']
        
        return True
        
    except Exception as e:
        print(f"ERROR restoring pose: {e}")
        return False
    finally:
        if original_active:
            bpy.context.view_layer.objects.active = original_active

def calculate_pose_difference(base_pose_data, target_pose_data):
    """Вычисляет разницу трансформов между базовой позой и целевой позой"""
    transform_diff = {}
    
    for bone_name in target_pose_data.keys():
        if bone_name in base_pose_data:
            base_data = base_pose_data[bone_name]
            target_data = target_pose_data[bone_name]
            
            # Вычисляем разницу location
            loc_diff = Vector((
                target_data['location'].x - base_data['location'].x,
                target_data['location'].y - base_data['location'].y, 
                target_data['location'].z - base_data['location'].z
            ))
            
            # Вычисляем разницу rotation (кватернион)
            if base_data['rotation_mode'] == 'QUATERNION' and target_data['rotation_mode'] == 'QUATERNION':
                base_rot = base_data['rotation']
                target_rot = target_data['rotation']
                rot_diff = target_rot @ base_rot.conjugated()
            else:
                # Для эйлеров - конвертируем в кватернионы
                base_rot = base_data['rotation'].to_quaternion()
                target_rot = target_data['rotation'].to_quaternion() 
                rot_diff = target_rot @ base_rot.conjugated()
            
            # Вычисляем разницу scale
            scale_diff = Vector((
                target_data['scale'].x / base_data['scale'].x if base_data['scale'].x != 0 else 1.0,
                target_data['scale'].y / base_data['scale'].y if base_data['scale'].y != 0 else 1.0,
                target_data['scale'].z / base_data['scale'].z if base_data['scale'].z != 0 else 1.0
            ))
            
            # Сохраняем разницу только если есть значимые изменения
            if (loc_diff.length > 0.001 or 
                rot_diff.angle > 0.001 or 
                any(abs(s - 1.0) > 0.001 for s in scale_diff)):
                
                transform_diff[bone_name] = {
                    'location': loc_diff,
                    'rotation': rot_diff,
                    'scale': scale_diff,
                    'rotation_mode': target_data['rotation_mode']
                }
    return transform_diff

def temporarily_remove_constraints(armature_obj):
    """Временно удаляет все констрейнты и возвращает полные данные для восстановления"""
    constraints_data = {}
    
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')
    
    for pb in armature_obj.pose.bones:
        clist = []
        for c in pb.constraints:
            c_data = {"type": c.type, "properties": {}}
            # Сохраняем ВСЕ свойства констрейнта
            for prop in dir(c):
                if prop.startswith("_"):
                    continue
                if prop in {"bl_rna", "rna_type"}:
                    continue
                try:
                    val = getattr(c, prop)
                except Exception:
                    continue
                
                # Сохраняем разные типы данных
                if isinstance(val, (int, float, str, bool)):
                    c_data["properties"][prop] = val
                elif isinstance(val, (list, tuple)):
                    try:
                        c_data["properties"][prop] = list(val)
                    except Exception:
                        pass
                elif hasattr(val, "name"):
                    c_data["properties"][prop] = {"__name__": val.name}
                # Добавляем другие типы по необходимости
            
            clist.append(c_data)
        
        if clist:
            constraints_data[pb.name] = clist
        
        # Удаляем все констрейнты кости
        for constr in list(pb.constraints):
            pb.constraints.remove(constr)
    
    bpy.ops.object.mode_set(mode='OBJECT')
    return constraints_data

def restore_constraints_from_data(armature_obj, constraints_data):
    """Восстанавливает констрейнты из данных с сохранением всех связей"""
    if not constraints_data:
        return
    
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')
    
    for pb_name, clist in constraints_data.items():
        if pb_name not in armature_obj.pose.bones:
            continue
            
        pb = armature_obj.pose.bones[pb_name]
        
        for c_info in clist:
            c_type = c_info.get("type")
            c_new = pb.constraints.new(type=c_type)
            props = c_info.get("properties", {})
            
            # Восстанавливаем ВСЕ свойства
            for k, v in props.items():
                try:
                    # Особый случай: свойства-объекты (кости, арматуры и т.д.)
                    if isinstance(v, dict) and "__name__" in v:
                        obj_name = v["__name__"]
                        obj = bpy.data.objects.get(obj_name)
                        if obj and hasattr(c_new, k):
                            try:
                                setattr(c_new, k, obj)
                            except Exception:
                                pass
                    # Обычные свойства
                    else:
                        if hasattr(c_new, k):
                            try:
                                setattr(c_new, k, v)
                            except Exception:
                                pass
                except Exception:
                    pass
    
    bpy.ops.object.mode_set(mode='OBJECT')

def apply_current_pose_as_rest_pose(armature_obj):
    """Применяет текущую позу как rest-pose через Blender operators"""
    original_mode = bpy.context.object.mode
    original_active = bpy.context.view_layer.objects.active
    
    try:
        # Переходим в режим позы
        bpy.context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode='POSE')
        
        # Выделяем все кости
        bpy.ops.pose.select_all(action='SELECT')
        
        # Используем встроенный оператор Blender для применения позы как rest-pose
        bpy.ops.pose.armature_apply(selected=False)
        
    except Exception as e:
        print(f"ERROR applying pose as rest pose: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Возвращаемся в исходный режим
        if original_active:
            bpy.context.view_layer.objects.active = original_active
        try:
            bpy.ops.object.mode_set(mode=original_mode)
        except:
            pass