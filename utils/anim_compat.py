"""Доступ к F-кривым и группам экшена.

Базовый API — slotted actions (Blender 4.4+, единственный вариант в 5.x).
В 4.2–4.3 слотов нет — там работает legacy `Action.fcurves` / `Action.groups`.
"""
import bpy

SLOTTED = bpy.app.version >= (4, 4, 0)


def _slot(action, id_type='OBJECT', create=False):
    # shortcut: работаем с первым слотом — экшены аддона однослотовые; для многослотовых экшенов передавать слот явно
    if action.slots:
        return action.slots[0]
    return action.slots.new(id_type, "Slot") if create else None


def channelbag(action, create=False):
    """Channelbag первого слота экшена (None, если кривых ещё нет и create=False)."""
    slot = _slot(action, create=create)
    if slot is None:
        return None
    if not action.layers:
        if not create:
            return None
        action.layers.new("Layer")
    layer = action.layers[0]
    if not layer.strips:
        if not create:
            return None
        layer.strips.new(type='KEYFRAME')
    return layer.strips[0].channelbag(slot, ensure=create)


def get_fcurves(action):
    """F-кривые экшена (пустой кортеж, если их нет)."""
    if not SLOTTED:
        return action.fcurves
    bag = channelbag(action)
    return bag.fcurves if bag else ()


def get_groups(action):
    """Группы каналов экшена (пустой кортеж, если их нет)."""
    if not SLOTTED:
        return action.groups
    bag = channelbag(action)
    return bag.groups if bag else ()


def new_fcurve(action, data_path, index=0, group=""):
    """Создаёт F-кривую, при необходимости — в группе `group`."""
    if not SLOTTED:
        return action.fcurves.new(data_path, index=index, action_group=group)
    bag = channelbag(action, create=True)
    fc = bag.fcurves.new(data_path, index=index)
    if group:
        fc.group = bag.groups.get(group) or bag.groups.new(group)
    return fc


def remove_fcurve(action, fcurve):
    if not SLOTTED:
        action.fcurves.remove(fcurve)
    else:
        channelbag(action).fcurves.remove(fcurve)


def assign_action(id_owner, action):
    """Назначает экшен объекту; в 4.4+ гарантирует, что выбран слот (иначе анимация не играет)."""
    if not id_owner.animation_data:
        id_owner.animation_data_create()
    ad = id_owner.animation_data
    ad.action = action
    if SLOTTED and action and not ad.action_slot:
        slot = next((s for s in action.slots if s.target_id_type in {id_owner.id_type, 'UNSPECIFIED'}), None)
        ad.action_slot = slot or action.slots.new(id_owner.id_type, id_owner.name)
