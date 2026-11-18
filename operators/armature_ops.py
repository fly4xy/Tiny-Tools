import bpy, os, json, shutil

from bpy.types import Operator
from ..utils.modal_job import ModalJob
from bpy.props import StringProperty, BoolProperty
from datetime import datetime
from pathlib import Path

from ..utils.file_utils import (
    save_skeleton_to_json, 
    load_skeleton_from_json,
    load_skeleton_bones_from_json,
    load_skeleton_constraints_from_json,
    get_backup_directory
)

from ..utils.armature_utils import(
    adjust_animation_for_pose,
    clear_pose,
    get_current_pose_data,
    restore_pose_from_data,
    process_mesh_with_pose,
    calculate_pose_difference,
    apply_current_pose_as_rest_pose,
    temporarily_remove_constraints,
    restore_constraints_from_data

)
from ..utils.anim_compat import get_fcurves, get_groups, assign_action

#Бэкап и Восстановление СКЕЛЕТА

class TT_OT_BackupArmature(Operator):
    bl_idname = "tiny_tools.backup_armature"
    bl_label = "Backup Armature to JSON"
    bl_description = "Backup selected armature to JSON (Rest pose, hierarchy, constraints)"

    def execute(self, context):
        props = context.scene.tiny_tools_props
        arm_name = props.armature.source_armature
        if not arm_name or arm_name == "NONE" or arm_name not in bpy.data.objects:
            self.report({'ERROR'}, "Source armature not selected or not found")
            return {'CANCELLED'}
        arm = bpy.data.objects[arm_name]
        date = datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = f"BACKUP_{arm_name}_{date}.json"
        
        # ИСПОЛЬЗУЕМ ЕДИНУЮ ФУНКЦИЮ
        armature_dir = get_backup_directory('Armature')
        path = os.path.join(armature_dir, filename)
        
        try:
            save_skeleton_to_json(arm, str(path))
            self.report({'INFO'}, f"Saved backup: {filename}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to save: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

class TT_OT_RestoreArmature(Operator):
    bl_idname = "tiny_tools.restore_armature"
    bl_label = "Apply JSON to Armature"
    bl_description = "Apply JSON data to the chosen target armature"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.tiny_tools_props
        target_name = props.armature.target_armature
        json_path = props.armature.json_path

        if not json_path:
            self.report({'ERROR'}, "JSON файл не выбран")
            return {'CANCELLED'}
        if not target_name or target_name == "NONE" or target_name not in bpy.data.objects:
            self.report({'ERROR'}, "Target armature not selected or not found")
            return {'CANCELLED'}

        target = bpy.data.objects[target_name]
        source_name = self.get_source_armature_name(json_path)

        try:
            load_skeleton_from_json(target, bpy.path.abspath(json_path), source_arm_name=source_name)
            self.report({'INFO'}, f"Applied JSON to {target.name}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to restore: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

    def get_source_armature_name(self, json_path):
        """Получает имя исходной арматуры из JSON файла"""
        try:
            with open(bpy.path.abspath(json_path), "r", encoding="utf-8") as f:
                j = json.load(f)
            source_name = None
            for pb_name, clist in j.get("constraints", {}).items():
                for c in clist:
                    props_dict = c.get("properties", {})
                    for _, vv in props_dict.items():
                        if isinstance(vv, dict) and "__name__" in vv:
                            maybe = vv["__name__"]
                            if maybe in bpy.data.objects and bpy.data.objects[maybe].type == 'ARMATURE':
                                source_name = maybe
                                break
                    if source_name:
                        break
                if source_name:
                    break
            return source_name
        except Exception:
            return None

class TT_OT_RestoreBonesOnly(Operator):
    bl_idname = "tiny_tools.restore_bones_only"
    bl_label = "Restore Bones Only"
    bl_description = "Restore only bone hierarchy and positions from JSON"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.tiny_tools_props
        target_name = props.armature.target_armature
        json_path = props.armature.json_path

        if not json_path:
            self.report({'ERROR'}, "JSON файл не выбран")
            return {'CANCELLED'}
        if not target_name or target_name == "NONE" or target_name not in bpy.data.objects:
            self.report({'ERROR'}, "Target armature not selected or not found")
            return {'CANCELLED'}

        target = bpy.data.objects[target_name]

        try:
            load_skeleton_bones_from_json(target, bpy.path.abspath(json_path))
            self.report({'INFO'}, f"Restored bones to {target.name}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to restore bones: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

class TT_OT_RestoreConstraintsOnly(Operator):
    bl_idname = "tiny_tools.restore_constraints_only"
    bl_label = "Restore Constraints Only"
    bl_description = "Restore only constraints from JSON"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.tiny_tools_props
        target_name = props.armature.target_armature
        json_path = props.armature.json_path

        if not json_path:
            self.report({'ERROR'}, "JSON файл не выбран")
            return {'CANCELLED'}
        if not target_name or target_name == "NONE" or target_name not in bpy.data.objects:
            self.report({'ERROR'}, "Target armature not selected or not found")
            return {'CANCELLED'}

        target = bpy.data.objects[target_name]
        source_name = TT_OT_RestoreArmature.get_source_armature_name(self, json_path)

        try:
            load_skeleton_constraints_from_json(target, bpy.path.abspath(json_path), source_arm_name=source_name)
            self.report({'INFO'}, f"Restored constraints to {target.name}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to restore constraints: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

#Бэкап и Восстановление АНИМАЦИЙ

class TT_OT_ExportAllAnimations(ModalJob, Operator):
    bl_idname = "tiny_tools.export_all_animations"
    bl_label = "Export All Animations"
    bl_description = "Export all armature animations to one JSON file with GZIP compression (Esc cancels)"

    def job(self, context, state):
        from ..utils.file_utils import export_animations_to_json_iter
        props = context.scene.tiny_tools_props
        arm = bpy.data.objects.get(props.armature.source_armature)
        if not arm:
            return ('ERROR', "Source armature not selected or not found")
        date = datetime.now().strftime("%Y-%m-%d_%H-%M")
        blend_name = Path(bpy.data.filepath).stem if bpy.data.filepath else "unsaved"
        filename = f"{blend_name}_animations_{date}.json.gz"
        yield from export_animations_to_json_iter(arm, os.path.join(get_backup_directory('Animations'), filename))
        return ('INFO', f"Exported all animations with GZIP: {filename}")

    def cancel_job(self, context, state):
        return "file not written"  # файл пишется только в конце

class TT_OT_ExportActiveAnimation(Operator):
    bl_idname = "tiny_tools.export_active_animation"
    bl_label = "Export Active Animation"
    bl_description = "Export active animation to JSON file with GZIP compression"
    
    def execute(self, context):
        # Получаем активную анимацию
        active_action = None
        active_obj = context.active_object
        
        if active_obj and active_obj.animation_data and active_obj.animation_data.action:
            active_action = active_obj.animation_data.action
        else:
            # Пробуем найти через арматуру из модификаторов
            if active_obj and active_obj.type == 'MESH':
                from ..utils.action_utils import find_armature_from_modifiers
                armature_obj = find_armature_from_modifiers(active_obj)
                if armature_obj and armature_obj.animation_data and armature_obj.animation_data.action:
                    active_action = armature_obj.animation_data.action
        
        if not active_action:
            self.report({'ERROR'}, "No active animation found")
            return {'CANCELLED'}
        
        date = datetime.now().strftime("%Y-%m-%d_%H-%M")
        animations_dir = get_backup_directory('Animations')
        clean_name = self.clean_filename(active_action.name)  # ТЕПЕРЬ ЭТОТ МЕТОД ЕСТЬ
        filename = f"{clean_name}_{date}.json.gz"
        path = os.path.join(animations_dir, filename)
        
        try:
            from ..utils.file_utils import export_animations_to_json
            export_animations_to_json(None, path, [active_action.name])
            self.report({'INFO'}, f"Exported active animation with GZIP: {filename}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export animation: {e}")
            return {'CANCELLED'}
            
        return {'FINISHED'}
    
    def clean_filename(self, filename):
        """Очищает имя файла от недопустимых символов"""
        import re
        # Заменяем недопустимые символы на подчеркивания
        clean_name = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Удаляем начальные и конечные пробелы/точки
        clean_name = clean_name.strip(' .')
        # Если имя стало пустым, используем запасной вариант
        if not clean_name:
            clean_name = "unnamed_animation"
        return clean_name

class TT_OT_ExportEachAnimation(ModalJob, Operator):
    bl_idname = "tiny_tools.export_each_animation"
    bl_label = "Export Each Animation Separately"
    bl_description = "Export each animation to a separate JSON file with GZIP compression (Esc cancels)"

    def job(self, context, state):
        from ..utils.file_utils import export_animations_to_json
        from ..utils.fbx_export import clean_filename
        if not bpy.data.actions:
            return ('WARNING', "No animations to export")
        props = context.scene.tiny_tools_props
        arm_obj = bpy.data.objects.get(props.armature.source_armature) or \
            next((o for o in context.scene.objects if o.type == 'ARMATURE'), None)
        if not arm_obj:
            return ('ERROR', "No armature found for export")
        date = datetime.now().strftime("%Y-%m-%d_%H-%M")
        folder = os.path.join(get_backup_directory('Animations'), f"animations_{date}")
        Path(folder).mkdir(parents=True, exist_ok=True)
        names = [a.name for a in bpy.data.actions]
        state["written"] = 0
        for i, name in enumerate(names):
            yield i, len(names), name
            export_animations_to_json(arm_obj, os.path.join(folder, f"{clean_filename(name)}.json.gz"), [name])
            state["written"] += 1
        return ('INFO', f"Exported {len(names)} animations with GZIP to {folder}")

    def cancel_job(self, context, state):
        return f"{state.get('written', 0)} file(s) already written"

class TT_OT_ExportAnimationsFBX(ModalJob, Operator):
    bl_idname = "tiny_tools.export_animations_fbx"
    bl_label = "Export Animations (FBX)"
    bl_description = ("Export the skeleton with animation (no meshes) to FBX for game engines: "
                      "Active — the current animation, All — every animation of this skeleton into separate files. "
                      "Esc cancels")

    mode: bpy.props.EnumProperty(items=[('ACTIVE', "Active", ""), ('ALL', "All", "")])

    def job(self, context, state):
        from ..utils.fbx_export import export_actions_fbx_iter
        from ..utils.action_utils import is_action_compatible
        props = context.scene.tiny_tools_props
        arm = bpy.data.objects.get(props.armature.source_armature)
        if not arm or arm.type != 'ARMATURE':
            return ('ERROR', "Source armature not selected or not found")
        if self.mode == 'ACTIVE':
            action = arm.animation_data.action if arm.animation_data else None
            actions = [action] if action else []
        else:
            actions = [a for a in bpy.data.actions if is_action_compatible(a, arm)]
        if not actions:
            return ('ERROR', "No animations for this armature")
        p = props.animation
        folder = bpy.path.abspath(p.fbx_export_dir) if p.fbx_export_dir else get_backup_directory('FBX')
        state["actions"] = actions
        paths = yield from export_actions_fbx_iter(context, arm, actions, folder, p)
        return ('INFO', f"Exported {len(paths)} FBX file(s) to {folder}")

    def cancel_job(self, context, state):
        return "scene restored, files exported so far are kept"

class TT_OT_LoadAnimationList(Operator):
    bl_idname = "tiny_tools.load_animation_list"
    bl_label = "Load Animation List"
    bl_description = "Load list of animations from JSON file"
    
    def execute(self, context):
        props = context.scene.tiny_tools_props
        json_path = props.animation.animation_json_path

        if not json_path:
            self.report({'ERROR'}, "Animation JSON file not selected")
            return {'CANCELLED'}

        try:
            from ..utils.file_utils import load_animations_from_json
            animations = load_animations_from_json(bpy.path.abspath(json_path))
            
            # Очищаем текущий список
            props.animation.loaded_animations_list.clear()
            
            # Заполняем новыми анимациями
            for anim in animations:
                item = props.animation.loaded_animations_list.add()
                item.name = anim.get('name', 'Unknown')
                item.frame_start = anim.get('frame_start', 0)
                item.frame_end = anim.get('frame_end', 0)
                item.exists_in_blend = anim.get('exists_in_blend', False)  # ДОБАВИТЬ ЭТУ СТРОКУ
            
            # Показываем блок с загруженными анимациями
            props.animation.show_loaded_animations = True
            
            self.report({'INFO'}, f"Loaded {len(animations)} animations")
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load animation list: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

class TT_OT_ClearLoadedAnimations(Operator):
    bl_idname = "tiny_tools.clear_loaded_animations"
    bl_label = "Clear Loaded Animations"
    bl_description = "Clear loaded animations cache"
    
    def execute(self, context):
        props = context.scene.tiny_tools_props
        props.animation.loaded_animations_list.clear()
        props.animation.show_loaded_animations = False
        return {'FINISHED'}

class TT_OT_ImportSelectedAnimations(ModalJob, Operator):
    bl_idname = "tiny_tools.import_selected_animations"
    bl_label = "Import Selected Animations"
    bl_description = ("Import the selected animations from the JSON file. "
                      "Replace mode overwrites existing animations (Ctrl+Z reverts). Esc stops")
    bl_options = {'REGISTER', 'UNDO'}

    def job(self, context, state):
        from ..utils.file_utils import import_animations_from_json_iter
        props = context.scene.tiny_tools_props
        json_path = props.animation.animation_json_path
        if not json_path:
            return ('ERROR', "Animation JSON file not selected")
        selected = [i for i, item in enumerate(props.animation.loaded_animations_list) if item.select]
        if not selected:
            return ('WARNING', "No animations selected")
        imported, skipped = yield from import_animations_from_json_iter(
            bpy.path.abspath(json_path), selected, props.animation.animation_import_mode)
        if imported:
            return ('INFO', f"Imported {imported} animations ({skipped} skipped)")
        return ('WARNING', f"No animations imported ({skipped} skipped)")

#Анимации

class TT_OT_SelectAnimation(Operator):
    bl_idname = "tiny_tools.select_animation"
    bl_label = "Select Animation"
    bl_description = "Select this animation and set it as active"
    bl_options = {'REGISTER', 'UNDO'}
    
    action_name: StringProperty() # type: ignore
    
    def execute(self, context):
        action = bpy.data.actions.get(self.action_name)
        if not action:
            return {'CANCELLED'}
        
        # Ищем подходящий объект для экшена
        from ..utils.action_utils import find_target_object_for_action
        target_obj = find_target_object_for_action(action, context)
        
        if not target_obj:
            self.report({'WARNING'}, f"No compatible object found for action '{action.name}'")
            return {'CANCELLED'}
        
        # Устанавливаем экшен на найденный объект
        assign_action(target_obj, action)
        
        # Обновляем интерфейс
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
                
        return {'FINISHED'}

class TT_OT_AddAnimation(Operator):
    bl_idname = "tiny_tools.add_animation"
    bl_label = "Add Animation"
    bl_description = "Create new animation"
    bl_options = {'REGISTER', 'UNDO'}
    
    new_animation_name: StringProperty(name="Animation Name", default="NewAnimation") # type: ignore
    
    def execute(self, context):
        if not self.new_animation_name:
            self.report({'WARNING'}, "Animation name cannot be empty")
            return {'CANCELLED'}
        
        # Создаем новую анимацию
        new_action = bpy.data.actions.new(name=self.new_animation_name)
        
        # Устанавливаем как активную если есть подходящий объект
        active_obj = context.active_object
        if active_obj:
            assign_action(active_obj, new_action)
        
        return {'FINISHED'}
    
    def invoke(self, context, event):
        self.new_animation_name = "NewAnimation"
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_animation_name")

class TT_OT_RenameAnimation(Operator):
    bl_idname = "tiny_tools.rename_animation"
    bl_label = "Rename Animation"
    bl_description = "Rename selected or active animation"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        props = context.scene.tiny_tools_props

        if not props.animation.animation_rename_new_name:
            self.report({'WARNING'}, "Animation name cannot be empty")
            return {'CANCELLED'}
        
        # Приоритет: выбранные галочкой → активный
        selected_actions = [action for action in bpy.data.actions if getattr(action, "select", False)]
        
        if selected_actions:
            # Переименовываем первый выбранный
            selected_actions[0].name = props.animation.animation_rename_new_name
        else:
            # Переименовываем активный
            active_action = self.get_active_action_with_priority(context)
            if active_action:
                active_action.name = props.animation.animation_rename_new_name
            else:
                self.report({'WARNING'}, "No animation selected or active")
                return {'CANCELLED'}
        
        return {'FINISHED'}
    
    def get_active_action_with_priority(self, context):
        """Копия метода из панели для определения активного экшена"""
        active_obj = context.active_object
        if not active_obj:
            return None
        
        if active_obj.animation_data and active_obj.animation_data.action:
            return active_obj.animation_data.action
        
        if active_obj.type == 'MESH':
            from ..utils.action_utils import find_armature_from_modifiers
            armature_obj = find_armature_from_modifiers(active_obj)
            if armature_obj and armature_obj.animation_data and armature_obj.animation_data.action:
                return armature_obj.animation_data.action
        
        return None
    
    def invoke(self, context, event):
        # Устанавливаем текущее имя анимации по умолчанию
        props = context.scene.tiny_tools_props
        props.animation.animation_rename_new_name = ""
        
        # Находим анимацию для переименования
        selected_actions = [action for action in bpy.data.actions if getattr(action, "select", False)]
        if selected_actions:
            props.animation.animation_rename_new_name = selected_actions[0].name
        else:
            active_action = self.get_active_action_with_priority(context)
            if active_action:
                props.animation.animation_rename_new_name = active_action.name

        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.tiny_tools_props
        layout.prop(props.animation, "animation_rename_new_name")

class TT_OT_DeleteAnimations(Operator):
    bl_idname = "tiny_tools.delete_animations"
    bl_label = "Delete Animations"
    bl_description = "Delete selected animations"
    bl_options = {'REGISTER', 'UNDO'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)
    
    def execute(self, context):
        selected_actions = [action for action in bpy.data.actions if getattr(action, "select", False)]
        
        if not selected_actions:
            self.report({'WARNING'}, "No animations selected")
            return {'CANCELLED'}
        
        deleted_count = 0
        for action in selected_actions:
            try:
                bpy.data.actions.remove(action)
                deleted_count += 1
            except:
                self.report({'WARNING'}, f"Could not delete {action.name}")
        
        self.report({'INFO'}, f"Deleted {deleted_count} animations")
        return {'FINISHED'}

class TT_OT_ToggleAllAnimationsLock(Operator):
    bl_idname = "tiny_tools.toggle_all_animations_lock"
    bl_label = "Lock/Unlock All Animations"
    bl_description = "Lock or unlock all animations' bone groups"
    bl_options = {'REGISTER', 'UNDO'}
    
    lock_all: BoolProperty(default=True)  # type: ignore # True = lock, False = unlock
    
    def execute(self, context):
        for action in bpy.data.actions:
            # Фильтр поиска если нужно
            props = context.scene.tiny_tools_props
            if props.animation.animation_search:
                if props.animation.animation_search.lower() not in action.name.lower():
                    continue
            
            # Блокируем/разблокируем все группы
            for group in get_groups(action):
                group.lock = self.lock_all
                
            for fcurve in get_fcurves(action):
                if fcurve.group and fcurve.group.lock == self.lock_all:
                    fcurve.lock = self.lock_all
                    # fcurve.mute = self.lock_all
        
        # Обновляем интерфейс
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
                
        return {'FINISHED'}

class TT_OT_ToggleActionLock(Operator):
    bl_idname = "tiny_tools.toggle_action_lock"
    bl_label = "Lock/Unlock"
    bl_description = "Lock or unlock this action's bone groups and their F-curves"
    bl_options = {'REGISTER', 'UNDO'}
    
    action_name: StringProperty() # type: ignore
    
    def execute(self, context):
        action = bpy.data.actions.get(self.action_name)
        if not action:
            return {'CANCELLED'}
        
        # Определяем текущее состояние блокировки
        current_state = self.get_action_lock_state(action)
        
        # Переключаем состояние
        if current_state in ['ALL_UNLOCKED', 'PARTLY_LOCKED']:
            # Блокируем все группы и F-curves
            self.lock_action_groups_and_curves(action, True)
        else:
            # Разблокируем все группы и F-curves
            self.lock_action_groups_and_curves(action, False)
        
        return {'FINISHED'}
    
    def get_action_lock_state(self, action):
        """Определяет состояние блокировки групп костей в анимации"""
        if not get_groups(action):
            return 'ALL_UNLOCKED'
        
        locked_count = 0
        total_count = 0
        
        for group in get_groups(action):
            total_count += 1
            if group.lock:
                locked_count += 1
        
        if locked_count == 0:
            return 'ALL_UNLOCKED'
        elif locked_count == total_count:
            return 'ALL_LOCKED'
        else:
            return 'PARTLY_LOCKED'
    
    def lock_action_groups_and_curves(self, action, lock_state):
        """Блокирует или разблокирует все группы костей и их F-curves в анимации"""
        # Блокируем/разблокируем группы
        for group in get_groups(action):
            group.lock = lock_state
        
        # Блокируем/разблокируем F-curves, принадлежащие этим группам
        for fcurve in get_fcurves(action):
            if fcurve.group and fcurve.group.lock == lock_state:
                fcurve.lock = lock_state
                # fcurve.mute = lock_state

#Позы

class TT_OT_CopyPose(Operator):
    bl_idname = "tiny_tools.copy_pose"
    bl_label = "Copy Pose"
    bl_description = "Copy current pose to cache"
    
    def execute(self, context):
        obj = context.active_object

        original_active = context.view_layer.objects.active
        original_mode = original_active.mode if original_active else 'OBJECT'

        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an armature object")
            return {'CANCELLED'}  
        try:
            from ..utils.file_utils import save_pose_to_cache
            save_pose_to_cache(obj, "copied_pose")
            self.report({'INFO'}, "Pose copied to cache")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to copy pose: {e}")
            return {'CANCELLED'}
        finally:
            context.view_layer.objects.active = original_active
            try:
                bpy.ops.object.mode_set(mode=original_mode)
            except:
                pass
        
        return {'FINISHED'}

class TT_OT_PastePose(Operator):
    bl_idname = "tiny_tools.paste_pose"
    bl_label = "Paste Pose"
    bl_description = "Paste pose from cache"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        obj = context.active_object

        original_active = context.view_layer.objects.active
        original_mode = original_active.mode if original_active else 'OBJECT'

        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an armature object")
            return {'CANCELLED'}
        
        try:
            from ..utils.file_utils import load_pose_from_cache
            success = load_pose_from_cache(obj, "copied_pose")
            if success:
                self.report({'INFO'}, "Pose pasted from cache")
            else:
                self.report({'ERROR'}, "No pose in cache - copy pose first")
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to paste pose: {e}")
            return {'CANCELLED'}
        finally:
            context.view_layer.objects.active = original_active
            try:
                bpy.ops.object.mode_set(mode=original_mode)
            except:
                pass
        
        return {'FINISHED'}

#Pose Master

class TT_OT_VerifyPoseArmature(Operator):
    bl_idname = "tiny_tools.verify_pose_armature"
    bl_label = "Verify Armature"
    bl_description = "Verify if armature is ready for pose operations"
    
    def execute(self, context):
        props = context.scene.tiny_tools_props
        pose_props = props.pose_master
        
        target_name = pose_props.pose_target_armature
            
        if not target_name or target_name not in bpy.data.objects:
            self.report({'ERROR'}, "Target armature not selected or not found")
            return {'CANCELLED'}
        
        target_armature = bpy.data.objects[target_name]
        
        try:
            # Простая проверка - арматура существует и в режиме объекта
            if target_armature.type != 'ARMATURE':
                pose_props.pose_verification_status = 'INVALID'
                pose_props.pose_verification_message = "Selected object is not an armature"
                self.report({'ERROR'}, "Selected object is not an armature")
            else:
                pose_props.pose_verification_status = 'VALID'
                pose_props.pose_verification_message = "Armature ready for pose operations"
                self.report({'INFO'}, "Armature verification successful")
                
        except Exception as e:
            pose_props.pose_verification_status = 'INVALID'
            pose_props.pose_verification_message = f"Verification error: {str(e)}"
            self.report({'ERROR'}, f"Verification failed: {e}")
            return {'CANCELLED'}
            
        return {'FINISHED'}

class TT_OT_UpdatePoseCounts(Operator):
    bl_idname = "tiny_tools.update_pose_counts"
    bl_label = "Update Counts"
    bl_description = "Update selected animations and linked meshes counts"
    
    def execute(self, context):
        props = context.scene.tiny_tools_props
        pose_props = props.pose_master
        
        # Обновляем количество выбранных анимаций
        selected_animations = [action for action in bpy.data.actions if getattr(action, "select", False)]
        pose_props.selected_animations_count = len(selected_animations)
        
        # Обновляем количество связанных мешей
        target_name = pose_props.pose_target_armature
        linked_meshes = []
        
        if target_name and target_name in bpy.data.objects:
            target_armature = bpy.data.objects[target_name]
            
            # Находим все меши с модификатором арматуры, ссылающимся на эту арматуру
            for obj in bpy.data.objects:
                if obj.type == 'MESH':
                    for mod in obj.modifiers:
                        if mod.type == 'ARMATURE' and mod.object == target_armature:
                            linked_meshes.append(obj)
                            break
            
            # Если включена опция "только выделенные", фильтруем
            if pose_props.apply_only_to_selected_meshes:
                selected_meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
                linked_meshes = [mesh for mesh in linked_meshes if mesh in selected_meshes]
        
        pose_props.linked_meshes_count = len(linked_meshes)
        
        return {'FINISHED'}

def _mesh_snapshot(o):
    """Координаты меша и всех shape keys — чтобы отменить запекание позы"""
    import numpy as np
    n = len(o.data.vertices)
    co = np.empty(n * 3, dtype=np.float32)
    o.data.vertices.foreach_get("co", co)
    keys = []
    if o.data.shape_keys:
        for kb in o.data.shape_keys.key_blocks:
            a = np.empty(n * 3, dtype=np.float32)
            kb.data.foreach_get("co", a)
            keys.append(a)
    return co, keys


def _mesh_restore(o, snap):
    co, keys = snap
    o.data.vertices.foreach_set("co", co)
    if o.data.shape_keys:
        for kb, a in zip(o.data.shape_keys.key_blocks, keys):
            kb.data.foreach_set("co", a)
    o.data.update()


class TT_OT_ApplyPoseMaster(ModalJob, Operator):
    bl_idname = "tiny_tools.apply_pose_master"
    bl_label = "Apply Pose as Rest"
    bl_description = ("Apply the current pose as the new rest pose with the selected options. "
                      "Esc during mesh processing cancels and reverts")
    bl_options = {'REGISTER', 'UNDO'}

    def job(self, context, state):
        props = context.scene.tiny_tools_props
        pose_props = props.pose_master
        target_name = pose_props.pose_target_armature
        if not target_name or target_name not in bpy.data.objects:
            return ('ERROR', "Target armature not found")
        target_armature = bpy.data.objects[target_name]
        if target_armature.type != 'ARMATURE':
            return ('ERROR', f"'{target_name}' is not an armature")
        if target_armature.name not in context.view_layer.objects:
            return ('ERROR', f"'{target_name}' is not in the View Layer")

        # Меши вне View Layer нельзя обработать, а после смены rest-позы они деформируются неверно — отменяем заранее
        if pose_props.apply_to_linked_meshes and not pose_props.apply_only_to_selected_meshes:
            unreachable = [o.name for o in bpy.data.objects if o.type == 'MESH'
                           and o.name not in context.view_layer.objects
                           and any(m.type == 'ARMATURE' and m.object == target_armature for m in o.modifiers)]
            if unreachable:
                shown = ", ".join(unreachable[:5]) + (f" (+{len(unreachable) - 5})" if len(unreachable) > 5 else "")
                return ('ERROR', f"Linked meshes outside the View Layer: {shown}. "
                                 "Enable their collections or use 'Apply Only to Selected Meshes'")

        original_active = context.view_layer.objects.active
        original_mode = original_active.mode if original_active else 'OBJECT'
        original_action = target_armature.animation_data.action if target_armature.animation_data else None
        if target_armature.animation_data:
            target_armature.animation_data.action = None

        constraints_cache = None
        failed_meshes = []
        state["meshes"] = []
        try:
            context.view_layer.objects.active = target_armature
            bpy.ops.object.mode_set(mode='POSE')
            original_pose_data = get_current_pose_data(target_armature)
            if pose_props.ignore_constraints:
                constraints_cache = temporarily_remove_constraints(target_armature)

            linked_meshes = []
            if pose_props.apply_to_linked_meshes:
                linked_meshes = [o for o in bpy.data.objects if o.type == 'MESH'
                                 and any(m.type == 'ARMATURE' and m.object == target_armature for m in o.modifiers)
                                 and (not pose_props.apply_only_to_selected_meshes or o.select_get())]
            for i, mesh_obj in enumerate(linked_meshes):
                yield i, len(linked_meshes), mesh_obj.name
                state["meshes"].append((mesh_obj, _mesh_snapshot(mesh_obj)))
                try:
                    ok = process_mesh_with_pose(mesh_obj, target_armature)
                except Exception as e:
                    print(f"Failed to process mesh {mesh_obj.name}: {e}")
                    ok = False
                if not ok:
                    failed_meshes.append(mesh_obj.name)
            # последняя точка отмены: дальше подгонка анимаций и rest-поза выполняются целиком
            yield len(linked_meshes), max(len(linked_meshes), 1), "Applying rest pose"

            transform_diff = {}
            if pose_props.adapt_selected_animations:
                clear_pose(target_armature)
                base_pose_data = get_current_pose_data(target_armature)
                restore_pose_from_data(target_armature, original_pose_data)
                transform_diff = calculate_pose_difference(base_pose_data, original_pose_data)
            if transform_diff:
                for action in [a for a in bpy.data.actions if getattr(a, "select", False)]:
                    try:
                        adjust_animation_for_pose(action, transform_diff)
                    except Exception as e:
                        print(f"Failed to adjust animation {action.name}: {e}")
            apply_current_pose_as_rest_pose(target_armature)
            state["meshes"] = []  # rest применён — откатывать меши уже нельзя
        finally:
            # Констрейнты возвращаем всегда, даже после ошибки или отмены — иначе они потеряны
            if constraints_cache is not None:
                try:
                    restore_constraints_from_data(target_armature, constraints_cache)
                except Exception as e:
                    print(f"Failed to restore constraints: {e}")
            bpy.context.view_layer.objects.active = original_active
            if target_armature.animation_data:
                assign_action(target_armature, original_action)
            if original_active and original_mode != 'OBJECT':
                try:
                    bpy.ops.object.mode_set(mode=original_mode)
                except RuntimeError:
                    pass
        if failed_meshes:
            return ('WARNING', f"Pose applied, but {len(failed_meshes)} mesh(es) failed: {', '.join(failed_meshes[:5])}")
        return ('INFO', "Pose operations completed successfully")

    def cancel_job(self, context, state):
        for obj, snap in state.get("meshes", []):
            _mesh_restore(obj, snap)
        return True

class TT_OT_OpenBackupFolder(Operator):
    bl_idname = "tiny_tools.open_backup_folder"
    bl_label = "Open Backup Folder"
    bl_description = "Open the folder where Tiny Tools saves armature and animation backups"

    path: StringProperty(options={'SKIP_SAVE'})  # пусто — папка BACKUP_<файл>

    def execute(self, context):
        path = bpy.path.abspath(self.path) if self.path else get_backup_directory()
        os.makedirs(path, exist_ok=True)
        bpy.ops.wm.path_open(filepath=path)
        return {'FINISHED'}

class TT_OT_SetFrameRangeFromAction(Operator):
    bl_idname = "tiny_tools.set_frame_range_from_action"
    bl_label = "Set Frame Range"
    bl_description = "Set the scene frame range to the active animation's range"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        action = TT_OT_RenameAnimation.get_active_action_with_priority(self, context)
        if not action:
            self.report({'WARNING'}, "No active animation")
            return {'CANCELLED'}
        start, end = action.frame_range
        context.scene.frame_start, context.scene.frame_end = int(round(start)), int(round(end))
        self.report({'INFO'}, f"Frame range: {context.scene.frame_start}-{context.scene.frame_end}")
        return {'FINISHED'}

#Ключи

class TT_OT_SoftCopyKeyframes(Operator):
    bl_idname = "tiny_tools.soft_copy_keyframes"
    bl_label = "Soft Copy Keys"
    bl_description = "Copy only existing keyframes at current frame"
    
    def execute(self, context):
        obj = context.active_object
        if not obj or not obj.animation_data or not obj.animation_data.action:
            self.report({'ERROR'}, "No active action found")
            return {'CANCELLED'}
        
        frame = context.scene.frame_current
        action = obj.animation_data.action
        
        from ..utils.action_utils import soft_copy_keyframes, cache_keyframes
        keyframe_data = soft_copy_keyframes(action, frame)
        cache_keyframes(keyframe_data, "copied_keys")
        
        self.report({'INFO'}, f"Soft copied {len(keyframe_data)} keys at frame {frame}")
        return {'FINISHED'}

class TT_OT_HardCopyKeyframes(Operator):
    bl_idname = "tiny_tools.hard_copy_keyframes"
    bl_label = "Hard Copy Keys"
    bl_description = "Copy all parameter values at current frame (virtual keys)"
    
    def execute(self, context):
        obj = context.active_object
        if not obj or not obj.animation_data or not obj.animation_data.action:
            self.report({'ERROR'}, "No active action found")
            return {'CANCELLED'}
        
        frame = context.scene.frame_current
        action = obj.animation_data.action
        
        from ..utils.action_utils import hard_copy_keyframes, cache_keyframes
        keyframe_data = hard_copy_keyframes(action, frame)
        cache_keyframes(keyframe_data, "copied_keys")
        
        self.report({'INFO'}, f"Hard copied {len(keyframe_data)} keys at frame {frame}")
        return {'FINISHED'}

class TT_OT_PasteKeyframes(Operator):
    bl_idname = "tiny_tools.paste_keyframes"
    bl_label = "Paste Keys"
    bl_description = "Paste copied keyframes at current frame"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        obj = context.active_object
        if not obj or not obj.animation_data or not obj.animation_data.action:
            self.report({'ERROR'}, "No active action found")
            return {'CANCELLED'}
        
        frame = context.scene.frame_current
        action = obj.animation_data.action
        
        from ..utils.action_utils import get_cached_keyframes
        keyframe_data = get_cached_keyframes("copied_keys")
        
        if not keyframe_data:
            self.report({'ERROR'}, "No keys in cache - copy keys first")
            return {'CANCELLED'}
        
        from ..utils.action_utils import paste_keyframes
        pasted_count = paste_keyframes(action, frame, keyframe_data)

        self.report({'INFO'}, f"Pasted {pasted_count} keys at frame {frame}")
        return {'FINISHED'}

#Подсветка костей в аутлайнере

class TT_OT_BoneSelectLink(Operator):
    bl_idname = "tiny_tools.bone_select_link"
    bl_label = "Bone Select Link"
    bl_description = "Sync bone selection with Outliner (Toggle)"
    
    _timer = None
    _running = False
    _last_selected_bones = set()
    
    @classmethod
    def poll(cls, context):
        # Разрешаем запуск только если оператор не уже работает
        return not cls._running
    
    def modal(self, context, event):
        # Проверяем выключена ли опция sync
        if not context.scene.tiny_tools_props.bone_select_link:
            self.stop_modal(context)
            return {'CANCELLED'}
        
        # Обрабатываем только TIMER события, остальные пропускаем
        # Преобразуем event.type в строку чтобы избежать ошибок со странными event.type
        event_type = str(event.type) if hasattr(event, 'type') else 'UNKNOWN'

        # Проверяем выделение каждые 0.3 секунды (интервал из event_timer_add)
        if event_type == 'TIMER':
            current_selected_bones = set()
            
            # Собираем выделенные кости в зависимости от режима
            if bpy.context.mode == 'POSE' and bpy.context.selected_pose_bones:
                for bone in bpy.context.selected_pose_bones:
                    current_selected_bones.add(bone.name)
            elif bpy.context.mode == 'EDIT_ARMATURE' and bpy.context.selected_bones:
                for bone in bpy.context.selected_bones:
                    current_selected_bones.add(bone.name)
            
            if current_selected_bones != self._last_selected_bones:
                self._last_selected_bones = current_selected_bones.copy()
                
                if current_selected_bones:
                    from ..utils.selection_sync import focus_on_selected_bone_in_outliner
                    focus_on_selected_bone_in_outliner()
        
        return {'PASS_THROUGH'}
    
    def execute(self, context):
        props = context.scene.tiny_tools_props
        
        if not self._running:
            # Запускаем модальный режим
            props.bone_select_link = True
            type(self)._running = True
            self._timer = context.window_manager.event_timer_add(0.3, window=context.window)
            context.window_manager.modal_handler_add(self)
            print("Bone Select Link started")
            return {'RUNNING_MODAL'}
        else:
            return {'CANCELLED'}
    
    def stop_modal(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
        type(self)._running = False
        self._last_selected_bones = set()
        print("Bone Select Link stopped")
    
    def cancel(self, context):
        self.stop_modal(context)
        return {'CANCELLED'}

class TT_OT_StopBoneSelectLink(Operator):
    bl_idname = "tiny_tools.stop_bone_select_link"
    bl_label = "Stop Bone Select Link"
    bl_description = "Stop bone selection sync"
    
    def execute(self, context):
        props = context.scene.tiny_tools_props
        props.bone_select_link = False
        return {'FINISHED'}

#Утилиты

class TT_OT_ClearSearchField(Operator):
    bl_idname = "tiny_tools.clear_search_field"
    bl_label = "Clear Search Field"
    bl_description = "Clear search field"
    
    search_field: StringProperty(default="animation.animation_search") # type: ignore
    
    def execute(self, context):
        props = context.scene.tiny_tools_props

        # РАЗБИВАЕМ ПУТЬ НА ЧАСТИ, ЧТОБЫ ПОЛУЧИТЬ ДОСТУП КО ВЛОЖЕННОМУ ПОЛЮ
        if '.' in self.search_field:
            parts = self.search_field.split('.')
            current_obj = props
            
            for part in parts[:-1]:
                current_obj = getattr(current_obj, part)
    
            setattr(current_obj, parts[-1], "")
        else:
            setattr(props, self.search_field, "")
        return {'FINISHED'}


classes = (
    #Скелет (бэкап)
    TT_OT_BackupArmature,
    TT_OT_RestoreArmature,
    TT_OT_RestoreBonesOnly,
    TT_OT_RestoreConstraintsOnly,
    #Анимации (бэкап)
    TT_OT_ExportAllAnimations,
    TT_OT_ExportActiveAnimation,
    TT_OT_ExportEachAnimation,
    TT_OT_ExportAnimationsFBX,
    TT_OT_LoadAnimationList,
    TT_OT_ClearLoadedAnimations,
    TT_OT_ImportSelectedAnimations,
    #Анимации
    TT_OT_SelectAnimation,
    TT_OT_ToggleAllAnimationsLock,
    TT_OT_ToggleActionLock,
    TT_OT_AddAnimation,
    TT_OT_RenameAnimation, 
    TT_OT_DeleteAnimations,
    #Позы
    TT_OT_CopyPose,
    TT_OT_PastePose,
    #Pose Master
    TT_OT_VerifyPoseArmature,
    TT_OT_UpdatePoseCounts,
    TT_OT_ApplyPoseMaster,
    TT_OT_OpenBackupFolder,
    TT_OT_SetFrameRangeFromAction,
    #Ключи
    TT_OT_SoftCopyKeyframes,
    TT_OT_HardCopyKeyframes, 
    TT_OT_PasteKeyframes,
    #Подсветка костей в аутлайнере
    TT_OT_BoneSelectLink,
    TT_OT_StopBoneSelectLink,
    #Утилиты
    TT_OT_ClearSearchField,
    #Другое
)