import bpy, blf
from bpy.types import Operator
from bpy.props import StringProperty

_tooltip_states = {}

def tooltip_blocks(lines, cjk=False):
    """Склеивает строки подсказки в абзацы: пустая строка — новый блок, строка с эмодзи — новый пункт,
    иначе — продолжение предыдущего пункта (в данных текст когда-то резался вручную)."""
    blocks, block = [], []
    for line in lines:
        s = line.strip()
        if not s:
            if block:
                blocks.append(block)
                block = []
        elif block and (s[0].isalnum() or ord(s[0]) < 0x2000):  # эмодзи/символ начинает новый пункт
            block[-1] += ("" if cjk else " ") + s
        else:
            block.append(s)
    if block:
        blocks.append(block)
    return blocks


def wrap_text(text, max_px, cjk=False):
    """Переносит текст по ширине в пикселях, измеряя шрифтом интерфейса (китайский — посимвольно)."""
    units = list(text) if cjk else text.split(" ")
    sep = "" if cjk else " "
    lines, cur = [], ""
    for u in units:
        cand = cur + sep + u if cur else u
        if cur and blf.dimensions(0, cand)[0] * 1.08 > max_px:  # запас: метки Blender шире замера blf
            lines.append(cur)
            cur = u
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


_wrap_cache = {}


def draw_tooltip(layout, tooltip_data, tooltip_id, icon='QUESTION'):
    """Сворачиваемый блок Help: текст переносится по текущей ширине панели"""
    context = bpy.context
    language = context.scene.tiny_tools_props.tooltip_language
    is_expanded = _tooltip_states.get(tooltip_id, False)

    box = layout.box()
    header_row = box.row()
    op = header_row.operator("tiny_tools.toggle_tooltip",
                             icon='TRIA_DOWN' if is_expanded else 'TRIA_RIGHT', text="", emboss=False)
    op.tooltip_id = tooltip_id
    header_row.label(text="Help", icon=icon)
    if not is_expanded:
        return

    lang_row = header_row.row(align=True)
    lang_row.alignment = 'RIGHT'
    for code in ('EN', 'RU', 'ZH'):
        lang_row.operator("tiny_tools.set_tooltip_language", text=code.lower(), depress=(language == code)).language = code

    lines = tooltip_data.get(tooltip_id, {}).get(f"text_{language.lower()}", [])
    cjk = language == 'ZH'
    scale = context.preferences.system.ui_scale or 1.0
    points = context.preferences.ui_styles[0].widget.points
    # ширина региона минус отступы панели, рамки и самого блока
    max_px = max(120.0, (context.region.width if context.region else 300) - 46 * scale)
    key = (tooltip_id, language, int(max_px), round(scale, 2))
    if key not in _wrap_cache:
        blf.size(0, points * scale)
        _wrap_cache[key] = [[wl for item in block for wl in wrap_text(item, max_px, cjk)]
                            for block in tooltip_blocks(lines, cjk)]
    for block in _wrap_cache[key]:
        col = box.box().column(align=True)
        col.scale_y = 0.75
        for line in block:
            col.label(text=line)

class TT_OT_ToggleTooltip(Operator):
    """Оператор для переключения состояния тултипа"""
    bl_idname = "tiny_tools.toggle_tooltip"
    bl_label = "Toggle Tooltip"
    bl_options = {'INTERNAL'}
    
    tooltip_id: StringProperty() # type: ignore
    
    def execute(self, context):
        # Переключаем состояние
        _tooltip_states[self.tooltip_id] = not _tooltip_states.get(self.tooltip_id, False)
        return {'FINISHED'}

class TT_OT_SetTooltipLanguage(Operator):
    """Оператор для установки языка тултипов"""
    bl_idname = "tiny_tools.set_tooltip_language"
    bl_label = "Set Tooltip Language"
    bl_options = {'INTERNAL'}
    
    language: bpy.props.StringProperty() # type: ignore
    
    def execute(self, context):
        context.scene.tiny_tools_props.tooltip_language = self.language
        return {'FINISHED'}