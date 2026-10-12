"""The «Датасеты D&D…» sheet (add-dnd-module-foundation, tasks 5.1/5.2;
design Д3/Д9; spec dnd-dataset-library «Экран датасетов», «Импорт
пользовательского датасета файлом», «Подключение наборов к игре»).

The module's screen rides the kernel's window-class contract (modal-sheets,
retired by NRI-0024 to the three-class norm): a ``QDialog(parent=MainWindow)``
shown through ``ApplicationWiring.open_sheet`` — the ``Qt.Sheet`` attached
native sheet with NO Qt modality (PR-012), the widget-side
:class:`SheetFrame` chrome («caption + Закрыть», the caption one
windowTitle-threaded value, the canvas the sheet surface from the first
pixel through ``attach_theme(sheet=True)``), the connector's stack and the
menu gate arriving for free through ``sheet_stack_changed``. Esc and the
header button share the frame's one ``reject`` path; the sheet never
remembers a placement (fixed default, growth is not its contract — the body
scrolls).

Content per task 5.2: the storage list (title, id, source, the sidecar's
last-check state), the per-row «подключён к этой игре» checkbox whose toggle
goes through :class:`DatasetConnectionsService` (disconnect removes only the
link — the file stays), the missing-id marker line for connected ids whose
shelf left the storage (spec «Пропавший набор помечен» — listed, kept,
disconnectable), and the three action buttons: «Загрузить SRD» (the
idempotent official bootstrap re-run — the same service method the first
attach schedules), «Импорт файла…» (task 5.1 below) and «Повторить проверку»
for the selected shelf.

The import contour (task 5.1) shows every spec branch as a modeless box on
the shared loop (PR-010 posture — no ``.exec()``, no nested loop): errors
refuse with the report and the storage stays untouched, warnings import and
are listed, an existing homebrew id asks for a replacement confirmation
before the second, confirmed request, the SRD shelf refuses outright, and a
file that cannot be read says why. The file pick is a system popup — the
fixed exception class of the window contract — always with
``DontUseNativeDialog`` (L1: the Russian Qt panel, never the native one).

Async posture: every session-touching flow starts through the connector's
``run_locked`` (the caller injects the callable — the sheet owns no session,
coding principle 1); the SRD re-run is files + network only and runs as a
plain task outside the lock, the way the façade's attach bootstrap does. All
in-flight tasks are cancelled in :meth:`done`, so a closed sheet never
repaints itself and never leaves a half-flow behind.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Coroutine

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.dd.application.dataset_import_service import (
    DatasetImportOutcome,
    DatasetImportStatus,
)
from app.dd.domain.dataset import DatasetSource
from app.dd.domain.validation_report import ValidationReport
from app.presentation.views.sheet_frame import SheetFrame

if TYPE_CHECKING:
    from app.dd.application.dataset_connections_service import (
        DatasetConnectionsService,
    )
    from app.dd.application.dataset_import_service import DatasetImportService
    from app.dd.application.dataset_library_service import DatasetLibraryService
    from app.dd.application.generation_deps import GenerationDeps
    from app.dd.application.reference_visibility_service import (
        ReferenceVisibilityService,
    )

#: Header caption and menu entry of the sheet — one name (spec main-window
#: «одноимённый лист»); SheetFrame threads it into windowTitle and the header.
DD_DATASETS_SHEET_TITLE = "Датасеты D&D…"

#: Box captions of the sheet's own flows.
DD_IMPORT_TITLE = "Импорт датасета D&D"
DD_IMPORT_CONFIRM_TITLE = "Замена датасета"
DD_SRD_TITLE = "D&D-датасеты"
DD_RECHECK_TITLE = "Проверка датасета"

#: The generic answer for an import/SRD crash nothing else explains —
#: coding principle 3: persistence/network errors never go silent.
DD_IMPORT_UNEXPECTED_BODY = (
    "Импорт датасета не завершился. Подробности — в журнале приложения; "
    "хранилище не изменено, если набор не появился в списке."
)
DD_SRD_UNEXPECTED_BODY = (
    "Загрузка официальных наборов SRD не завершилась. Подробности — в "
    "журнале приложения; повторить загрузку можно этой же кнопкой."
)
#: Recheck asked with no storage row selected (a missing-id row checks
#: nothing — there is no file to read).
DD_RECHECK_NO_CHOICE_BODY = (
    "Выберите набор из хранилища — повторная проверка выполняется для "
    "выбранного набора."
)
DD_RECHECK_GHOST_BODY = (
    "Набора уже нет в хранилище — проверять нечего. Список обновлён."
)

#: Column captions, task 5.2 («список хранилища с состоянием проверки и
#: источником, подключение к игре»).
_COLUMN_SET = ("Набор", "Источник", "Проверка", "Подключён к игре")
#: Sidecar states printed in the «Проверка» column.
_CHECK_NEVER = "не проверялся"
#: Source captions.
_SOURCE_SRD = "SRD"
_SOURCE_HOMEBREW = "импортированный"
_SOURCE_UNKNOWN = "—"

#: Fallback content margins — the numbers tokens.json carries (space.md /
#: space.sm); only an off-skin sheet ever reads them (the SheetFrame pattern).
_SIDE_MARGIN_FALLBACK_PX = 16
_ROW_MARGIN_FALLBACK_PX = 8


def report_lines(report: ValidationReport, limit: int = 12) -> list[str]:
    """The box-facing lines of a report: every issue as ``path — text``,
    capped with an honest tail so a giant report never floods a box."""
    lines = [f"{issue.path} — {issue.message}" for issue in report.issues[:limit]]
    rest = len(report.issues) - limit
    if rest > 0:
        lines.append(f"… и ещё {rest}")
    return lines


class DndDatasetsSheet(SheetFrame):
    """Storage list + connections + SRD/import/recheck on one sheet."""

    #: Sheet default (design Д6 posture: fixed default, no placement memory).
    DEFAULT_SIZE = QSize(680, 560)
    #: Usability floor — four columns plus the button row.
    MIN_SIZE = QSize(460, 320)

    def __init__(
        self,
        *,
        library: "DatasetLibraryService",
        connections: "DatasetConnectionsService",
        importer: "DatasetImportService",
        run_locked: Callable[[Coroutine], asyncio.Task],
        parent: QWidget | None = None,
        theme=None,
        reference_visibility: "ReferenceVisibilityService | None" = None,
        generation_open: "Callable[[], None] | None" = None,
        generation_deps: "GenerationDeps | None" = None,
    ) -> None:
        super().__init__(DD_DATASETS_SHEET_TITLE, parent, theme)
        self._library = library
        self._connections = connections
        self._importer = importer
        self._run_locked = run_locked
        # The reference-toggle holder (add-dnd-game-face task 3.3): None (a
        # partial composition) prints no checkbox at all — the sheet never
        # offers a switch nothing would obey.
        self._reference_visibility = reference_visibility
        # Точка входа генерации (add-dnd-lss-generation task 7.2): opener
        # поднимает лист-задачу на стеке коннектора (façade держит единственный
        # экземпляр); без собранной генерации (частичная композиция) кнопка
        # не печатается — постур модуля «ни мёртвых действий».
        self._generation_open = generation_open
        self._generation_deps = generation_deps
        # The statuses of the last successful frame load (connected ids and
        # the missing markers); None until the first frame has arrived.
        self._statuses: list | None = None
        # dataset_id per table row, row index → id (recheck reads the
        # selection through this).
        self._row_ids: list[str] = []
        # Every flow task started by a click — done() cancels what is left
        # (a closed sheet never repaints, never resumes into deleted C++).
        self._tasks: set[asyncio.Task] = set()
        # Live refs of the modeless boxes (PR-010 posture: the ref keeps the
        # box out of Qt's garbage until finished, then drops).
        self._notice_box: QMessageBox | None = None
        self._confirm_box: QMessageBox | None = None

        self.setMinimumSize(self.MIN_SIZE)
        self.resize(self.DEFAULT_SIZE)

        side_px = self._token_px("space.md", _SIDE_MARGIN_FALLBACK_PX)
        row_px = self._token_px("space.sm", _ROW_MARGIN_FALLBACK_PX)

        content = QWidget(self)
        body = QVBoxLayout(content)
        body.setContentsMargins(side_px, row_px, side_px, side_px)
        body.setSpacing(row_px)

        self._missing_label = QLabel(content)
        self._missing_label.setObjectName("ddMissingDatasetsLabel")
        self._missing_label.setWordWrap(True)
        self._missing_label.hide()
        body.addWidget(self._missing_label)

        # The game-wide reference toggle (task 3.3, spec dnd-reference-records
        # «Справочные сущности участвуют в поиске под одним переключателем»):
        # one checkbox above the table, its caption naming the very switch;
        # the click writes through the shared holder (one transaction), the
        # reference source answers the new state on the next surface read.
        self._reference_box: QCheckBox | None = None
        if self._reference_visibility is not None:
            self._reference_box = QCheckBox(
                "Показывать справочные записи в поиске", content
            )
            self._reference_box.setObjectName("ddReferenceSearchBox")
            # The holder is loaded by the composition before this sheet is
            # ever built — the checkbox mirrors its current state from the
            # first pixel; setChecked precedes the connect (the repaint-is-
            # not-a-click ordering of the per-row boxes).
            self._reference_box.setChecked(self._reference_visibility.visible)
            # The write rides ``toggled``, not ``clicked`` (add-dnd-game-face
            # task 12.1): QAccessibleButton's Toggle action — the very action
            # cocoa maps AXPress onto for the CheckBox role (the PR-001
            # lesson) — flips ``checked`` through toggle() WITHOUT emitting
            # clicked. A clicked-wired switch therefore shows an AT reader a
            # tick that lies (the NRI-0023 F2 class, widget side; the kernel's
            # desk-panel seat checkboxes already ride toggled for the same
            # reason). Repaints never fire the write-back: setChecked
            # precedes the connect, and the one later rollback blocks the
            # signals around its setChecked (see _on_reference_done).
            self._reference_box.toggled.connect(self._on_reference_toggled)
            body.addWidget(self._reference_box)

        self._table = QTableWidget(0, len(_COLUMN_SET), content)
        self._table.setObjectName("ddDatasetTable")
        self._table.setHorizontalHeaderLabels(_COLUMN_SET)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, len(_COLUMN_SET)):
            self._table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        body.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        self._srd_button = QPushButton("Загрузить SRD", content)
        self._srd_button.setObjectName("ddSrdButton")
        self._srd_button.clicked.connect(self._on_srd_clicked)
        self._import_button = QPushButton("Импорт файла…", content)
        self._import_button.setObjectName("ddImportButton")
        self._import_button.clicked.connect(self._on_import_clicked)
        self._recheck_button = QPushButton("Повторить проверку", content)
        self._recheck_button.setObjectName("ddRecheckButton")
        self._recheck_button.clicked.connect(self._on_recheck_clicked)
        buttons.addWidget(self._srd_button)
        buttons.addWidget(self._import_button)
        buttons.addWidget(self._recheck_button)
        self._generation_button: QPushButton | None = None
        if self._generation_open is not None:
            # Кнопка живёт, только пока собран opener; гейт и подсказка —
            # общие AI-двери (task 7.5): неактивная кнопка носит ту же
            # русскую подсказку, что AI-кнопки карточек.
            self._generation_button = QPushButton("Сгенерировать ИИ", content)
            self._generation_button.setObjectName("ddGenerateAiButton")
            self._generation_button.clicked.connect(self._on_generation_clicked)
            buttons.addWidget(self._generation_button)
            self._apply_generation_gate()
        buttons.addStretch(1)
        body.addLayout(buttons)

        self.add_content(content)
        # The list paints without the session (files only); the connection
        # state rides the first frame the opener loads via request_refresh.
        self._rebuild_rows()

    def _token_px(self, key: str, fallback: int) -> int:
        """A size token in px from the runtime's loaded tokens; off-skin the
        sheet keeps the token's own number (the SheetFrame fallback pattern;
        the theme ref itself is the base frame's)."""
        tokens = self._theme.tokens if self._theme is not None else None
        if tokens is None:
            return fallback
        return int(tokens[key][self._theme.theme].removesuffix("px"))

    # ── вход генерации (add-dnd-lss-generation task 7.2/7.5) ─────────────────

    def _apply_generation_gate(self) -> None:
        """Неактивная кнопка генерации = закрытый общий AI-гейт; подсказка
        — та же, что у AI-кнопок карточек (дверь несёт façade-тексты)."""
        if self._generation_button is None:
            return
        if self._generation_deps is None:
            return  # opener без дверей (тестовая композиция) — кнопка живая
        available = bool(self._generation_deps.available())
        self._generation_button.setEnabled(available)
        self._generation_button.setToolTip(
            "" if available else self._generation_deps.hint()
        )

    def showEvent(self, event) -> None:
        # Настройка LLM и описание мира меняются посреди сессии — гейт
        # перечитывается на каждом показе листа.
        self._apply_generation_gate()
        super().showEvent(event)

    def _on_generation_clicked(self) -> None:
        if self._generation_open is not None:
            self._generation_open()

    # ── frame loading ─────────────────────────────────────────────────────────

    def request_refresh(self) -> None:
        """Re-read the game's connection statuses and repaint (storage part
        repaints immediately from the files; the session half rides the
        connector's lock)."""
        self._start_locked(
            self._connections.statuses(), self._on_frame_loaded
        )

    def _on_frame_loaded(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        try:
            statuses = task.result()
        except Exception as exc:  # noqa: BLE001 — the reader sees the reason
            logging.getLogger("app.dd.sheet").warning(
                "Datasets sheet frame load failed: %s", exc
            )
            self._show_notice(
                QMessageBox.Icon.Warning,
                "D&D-датасеты",
                f"Не удалось загрузить список датасетов: {exc}",
            )
            return
        self._statuses = statuses
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        """Repaint the table from the storage files + the last frame."""
        statuses = self._statuses or []
        connected = {status.dataset_id for status in statuses}
        self._table.setRowCount(0)
        self._row_ids = []
        for shelf in self._library.list_storage():
            check = shelf.meta.check_errors
            self._append_row(
                shelf.dataset_id,
                f"{shelf.title} — {shelf.dataset_id}",
                (
                    _SOURCE_SRD
                    if shelf.meta.source is DatasetSource.SRD
                    else _SOURCE_HOMEBREW
                ),
                _CHECK_NEVER if check is None else f"ошибок: {check}",
                connected=shelf.dataset_id in connected,
            )
        missing = [s.dataset_id for s in statuses if not s.present]
        for dataset_id in missing:
            self._append_row(
                dataset_id,
                f"{dataset_id} — набор отсутствует в хранилище",
                _SOURCE_UNKNOWN,
                _SOURCE_UNKNOWN,
                connected=True,
            )
        if missing:
            self._missing_label.setText(
                "Подключённые наборы отсутствуют в хранилище: "
                + ", ".join(missing)
            )
        self._missing_label.setVisible(bool(missing))

    def _append_row(
        self,
        dataset_id: str,
        name_text: str,
        source_text: str,
        check_text: str,
        *,
        connected: bool,
    ) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        for column, text in enumerate((name_text, source_text, check_text)):
            self._table.setItem(row, column, QTableWidgetItem(text))
        holder = QWidget(self._table)
        row_layout = QHBoxLayout(holder)
        row_layout.setContentsMargins(4, 0, 4, 0)
        row_layout.addStretch(1)
        box = QCheckBox(holder)
        box.setObjectName("ddDatasetConnectBox")
        # Icon-less control named by what its press does at this row (the
        # naming half of the accessibility contract, widget side).
        box.setAccessibleName(
            "Отключить набор от игры" if connected else "Подключить набор к игре"
        )
        row_layout.addWidget(box)
        row_layout.addStretch(1)
        # setChecked BEFORE the connect: a programmatic repaint can never
        # masquerade as a user toggle. The write rides ``toggled``, not
        # ``clicked`` — the checkbox's accessibility Toggle (what cocoa's
        # AXPress becomes for this role, the PR-001 fact) flips the state
        # through toggle() without emitting clicked, so a clicked-wired
        # switch would show an AT reader a tick that lies (add-dnd-game-face
        # task 12.1; the kernel's desk-panel seats use the same state
        # channel).
        box.setChecked(connected)
        box.toggled.connect(
            lambda checked, _id=dataset_id: self._on_connect_toggled(_id, checked)
        )
        self._table.setCellWidget(row, 3, holder)
        self._row_ids.append(dataset_id)

    # ── connections (spec «Подключение наборов к игре») ───────────────────────

    def _on_connect_toggled(self, dataset_id: str, checked: bool) -> None:
        self._start_locked(
            self._toggle_async(dataset_id, checked), self._on_toggle_done
        )

    async def _toggle_async(self, dataset_id: str, checked: bool) -> None:
        """Write the link, then re-read the frame INSIDE the same locked task
        (a second run_locked here would deadlock the session lock)."""
        if checked:
            await self._connections.connect(dataset_id)
        else:
            await self._connections.disconnect(dataset_id)
        self._statuses = await self._connections.statuses()
        self._rebuild_rows()

    def _on_toggle_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        try:
            task.result()
        except Exception as exc:  # noqa: BLE001 — principle 3: never silent
            logging.getLogger("app.dd.sheet").warning(
                "Dataset connection change failed: %s", exc
            )
            self._show_notice(
                QMessageBox.Icon.Warning,
                "D&D-датасеты",
                f"Не удалось изменить подключение набора: {exc}",
            )

    # ── reference-search toggle (task 3.3) ─────────────────────────────────────

    def _on_reference_toggled(self, checked: bool) -> None:
        # The box exists only together with the holder (the readiness of the
        # layout branch); the click therefore never arrives without it.
        assert self._reference_visibility is not None
        self._start_locked(
            self._reference_visibility.set_visible(checked),
            self._on_reference_done,
        )

    def _on_reference_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        try:
            task.result()
        except Exception as exc:  # noqa: BLE001 — principle 3: never silent
            logging.getLogger("app.dd.sheet").warning(
                "Reference search visibility change failed: %s", exc
            )
            # The write failed: the holder and the stored row still answer
            # the previous state — the checkbox walks back to it honestly,
            # the tick never pretends a switch the search will not obey.
            # The walk-back is a repaint, not a user gesture: it blocks the
            # state channel it rides (task 12.1 — with toggled wired, an
            # unblocked rollback would answer its own tick with a fresh
            # write attempt on the value the holder just refused).
            assert self._reference_visibility is not None
            if self._reference_box is not None:
                self._reference_box.blockSignals(True)
                self._reference_box.setChecked(self._reference_visibility.visible)
                self._reference_box.blockSignals(False)
            self._show_notice(
                QMessageBox.Icon.Warning,
                "D&D-датасеты",
                f"Не удалось сохранить настройку поиска по справочнику: {exc}",
            )

    # ── official SRD re-run (spec «Повторный запуск не качает» / повтор) ──────

    def _on_srd_clicked(self) -> None:
        """Files + network only — a plain task OUTSIDE the session lock, the
        very idiom of the façade's attach bootstrap (:meth:`DndModule`);
        without a running loop (an offscreen probe outside the qasync
        contour) nothing is scheduled and the next ask goes through here."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logging.getLogger("app.dd.sheet").debug(
                "SRD re-run skipped: no running event loop"
            )
            return
        task = loop.create_task(self._library.download_official_datasets())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(self._on_srd_done)

    def _on_srd_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        try:
            result = task.result()
        except Exception as exc:  # noqa: BLE001 — principle 3
            logging.getLogger("app.dd.sheet").error(
                "Datasets sheet SRD re-run crashed: %s", exc, exc_info=True
            )
            self._show_notice(
                QMessageBox.Icon.Warning, DD_SRD_TITLE, DD_SRD_UNEXPECTED_BODY
            )
            return
        # The user asked by hand — the answer is printed even when the honest
        # answer is «already there, no network was touched» (spec: «Успех и
        # каждая ошибка выводятся пользователю по-русски»).
        icon = (
            QMessageBox.Icon.Information
            if result.ok
            else QMessageBox.Icon.Warning
        )
        self._show_notice(icon, DD_SRD_TITLE, result.summary)
        self.request_refresh()

    # ── file import (task 5.1) ────────────────────────────────────────────────

    def _on_import_clicked(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Импорт датасета D&D",
            "",
            "JSON-датасеты (*.json);;Все файлы (*)",
            # L1 (NRI-0014): always the Russian Qt panel, never the native one.
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return  # the отвод is a no-op — the storage was never approached
        try:
            content = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self._show_notice(
                QMessageBox.Icon.Warning,
                DD_IMPORT_TITLE,
                f"Не удалось прочитать файл «{path}»: {exc}",
            )
            return
        self._spawn_import(content, confirmed=False)

    def _spawn_import(self, content: str, *, confirmed: bool) -> None:
        """One import request under the session lock (the flow reads the
        game's connection list for the validator's corpus). The content
        travels through the callback: a confirmation re-request sends the
        very bytes the first request checked, not a re-read of a file the
        master may have edited in between."""
        self._start_locked(
            self._importer.import_dataset(content, confirmed=confirmed),
            lambda finished, _bytes=content: self._on_import_done(finished, _bytes),
        )

    def _on_import_done(self, task: asyncio.Task, content: str) -> None:
        """The spec's branch list, one tree one home: confirm → refusal →
        stored-with-warnings → stored (the task never raised)."""
        if task.cancelled():
            return
        try:
            outcome: DatasetImportOutcome = task.result()
        except Exception as exc:  # noqa: BLE001 — principle 3
            logging.getLogger("app.dd.sheet").error(
                "Dataset import flow crashed: %s", exc, exc_info=True
            )
            self._show_notice(
                QMessageBox.Icon.Warning, DD_IMPORT_TITLE, DD_IMPORT_UNEXPECTED_BODY
            )
            return
        if outcome.status is DatasetImportStatus.NEEDS_CONFIRMATION:
            # Spec «заменять только после подтверждения»: the answer arrives
            # through finished on the shared loop; the отвод leaves the
            # storage exactly as it stood.
            self._ask_replacement(outcome, content)
            return
        if outcome.status is DatasetImportStatus.BLOCKED:
            self._show_import_refusal(outcome)
            return
        # STORED — the shelf (or its replacement) is in; warnings always
        # accompany the success (spec scenario «Импорт с предупреждениями»).
        verb = "заменён" if outcome.replaced else "импортирован"
        warnings = (
            outcome.report.warnings if outcome.report is not None else ()
        )
        if warnings:
            lines = "\n".join(
                f"{issue.path} — {issue.message}" for issue in warnings
            )
            self._show_notice(
                QMessageBox.Icon.Information,
                DD_IMPORT_TITLE,
                f"Набор «{outcome.title}» {verb}. Предупреждения:\n{lines}",
            )
        else:
            self._show_notice(
                QMessageBox.Icon.Information,
                DD_IMPORT_TITLE,
                f"Набор «{outcome.title}» {verb} в хранилище.",
            )
        self.request_refresh()

    def _show_import_refusal(self, outcome: DatasetImportOutcome) -> None:
        if outcome.report is not None and outcome.report.errors:
            lines = "\n".join(report_lines(outcome.report))
            self._show_notice(
                QMessageBox.Icon.Warning,
                DD_IMPORT_TITLE,
                f"Импорт отклонён — отчёт проверки:\n{lines}",
            )
            return
        # SRD protection / an unshelv-able document: the store's own sentence.
        self._show_notice(
            QMessageBox.Icon.Warning, DD_IMPORT_TITLE, outcome.message
        )

    def _ask_replacement(
        self, outcome: DatasetImportOutcome, content: str
    ) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(DD_IMPORT_CONFIRM_TITLE)
        box.setText(outcome.message)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        self._confirm_box = box
        box.finished.connect(
            lambda result, _bytes=content: self._on_replace_answered(result, _bytes)
        )
        box.show()

    def _on_replace_answered(self, result: int, content: str) -> None:
        """Yes re-requests the SAME bytes with the confirmation flag; No
        (Esc/close alike) is the spec's бездействие."""
        self._confirm_box = None
        if result != QMessageBox.StandardButton.Yes:
            return
        self._spawn_import(content, confirmed=True)

    # ── re-check (task 5.2 «кнопки … повторной проверки») ─────────────────────

    def _on_recheck_clicked(self) -> None:
        row = self._table.currentRow()
        dataset_id = self._row_ids[row] if 0 <= row < len(self._row_ids) else None
        if dataset_id is None or dataset_id not in {
            shelf.dataset_id for shelf in self._library.list_storage()
        }:
            self._show_notice(
                QMessageBox.Icon.Information,
                DD_RECHECK_TITLE,
                DD_RECHECK_NO_CHOICE_BODY,
            )
            return
        self._start_locked(self._importer.recheck(dataset_id), self._on_recheck_done)

    def _on_recheck_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        try:
            report = task.result()
        except Exception as exc:  # noqa: BLE001 — principle 3
            logging.getLogger("app.dd.sheet").warning(
                "Dataset re-check failed: %s", exc
            )
            self._show_notice(
                QMessageBox.Icon.Warning,
                DD_RECHECK_TITLE,
                f"Проверка не завершилась: {exc}",
            )
            return
        if report is None:
            # The shelf left the storage between the click and the read.
            self._show_notice(
                QMessageBox.Icon.Warning, DD_RECHECK_TITLE, DD_RECHECK_GHOST_BODY
            )
            self.request_refresh()
            return
        if report.errors:
            lines = "\n".join(report_lines(report))
            self._show_notice(
                QMessageBox.Icon.Warning,
                DD_RECHECK_TITLE,
                f"Проверка нашла ошибки:\n{lines}",
            )
        elif report.warnings:
            lines = "\n".join(report_lines(report))
            self._show_notice(
                QMessageBox.Icon.Information,
                DD_RECHECK_TITLE,
                f"Ошибок нет. Предупреждения:\n{lines}",
            )
        else:
            self._show_notice(
                QMessageBox.Icon.Information,
                DD_RECHECK_TITLE,
                "Ошибок и предупреждений нет.",
            )
        self.request_refresh()

    # ── flow plumbing ─────────────────────────────────────────────────────────

    def _start_locked(
        self, coro: Coroutine, on_done: Callable[[asyncio.Task], None]
    ) -> asyncio.Task:
        task = self._run_locked(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(on_done)
        return task

    def _show_notice(
        self, icon: QMessageBox.Icon, title: str, body: str
    ) -> None:
        """Modeless information/warning box (PR-010 posture: show(), live ref
        until finished, never a nested event loop).

        fix-dnd-followups (Д1, notes.md 2.1 «тот же дефект с той же причиной»):
        a QMessageBox is ApplicationModal BY DEFAULT, and the sheet-parented
        box held the keyboard — with the SRD result open, Esc closed the box
        instead of the sheet. The spec («Уведомление результата SHALL быть
        необязывающим») demands the opposite, so the box explicitly wears
        Qt's NonModal, exactly like the façade's ``_show_datasets_box``."""
        box = QMessageBox(self)
        box.setWindowModality(Qt.WindowModality.NonModal)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(body)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._notice_box = box
        box.finished.connect(self._notice_box_finished)
        box.show()

    def _notice_box_finished(self, _result: int) -> None:
        self._notice_box = None

    # ── leaving the sheet ─────────────────────────────────────────────────────

    def done(self, result: int) -> None:  # noqa: N802 — Qt API name
        """Every close route («Закрыть»/Esc/close()) passes here: in-flight
        tasks die with the sheet — a closed layer never repaints itself and
        never resumes into deleted C++ (the PR-037 posture, widget edition).
        Finished tasks have already dropped themselves from the set."""
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        super().done(result)
