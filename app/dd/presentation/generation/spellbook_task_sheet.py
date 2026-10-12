"""Лист-задача генерации файла заклинаний (add-dnd-lss-generation, task 7.2).

Spec «Генерация файла заклинаний»: идея + число заклинаний (1…10), круг —
:class:`SpellbookChannel` через :func:`run_rounds`; конверт Foundry Item
достраивает канал. Принятие — существующая дверь :class:`GrimoireImportService`
через :class:`SpellbookAcceptanceService`: структурные ошибки блокируют
принятие, семантические предупреждения (в т.ч. «слаг вне SRD») остаются
предупреждениями — мастер принимает осознанно. Лицензии здесь нет (спека
не требует), принятие создаёт НОВЫЙ хоумбрю-гримуар: существующие файлы
генерация не меняет.

Жизнь листа — общая (:mod:`.base`): закрытие с in-flight = подтверждение +
отмена (не ошибка), released-лист молчит, гейт и русские ошибки канала —
там же.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Callable

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.dd.application.generation_deps import GenerationDeps
from app.dd.application.generation_inputs import GenerationInputs
from app.dd.application.generation_loop import (
    GenerationRoundResult,
    run_rounds,
)
from app.dd.application.grimoire_import_service import GrimoireImportStatus
from app.dd.application.spellbook_channel import (
    SPELL_COUNT_MAX,
    SPELL_COUNT_MIN,
    SPELL_DEFAULT_COUNT,
    SpellbookAcceptanceService,
    SpellbookChannel,
)
from app.dd.presentation.datasets_sheet import report_lines
from app.dd.presentation.generation.base import DndGenerationTaskSheet

#: Заголовок листа = заголовок окна (одна нить имени модульных листов).
DD_SPELLBOOK_TASK_TITLE = "Генерация файла заклинаний…"
#: Тексты статуса — объект pinned-контракта листа.
STATUS_IDLE = "ожидает"
STATUS_RUNNING = "генерация…"
STATUS_CANCELLED = "отменено"
STATUS_CHANNEL_ERROR = "ошибка канала — можно перезапустить"
STATUS_ERRORS = "ошибки валидатора — доступен ещё круг"
STATUS_READY = "готово к принятию"
STATUS_READY_WARN = "готово с предупреждениями — принятие осознанное"
STATUS_ACCEPTED = "принято новым гримуаром"
NO_ISSUES_TEXT = "Замечаний нет."


class DndSpellbookTaskSheet(DndGenerationTaskSheet):
    """Один документ, один круг за запуск, принятие — дверь гримуарного импорта."""

    def __init__(
        self,
        *,
        deps: GenerationDeps,
        inputs: GenerationInputs,
        acceptance: SpellbookAcceptanceService,
        run_locked: Callable[[Coroutine], asyncio.Task],
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(
            DD_SPELLBOOK_TASK_TITLE,
            deps=deps,
            run_locked=run_locked,
            parent=parent,
            theme=theme,
        )
        self._inputs = inputs
        self._acceptance = acceptance
        self._result: GenerationRoundResult | None = None
        self._task: asyncio.Task | None = None
        self._accepted = False
        # Словарь, который видел предпросмотр, уходит двери принятия — тогда
        # пересечение с SRD дверь отмечает ровно теми же предупреждениями.
        self._srd_slugs: tuple[str, ...] | None = None
        self._replace_box: QMessageBox | None = None
        self.setObjectName("ddSpellbookTaskSheet")
        self.setMinimumSize(520, 460)
        self.resize(560, 620)

        content = QWidget(self)
        body = QVBoxLayout(content)
        side_px = self._token_px("space.md", 16)
        row_px = self._token_px("space.sm", 8)
        body.setContentsMargins(side_px, row_px, side_px, side_px)
        body.setSpacing(row_px)

        body.addWidget(QLabel("Идея:", content))
        self._idea = QPlainTextEdit(content)
        self._idea.setObjectName("ddSpellbookGenIdea")
        self._idea.setPlaceholderText(
            "Идея файла — какие заклинания и для какого уголка мира"
        )
        self._idea.setFixedHeight(64)
        body.addWidget(self._idea)

        controls = QHBoxLayout()
        self._count = QSpinBox(content)
        self._count.setObjectName("ddSpellbookGenCount")
        self._count.setRange(SPELL_COUNT_MIN, SPELL_COUNT_MAX)
        self._count.setValue(SPELL_DEFAULT_COUNT)
        self._count.setPrefix("заклинаний: ")
        self._start_button = QPushButton("Сгенерировать", content)
        self._start_button.setObjectName("ddSpellbookGenStart")
        self._start_button.clicked.connect(self._on_start_clicked)
        self._status = QLabel(STATUS_IDLE, content)
        self._status.setObjectName("ddSpellbookGenStatus")
        controls.addWidget(self._count)
        controls.addWidget(self._gate_button(self._start_button))
        controls.addStretch(1)
        controls.addWidget(self._status)
        body.addLayout(controls)

        self._preview = QPlainTextEdit(content)
        self._preview.setObjectName("ddSpellbookGenPreview")
        self._preview.setReadOnly(True)
        self._preview.hide()
        body.addWidget(self._preview, 1)

        self._report = QLabel(content)
        self._report.setObjectName("ddSpellbookGenReport")
        self._report.setWordWrap(True)
        self._report.hide()
        body.addWidget(self._report)

        actions_row = QHBoxLayout()
        self._accept_button = QPushButton("Принять новым гримуаром", content)
        self._accept_button.setObjectName("ddSpellbookGenAccept")
        self._accept_button.setEnabled(False)
        self._accept_button.clicked.connect(
            lambda _checked=False: self._on_accept_clicked()
        )
        self._regen_button = QPushButton("Перегенерировать", content)
        self._regen_button.setObjectName("ddSpellbookGenRegen")
        self._regen_button.clicked.connect(
            lambda _checked=False: self._start(previous=None)
        )
        self._again_button = QPushButton("Ещё круг", content)
        self._again_button.setObjectName("ddSpellbookGenAgain")
        self._again_button.clicked.connect(self._on_again_clicked)
        self._cancel_button = QPushButton("Отменить", content)
        self._cancel_button.setObjectName("ddSpellbookGenCancel")
        self._cancel_button.clicked.connect(self._on_cancel_clicked)
        actions_row.addWidget(self._accept_button)
        actions_row.addWidget(self._gate_button(self._regen_button))
        actions_row.addWidget(self._gate_button(self._again_button))
        actions_row.addWidget(self._cancel_button)
        actions_row.addStretch(1)
        body.addLayout(actions_row)

        self.add_content(content)

    # ── круг ───────────────────────────────────────────────────────────────────

    def _on_start_clicked(self) -> None:
        self._start(previous=None)

    def _on_again_clicked(self) -> None:
        self._start(previous=self._result)

    def _start(self, *, previous: GenerationRoundResult | None) -> None:
        if self._released or self._task is not None:
            return
        if not self._deps.available():
            return
        self._result = None
        self._accepted = False
        self._preview.clear()
        self._preview.hide()
        self._report.clear()
        self._report.hide()
        self._accept_button.setEnabled(False)
        self._again_button.setEnabled(False)
        self._status.setText(STATUS_RUNNING)
        self._task = self._spawn(self._round(previous), self._on_round_done)

    async def _round(
        self, previous: GenerationRoundResult | None
    ) -> GenerationRoundResult:
        context = await self._inputs.spellbook_context(
            world=self._deps.world(),
            idea=self._idea.toPlainText(),
            count=self._count.value(),
        )
        self._srd_slugs = context.srd_slugs
        return await run_rounds(
            SpellbookChannel(),
            context,
            self._deps.make_answer(),
            previous=previous,
            on_phase=self._on_phase,
        )

    def _on_phase(self, phase: str) -> None:
        if not self._released and self._task is not None:
            self._status.setText(f"{STATUS_RUNNING} {phase}")

    def _on_round_done(self, task: asyncio.Task) -> None:
        if self._cancelled_or_released(task):
            return  # отмена — не ошибка
        self._task = None
        if task.exception() is not None:
            self._unexpected(task)
            self._status.setText(STATUS_CHANNEL_ERROR)
            return
        self._result = task.result()
        self._render()

    def _render(self) -> None:
        result = self._result
        if result is None:
            return
        if result.error_message is not None:
            # Частичные ответы прерванного круга в предпросмотр не попадают;
            # секция перезапускается перегенерацией (spec «Ошибки канала»).
            self._status.setText(STATUS_CHANNEL_ERROR)
            self._preview.clear()
            self._preview.hide()
            self._report.setText(result.error_message)
            self._report.show()
            self._accept_button.setEnabled(False)
            self._again_button.setEnabled(False)
            return
        self._preview.setPlainText(self._pretty(result.document or ""))
        self._preview.show()
        lines = report_lines(result.report)
        self._report.setText("\n".join(lines) if lines else NO_ISSUES_TEXT)
        self._report.show()
        if result.ok:
            has_warnings = bool(result.report.issues)
            # Предупреждения не блокируют: осознанное принятие — право мастера.
            self._status.setText(
                STATUS_READY_WARN if has_warnings else STATUS_READY
            )
            self._accept_button.setEnabled(True)
            self._again_button.setEnabled(False)
        else:
            self._status.setText(STATUS_ERRORS)
            self._accept_button.setEnabled(False)
            self._again_button.setEnabled(bool(self._deps.available()))

    def refresh_gate(self) -> None:
        """Два условия у «Ещё круга» (гейт + живой ответ с ошибками) — база
        знает только первое, второе перекладываем здесь."""
        super().refresh_gate()
        if self._released:
            return
        gate = bool(self._deps.available())
        if not gate:
            return  # база сняла активность и дала общую подсказку
        result = self._result
        live = result is not None and result.error_message is None and not result.ok
        self._again_button.setEnabled(live)
        self._again_button.setToolTip("")

    @staticmethod
    def _pretty(document: str) -> str:
        try:
            return json.dumps(
                json.loads(document), ensure_ascii=False, indent=2
            )
        except (json.JSONDecodeError, TypeError):
            return document

    # ── отмена и принятие ──────────────────────────────────────────────────────

    def _on_cancel_clicked(self) -> None:
        if self._released:
            return
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._result = None
        self._accepted = False
        self._preview.clear()
        self._preview.hide()
        self._report.clear()
        self._report.hide()
        self._accept_button.setEnabled(False)
        self._status.setText(STATUS_CANCELLED)

    def _on_accept_clicked(self, *, confirmed: bool = False) -> None:
        result = self._result
        if (
            self._released
            or result is None
            or not result.ok
            or result.document is None
            or self._accepted
        ):
            return
        document = result.document
        srd_slugs = self._srd_slugs
        self._run_acceptance(self._accept(document, srd_slugs, confirmed), self._on_accept_done)

    async def _accept(
        self, document: str, srd_slugs: tuple[str, ...] | None, confirmed: bool
    ):
        # Дверь синхронная — под локом сессии она в той же позе, что и все
        # записные листы модуля.
        return self._acceptance.accept(document, confirmed=confirmed, srd_slugs=srd_slugs)

    def _on_accept_done(self, task: asyncio.Task) -> None:
        if self._cancelled_or_released(task):
            return
        if task.exception() is not None:
            self._unexpected(task)
            return
        outcome = task.result()
        if outcome.status is GrimoireImportStatus.STORED:
            self._accepted = True
            self._accept_button.setEnabled(False)
            self._status.setText(STATUS_ACCEPTED)
            return
        if outcome.status is GrimoireImportStatus.NEEDS_CONFIRMATION:
            self._ask_replace()
            return
        lines = (
            report_lines(outcome.report) if outcome.report is not None else []
        )
        body = outcome.message or "Файл заклинаний не принят."
        if lines:
            body = body + "\n\n" + "\n".join(lines)
        self._show_notice(body)

    def _ask_replace(self) -> None:
        """Такая content-addressed полка уже есть — штатный вопрос двери;
        подтверждение доходит ``confirmed=True`` и заменит СВОЮ полку."""
        box = QMessageBox(self.window())
        box.setWindowTitle(self.windowTitle())
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            "Такой файл уже лежит в хранилище под своей полкой. Заменить её "
            "этим документом?"
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        self._replace_box = box
        box.finished.connect(self._on_replace_answered)
        box.show()

    def _on_replace_answered(self, result: int) -> None:
        self._replace_box = None
        if result != QMessageBox.StandardButton.Yes or self._released:
            return
        self._on_accept_clicked(confirmed=True)
