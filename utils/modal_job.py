"""Длинные операции по шагам: интерфейс не замирает, прогресс-бар, Esc — отмена с откатом.

Оператор задаёт:
    job(self, context, state)    — генератор: yield (сделано, всего, текст); return (уровень, сообщение)
    cancel(self, context, state) — откат при Esc/ошибке; True, если данные восстановлены
Из скриптов и тестов (bpy.ops без окна) работа выполняется целиком в execute().
"""
import time
import bpy

JOB = {}  # текущая модальная операция для прогресс-бара: label, done, total, text

# события, которые пропускаем во время работы (навигация по виду); остальной ввод блокируется
_PASS = {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM',
         'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'TIMER_REPORT', 'NDOF_MOTION'}
_SLICE = 0.1  # секунд работы между отрисовками интерфейса


def run(gen):
    """Выполняет генератор шагов до конца и возвращает его результат."""
    while True:
        try:
            next(gen)
        except StopIteration as e:
            return e.value


def _redraw():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type in {'VIEW_3D', 'STATUSBAR'}:
                area.tag_redraw()


class ModalJob:
    """Миксин для Operator: длинная работа в модальном режиме с прогрессом и отменой по Esc."""

    def cancel_job(self, context, state):
        """True — данные восстановлены; False — сделанное остаётся (шаг Undo); str — свой итог, сцена не менялась"""
        return False

    def _report_result(self, result):
        level, msg = result or ('INFO', "Done")
        self.report({level}, msg)
        return {'CANCELLED'} if level == 'ERROR' else {'FINISHED'}

    def execute(self, context):
        state = {}
        try:
            return self._report_result(run(self.job(context, state)))
        except Exception as e:
            self.cancel_job(context, state)
            self.report({'ERROR'}, f"{self.bl_label} failed: {e}")
            return {'CANCELLED'}

    def invoke(self, context, event):
        if not context.window:
            return self.execute(context)
        self._state = {}
        # context из invoke между событиями недействителен — генератор работает с глобальным bpy.context
        self._gen = self.job(bpy.context, self._state)
        JOB.clear()
        JOB.update(label=self.bl_label, done=0, total=1, text="")
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        wm.progress_begin(0, 100)
        return {'RUNNING_MODAL'}

    def _stop(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        wm.progress_end()
        if context.workspace:
            context.workspace.status_text_set(None)
        JOB.clear()
        _redraw()

    def modal(self, context, event):
        if event.type == 'ESC' and event.value == 'PRESS':
            self._gen.close()  # finally-блоки генератора возвращают состояние сцены
            restored = self.cancel_job(context, self._state)
            self._stop(context)
            if isinstance(restored, str):  # итог отмены своими словами (данные сцены не менялись)
                detail = restored
            else:
                detail = "changes reverted" if restored else "finished part kept (Ctrl+Z reverts)"
            self.report({'WARNING'}, f"{self.bl_label}: cancelled — {detail}")
            return {'FINISHED'} if restored is False else {'CANCELLED'}
        if event.type != 'TIMER':
            return {'PASS_THROUGH'} if event.type in _PASS else {'RUNNING_MODAL'}
        t0 = time.perf_counter()
        try:
            while time.perf_counter() - t0 < _SLICE:
                done, total, text = next(self._gen)
                JOB.update(done=done, total=max(total, 1), text=text)
        except StopIteration as e:
            self._stop(context)
            return self._report_result(e.value)
        except Exception as e:
            self.cancel_job(context, self._state)
            self._stop(context)
            self.report({'ERROR'}, f"{self.bl_label} failed: {e}")
            return {'CANCELLED'}
        pct = JOB["done"] / JOB["total"]
        context.window_manager.progress_update(int(pct * 100))
        if context.workspace:
            context.workspace.status_text_set(f"{JOB['label']}: {JOB['text']}  {round(pct * 100)}%   —   Esc: cancel")
        _redraw()
        return {'RUNNING_MODAL'}
