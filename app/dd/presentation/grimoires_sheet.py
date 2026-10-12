"""The «Гримуары…» sheet (add-dnd-game-face, task 4.5; design Д8;
spec dnd-grimoire-import «Гримуары доступны из интерфейса игры»).

The module's grimoire screen rides the same window-class contract as the
datasets sheet (modal-sheets, the three-class norm): a
``QDialog(parent=MainWindow)`` shown through ``ApplicationWiring.open_sheet``
— the ``Qt.Sheet`` attached native sheet with NO Qt modality (PR-012), the
widget-side :class:`SheetFrame` chrome («caption + Закрыть», the caption one
windowTitle-threaded value, the canvas the sheet surface from the first
pixel), the connector's stack and the menu gate arriving for free through
``sheet_stack_changed``. Esc and the header button share the frame's one
``reject`` path; the sheet never remembers a placement.

Content per the spec: the storage list (title, id, per-row «подключён к этой
игре» checkbox through :class:`GrimoireConnectionsService` — disconnect
removes only the link, the file stays and may be connected again, spec
«Отключил — файл жив»), the marker line + row for connected ids whose file
left the shelf (spec «Пропавший файл помечен» — listed, kept, disconnectable),
and «Импорт файла…».

The import contour shows every spec branch as a modeless box on the shared
loop (PR-010 posture — no ``.exec()``): the parser's errors refuse with the
report and the storage stays untouched, warnings import and are listed, an
existing id asks for a replacement confirmation before the second, confirmed
request re-sends the very bytes, and a file that cannot be read says why.
The flow drives :class:`GrimoireImportService` as it is — the check-then-
shelve decision tree has exactly one home (coding principle 2). The import
is file-only (no session, no network), so it runs synchronously on the
click; the connections half is session work and rides the connector's
``run_locked`` like every other flow here. The file pick is a system popup —
the fixed exception class of the window contract — always with
``DontUseNativeDialog`` (L1: the Russian Qt panel, never the native one).

Async posture mirrors the datasets sheet: every session-touching flow starts
through the injected ``run_locked`` (the sheet owns no session, coding
principle 1), all in-flight tasks are cancelled in :meth:`done`, and the
closed sheet never repaints itself (the PR-037 posture, widget edition).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Coroutine

from PySide6.QtCore import QSize
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

from app.dd.application.grimoire_import_service import (
    GrimoireImportOutcome,
    GrimoireImportStatus,
)
from app.dd.presentation.datasets_sheet import report_lines
from app.presentation.views.sheet_frame import SheetFrame

if TYPE_CHECKING:
    from app.dd.application.grimoire_connections_service import (
        GrimoireConnectionsService,
    )
    from app.dd.application.grimoire_import_service import GrimoireImportService
    from app.dd.application.generation_deps import GenerationDeps
    from app.dd.infrastructure.grimoire_storage import GrimoireStorage

#: Header caption and menu entry of the sheet — one name (the «Датасеты D&D…»
#: precedent); SheetFrame threads it into windowTitle and the header.
DD_GRIMOIRES_SHEET_TITLE = "Гримуары…"

#: Box captions of the sheet's own flows.
DD_GRIMOIRES_IMPORT_TITLE = "Импорт гримуара D&D"
DD_GRIMOIRES_CONFIRM_TITLE = "Замена гримуара"

#: The generic answer for an import crash nothing else explains — coding
#: principle 3: persistence errors never go silent.
DD_GRIMOIRES_IMPORT_UNEXPECTED_BODY = (
    "Импорт гримуара не завершился. Подробности — в журнале приложения; "
    "хранилище не изменено, если гримуар не появился в списке."
)

#: Column captions: a grimoire shelf has no source/check state (its bytes
#: ARE the record, design Д8) — the name and the game's link are all the
#: master needs to connect, disconnect and spot a vanished file.
_COLUMN_SET = ("Гримуар", "Подключён к игре")

#: Fallback content margins — the numbers tokens.json carries (space.md /
#: space.sm); only an off-skin sheet ever reads them (the SheetFrame pattern).
_SIDE_MARGIN_FALLBACK_PX = 16
_ROW_MARGIN_FALLBACK_PX = 8


def _spell_phrase(count: int) -> str:
    """The Russian plural of «заклинание» for the import report — the master
    reads how many spells the file brought in."""
    if 11 <= count % 100 <= 14 or count % 10 == 0 or count % 10 >= 5:
        word = "заклинаний"
    elif count % 10 == 1:
        word = "заклинание"
    else:
        word = "заклинания"
    return f"{count} {word}"


class DndGrimoiresSheet(SheetFrame):
    """Storage list + per-row connection + file import on one sheet."""

    #: Sheet default (design Д6 posture: fixed default, no placement memory).
    DEFAULT_SIZE = QSize(620, 520)
    #: Usability floor — two columns plus the button row.
    MIN_SIZE = QSize(420, 300)

    def __init__(
        self,
        *,
        storage: "GrimoireStorage",
        connections: "GrimoireConnectionsService",
        importer: "GrimoireImportService",
        run_locked: Callable[[Coroutine], asyncio.Task],
        parent: QWidget | None = None,
        theme=None,
        generation_open: "Callable[[], None] | None" = None,
        generation_deps: "GenerationDeps | None" = None,
    ) -> None:
        super().__init__(DD_GRIMOIRES_SHEET_TITLE, parent, theme)
        self._storage = storage
        self._connections = connections
        self._importer = importer
        self._run_locked = run_locked
        # Вход ИИ-генерации файла заклинаний (add-dnd-lss-generation task 7.2):
        # opener поднимает лист-задачу, двери несут общий AI-гейт; без
        # собранной генерации кнопка не печатается (постур «ни мёртвых действий»).
        self._generation_open = generation_open
        self._generation_deps = generation_deps
        # The statuses of the last successful frame load (connected ids and
        # the present flags); None until the first frame has arrived.
        self._statuses: list | None = None
        # grimoire id per table row, row index → id (selection-free today,
        # the row map keeps the ghost rows addressable for the tests/flows).
        self._row_ids: list[str] = []
        # Every session flow task started by a click — done() cancels what is
        # left (a closed sheet never repaints, never resumes into deleted C++).
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
        self._missing_label.setObjectName("ddMissingGrimoiresLabel")
        self._missing_label.setWordWrap(True)
        self._missing_label.hide()
        body.addWidget(self._missing_label)

        self._table = QTableWidget(0, len(_COLUMN_SET), content)
        self._table.setObjectName("ddGrimoireTable")
        self._table.setHorizontalHeaderLabels(_COLUMN_SET)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        body.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        self._import_button = QPushButton("Импорт файла…", content)
        self._import_button.setObjectName("ddGrimoireImportButton")
        self._import_button.clicked.connect(self._on_import_clicked)
        buttons.addWidget(self._import_button)
        self._generation_button: QPushButton | None = None
        if self._generation_open is not None:
            self._generation_button = QPushButton("Сгенерировать ИИ", content)
            self._generation_button.setObjectName("ddGrimoireGenerateAiButton")
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
        """Общий AI-гейт: неактивная кнопка несёт ту же русскую подсказку,
        что AI-кнопки карточек (task 7.5)."""
        if self._generation_button is None or self._generation_deps is None:
            return
        available = bool(self._generation_deps.available())
        self._generation_button.setEnabled(available)
        self._generation_button.setToolTip(
            "" if available else self._generation_deps.hint()
        )

    def showEvent(self, event) -> None:
        # Гейт перечитывается на каждом показе: настройка LLM меняется
        # посреди живой сессии.
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
                "Grimoires sheet frame load failed: %s", exc
            )
            self._show_notice(
                QMessageBox.Icon.Warning,
                DD_GRIMOIRES_SHEET_TITLE,
                f"Не удалось загрузить список гримуаров: {exc}",
            )
            return
        self._statuses = statuses
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        """Repaint the table from the storage files + the last frame."""
        statuses = self._statuses or []
        connected = {status.grimoire_id for status in statuses}
        self._table.setRowCount(0)
        self._row_ids = []
        for shelf in self._storage.list_grimoires():
            self._append_row(
                shelf.grimoire_id,
                f"{shelf.title} — {shelf.grimoire_id}",
                connected=shelf.grimoire_id in connected,
            )
        missing = [s.grimoire_id for s in statuses if not s.present]
        for grimoire_id in missing:
            self._append_row(
                grimoire_id,
                f"{grimoire_id} — файл отсутствует в хранилище",
                connected=True,
            )
        if missing:
            self._missing_label.setText(
                "Подключённые гримуары отсутствуют в хранилище: "
                + ", ".join(missing)
            )
        self._missing_label.setVisible(bool(missing))

    def _append_row(
        self, grimoire_id: str, name_text: str, *, connected: bool
    ) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(name_text))
        holder = QWidget(self._table)
        row_layout = QHBoxLayout(holder)
        row_layout.setContentsMargins(4, 0, 4, 0)
        row_layout.addStretch(1)
        box = QCheckBox(holder)
        box.setObjectName("ddGrimoireConnectBox")
        # Icon-less control named by what its press does at this row (the
        # naming half of the accessibility contract, widget side).
        box.setAccessibleName(
            "Отключить гримуар от игры" if connected else "Подключить гримуар к игре"
        )
        row_layout.addWidget(box)
        row_layout.addStretch(1)
        # setChecked BEFORE the connect: a programmatic repaint can never
        # masquerade as a user toggle. The write rides ``toggled``, not
        # ``clicked`` — the checkbox's accessibility Toggle (what cocoa's
        # AXPress becomes for this role, the PR-001 fact) flips the state
        # through toggle() without emitting clicked, so a clicked-wired
        # switch would show an AT reader a tick that lies (the datasets
        # sheet's task 12.1 lesson, applied here from the first line).
        box.setChecked(connected)
        box.toggled.connect(
            lambda checked, _id=grimoire_id: self._on_connect_toggled(_id, checked)
        )
        self._table.setCellWidget(row, 1, holder)
        self._row_ids.append(grimoire_id)

    # ── connections (spec «Игра подключает гримуары списком, отключение
    # обратимо») ───────────────────────────────────────────────────────────────

    def _on_connect_toggled(self, grimoire_id: str, checked: bool) -> None:
        self._start_locked(
            self._toggle_async(grimoire_id, checked), self._on_toggle_done
        )

    async def _toggle_async(self, grimoire_id: str, checked: bool) -> None:
        """Write the link, then re-read the frame INSIDE the same locked task
        (a second run_locked here would deadlock the session lock)."""
        if checked:
            await self._connections.connect(grimoire_id)
        else:
            await self._connections.disconnect(grimoire_id)
        self._statuses = await self._connections.statuses()
        self._rebuild_rows()

    def _on_toggle_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        try:
            task.result()
        except Exception as exc:  # noqa: BLE001 — principle 3: never silent
            logging.getLogger("app.dd.sheet").warning(
                "Grimoire connection change failed: %s", exc
            )
            self._show_notice(
                QMessageBox.Icon.Warning,
                DD_GRIMOIRES_SHEET_TITLE,
                f"Не удалось изменить подключение гримуара: {exc}",
            )

    # ── file import (spec «Импорт из интерфейса») ─────────────────────────────

    def _on_import_clicked(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            DD_GRIMOIRES_IMPORT_TITLE,
            "",
            "JSON-файлы заклинаний (*.json);;Все файлы (*)",
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
                DD_GRIMOIRES_IMPORT_TITLE,
                f"Не удалось прочитать файл «{path}»: {exc}",
            )
            return
        self._run_import(content, confirmed=False)

    def _run_import(self, content: str, *, confirmed: bool) -> None:
        """One import request through the service's decision tree (files
        only — no session, no lock). The content travels through the
        callback: a confirmation re-request sends the very bytes the first
        request checked, not a re-read of a file the master may have edited
        in between (the datasets flow's posture, one decision one home)."""
        try:
            outcome: GrimoireImportOutcome = self._importer.import_grimoire(
                content, confirmed=confirmed
            )
        except Exception as exc:  # noqa: BLE001 — principle 3
            logging.getLogger("app.dd.sheet").error(
                "Grimoire import flow crashed: %s", exc, exc_info=True
            )
            self._show_notice(
                QMessageBox.Icon.Warning,
                DD_GRIMOIRES_IMPORT_TITLE,
                DD_GRIMOIRES_IMPORT_UNEXPECTED_BODY,
            )
            return
        if outcome.status is GrimoireImportStatus.NEEDS_CONFIRMATION:
            # Spec «Замена подтверждается»: the answer arrives through
            # finished on the shared loop; the отвод leaves the storage
            # exactly as it stood.
            self._ask_replacement(outcome, content)
            return
        if outcome.status is GrimoireImportStatus.BLOCKED:
            self._show_import_refusal(outcome)
            return
        # STORED — the shelf (or its replacement) is in; warnings always
        # accompany the import (spec «показан отчёт импорта»).
        verb = "заменён" if outcome.replaced else "импортирован"
        body = (
            f"Гримуар «{outcome.title}» {verb} в хранилище "
            f"({_spell_phrase(outcome.spell_count)})."
        )
        warnings = outcome.report.warnings if outcome.report is not None else ()
        if warnings:
            lines = "\n".join(
                f"{issue.path} — {issue.message}" for issue in warnings
            )
            self._show_notice(
                QMessageBox.Icon.Information,
                DD_GRIMOIRES_IMPORT_TITLE,
                f"{body} Предупреждения:\n{lines}",
            )
        else:
            self._show_notice(
                QMessageBox.Icon.Information, DD_GRIMOIRES_IMPORT_TITLE, body
            )
        self.request_refresh()

    def _show_import_refusal(self, outcome: GrimoireImportOutcome) -> None:
        if outcome.report is not None and outcome.report.errors:
            lines = "\n".join(report_lines(outcome.report))
            self._show_notice(
                QMessageBox.Icon.Warning,
                DD_GRIMOIRES_IMPORT_TITLE,
                f"Импорт отклонён — отчёт проверки:\n{lines}",
            )
            return
        # An id that cannot be a file name: the service's own sentence.
        self._show_notice(
            QMessageBox.Icon.Warning, DD_GRIMOIRES_IMPORT_TITLE, outcome.message
        )

    def _ask_replacement(
        self, outcome: GrimoireImportOutcome, content: str
    ) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(DD_GRIMOIRES_CONFIRM_TITLE)
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
        (Esc/close alike) is the spec's бездействие — the old file is whole."""
        self._confirm_box = None
        if result != QMessageBox.StandardButton.Yes:
            return
        self._run_import(content, confirmed=True)

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
        until finished, never a nested event loop)."""
        box = QMessageBox(self)
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
