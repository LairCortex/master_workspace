"""Лист-задача генерации хоумбрю-датасетов (add-dnd-lss-generation, task 7.1).

Spec «Задача генерации датасетов» + «Предпросмотр и принятие датасета»:
мастер отмечает секции, задаёт число сущностей (1…10, по умолчанию 5) и
идею; каждая отмеченная секция — отдельный вызов в отдельную задачу qasync
(провал соседней секции не переписывает готовую), каждая секция собирается
в отдельный файл ``dataset-<тип>.json`` с идентификатором ``hb-gen-<секция>``.
Круг ведёт существующий раннер :func:`run_rounds` с существующим каналом
:class:`DatasetSectionChannel`; принятие ведёт
:class:`DatasetSectionAcceptanceService` (лицензия подставляется в конверт,
дверь импорта проверяет и кладёт на полку, связь автоподключается).

Жизнь листа — в :mod:`.base`: закрытие с in-flight подтверждается и отменяет
(отмена не ошибка), released-лист молчит, кнопки генерации неактивны при
закрытом AI-гейте с общей русской подсказкой, ошибки канала показываются
русским текстом прямо в секции, которую можно перезапустить.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.dd.application.dataset_import_service import DatasetImportStatus
from app.dd.application.dataset_section_channel import (
    DATASET_LICENSE_CHOICES,
    DEFAULT_DATASET_LICENSE,
    SECTION_COUNT_MAX,
    SECTION_COUNT_MIN,
    SECTION_DEFAULT_COUNT,
    DatasetSectionAcceptanceService,
    DatasetSectionChannel,
)
from app.dd.application.generation_deps import GenerationDeps
from app.dd.application.generation_inputs import GenerationInputs
from app.dd.application.generation_loop import GenerationRoundResult, run_rounds
from app.dd.application.prompt_composer import PromptComposer
from app.dd.domain.lss_checks import SECTIONS
from app.dd.presentation.datasets_sheet import report_lines
from app.dd.presentation.generation.base import DndGenerationTaskSheet

#: Заголовок листа = заголовок листа-задачи (одна нить имени, прецедент
#: «Датасеты D&D…»).
DD_DATASET_TASK_TITLE = "Генерация датасетов D&D…"
#: Полка секции детерминирована её типом: повторная генерация той же секции
#: — вопрос двери о замене СВОЕЙ полки, а не тихий близнец.
DATASET_ID_PREFIX = "hb-gen-"
#: Тексты статусов секции (объекты тестового pinned-контракта листа).
STATUS_IDLE = "ожидает"
STATUS_RUNNING = "генерация…"
STATUS_CANCELLED = "отменено"
STATUS_CHANNEL_ERROR = "ошибка канала — можно перезапустить"
STATUS_ERRORS = "ошибки валидатора — доступен ещё круг"
STATUS_READY = "готово к принятию"
STATUS_READY_WARN = "готово (с предупреждениями) — можно принять"
STATUS_ACCEPTED = "принято и подключено"
NO_ISSUES_TEXT = "Замечаний нет."


def generation_dataset_id(section: str) -> str:
    """Имя полки для сгенерированной секции (одна функция — один адрес)."""
    return f"{DATASET_ID_PREFIX}{section}"


@dataclass
class _SectionJob:
    """Виджеты и состояние одной секции задачи."""

    section: str
    dataset_id: str
    check: QCheckBox
    count: QSpinBox
    status: QLabel
    preview: QPlainTextEdit
    report: QLabel
    license_box: QComboBox
    accept_button: QPushButton
    regen_button: QPushButton
    again_button: QPushButton
    cancel_button: QPushButton
    acceptance_row: QWidget
    result: GenerationRoundResult | None = None
    running: asyncio.Task | None = None
    accepted: bool = False
    extra: dict = field(default_factory=dict)


class DndDatasetTaskSheet(DndGenerationTaskSheet):
    """Задача генерации датасетов: секции независимы, принятие — дверь импорта."""

    def __init__(
        self,
        *,
        deps: GenerationDeps,
        inputs: GenerationInputs,
        acceptance: DatasetSectionAcceptanceService,
        run_locked: Callable[[Coroutine], asyncio.Task],
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(
            DD_DATASET_TASK_TITLE,
            deps=deps,
            run_locked=run_locked,
            parent=parent,
            theme=theme,
        )
        self._inputs = inputs
        self._acceptance = acceptance
        self._composer = PromptComposer()
        # Живая ссылка modeless-вопроса о замене полки (PR-010 поза).
        self._replace_box: QMessageBox | None = None
        self.setObjectName("ddDatasetTaskSheet")
        self.setMinimumSize(520, 460)
        self.resize(560, 640)

        content = QWidget(self)
        body = QVBoxLayout(content)
        side_px = self._token_px("space.md", 16)
        row_px = self._token_px("space.sm", 8)
        body.setContentsMargins(side_px, row_px, side_px, side_px)
        body.setSpacing(row_px)

        self._idea = QPlainTextEdit(content)
        self._idea.setObjectName("ddDatasetGenIdea")
        self._idea.setPlaceholderText(
            "Идея генерации — чем должны быть эти сущности в мире игры"
        )
        self._idea.setFixedHeight(64)
        body.addWidget(QLabel("Идея:", content))
        body.addWidget(self._idea)

        controls = QHBoxLayout()
        self._start_button = QPushButton("Сгенерировать", content)
        self._start_button.setObjectName("ddDatasetGenStart")
        self._start_button.clicked.connect(self._on_start_clicked)
        controls.addWidget(self._gate_button(self._start_button))
        controls.addStretch(1)
        body.addLayout(controls)

        # Секции живут в прокручиваемой области: шесть блоков с предпросмотром
        # не влезают ни в какой разумный лист, а горизонтальная геометрия
        # листов модуля от этого не зависит.
        scroller = QScrollArea(content)
        scroller.setObjectName("ddDatasetGenScroller")
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QScrollArea.Shape.NoFrame)
        sections_host = QWidget(scroller)
        sections_layout = QVBoxLayout(sections_host)
        sections_layout.setContentsMargins(0, 0, 0, 0)
        self._jobs: dict[str, _SectionJob] = {}
        for section in SECTIONS:
            sections_layout.addWidget(self._build_job(section, sections_host))
        sections_layout.addStretch(1)
        scroller.setWidget(sections_host)
        body.addWidget(scroller, 1)

        self.add_content(content)

    # ── сборка секции ──────────────────────────────────────────────────────────

    def _build_job(self, section: str, host: QWidget) -> QGroupBox:
        label = self._composer.section_label(section)
        box = QGroupBox(label, host)
        box.setObjectName(f"ddDatasetGen_{section}")
        grid = QVBoxLayout(box)

        header = QHBoxLayout()
        check = QCheckBox(label, box)
        check.setObjectName(f"ddDatasetGenSection_{section}")
        count = QSpinBox(box)
        count.setObjectName(f"ddDatasetGenCount_{section}")
        count.setRange(SECTION_COUNT_MIN, SECTION_COUNT_MAX)
        count.setValue(SECTION_DEFAULT_COUNT)
        count.setPrefix("сущностей: ")
        status = QLabel(STATUS_IDLE, box)
        status.setObjectName(f"ddDatasetGenStatus_{section}")
        header.addWidget(check)
        header.addWidget(count)
        header.addStretch(1)
        header.addWidget(status)
        grid.addLayout(header)

        preview = QPlainTextEdit(box)
        preview.setObjectName(f"ddDatasetGenPreview_{section}")
        preview.setReadOnly(True)
        preview.setFixedHeight(120)
        preview.hide()
        grid.addWidget(preview)

        report = QLabel(box)
        report.setObjectName(f"ddDatasetGenReport_{section}")
        report.setWordWrap(True)
        report.hide()
        grid.addWidget(report)

        acceptance_row = QWidget(box)
        acceptance_row.setObjectName(f"ddDatasetGenActions_{section}")
        actions = QHBoxLayout(acceptance_row)
        actions.setContentsMargins(0, 0, 0, 0)
        license_box = QComboBox(acceptance_row)
        license_box.setObjectName(f"ddDatasetGenLicense_{section}")
        license_box.addItems(DATASET_LICENSE_CHOICES)
        license_box.setCurrentText(DEFAULT_DATASET_LICENSE)
        # Caption is the spec-pinned action name (spec «Предпросмотр и принятие
        # датасета»: «кнопка „Принять в библиотеку“ недоступна» при ошибках);
        # a stock text Button is named by its caption in the a11y tree.
        accept_button = QPushButton("Принять в библиотеку", acceptance_row)
        accept_button.setObjectName(f"ddDatasetGenAccept_{section}")
        accept_button.setEnabled(False)
        accept_button.clicked.connect(
            lambda _checked=False, _job_section=section: self._on_accept_clicked(
                _job_section
            )
        )
        regen_button = QPushButton("Перегенерировать", acceptance_row)
        regen_button.setObjectName(f"ddDatasetGenRegen_{section}")
        regen_button.clicked.connect(
            lambda _checked=False, _job_section=section: self._start_section(
                _job_section, previous=None
            )
        )
        again_button = QPushButton("Ещё круг", acceptance_row)
        again_button.setObjectName(f"ddDatasetGenAgain_{section}")
        again_button.clicked.connect(
            lambda _checked=False, _job_section=section: self._start_section(
                _job_section, previous=self._jobs[_job_section].result
            )
        )
        cancel_button = QPushButton("Отменить", acceptance_row)
        cancel_button.setObjectName(f"ddDatasetGenCancel_{section}")
        cancel_button.clicked.connect(
            lambda _checked=False, _job_section=section: self._on_cancel_clicked(
                _job_section
            )
        )
        actions.addWidget(QLabel("Лицензия:", acceptance_row))
        actions.addWidget(license_box)
        actions.addWidget(accept_button)
        actions.addWidget(regen_button)
        actions.addWidget(again_button)
        actions.addWidget(cancel_button)
        actions.addStretch(1)
        acceptance_row.hide()
        grid.addWidget(acceptance_row)

        # Гейт только у генерирующих кнопок: принятие — не обращение к
        # ассистенту, оно живёт правом результата (spec «Гейт активации»).
        self._gate_button(regen_button)
        self._gate_button(again_button)
        job = _SectionJob(
            section=section,
            dataset_id=generation_dataset_id(section),
            check=check,
            count=count,
            status=status,
            preview=preview,
            report=report,
            license_box=license_box,
            accept_button=accept_button,
            regen_button=regen_button,
            again_button=again_button,
            cancel_button=cancel_button,
            acceptance_row=acceptance_row,
        )
        self._jobs[section] = job
        return box

    # ── запуск кругов ──────────────────────────────────────────────────────────

    def refresh_gate(self) -> None:
        """Гейт перекладывает «Ещё круг» заново: у кнопки два условия
        (общий AI-гейт и живой ответ с ошибками), а база знает только первое."""
        super().refresh_gate()
        if self._released:
            return
        gate = bool(self._deps.available())
        for job in self._jobs.values():
            result = job.result
            live_again = (
                result is not None
                and result.error_message is None
                and not result.ok
                and gate
            )
            if not gate:
                continue  # база уже сняла активность и дала общую подсказку
            job.again_button.setEnabled(live_again)
            job.again_button.setToolTip("")

    def _on_start_clicked(self) -> None:
        """Отмеченные секции — независимые задачи qasync (spec: провал
        соседней не переписывает готовую)."""
        for section, job in self._jobs.items():
            if job.check.isChecked() and job.running is None:
                self._start_section(section, previous=None)

    def _start_section(
        self, section: str, *, previous: GenerationRoundResult | None
    ) -> None:
        job = self._jobs[section]
        if self._released or job.running is not None:
            return
        if not self._deps.available():
            # Кнопка неактивна, но прямой вызов (тест/клавиатура) не должен
            # запускать сеть при закрытом гейте.
            return
        job.result = None
        job.accepted = False
        job.status.setText(STATUS_RUNNING)
        job.preview.clear()
        job.preview.hide()
        job.report.clear()
        job.report.hide()
        job.acceptance_row.show()
        job.accept_button.setEnabled(False)
        job.running = self._spawn(self._round(job, previous), self._on_round_done)

    async def _round(
        self, job: _SectionJob, previous: GenerationRoundResult | None
    ) -> tuple[_SectionJob, GenerationRoundResult]:
        context = await self._inputs.dataset_section_context(
            job.section,
            job.dataset_id,
            world=self._deps.world(),
            idea=self._idea.toPlainText(),
            count=job.count.value(),
        )
        channel = DatasetSectionChannel(job.section, job.dataset_id)
        result = await run_rounds(
            channel,
            context,
            self._deps.make_answer(),
            previous=previous,
            on_phase=lambda phase, _job=job: self._on_phase(_job, phase),
        )
        return job, result

    def _on_phase(self, job: _SectionJob, phase: str) -> None:
        # Штатный индикатор фаз (design Д8): статус секции озвучивает повтор.
        if not self._released and job.running is not None:
            job.status.setText(f"{STATUS_RUNNING} {phase}")

    def _on_round_done(self, task: asyncio.Task) -> None:
        if self._cancelled_or_released(task):
            return  # отмена — не ошибка: диалога нет (spec, task 7.4)
        if task.exception() is not None:
            job = self._job_from_task(task)
            self._unexpected(task)
            if job is not None:
                job.running = None
                job.status.setText(STATUS_CHANNEL_ERROR)
            return
        job, result = task.result()
        job.running = None
        job.result = result
        self._render(job)

    def _job_from_task(self, task: asyncio.Task) -> _SectionJob | None:
        for job in self._jobs.values():
            if job.running is task:
                return job
        return None

    # ── отмена секции ──────────────────────────────────────────────────────────

    def _on_cancel_clicked(self, section: str) -> None:
        """Отмена секции — не ошибка: бокса нет, секция возвращается в
        ожидание; готовый результат соседних секций не трогается."""
        job = self._jobs[section]
        if self._released:
            return
        if job.running is not None:
            job.running.cancel()
            job.running = None
        job.result = None
        job.accepted = False
        job.preview.clear()
        job.preview.hide()
        job.report.clear()
        job.report.hide()
        job.acceptance_row.hide()
        job.accept_button.setEnabled(False)
        job.status.setText(STATUS_CANCELLED)

    # ── отрисовка результата ───────────────────────────────────────────────────

    def _render(self, job: _SectionJob) -> None:
        result = job.result
        if result is None:
            return
        if result.error_message is not None:
            # Сбой канала: русское сообщение в листе, предпросмотр пустой —
            # частичные ответы прерванных кругов в него не попадают (spec
            # «Ошибки канала LLM»); секция перезапускается «Ещё кругом»
            # только после живого ответа, иначе — «Перегенерировать».
            job.status.setText(STATUS_CHANNEL_ERROR)
            job.preview.clear()
            job.preview.hide()
            job.report.setText(result.error_message)
            job.report.show()
            job.acceptance_row.show()
            job.accept_button.setEnabled(False)
            job.again_button.setEnabled(False)
            return
        job.preview.setPlainText(self._pretty(result.document or ""))
        job.preview.show()
        lines = report_lines(result.report)
        job.report.setText("\n".join(lines) if lines else NO_ISSUES_TEXT)
        job.report.show()
        job.acceptance_row.show()
        # «Ещё круг» — ручная дозаправка круга при ошибках валидатора (spec
        # «Лимит автоматических кругов»); при принятом-готовом документе он
        # не нужен, при сбое канала нечего исправлять (нет ответа-основы).
        job.again_button.setEnabled((not result.ok) and bool(self._deps.available()))
        if result.ok:
            has_warnings = bool(result.report.issues)
            job.status.setText(STATUS_READY_WARN if has_warnings else STATUS_READY)
            job.accept_button.setEnabled(True)
        else:
            job.status.setText(STATUS_ERRORS)
            job.accept_button.setEnabled(False)

    @staticmethod
    def _pretty(document: str) -> str:
        try:
            return json.dumps(
                json.loads(document), ensure_ascii=False, indent=2
            )
        except (json.JSONDecodeError, TypeError):
            return document

    # ── принятие (дверь импорта + автоподключение) ────────────────────────────

    def _on_accept_clicked(
        self, section: str, *, confirmed: bool = False
    ) -> None:
        job = self._jobs[section]
        if (
            self._released
            or job.result is None
            or not job.result.ok
            or job.accepted
            or job.result.document is None
        ):
            return  # документ с ошибками не принимается (spec-гейт)
        document = job.result.document
        license_choice = job.license_box.currentText()
        self._run_acceptance(
            self._accept(job, document, license_choice, confirmed),
            self._on_accept_done,
        )

    async def _accept(
        self,
        job: _SectionJob,
        document: str,
        license_choice: str,
        confirmed: bool,
    ) -> tuple[_SectionJob, object]:
        outcome = await self._acceptance.accept(
            document, license_choice, confirmed=confirmed
        )
        return job, outcome

    def _on_accept_done(self, task: asyncio.Task) -> None:
        if self._cancelled_or_released(task):
            return
        if task.exception() is not None:
            self._unexpected(task)
            return
        job, outcome = task.result()
        if outcome.accepted:
            job.accepted = True
            job.accept_button.setEnabled(False)
            job.status.setText(STATUS_ACCEPTED)
            return
        import_outcome = outcome.import_outcome
        if import_outcome.status is DatasetImportStatus.NEEDS_CONFIRMATION:
            self._ask_replace(job)
            return
        lines = (
            report_lines(import_outcome.report)
            if import_outcome.report is not None
            else []
        )
        body = import_outcome.message or "Датасет не принят."
        if lines:
            body = body + "\n\n" + "\n".join(lines)
        self._show_notice(body)

    def _ask_replace(self, job: _SectionJob) -> None:
        """Полка с таким адресом уже есть — штатный вопрос двери импорта;
        подтверждение доходит ``confirmed=True``."""
        box = QMessageBox(self.window())
        box.setWindowTitle(self.windowTitle())
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            f"Набор «{job.dataset_id}» уже лежит в хранилище. Заменить его "
            "этим документом?"
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        self._replace_box = box
        box.finished.connect(
            lambda result, _job=job: self._on_replace_answered(result, _job)
        )
        box.show()

    def _on_replace_answered(self, result: int, job: _SectionJob) -> None:
        self._replace_box = None
        if result != QMessageBox.StandardButton.Yes or self._released:
            return
        self._on_accept_clicked(job.section, confirmed=True)
