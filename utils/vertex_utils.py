import bpy, bmesh, math
from mathutils import Vector, kdtree, geometry
from .modal_job import run

_vertex_pairs_cache = {}

def get_cached_vertex_pairs(obj, search_radius, algorithm='SPATIAL_HASH',
                          check_topology=False, check_normals=False, normal_threshold=45.0):
    return run(get_cached_vertex_pairs_iter(obj, search_radius, algorithm, check_topology, check_normals, normal_threshold))


def get_cached_vertex_pairs_iter(obj, search_radius, algorithm='SPATIAL_HASH',
                                 check_topology=False, check_normals=False, normal_threshold=45.0):
    """Кэшированные пары вершин (генератор шагов: первый расчёт на большом меше долгий)"""
    import numpy as np
    co = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
    obj.data.vertices.foreach_get("co", co)
    mesh_hash = hash((obj.data.name, co.tobytes()))
    if len(_vertex_pairs_cache) > 16:
        _vertex_pairs_cache.clear()
    cache_key = f"{mesh_hash}_{search_radius}_{algorithm}_{check_topology}_{check_normals}_{normal_threshold}"
    
    if cache_key not in _vertex_pairs_cache:
        print(f"Calculating vertex pairs using {algorithm} with topology={check_topology}, normals={check_normals}")
        _vertex_pairs_cache[cache_key] = yield from get_symmetrical_vertex_pairs_iter(
            obj, search_radius, check_topology, check_normals, normal_threshold
        )
    
    return _vertex_pairs_cache[cache_key]

def clear_vertex_pairs_cache():
    """Очистка кэша"""
    _vertex_pairs_cache.clear()
    
def clean_vertex_groups_across_scene():
    """Проходится по всем объектам сцены и очищает вертекс-группы"""
    total_cleaned = 0
    
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
            
        # Проверяем есть ли у объекта модификатор Armature
        armature_modifier = None
        armature_obj = None
        
        for mod in obj.modifiers:
            if mod.type == 'ARMATURE' and mod.object:
                armature_modifier = mod
                armature_obj = mod.object
                break
        
        if not armature_obj or armature_obj.type != 'ARMATURE':
            continue
            
        # Получаем список всех костей в армачуре
        bone_names = set()
        if armature_obj.data:
            if armature_obj.data.bones:
                bone_names.update(bone.name for bone in armature_obj.data.bones)
            if armature_obj.pose and armature_obj.pose.bones:
                bone_names.update(bone.name for bone in armature_obj.pose.bones)
            if armature_obj.data.edit_bones:
                bone_names.update(bone.name for bone in armature_obj.data.edit_bones)
        
        if not bone_names:
            continue
            
        # Очищаем вертекс-группы объекта
        cleaned = clean_object_vertex_groups(obj, bone_names)
        total_cleaned += cleaned
        
    return total_cleaned

def clean_object_vertex_groups(obj, valid_bone_names):
    """Очищает вертекс-группы конкретного объекта"""
    cleaned_count = 0
    
    # Собираем названия групп для удаления
    groups_to_remove = []
    
    for vgroup in obj.vertex_groups:
        group_name = vgroup.name
        
        # Пропускаем группы с TEMP_ в начале
        if group_name.startswith('TEMP_'):
            continue
            
        # Пропускаем группы, которые есть в списке костей
        if group_name in valid_bone_names:
            continue
            
        # Пропускаем специальные группы, которые могут быть нужны
        if group_name in ['Group', 'root', 'Root']:
            continue
            
        groups_to_remove.append(group_name)
    
    # Удаляем группы по имени (безопасный способ)
    for group_name in groups_to_remove:
        try:
            # Находим группу по имени и удаляем
            vgroup = obj.vertex_groups.get(group_name)
            if vgroup:
                obj.vertex_groups.remove(vgroup)
                cleaned_count += 1
                print(f"Removed vertex group: {group_name} from {obj.name}")
        except Exception as e:
            print(f"Failed to remove vertex group {group_name}: {e}")
    
    return cleaned_count

def get_symmetrical_vertex_pairs_iter(obj, search_radius=0.001,check_topology=False, check_normals=False, normal_threshold=45.0):
    """Быстрый поиск симметричных пар вершин с опциональными проверками"""
    import bmesh
    from mathutils import Vector
    from collections import defaultdict
    import math
    
    # Создаем bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    
    # Вычисляем нормали если нужно
    if check_normals:
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    
    # 1. АДАПТИВНЫЙ РАЗМЕР ЯЧЕЙКИ
    mesh_dimensions = obj.dimensions
    avg_dimension = sum(mesh_dimensions) / 3
    cell_size = max(search_radius * 2, avg_dimension / 50)
    
    # 2. ПРЕДВАРИТЕЛЬНАЯ ФИЛЬТРАЦИЯ
    y_tolerance = search_radius * 1.5
    z_tolerance = search_radius * 1.5
    
    # 3. ПРЕДВАРИТЕЛЬНОЕ РАЗБИЕНИЕ НА КОМПОНЕНТЫ СВЯЗНОСТИ (если нужно)
    connected_components = []
    if check_topology:
        connected_components = get_connected_components_bmesh(bm)
    
    # Преобразуем threshold в радианы для скалярного произведения
    normal_cos_threshold = math.cos(math.radians(normal_threshold))
    
    spatial_hash = defaultdict(list)
    for vert in bm.verts:
        key = (
            int(vert.co.x / cell_size),
            int(vert.co.y / cell_size), 
            int(vert.co.z / cell_size)
        )
        spatial_hash[key].append(vert)
    
    vertex_pairs = {}
    processed = set()
    total = len(bm.verts)

    for vert in bm.verts:
        if vert.index % 2000 == 0:
            yield vert.index, total, "Vertex pairs"
        if vert.index in processed:
            continue
            
        sym_co = Vector((-vert.co.x, vert.co.y, vert.co.z))
        sym_key = (
            int(sym_co.x / cell_size),
            int(sym_co.y / cell_size),
            int(sym_co.z / cell_size)
        )
        
        closest_vert = None
        min_distance = search_radius
        
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    check_key = (sym_key[0] + dx, sym_key[1] + dy, sym_key[2] + dz)
                    if check_key in spatial_hash:
                        for other_vert in spatial_hash[check_key]:
                            if other_vert.index in processed:
                                continue
                            
                            # ПРЕДВАРИТЕЛЬНАЯ ФИЛЬТРАЦИЯ по YZ
                            if abs(other_vert.co.y - sym_co.y) > y_tolerance:
                                continue
                            if abs(other_vert.co.z - sym_co.z) > z_tolerance:
                                continue
                            
                            # ПРОВЕРКА НОРМАЛЕЙ
                            if check_normals:
                                # Нормаль симметричной вершины должна быть отражена
                                expected_normal = Vector((-vert.normal.x, vert.normal.y, vert.normal.z))
                                dot_product = expected_normal.dot(other_vert.normal)
                                if dot_product < normal_cos_threshold:
                                    continue
                            
                            distance = (other_vert.co - sym_co).length
                            if distance < min_distance:
                                min_distance = distance
                                closest_vert = other_vert
        
        if closest_vert:
            # ПРОВЕРКА ТОПОЛОГИИ
            if check_topology:
                same_component = any(vert.index in comp and closest_vert.index in comp 
                                   for comp in connected_components)
                if not same_component:
                    continue
            
            vertex_pairs[vert.index] = closest_vert.index
            vertex_pairs[closest_vert.index] = vert.index
            processed.add(vert.index)
            processed.add(closest_vert.index)
    
    bm.free()
    
    print(f"Found {len(vertex_pairs)//2} symmetrical pairs (topology: {check_topology}, normals: {check_normals})")
    return vertex_pairs

def get_connected_components_bmesh(bm):
    """Разбивает BMesh на связные компоненты"""
    components = []
    visited = set()
    
    for vert in bm.verts:
        if vert.index in visited:
            continue
        
        component = set()
        stack = [vert]
        
        while stack:
            current = stack.pop()
            if current.index in visited:
                continue
            visited.add(current.index)
            component.add(current.index)
            
            # Добавляем всех соседей через ребра
            for edge in current.link_edges:
                for v in edge.verts:
                    if v.index not in visited:
                        stack.append(v)
        
        components.append(component)
    
    return components

def backup_modifier_states(obj):
    """Сохраняет состояния модификаторов объекта"""
    modifier_states = {}
    for mod in obj.modifiers:
        modifier_states[mod.name] = {
            'show_viewport': mod.show_viewport,
            'show_render': mod.show_render
        }
    return modifier_states

def restore_modifier_states(obj, modifier_states):
    """Восстанавливает состояния модификаторов"""
    for mod in obj.modifiers:
        if mod.name in modifier_states:
            state = modifier_states[mod.name]
            mod.show_viewport = state['show_viewport']
            mod.show_render = state['show_render']

def disable_modifiers_temporarily(obj):
    """Временно отключает все модификаторы"""
    for mod in obj.modifiers:
        mod.show_viewport = False
        mod.show_render = False

def get_opposite_group_name(group_name, direction):
    """Генерирует имя противоположной группы с сохранением регистра"""
    name_lower = group_name.lower()
    
    # Определяем суффиксы и их противоположности
    suffix_pairs = [
        ('.l', '.r'), ('.r', '.l'),
        ('.left', '.right'), ('.right', '.left'),
        ('_l', '_r'), ('_r', '_l'),
        ('_left', '_right'), ('_right', '_left')
    ]
    
    for suffix, opposite_suffix in suffix_pairs:
        if name_lower.endswith(suffix):
            # Сохраняем оригинальный регистр
            if group_name.endswith(suffix.upper()):
                # Верхний регистр: NAME.L -> NAME.R
                base_name = group_name[:-len(suffix)]
                return base_name + opposite_suffix.upper()
            elif group_name[-(len(suffix)):].istitle():
                # Capitalize: Name.Left -> Name.Right
                base_name = group_name[:-len(suffix)]
                return base_name + opposite_suffix.title()
            else:
                # Нижний регистр: name.l -> name.r
                base_name = group_name[:-len(suffix)]
                return base_name + opposite_suffix
    
    # Если суффикс не найден, добавляем стандартный
    if direction == 'L_TO_R':
        return group_name + '.R'
    else:
        return group_name + '.L'

def get_vertices_with_weights(obj, vg_name):
    """Быстрое получение вершин с весами через BMesh"""
    vg = obj.vertex_groups.get(vg_name)
    if not vg:
        return []
    
    # Создаем bmesh для доступа к данным вершин
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    
    # Получаем слой весов для быстрого доступа
    deform_layer = bm.verts.layers.deform.active
    if not deform_layer:
        bm.free()
        return []
    
    weighted_vertices = []
    vg_index = vg.index
    
    for vert in bm.verts:
        if vg_index in vert[deform_layer]:
            weight = vert[deform_layer][vg_index]
            if weight > 0:
                weighted_vertices.append((vert.index, weight))
    
    bm.free()
    return weighted_vertices

def clear_vertex_group_weights(obj, vg_name):
    """Очищает все веса группы (vg.remove на C; без bm.to_mesh, который переписывает весь меш с shape keys)"""
    vg = obj.vertex_groups.get(vg_name)
    if vg:
        vg.remove(range(len(obj.data.vertices)))

def smooth_vertex_group(obj, vg_name, iterations=1, intensity=0.5, exclude_temp_groups=True):
    """Сглаживает веса вертекс-группы с использованием Лапласиана"""
    if exclude_temp_groups and vg_name.startswith('TEMP_'):
        return False
        
    vg = obj.vertex_groups.get(vg_name)
    if not vg:
        return False
        
    # Получаем все веса
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    
    try:
        deform_layer = bm.verts.layers.deform.active
        if not deform_layer:
            return False
            
        vg_index = vg.index
        
        # Создаем копию текущих весов для работы
        current_weights = {}
        for vert in bm.verts:
            if vg_index in vert[deform_layer]:
                current_weights[vert.index] = vert[deform_layer][vg_index]
        
        # Многократное сглаживание
        for iteration in range(iterations):
            new_weights = current_weights.copy()
            
            for vert_index, current_weight in current_weights.items():
                vert = bm.verts[vert_index]
                
                # Собираем веса соседей из ТЕКУЩЕЙ итерации
                neighbor_weights = []
                for edge in vert.link_edges:
                    for neighbor in edge.verts:
                        if neighbor.index != vert_index and neighbor.index in current_weights:
                            neighbor_weights.append(current_weights[neighbor.index])
                
                if neighbor_weights:
                    avg_neighbor = sum(neighbor_weights) / len(neighbor_weights)
                    new_weight = current_weight * (1 - intensity) + avg_neighbor * intensity
                    new_weights[vert_index] = max(0.0, min(1.0, new_weight))
            
            # Обновляем веса для следующей итерации
            current_weights = new_weights
        
        # Применяем финальные веса
        for vert_index, final_weight in current_weights.items():
            vg.add([vert_index], final_weight, 'REPLACE')
        
        return True
        
    except Exception as e:
        print(f"Error smoothing vertex group {vg_name}: {e}")
        return False
    finally:
        bm.free()

def smooth_multiple_vertex_groups(obj, vg_names, iterations=1, intensity=0.5, exclude_temp_groups=True):
    return run(smooth_multiple_vertex_groups_iter(obj, vg_names, iterations, intensity, exclude_temp_groups))


def smooth_multiple_vertex_groups_iter(obj, vg_names, iterations=1, intensity=0.5, exclude_temp_groups=True):
    """Сглаживает несколько вертекс-групп (генератор шагов)"""
    smoothed_count = 0
    for i, vg_name in enumerate(vg_names):
        yield i, len(vg_names), f"Smooth {vg_name}"
        if smooth_vertex_group(obj, vg_name, iterations, intensity, exclude_temp_groups):
            smoothed_count += 1
    return smoothed_count

def get_mirrored_group_names(obj, direction='L_TO_R',groups_mode='ALL'):
    """Возвращает список групп, которые были зеркалированы (L->R или R->L)"""
    mirrored_groups = []
    
    if groups_mode == 'ALL':
        for vg in obj.vertex_groups:
            vg_name = vg.name
            name_lower = vg_name.lower()
            
            if direction == 'L_TO_R':
                # Ищем R группы (целевые)
                if any(name_lower.endswith(suffix) for suffix in ['.r', '.right', '_r', '_right']):
                    mirrored_groups.append(vg_name)
            else:  # R_TO_L
                # Ищем L группы (целевые)
                if any(name_lower.endswith(suffix) for suffix in ['.l', '.left', '_l', '_left']):
                    mirrored_groups.append(vg_name)
    else:
        active_vg = obj.vertex_groups.active
        if not active_vg:
            return 0
        
        # Источник — сторона направления, какая бы группа пары ни была активной
        name = active_vg.name
        lower = name.lower()
        is_left = any(lower.endswith(s) for s in ('.l', '.left', '_l', '_left'))
        is_right = any(lower.endswith(s) for s in ('.r', '.right', '_r', '_right'))
        if (direction == 'L_TO_R' and is_right) or (direction == 'R_TO_L' and is_left):
            return get_opposite_group_name(name, direction)
        return name
    
    return mirrored_groups

def mirror_vertex_weights(*args, **kwargs):
    return run(mirror_vertex_weights_iter(*args, **kwargs))


def mirror_vertex_weights_iter(obj, direction='L_TO_R', weight_mode='REPLACE_ALL', vertex_pairs=None, projection_method='DIRECT',
                          groups_mode='ALL',check_normals=False, normal_threshold=45.0, search_radius=0.001,
                          normal_projection=True, normal_projection_distance=.01, normal_projection_steps=3, normal_projection_smooth_steps=2,
                          edge_length_mult=3):
    """Зеркалит веса вертекс-групп с выбором режима групп"""
    
    # Сохраняем и отключаем модификаторы
    modifier_states = backup_modifier_states(obj)
    disable_modifiers_temporarily(obj)
    
    try:
        mirrored_count = 0
        
        groups_to_process = get_source_groups(obj, direction, groups_mode)
        
        # Обрабатываем группы
        for i, source_name in enumerate(groups_to_process):
            yield i, len(groups_to_process), source_name
            # Генерируем имя целевой группы
            target_vg_name = get_opposite_group_name(source_name, direction)
            target_vg = obj.vertex_groups.get(target_vg_name)
            
            # Создаем целевую группу если её нет
            if not target_vg:
                target_vg = obj.vertex_groups.new(name=target_vg_name)
            elif weight_mode == 'REPLACE_ALL':
                # Очищаем веса только в режиме Replace All
                clear_vertex_group_weights(obj, target_vg_name)
            
            # Получаем вершины с ненулевыми весами
            weighted_vertices = get_vertices_with_weights(obj, source_name)
            
            # Применяем выбранный метод проекции
            if projection_method == 'DIRECT':
                _apply_direct_mirror(weighted_vertices, target_vg, vertex_pairs)
            elif projection_method == 'GRADIENT':
                _apply_gradient_mirror(obj, source_name, target_vg, vertex_pairs, check_normals, normal_threshold,
                                       search_radius, normal_projection, normal_projection_distance,normal_projection_steps,
                                       normal_projection_smooth_steps,edge_length_mult)
            elif projection_method == 'INTERPOLATION':
                _apply_interpolation_mirror(obj, source_name, target_vg, vertex_pairs, check_normals, normal_threshold,
                                            search_radius, normal_projection, normal_projection_distance,normal_projection_steps,
                                            normal_projection_smooth_steps,edge_length_mult)
            
            mirrored_count += 1
        
        return mirrored_count
        
    finally:
        # Всегда восстанавливаем модификаторы
        restore_modifier_states(obj, modifier_states)

def _apply_direct_mirror(weighted_vertices, target_vg, vertex_pairs):
    """Прямое копирование весов (текущий метод) - зеркалирует веса через пары вершин"""
    if not vertex_pairs:
        print("Warning: No vertex pairs found for direct mirroring")
        return
    
    mirrored_count = 0
    skipped_count = 0
    
    for vert_index, weight in weighted_vertices:
        if vert_index in vertex_pairs:
            target_vert_index = vertex_pairs[vert_index]
            try:
                target_vg.add([target_vert_index], weight, 'REPLACE')
                mirrored_count += 1
            except Exception as e:
                print(f"Failed to add weight to vertex {target_vert_index}: {e}")
                skipped_count += 1
        else:
            skipped_count += 1
    
    if skipped_count > 0:
        print(f"Direct mirror: {mirrored_count} vertices mirrored, {skipped_count} skipped (no pairs)")
    else:
        print(f"Direct mirror: {mirrored_count} vertices mirrored")

def _apply_gradient_mirror(obj, source_name, target_vg, vertex_pairs, check_normals=False, normal_threshold=45.0, search_radius=0.001,
                          normal_projection=False, normal_projection_distance=10, normal_projection_steps=3,
                          normal_projection_smooth_steps=0, edge_length_mult=3):
    """Градиентный перенос весов с учетом разной плотности сетки"""    
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    
    try:
        # 1. Собираем данные исходной стороны
        source_vg = obj.vertex_groups.get(source_name)
        if not source_vg:
            return 0
            
        source_weights = {}
        deform_layer = bm.verts.layers.deform.active
        vg_index = source_vg.index
        
        for vert in bm.verts:
            if vg_index in vert[deform_layer]:
                weight = vert[deform_layer][vg_index]
                if weight > 0:
                    source_weights[vert.index] = (weight, vert.co.copy(), vert.normal.copy())
        
        print(f"Source vertices with weights: {len(source_weights)}")
        
        # 2. Прямое зеркалирование для вершин с парами
        vertices_with_weights = set()
        
        for src_vert_index, src_data in source_weights.items():
            if src_vert_index in vertex_pairs:
                src_weight, src_pos, src_normal = src_data # Тут кортедж из трех элементов. Неиспользуемые удалять нельзя
                target_vert_index = vertex_pairs[src_vert_index]
                target_vg.add([target_vert_index], src_weight, 'REPLACE')
                vertices_with_weights.add(target_vert_index)
        
        print(f"Direct mirror: {len(vertices_with_weights)} vertices")
        
        # 3. Строим KD-дерево для исходных вершин
        if not source_weights:
            return len(vertices_with_weights)
            
        kd = kdtree.KDTree(len(source_weights))
        
        for src_vert_index, src_data in source_weights.items():
            weight, pos, normal = src_data
            kd.insert(pos, src_vert_index)
        kd.balance()
        
        # 4. Автоматически определяем радиус поиска на основе средней длины ребра
        avg_edge_length = _calculate_average_edge_length(bm)
        search_radius_recalc = avg_edge_length * edge_length_mult
        
        print(f"Average edge length: {avg_edge_length:.4f}, Search radius: {search_radius_recalc:.4f}")
        
        # 5. Градиентное заполнение для вершин без пар
        fill_count = 0
        normal_threshold_cos = math.cos(math.radians(normal_threshold))
        
        for target_vert in bm.verts:
            if target_vert.index in vertices_with_weights:
                continue

            # Позиция симметричной вершины на исходной стороне
            sym_src_pos = Vector((-target_vert.co.x, target_vert.co.y, target_vert.co.z))

            # Ищем ближайшие исходные вершины в радиусе
            nearest_sources = []
            for (co, src_vert_index, dist) in kd.find_range(sym_src_pos, search_radius_recalc):
                if dist <= search_radius_recalc:
                    src_weight, src_pos, src_normal = source_weights[src_vert_index]

                    # ПРОВЕРЯЕМ НОРМАЛИ ТОЛЬКО ЕСЛИ ВКЛЮЧЕНО
                    if check_normals:
                        expected_normal = Vector((-src_normal.x, src_normal.y, src_normal.z))
                        dot_product = expected_normal.dot(target_vert.normal)
                        if dot_product <= normal_threshold_cos:
                            continue  # Пропускаем если нормали не совпадают

                    nearest_sources.append((src_weight, dist, src_vert_index))

            if nearest_sources:
                # Взвешенная интерполяция по расстоянию (гауссово ядро)
                total_weight = 0.0
                total_influence = 0.0

                for src_weight, dist, _ in nearest_sources:
                    # Гауссово ядро для взвешивания
                    influence = math.exp(-(dist * dist) / (2 * (search_radius_recalc * 0.5) ** 2))
                    total_weight += src_weight * influence
                    total_influence += influence

                if total_influence > 0:
                    final_weight = total_weight / total_influence
                    if final_weight > 0.001:  # Порог чтобы избежать шума
                        target_vg.add([target_vert.index], final_weight, 'REPLACE')
                        vertices_with_weights.add(target_vert.index)
                        fill_count += 1
        
        print(f"Gradient fill: {fill_count} vertices filled")

        # Дополнительный пасс: проекция по направлению нормалей (полезно для выпуклых/несимметричных областей)
        projection_fill = 0
        projection_filled_indices = set()
        projection_weights = {}
        if normal_projection and normal_projection_distance and kd:
            # Количество шагов проекции (линейно вдоль нормали)
            for target_vert in bm.verts:
                if target_vert.index in vertices_with_weights:
                    continue

                sym_src_pos = Vector((-target_vert.co.x, target_vert.co.y, target_vert.co.z))

                # Направление для проекции: зеркальное направление нормали целевой вершины
                mirrored_normal = Vector((-target_vert.normal.x, target_vert.normal.y, target_vert.normal.z))
                if mirrored_normal.length == 0:
                    continue
                mirrored_normal.normalize()

                found = False
                for step_i in range(1, normal_projection_steps + 1):
                    t = (normal_projection_distance * step_i) / normal_projection_steps
                    probe_pos = sym_src_pos + mirrored_normal * t

                    nearest = kd.find(probe_pos)
                    if not nearest:
                        continue

                    co_near, src_idx, dist = nearest
                    if dist is None:
                        continue

                    if dist <= normal_projection_distance and src_idx in source_weights:
                        # При необходимости проверяем нормали
                        if check_normals:
                            src_weight, src_pos, src_normal = source_weights[src_idx]
                            expected_normal = Vector((-src_normal.x, src_normal.y, src_normal.z))
                            dot_product = expected_normal.dot(target_vert.normal)
                            if dot_product <= normal_threshold_cos:
                                continue
                        src_weight = source_weights[src_idx][0]
                        if src_weight > 0.001:
                            target_vg.add([target_vert.index], src_weight, 'REPLACE')
                            vertices_with_weights.add(target_vert.index)
                            projection_fill += 1
                            projection_filled_indices.add(target_vert.index)
                            projection_weights[target_vert.index] = src_weight
                            found = True
                            break

                # optionally could continue to next vertex
            print(f"Normal projection fill: {projection_fill} vertices filled")

            # Если нужно применить сглаживание только к запроджекшенным вершинам
            if normal_projection_smooth_steps and projection_filled_indices:
                # Создаем временную группу и заливаем туда только запроджекшенные веса
                temp_name = f"temporary_proj_smooth_{target_vg.name}"
                # Удалим если вдруг существует
                existing = obj.vertex_groups.get(temp_name)
                if existing:
                    obj.vertex_groups.remove(existing)

                temp_vg = obj.vertex_groups.new(name=temp_name)
                for vidx in projection_filled_indices:
                    w = projection_weights.get(vidx, 0.0)
                    if w > 0.0:
                        temp_vg.add([vidx], w, 'REPLACE')

                # Запускаем сглаживание на временной группе
                smooth_vertex_group(obj, temp_name, normal_projection_smooth_steps, .5)

                # Копируем сглаженные веса обратно только для тех вершин, которые были запроджекшены
                smoothed = get_vertices_with_weights(obj, temp_name)
                for vidx, w in smoothed:
                    if vidx in projection_filled_indices:
                        target_vg.add([vidx], w, 'REPLACE')

                # Удаляем временную группу
                try:
                    obj.vertex_groups.remove(temp_vg)
                except Exception:
                    pass

        return len(vertices_with_weights)
        
    except Exception as e:
        print(f"Error in gradient mirror: {e}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        bm.free()

def _calculate_average_edge_length(bm):
    """Вычисляет среднюю длину ребра в меше"""
    total_length = 0.0
    edge_count = 0
    
    for edge in bm.edges:
        if edge.is_valid:
            length = edge.calc_length()
            total_length += length
            edge_count += 1
    
    return total_length / edge_count if edge_count > 0 else 0.1

def _apply_interpolation_mirror(obj, source_name, target_vg, vertex_pairs, check_normals=False, normal_threshold=45.0, search_radius=0.001,
                                normal_projection=False, normal_projection_distance=0.01, normal_projection_steps=3, normal_projection_smooth_steps=2,
                                edge_length_mult=3):
    """Интерполяционный метод с использованием билинейной интерполяции"""
    import bmesh
    from mathutils import Vector
    
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    
    try:
        source_vg = obj.vertex_groups.get(source_name)
        if not source_vg:
            return 0
            
        # 1. Собираем веса исходной стороны
        source_weights = {}
        deform_layer = bm.verts.layers.deform.active
        vg_index = source_vg.index
        
        for vert in bm.verts:
            if vg_index in vert[deform_layer]:
                weight = vert[deform_layer][vg_index]
                if weight > 0:
                    source_weights[vert.index] = (weight, vert.co.copy())
        
        print(f"Source vertices for interpolation: {len(source_weights)}")
        
        # 2. Прямое зеркалирование для вершин с парами
        vertices_with_weights = set()
        
        for src_vert_index, src_data in source_weights.items():
            if src_vert_index in vertex_pairs:
                src_weight = src_data[0]
                target_vert_index = vertex_pairs[src_vert_index]
                target_vg.add([target_vert_index], src_weight, 'REPLACE')
                vertices_with_weights.add(target_vert_index)
        
        print(f"Direct mirror in interpolation: {len(vertices_with_weights)} vertices")
        
        # 3. Строим BVH дерево для быстрого поиска треугольников
        bvh_tree, face_to_orig = _create_bvh_tree_from_faces(bm, source_weights)
        if not bvh_tree or not face_to_orig:
            print("No BVH tree created, falling back to gradient method")
            return _apply_gradient_mirror(obj, source_name, target_vg, vertex_pairs, check_normals,
                                          normal_threshold, search_radius,
                                          normal_projection, normal_projection_distance,
                                          normal_projection_steps, normal_projection_smooth_steps,
                                          edge_length_mult)
        
        # 4. Интерполяционное заполнение для вершин без пар
        fill_count = 0
        
        for target_vert in bm.verts:
            if target_vert.index in vertices_with_weights:
                continue
                
            # Позиция симметричной вершины на исходной стороне
            sym_src_pos = Vector((-target_vert.co.x, target_vert.co.y, target_vert.co.z))
            
            # Ищем ближайший треугольник на исходной стороне
            nearest_face = _find_nearest_face_with_weights(bvh_tree, face_to_orig, sym_src_pos, source_weights)
            
            if nearest_face:
                # Интерполируем вес на основе барицентрических координат
                interpolated_weight = _interpolate_weight_in_face(nearest_face, sym_src_pos, source_weights)
                
                if interpolated_weight is not None and interpolated_weight > 0.001:
                    target_vg.add([target_vert.index], interpolated_weight, 'REPLACE')
                    fill_count += 1
        
        print(f"Interpolation fill: {fill_count} vertices filled")
        return len(vertices_with_weights) + fill_count
        
    except Exception as e:
        print(f"Error in interpolation mirror: {e}")
        import traceback
        traceback.print_exc()
        return _apply_gradient_mirror(obj, source_name, target_vg, vertex_pairs, check_normals,
                                      normal_threshold, search_radius,
                                      normal_projection, normal_projection_distance,
                                      normal_projection_steps, normal_projection_smooth_steps,
                                      edge_length_mult)  # Fallback
    finally:
        bm.free()

def _create_bvh_tree_from_faces(bm, source_weights):
    """Создает BVH дерево из треугольников с весами"""
    from mathutils.bvhtree import BVHTree
    
    vertices = []  # Все вершины в плоском списке
    faces = []     # Индексы для каждого треугольника
    face_to_orig = []  # Маппинг к оригинальным face объектам
    vert_count = 0
    
    # Собираем только те треугольники, у которых все вершины имеют веса
    for face in bm.faces:
        if len(face.verts) == 3:  # Работаем только с треугольниками
            face_has_weights = True
            face_verts = []
            
            for vert in face.verts:
                if vert.index not in source_weights:
                    face_has_weights = False
                    break
                face_verts.append(vert.co.copy())  # Важно: copy() чтобы не было ссылок
            
            if face_has_weights:
                vertices.extend(face_verts)  # Добавляем 3 вершины
                faces.append([vert_count, vert_count + 1, vert_count + 2])  # Индексы этих вершин
                face_to_orig.append(face)  # Сохраняем ссылку на оригинальный face
                vert_count += 3
    
    if not faces:
        return None, None
    
    # Создаем BVH дерево и возвращаем его вместе с маппингом
    return BVHTree.FromPolygons(vertices, faces), face_to_orig

def _find_nearest_face_with_weights(bvh_tree, face_to_orig, position, source_weights):
    """Находит ближайший треугольник с весами к заданной позиции"""
    if not bvh_tree or not face_to_orig:
        return None
    
    # Ищем ближайшую точку на меше
    result = bvh_tree.find_nearest(position)
    if not result:
        return None
        
    location, normal, index, distance = result
    
    if index is not None and index < len(face_to_orig):
        return face_to_orig[index]  # Возвращаем оригинальный face
    
    return None

def _interpolate_weight_in_face(face, position, source_weights):
    """Интерполирует вес в треугольнике на основе барицентрических координат"""
    if len(face.verts) != 3:
        return None
    
    # Получаем вершины треугольника
    v1, v2, v3 = face.verts
    p1, p2, p3 = v1.co, v2.co, v3.co
    
    # Вычисляем барицентрические координаты
    barycentric = geometry.barycentric_transform(
        position, 
        p1, p2, p3,
        Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    )
    
    # Получаем веса вершин
    w1 = source_weights[v1.index][0]
    w2 = source_weights[v2.index][0] 
    w3 = source_weights[v3.index][0]
    
    # Интерполируем вес
    interpolated_weight = (barycentric.x * w1 + 
                          barycentric.y * w2 + 
                          barycentric.z * w3)
    
    return max(0.0, min(1.0, interpolated_weight))

SIDE_SUFFIXES = {'L': ('.l', '.left', '_l', '_left'), 'R': ('.r', '.right', '_r', '_right')}

def group_side(name):
    """'L', 'R' или None — по суффиксу имени группы (без учёта регистра)"""
    lower = name.lower()
    for side, suffixes in SIDE_SUFFIXES.items():
        if lower.endswith(suffixes):
            return side
    return None

def get_mirror_group_name(name):
    """Имя парной группы (с сохранением регистра) или None, если у группы нет суффикса стороны"""
    side = group_side(name)
    return get_opposite_group_name(name, 'L_TO_R' if side == 'L' else 'R_TO_L') if side else None

def get_source_groups(obj, direction, groups_mode):
    """Исходные группы для симметризации: все группы стороны-источника или источник активной пары"""
    if groups_mode == 'SELECTED':
        src = get_mirrored_group_names(obj, direction, 'SELECTED')
        return [src] if src and obj.vertex_groups.get(src) else []
    source_side = 'L' if direction == 'L_TO_R' else 'R'
    return [vg.name for vg in obj.vertex_groups if group_side(vg.name) == source_side]

def mirror_weights_blender(obj, direction='L_TO_R', groups_mode='ALL', use_topology=False):
    return run(mirror_weights_blender_iter(obj, direction, groups_mode, use_topology))


def mirror_weights_blender_iter(obj, direction='L_TO_R', groups_mode='ALL', use_topology=False):
    """Symmetrize встроенным оператором Blender: целевая группа = зеркало исходной (как Smart/Direct, но на C).

    Источник копируется во временную группу, копия зеркалится на месте, результат переносится в парную группу —
    остальные группы, их порядок и блокировки не трогаются.
    """
    sources = get_source_groups(obj, direction, groups_mode)
    original_active = obj.vertex_groups.active.name if obj.vertex_groups.active else None
    done = 0
    for src in sources:
        yield done, len(sources), src
        target_name = get_opposite_group_name(src, direction)
        obj.vertex_groups.active_index = obj.vertex_groups[src].index
        bpy.ops.object.vertex_group_copy()
        tmp = obj.vertex_groups.active
        try:
            bpy.ops.object.vertex_group_mirror(mirror_weights=True, flip_group_names=False,
                                               all_groups=False, use_topology=use_topology)
            mirrored = get_vertices_with_weights(obj, tmp.name)
        finally:
            obj.vertex_groups.remove(tmp)
        target = obj.vertex_groups.get(target_name) or obj.vertex_groups.new(name=target_name)
        clear_vertex_group_weights(obj, target_name)
        for vert_index, weight in mirrored:
            target.add([vert_index], weight, 'REPLACE')
        done += 1
    if original_active and obj.vertex_groups.get(original_active):
        obj.vertex_groups.active_index = obj.vertex_groups[original_active].index
    return done


# ======================= Скиннинг: сглаживание и перенос весов =======================

def _read_weights(obj, names):
    """{имя группы: np.array весов по всем вершинам}"""
    import numpy as np
    n = len(obj.data.vertices)
    idx = {obj.vertex_groups[nm].index: nm for nm in names if obj.vertex_groups.get(nm)}
    out = {nm: np.zeros(n, dtype=np.float64) for nm in idx.values()}
    for v in obj.data.vertices:
        for g in v.groups:
            nm = idx.get(g.group)
            if nm is not None:
                out[nm][v.index] = g.weight
    return out


def _write_weights(obj, name, w, mask=None, eps=1e-4):
    """Записывает массив весов в группу (создаёт её); mask — какие вершины разрешено менять."""
    import numpy as np
    vg = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
    idxs = np.arange(len(w)) if mask is None else np.nonzero(mask)[0]
    keep = w[idxs] > eps
    if (~keep).any():
        vg.remove(idxs[~keep].tolist())
    for i, val in zip(idxs[keep].tolist(), np.minimum(w[idxs[keep]], 1.0).tolist()):
        vg.add([i], val, 'REPLACE')


def _edges(mesh):
    import numpy as np
    e = np.empty(len(mesh.edges) * 2, dtype=np.int64)
    mesh.edges.foreach_get("vertices", e)
    return e.reshape(-1, 2)


def smooth_groups(obj, names, iterations=2, factor=0.5):
    return run(smooth_groups_iter(obj, names, iterations, factor))


def smooth_groups_iter(obj, names, iterations=2, factor=0.5):
    """Лапласово сглаживание весов по рёбрам меша (numpy). Веса растекаются и на соседние вершины, как в Blender Smooth.
    Заблокированные группы (lock_weight) пропускаются. Возвращает число сглаженных групп."""
    import numpy as np
    names = [nm for nm in names if obj.vertex_groups.get(nm) and not obj.vertex_groups[nm].lock_weight]
    if not names:
        return 0
    e = _edges(obj.data)
    n = len(obj.data.vertices)
    deg = np.bincount(e.ravel(), minlength=n).astype(np.float64)
    has = deg > 0
    for i, (nm, w) in enumerate(_read_weights(obj, names).items()):
        yield i, len(names), f"Smooth {nm}"
        for _ in range(iterations):
            s = np.bincount(e[:, 0], weights=w[e[:, 1]], minlength=n) + np.bincount(e[:, 1], weights=w[e[:, 0]], minlength=n)
            w = np.where(has, w * (1 - factor) + (s / np.maximum(deg, 1)) * factor, w)
        _write_weights(obj, nm, w)
    return len(names)


def transfer_weights(src, dst, names, max_distance=0.0, check_normals=True, normal_threshold=60.0, replace=True):
    return run(transfer_weights_iter(src, dst, names, max_distance, check_normals, normal_threshold, replace))


def transfer_weights_iter(src, dst, names, max_distance=0.0, check_normals=True, normal_threshold=60.0, replace=True):
    """Переносит веса групп names с меша src на меш dst (мировые координаты, разная топология и плотность).

    Как в Smart-симметризации: вес берётся барицентрически из ближайшего треугольника источника;
    если он дальше max_distance или смотрит в другую сторону (нормали) — гауссово среднее ближайших вершин
    с подходящей нормалью; что осталось — заполняется от соседей по рёбрам. max_distance 0 = 3 средних ребра.
    Возвращает (число групп, число вершин, заполненных от соседей).
    """
    import numpy as np
    from mathutils import kdtree
    from mathutils.bvhtree import BVHTree
    from mathutils.interpolate import poly_3d_calc

    sm, dm = src.data, dst.data
    S, D = src.matrix_world, dst.matrix_world
    nS, nD = S.to_3x3().inverted().transposed(), D.to_3x3().inverted().transposed()
    s_co = [S @ v.co for v in sm.vertices]
    s_no = [(nS @ v.normal).normalized() for v in sm.vertices]
    if hasattr(sm, "calc_loop_triangles"):
        sm.calc_loop_triangles()
    tris = [tuple(t.vertices) for t in sm.loop_triangles]
    if not tris:
        raise ValueError(f"'{src.name}' has no faces")
    bvh = BVHTree.FromPolygons(s_co, tris)
    kd = kdtree.KDTree(len(s_co))
    for i, co in enumerate(s_co):
        kd.insert(co, i)
    kd.balance()
    if max_distance <= 0:
        lens = [(s_co[a] - s_co[b]).length for a, b in (e.vertices for e in sm.edges)]
        max_distance = 3 * (sum(lens) / len(lens) if lens else 0.1)
    cos_t = math.cos(math.radians(normal_threshold))

    K = 8
    n = len(dm.vertices)
    idx = np.zeros((n, K), dtype=np.int64)
    fac = np.zeros((n, K), dtype=np.float64)
    found = np.zeros(n, dtype=bool)
    sigma2 = 2 * (max_distance * 0.5) ** 2
    for v in dm.vertices:
        if v.index % 2000 == 0:
            yield v.index, n, "Matching surfaces"
        p = D @ v.co
        dn = (nD @ v.normal).normalized()
        loc, normal, fi, dist = bvh.find_nearest(p, max_distance)
        if loc is not None and (not check_normals or normal.dot(dn) >= cos_t):
            t = tris[fi]
            bw = poly_3d_calc([s_co[t[0]], s_co[t[1]], s_co[t[2]]], loc)
            idx[v.index, :3], fac[v.index, :3] = t, bw
            found[v.index] = True
            continue
        cand = [(i, d) for co, i, d in kd.find_n(p, K)
                if d <= max_distance and (not check_normals or s_no[i].dot(dn) >= cos_t)]
        if cand:
            g = np.array([math.exp(-d * d / sigma2) for _, d in cand])
            idx[v.index, :len(cand)] = [i for i, _ in cand]
            fac[v.index, :len(cand)] = g / g.sum()
            found[v.index] = True

    e = _edges(dm)
    src_w = _read_weights(src, names)
    dst_old = _read_weights(dst, [nm for nm in src_w if dst.vertex_groups.get(nm)])
    filled = 0
    for gi, (nm, ws) in enumerate(src_w.items()):
        yield gi, len(src_w), f"Transfer {nm}"
        w = (ws[idx] * fac).sum(axis=1)
        known = found.copy()
        # дыры (нет источника рядом / нормали не совпали): среднее от уже известных соседей, волной
        for _ in range(100):
            if known.all():
                break
            s = np.bincount(e[:, 0], weights=np.where(known[e[:, 1]], w[e[:, 1]], 0), minlength=n) + \
                np.bincount(e[:, 1], weights=np.where(known[e[:, 0]], w[e[:, 0]], 0), minlength=n)
            c = np.bincount(e[:, 0], weights=known[e[:, 1]], minlength=n) + np.bincount(e[:, 1], weights=known[e[:, 0]], minlength=n)
            new = ~known & (c > 0)
            if not new.any():
                break
            w[new] = s[new] / c[new]
            known |= new
        filled = max(filled, int((known & ~found).sum()))
        old = dst_old.get(nm)
        mask = None if replace or old is None else old <= 1e-6  # Add Missing: только вершины без веса
        _write_weights(dst, nm, w, mask)
    return len(src_w), filled


def snapshot_groups(obj, names):
    """Снимок весов групп для отката: {имя: массив весов или None, если группы не было}"""
    names = list(dict.fromkeys(names))
    existing = _read_weights(obj, [n for n in names if obj.vertex_groups.get(n)])
    return {n: existing.get(n) for n in names}


def restore_groups(obj, snap):
    """Возвращает группы к снимку: веса как были, созданные после снимка группы удаляются"""
    for name, w in snap.items():
        if w is None:
            vg = obj.vertex_groups.get(name)
            if vg:
                obj.vertex_groups.remove(vg)
        else:
            _write_weights(obj, name, w, eps=0.0)  # точно как было, включая крошечные веса
