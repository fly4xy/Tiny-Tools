"""Экспорт анимаций в FBX для игровых движков: только скелет, по файлу на анимацию."""
import math
import os
import re
import bpy
from .anim_compat import assign_action
from .modal_job import run


def clean_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', '_', name).strip(' .')
    return name or "unnamed_animation"


def export_actions_fbx(context, arm, actions, folder, p):
    return run(export_actions_fbx_iter(context, arm, actions, folder, p))


def export_actions_fbx_iter(context, arm, actions, folder, p):
    """Экспортирует каждую анимацию из actions отдельным FBX (скелет без мешей). p — TinyToolsAnimationProps.

    Без Add Root объект арматуры на время экспорта называется 'Armature': Unreal пропускает такой узел
    и не создаёт лишнюю корневую кость. Всё состояние сцены восстанавливается.
    """
    scene = context.scene
    ad = arm.animation_data
    saved = dict(
        name=arm.name, action=ad.action if ad else None,
        slot=getattr(ad, "action_slot", None) if ad else None,
        frames=(scene.frame_start, scene.frame_end, scene.frame_current),
        active=context.view_layer.objects.active,
        selected=list(context.selected_objects),
    )
    clash = bpy.data.objects.get("Armature") if not p.fbx_add_root and arm.name != "Armature" else None
    os.makedirs(folder, exist_ok=True)
    paths = []
    try:
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if clash:
            clash.name = "Armature__tt_tmp"
        if not p.fbx_add_root:
            arm.name = "Armature"
        for o in context.selected_objects:
            o.select_set(False)
        arm.select_set(True)
        context.view_layer.objects.active = arm
        for i, action in enumerate(actions):
            yield i, len(actions), action.name
            assign_action(arm, action)
            start, end = action.frame_range
            scene.frame_start, scene.frame_end = math.floor(start), max(math.ceil(end), math.floor(start) + 1)
            path = os.path.join(folder, clean_filename(p.fbx_prefix + action.name) + ".fbx")
            bpy.ops.export_scene.fbx(
                filepath=path, use_selection=True, object_types={'ARMATURE'},
                use_armature_deform_only=p.fbx_deform_only, add_leaf_bones=p.fbx_leaf_bones,
                apply_unit_scale=True, apply_scale_options=p.fbx_apply_scale, global_scale=p.fbx_global_scale,
                bake_anim=True, bake_anim_use_all_bones=True, bake_anim_use_nla_strips=False,
                bake_anim_use_all_actions=False, bake_anim_force_startend_keying=p.fbx_force_startend,
                bake_anim_simplify_factor=p.fbx_simplify)
            paths.append(path)
    finally:
        arm.name = saved["name"]
        if clash:
            clash.name = "Armature"
        if ad:
            ad.action = saved["action"]
            if saved["slot"] is not None and saved["action"]:
                ad.action_slot = saved["slot"]
        scene.frame_start, scene.frame_end, scene.frame_current = saved["frames"]
        for o in context.selected_objects:
            o.select_set(False)
        for o in saved["selected"]:
            o.select_set(True)
        context.view_layer.objects.active = saved["active"]
    return paths
