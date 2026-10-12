"""Лист-задача генерации персонажа (add-dnd-lss-generation, task 7.3).

Один лист в двух режимах (design Д7): «Сгенерировать персонажа…» из меню
модуля — создание с нуля (концепция + опциональные пре-выборы уровня/вида/
класса из подключённых источников); «Дозаполнить ИИ» из D&D-таба карточки —
дозаполнение: тот же лист принимает текущий документ карточки и просит
модель дописать только пустые поля.

Результат идёт через импортный конвейер существующего импорта (design Д5,
spec «Генерация персонажа с нуля» / «Дозаполнение персонажа»): создание
рождает обычного персонажа с D&D-табом и всегда сохранённым сырым файлом,
дозаполнение перезаписывает карточку после подтверждения двери (перезапись
требует подтверждения — штатный вопрос :class:`CharacterImportService`).

Гейт «≥1 подключённый датасет» проверяет façade перед открытием листа и
объясняет отказ modeless-боксом (spec «Гейт активации генерации»); «пусто
дозаполнять» отказывает русским текстом и не запускает круг.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Callable

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.dd.application.character_channel import CharacterChannel
from app.dd.application.character_import_service import CharacterImportStatus
from app.dd.application.generation_deps import GenerationDeps
from app.dd.application.generation_inputs import GenerationInputs
from app.dd.application.generation_loop import (
    GenerationRoundResult,
    run_rounds,
)
from app.dd.application.prompt_composer import SlugVocabularyEntry
from app.dd.presentation.datasets_sheet import report_lines
from app.dd.presentation.generation.base import DndGenerationTaskSheet

if TYPE_CHECKING:
    from app.dd.application.character_import_service import CharacterImportService

#: Заголовки двух режимов одного листа (одна нить имени с пунктами входа).
DD_CHARACTER_TASK_TITLE = "Генерация персонажа…"
DD_TOP_UP_TASK_TITLE = "Дозаполнение персонажа…"
#: Тексты статуса — объект pinned-контракта листа.
STATUS_IDLE = "ожидает"
STATUS_RUNNING = "генерация…"
STATUS_CANCELLED = "отменено"
STATUS_CHANNEL_ERROR = "ошибка канала — можно перезапустить"
STATUS_ERRORS = "ошибки валидатора — доступен ещё круг"
STATUS_READY = "готово к принятию"
STATUS_READY_WARN = "готово (с предупреждениями) — можно принять"
STATUS_ACCEPTED_CREATE = "принято: персонаж создан"
STATUS_ACCEPTED_TOP_UP = "принято: карточка обновлена"
NO_ISSUES_TEXT = "Замечаний нет."
#: Пункт «не выбрано» в пре-выборах и уровне.
UNSET_ITEM = "—"


class DndCharacterTaskSheet(DndGenerationTaskSheet):
    """Создание и дозаполнение: один круг, один документ, импортный конвейер."""

    def __init__(
        self,
        *,
        deps: GenerationDeps,
        inputs: GenerationInputs,
        character_import: "CharacterImportService",
        run_locked: Callable[[Coroutine], asyncio.Task],
        character_id: int | None = None,
        current_document: str | None = None,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        self._top_up = current_document is not None
        super().__init__(
            DD_TOP_UP_TASK_TITLE if self._top_up else DD_CHARACTER_TASK_TITLE,
            deps=deps,
            run_locked=run_locked,
            parent=parent,
            theme=theme,
        )
        self._inputs = inputs
        self._importer = character_import
        self._character_id = character_id
        self._current_document = current_document
        self._result: GenerationRoundResult | None = None
        self._task: asyncio.Task | None = None
        self._accepted = False
        self._overwrite_confirm_box: QMessageBox | None = None
        self.setObjectName(
            "ddCharacterTopUpTaskSheet" if self._top_up else "ddCharacterTaskSheet"
        )
        self.setMinimumSize(520, 460)
        self.resize(560, 620)

        content = QWidget(self)
        body = QVBoxLayout(content)
        side_px = self._token_px("space.md", 16)
        row_px = self._token_px("space.sm", 8)
        body.setContentsMargins(side_px, row_px, side_px, side_px)
        body.setSpacing(row_px)

        self._concept = QPlainTextEdit(content)
        self._concept.setObjectName("ddCharacterGenConcept")
        self._concept.setFixedHeight(72)
        self._concept.setPlaceholderText(
            "Концепция персонажа — кем он должен быть в мире игры"
            if not self._top_up
            else "Опциональная подсказка для дозаполнения пустых полей"
        )
        body.addWidget(QLabel("Концепция:" if not self._top_up else "Подсказка:", content))
        body.addWidget(self._concept)

        if not self._top_up:
            # Пре-выборы только в режиме создания: дозаполнение не выбирает
            # лицо заново, оно дописывает пустое (spec «Дозаполнение»).
            pre = QFormLayout()
            self._level = QComboBox(content)
            self._level.setObjectName("ddCharacterGenLevel")
            self._level.addItem(UNSET_ITEM)
            for value in range(1, 21):
                self._level.addItem(str(value))
            self._races = QComboBox(content)
            self._races.setObjectName("ddCharacterGenRace")
            self._races.addItem(UNSET_ITEM)
            self._classes = QComboBox(content)
            self._classes.setObjectName("ddCharacterGenClass")
            self._classes.addItem(UNSET_ITEM)
            pre.addRow("Уровень:", self._level)
            pre.addRow("Вид:", self._races)
            pre.addRow("Класс:", self._classes)
            body.addLayout(pre)
            # Словарь подключённых источников листится из игры вне лока:
            # файлы индекса, сессия не трогается.
            self._spawn(self._load_choices(), self._on_choices_loaded)
        else:
            self._level = None
            self._races = None
            self._classes = None

        controls = QHBoxLayout()
        self._start_button = QPushButton(
            "Дозаполнить" if self._top_up else "Сгенерировать", content
        )
        self._start_button.setObjectName(
            "ddCharacterTopUpStart" if self._top_up else "ddCharacterGenStart"
        )
        self._start_button.clicked.connect(self._on_start_clicked)
        self._status = QLabel(STATUS_IDLE, content)
        self._status.setObjectName("ddCharacterGenStatus")
        controls.addWidget(self._gate_button(self._start_button))
        controls.addStretch(1)
        controls.addWidget(self._status)
        body.addLayout(controls)

        self._preview = QPlainTextEdit(content)
        self._preview.setObjectName("ddCharacterGenPreview")
        self._preview.setReadOnly(True)
        self._preview.hide()
        body.addWidget(self._preview, 1)

        self._report = QLabel(content)
        self._report.setObjectName("ddCharacterGenReport")
        self._report.setWordWrap(True)
        self._report.hide()
        body.addWidget(self._report)

        actions = QHBoxLayout()
        self._accept_button = QPushButton("Принять в игру", content)
        self._accept_button.setObjectName("ddCharacterGenAccept")
        self._accept_button.setEnabled(False)
        self._accept_button.clicked.connect(
            lambda _checked=False: self._on_accept_clicked()
        )
        self._regen_button = QPushButton("Перегенерировать", content)
        self._regen_button.setObjectName("ddCharacterGenRegen")
        self._regen_button.clicked.connect(
            lambda _checked=False: self._start(previous=None)
        )
        self._again_button = QPushButton("Ещё круг", content)
        self._again_button.setObjectName("ddCharacterGenAgain")
        self._again_button.clicked.connect(
            lambda _checked=False: self._start(previous=self._result)
        )
        self._cancel_button = QPushButton("Отменить", content)
        self._cancel_button.setObjectName("ddCharacterGenCancel")
        self._cancel_button.clicked.connect(self._on_cancel_clicked)
        actions.addWidget(self._accept_button)
        actions.addWidget(self._gate_button(self._regen_button))
        actions.addWidget(self._gate_button(self._again_button))
        actions.addWidget(self._cancel_button)
        actions.addStretch(1)
        body.addLayout(actions)

        self.add_content(content)

    # ── пре-выборы ─────────────────────────────────────────────────────────────

    async def _load_choices(self) -> tuple[tuple[SlugVocabularyEntry, ...], tuple[SlugVocabularyEntry, ...]]:
        races = await self._inputs.section_entries("races")
        classes = await self._inputs.section_entries("classes")
        return races, classes

    def _on_choices_loaded(self, task: asyncio.Task) -> None:
        if self._cancelled_or_released(task):
            return
        if task.exception() is not None:
            self._unexpected(task)
            return
        races, classes = task.result()
        assert self._races is not None and self._classes is not None
        for entry in races:
            self._races.addItem(entry.name or entry.slug, userData=entry)
        for entry in classes:
            self._classes.addItem(entry.name or entry.slug, userData=entry)

    # ── круг ───────────────────────────────────────────────────────────────────

    def _on_start_clicked(self) -> None:
        self._start(previous=None)

    def _start(self, *, previous: GenerationRoundResult | None) -> None:
        if self._released or self._task is not None or not self._deps.available():
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

    def _preselect(self, combo: QComboBox | None) -> SlugVocabularyEntry | None:
        if combo is None:
            return None
        data = combo.currentData()
        return data if isinstance(data, SlugVocabularyEntry) else None

    async def _round(
        self, previous: GenerationRoundResult | None
    ) -> GenerationRoundResult:
        level_value = (
            self._level.currentText() if self._level is not None else UNSET_ITEM
        )
        level = int(level_value) if level_value.isdigit() else None
        try:
            context = await self._inputs.character_context(
                world=self._deps.world(),
                concept=self._concept.toPlainText(),
                current_document=self._current_document,
                level=level,
                race=self._preselect(self._races),
                char_class=self._preselect(self._classes),
            )
        except ValueError as exc:
            # Русский отказ контекста (в т.ч. «пусто дозаполнять») — как
            # сбой круга: лист жив, секцию можно перезапустить (task 7.5).
            return GenerationRoundResult(error_message=str(exc))
        return await run_rounds(
            CharacterChannel(context),
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
        """Как и в листе заклинаний: у «Ещё круга» два условия."""
        super().refresh_gate()
        if self._released:
            return
        if not self._deps.available():
            return
        result = self._result
        live = result is not None and result.error_message is None and not result.ok
        self._again_button.setEnabled(live)
        self._again_button.setToolTip("")

    @staticmethod
    def _pretty(document: str) -> str:
        try:
            data = json.loads(document)
        except (json.JSONDecodeError, TypeError):
            return document
        # Живой конверт носит data JSON-строкой — предпросмотр раскрывает её,
        # иначе мастер читает двойной экранированный текст.
        raw = data.get("data") if isinstance(data, dict) else None
        if isinstance(raw, str):
            try:
                data = {**data, "data": json.loads(raw)}
            except json.JSONDecodeError:
                pass
        return json.dumps(data, ensure_ascii=False, indent=2)

    # ── отмена и принятие (импортный конвейер) ────────────────────────────────

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
        character_id = self._character_id
        self._run_acceptance(
            self._import(document, character_id, confirmed), self._on_accept_done
        )

    async def _import(
        self, document: str, character_id: int | None, confirmed: bool
    ):
        return await self._importer.import_character(
            document, character_id=character_id, confirmed=confirmed
        )

    def _on_accept_done(self, task: asyncio.Task) -> None:
        if self._cancelled_or_released(task):
            return
        if task.exception() is not None:
            self._unexpected(task)
            return
        outcome = task.result()
        if outcome.status in (
            CharacterImportStatus.CREATED,
            CharacterImportStatus.OVERWRITTEN,
        ):
            self._accepted = True
            self._character_id = outcome.character_id
            self._accept_button.setEnabled(False)
            self._status.setText(
                STATUS_ACCEPTED_TOP_UP
                if self._top_up
                else STATUS_ACCEPTED_CREATE
            )
            return
        if outcome.status is CharacterImportStatus.NEEDS_CONFIRMATION:
            self._ask_overwrite()
            return
        lines = (
            report_lines(outcome.report) if outcome.report is not None else []
        )
        body = outcome.message or "Документ персонажа не принят."
        if lines:
            body = body + "\n\n" + "\n".join(lines)
        self._show_notice(body)

    def _ask_overwrite(self) -> None:
        """Перезапись карточки требует подтверждения (spec «Перезапись
        требует подтверждения»): подтверждение доходит ``confirmed=True``."""
        box = QMessageBox(self.window())
        box.setWindowTitle(self.windowTitle())
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            "Карточка персонажа будет перезаписана сгенерированным документом. "
            "Продолжить?"
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        self._overwrite_confirm_box = box
        box.finished.connect(self._on_overwrite_answered)
        box.show()

    def _on_overwrite_answered(self, result: int) -> None:
        self._overwrite_confirm_box = None
        if result != QMessageBox.StandardButton.Yes or self._released:
            return
        self._on_accept_clicked(confirmed=True)
