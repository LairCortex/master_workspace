"""Общая жизнь листа-задачи генерации (add-dnd-lss-generation, task 7.4/7.5).

Поза волн сущностных листов модуля, плюс две нормы спеки «Жизнь задачи в её
листе» и «Гейт активации генерации»:

* задачи qasync живут на общем цикле; сетевые круги НЕ идут через лок
  сессии (design Д8: секции не сериализуются против воли мастера), а
  принятие — идёт (одна транзакционная дверь ``run_locked``);
* закрытие листа с незавершёнными запросами — modeless-подтверждение с
  предупреждением об обрыве; согласие отменяет задачи и закрывает, отказ
  оставляет задачу жить. Отмена — НЕ ошибка: диалога об ошибке нет;
* released-лист не отвечает: любой done-колбэк проверяет ``_released``
  (,ID-идол widget-издания ``_root_alive`` из островов);
* кнопки генерации неактивны при закрытом общем AI-гейте и несут ту же
  русскую подсказку, что AI-кнопки карточек (тексты — одно знание в
  ``event_dialog_island_view_model``, сюда доходят дверью ``deps.hint``);
  гейт перечитывается при каждом показе листа, т.к. настройка LLM могла
  измениться посреди сессии.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Callable

from PySide6.QtWidgets import QMessageBox, QWidget

from app.dd.application.generation_deps import GenerationDeps
from app.presentation.views.sheet_frame import SheetFrame

#: Заголовок подтверждения закрытия с in-flight (spec «Жизнь задачи в её
#: листе»: предупреждение об обрыве запросов, отмена — не ошибка).
CLOSE_CONFIRM_TEXT = (
    "Генерация ещё выполняется. Закрыть лист? Незавершённые запросы будут "
    "прерваны, несохранённая задача не сохранится."
)
#: Русское тело непредвиденного сбоя задачи (не сбоя канала — те несёт
#: результат круга; сюда попадает только программа-ошибка).
TASK_UNEXPECTED_BODY = (
    "Задача генерации завершилась непредвиденной ошибкой. Подробности — в "
    "журнале приложения; попробуйте перезапустить секцию."
)


class DndGenerationTaskSheet(SheetFrame):
    """Жизненный цикл, общий для всех трёх листов-задач.

    Потомки регистрируют кнопки гейта (:meth:`_gate_button`) и запускают
    задачи (:meth:`_spawn` — сеть вне лока, :meth:`_run_acceptance` — дверь
    записи под локом). Никакого публичного API жизненный цикл не заводит:
    outside мир знает лист только как sheet из стека коннектора.
    """

    def __init__(
        self,
        title: str,
        *,
        deps: GenerationDeps,
        run_locked: Callable[[Coroutine], asyncio.Task],
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(title, parent, theme)
        self._deps = deps
        self._run_locked = run_locked
        # Все задачи листа — живые ссылки; закрытие отменяет то, что живо.
        self._tasks: set[asyncio.Task] = set()
        # Widget-издание «отвязанного острова»: после release ни один
        # done-колбэк не трогает виджеты и не показывает окон.
        self._released = False
        # Close с in-flight уже подтверждается — второе подтверждение не
        # наслаивается (modeless-окно живёт до finished, PR-010 поза).
        self._closing = False
        # Живые ссылки modeless-боксов (PR-010: без ссылки Qt заберёт окно).
        self._confirm_box: QMessageBox | None = None
        self._notice_box: QMessageBox | None = None
        # Кнопки, чью активность решает общий AI-гейт.
        self._gate_buttons: list[QWidget] = []

    # ── AI-гейт (task 7.5) ────────────────────────────────────────────────────

    def _gate_button(self, button: QWidget) -> QWidget:
        """Register a widget whose availability answers the shared AI gate."""
        self._gate_buttons.append(button)
        self._apply_gate_to(button)
        return button

    def _apply_gate_to(self, button: QWidget) -> None:
        available = bool(self._deps.available())
        button.setEnabled(available)
        # Неактивная кнопка носит ту же русскую подсказку, что AI-кнопки
        # карточек (spec «Гейт активации генерации»); у активной — без
        # подсказки, чтобы ложный смысл не появлялся.
        button.setToolTip("" if available else self._deps.hint())

    def refresh_gate(self) -> None:
        """Re-read the gate for every registered button (settings may have
        changed while the sheet sat on the stack)."""
        for button in self._gate_buttons:
            self._apply_gate_to(button)

    def showEvent(self, event) -> None:
        # Лист перепоказывают с поднимающего стека — гейт перечитывается на
        # каждом показе: настройка LLM меняется посреди живой сессии.
        if not self._released:
            self.refresh_gate()
        super().showEvent(event)

    # ── задачи (qasync на общем цикле) ────────────────────────────────────────

    def _spawn(
        self,
        coro: Coroutine,
        done: Callable[[asyncio.Task], None],
    ) -> asyncio.Task:
        """Запустить задачу вне лока сессии (сетевые круги; design Д8)."""
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._forget(task))
        task.add_done_callback(done)
        return task

    def _run_acceptance(
        self,
        coro: Coroutine,
        done: Callable[[asyncio.Task], None],
    ) -> asyncio.Task:
        """Запустить дверь записи (принятие) под локом сессии — одной
        транзакционной дверью, как любой иной пользовательский финиш."""
        task = self._run_locked(coro)
        self._tasks.add(task)
        task.add_done_callback(self._forget(task))
        task.add_done_callback(done)
        return task

    def _forget(self, task: asyncio.Task):
        def _drop(_done_task: asyncio.Task) -> None:
            self._tasks.discard(task)

        return _drop

    def _pending(self) -> list[asyncio.Task]:
        return [task for task in self._tasks if not task.done()]

    def _cancelled_or_released(self, task: asyncio.Task) -> bool:
        """Отмена и release — молчаливые исходы: done-колбэки начинают с
        этой проверки (spec «Отмена НЕ считается ошибкой»)."""
        return self._released or task.cancelled()

    # ── закрытие с in-flight (task 7.4) ───────────────────────────────────────

    def closeEvent(self, event) -> None:
        if self._released or not self._pending():
            self._release()
            # НЕ просто accept: QDialog::closeEvent доводит окно до done(), а
            # с ним и до finished — тем самым коннектор снимает лист со стека,
            # а façade забывает его из рефа (тот же выход, что у кнопки
            # «Закрыть» и Esc, ведущих сразу к reject/done); голый accept
            # оставил бы стек и реф façade держать мёртвый лист.
            super().closeEvent(event)
            return
        event.ignore()
        if self._closing:
            return  # подтверждение уже открыто — не наслаиваем
        self._closing = True
        box = QMessageBox(self.window())
        box.setWindowTitle(self.windowTitle())
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(CLOSE_CONFIRM_TEXT)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        self._confirm_box = box
        box.finished.connect(self._on_close_answered)
        box.show()  # modeless: вложенного цикла нет (guard test_no_dialog_exec)

    def _on_close_answered(self, result: int) -> None:
        # Живая ссылка сброшена — Qt отпустит окно вместе с родителем
        # (поза ``datasets_sheet._on_replace_answered``).
        self._confirm_box = None
        if result != QMessageBox.StandardButton.Yes:
            self._closing = False  # отказ — задача продолжает жить
            return
        for task in self._pending():
            task.cancel()  # отмена — не ошибка: диалога об ошибке не будет
        self._release()
        self.close()

    def _release(self) -> None:
        """Отвязка листа: дальше ни один колбэк не трогает виджеты."""
        self._released = True

    def force_close(self) -> None:
        """Снятие листа рукой façade (detach/выключение модуля): тихая
        отмена in-flight БЕЗ подтверждения — подтверждение принадлежит клику
        мастера (spec «Жизнь задачи в её листе»), уход игры не спрашивает."""
        self._closing = True
        for task in self._pending():
            task.cancel()
        self._release()
        self.close()

    # ── общие боксы ───────────────────────────────────────────────────────────

    def _show_notice(
        self, body: str, icon: QMessageBox.Icon = QMessageBox.Icon.Warning
    ) -> None:
        """Modeless-уведомление с живой ссылкой (PR-010 поза всех листов)."""
        box = QMessageBox(self.window())
        box.setWindowTitle(self.windowTitle())
        box.setIcon(icon)
        box.setText(body)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._notice_box = box
        box.finished.connect(self._notice_finished)
        box.show()

    def _notice_finished(self, _result: int) -> None:
        self._notice_box = None

    def _unexpected(self, task: asyncio.Task) -> None:
        """Программа-ошибка задачи: журнал + русский бокс (ошибки канала
        сюда не попадают — их несёт ``GenerationRoundResult.error_message``)."""
        logging.getLogger("app.dd.generation").error(
            "generation task failed: %s", task.exception(), exc_info=False
        )
        if not self._released:
            self._show_notice(TASK_UNEXPECTED_BODY)
