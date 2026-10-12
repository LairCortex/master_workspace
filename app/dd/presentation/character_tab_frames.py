"""The two module tabs of a character card (add-dnd-game-face tasks 8.2/8.3).

Design Д10: the kernel draws the strip and owns the lifecycle; the module
paints inside. These are plain Qt widgets (the card body is a QML island; a
module tab is a native widget the host overlays on the body slot), so their
accessibility follows the kernel's contract through Qt's own widget bridges:
every control is штатный (QComboBox/QLineEdit/QPushButton), a control whose
caption is not its own text carries that caption as ``accessibleName``, and
object names (``ddDndSlot_*`` etc.) give the offscreen tests their addresses —
the same posture the module's sheets keep.

Both frames read and write through the injected service and the index; the
service owns the transactions, the frames never touch a session. Reads and
writes ride the connector's session lock through the injected ``run_locked``
(the datasets sheet's discipline): a second ``run_locked`` from inside a
locked task would deadlock the lock, so a flow that writes and reloads does
both INSIDE one coroutine and renders from its result.

Failure posture: a failed load or write is a modeless Russian box (never a
nested loop, the PR-010 posture of every live box in this codebase) — the
card around the tab keeps working. A released tab answers nothing:
:meth:`_LockedFrame.release_tab` cancels the frame's in-flight tasks (the
host calls it before the widget leaves the window).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Coroutine

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.dd.application.character_channel import (
    TOP_UP_NOTHING_REFUSAL,
    top_up_missing_fields,
)
from app.dd.application.character_import_service import (
    CharacterImportOutcome,
    CharacterImportStatus,
)
from app.dd.application.grimoire_index_service import GrimoireIndexSnapshot
from app.dd.domain.character import (
    LEVEL_MAX,
    LINK_SLOTS,
    DdSpellLink,
    ReferenceLink,
)
from app.dd.presentation.captions import button_caption

if TYPE_CHECKING:
    from app.dd.application.character_document_builder import CharacterDocumentBuilder
    from app.dd.application.character_import_service import CharacterImportService
    from app.dd.application.dataset_index_service import (
        DatasetIndexService,
        IndexSnapshot,
    )
    from app.dd.application.dnd_character_extension_service import (
        DndCharacterExtensionService,
    )
    from app.dd.application.grimoire_index_service import GrimoireIndexService
    from app.dd.application.generation_deps import GenerationDeps
    from app.dd.domain.character import DdCharacterExt

#: The caption of the «link unset» item of every reference picker.
UNSET_ITEM = "— не выбрано"

#: The spec's exact wording of a dead source, shared by both tabs (spec
#: «Снятый датасет не калечит карточку» / «недоступный источник — снимок
#: имени с той же пометкой»).
SOURCE_UNAVAILABLE_NOTE = "источник не подключён"

#: The digital LSS sheet page (roadmap: «при наличии id уместен прямой адрес
#: /iframe/characters/digital/<id>/»). The template lives once, here.
LSS_DIGITAL_SHEET_URL = "https://longstoryshort.app/iframe/characters/digital/{sheet_id}/"

#: Journal name of both frames.
_FRAME_LOGGER = "app.dd.character_tab"

#: Caption of the frame failure boxes (the module's standing caption).
_TAB_TITLE = "D&D-модуль"

#: The two file doors of the «D&D» tab (task 9.4; spec dnd-character-import
#: «Перезаписать из файла LSS…» из карточки). Captions name the action and
#: the format; the creation half of the spec's two entries lives on the
#: module's menu (:attr:`app.dd.presentation.section.
#: DndWindowSection.character_import_requested`) — a fresh card has no id
#: and no module tab to hang this row on.
IMPORT_OVERWRITE_TEXT = "Перезаписать из файла LSS…"
SAVE_RAW_TEXT = "Сохранить исходный файл…"
#: The third file door, half of add-dnd-lss-generation task 5.3 (spec
#: dnd-character-export «Кнопка „Экспорт для LSS…“»): the document is rebuilt
#: from the CURRENT card state (name, links, level, blocks, spell slugs) —
#: never a copy of the stored raw file, which is what «Сохранить исходный
#: файл…» is for. The door works without any AI configuration (the builder
#: never touches the network).
EXPORT_FOR_LSS_TEXT = "Экспорт для LSS…"
#: Вход ИИ-дозаполнения (add-dnd-lss-generation task 7.3): тот же лист
#: персонажа в режиме дозаполнения, открывается из D&D-таба карточки.
TOP_UP_AI_TEXT = "Дозаполнить ИИ"
#: The filter both file dialogs print (the datasets sheet's filter, restated
#: for the character document). Public: the module façade's creation dialog
#: prints the same filter (add-dnd-game-face task 9.4).
CHARACTER_FILE_FILTER = "JSON-экспорт персонажа (*.json);;Все файлы (*)"

#: The sentinel a done callback receives for «the task failed or was
#: cancelled» — a plain ``None`` could not say that, the write coroutines
#: succeed with ``None`` themselves.
_TASK_FAILED = object()


def lss_sheet_url(sheet_id: str) -> str:
    """The system-browser address of one digital sheet (the tab's «Открыть в
    браузере» hands exactly this to ``QDesktopServices``)."""
    return LSS_DIGITAL_SHEET_URL.format(sheet_id=sheet_id.strip())


def _empty_grimoire_snapshot() -> GrimoireIndexSnapshot:
    """The shelf-less answer: a frame composed without the grimoire door
    reads an empty shelf instead of branching on ``None`` everywhere."""
    return GrimoireIndexSnapshot(ids=(), titles={}, spells={})


class _LockedFrame(QWidget):
    """Shared plumbing: the live-task set and the modeless failure box."""

    def __init__(self, run_locked: Callable[[Coroutine], asyncio.Task], parent=None):
        super().__init__(parent)
        # The card's body slot is a QML surface; the tab is the native widget
        # floated over it and carries its own canvas — the window palette
        # (the theme sets it app-wide) paints the themed background.
        self.setAutoFillBackground(True)
        self._run_locked = run_locked
        self._tasks: set[asyncio.Task] = set()
        self._notice_box: QMessageBox | None = None

    def _start_locked(self, coro: Coroutine, on_done: Callable) -> None:
        """One session-locked task with a done callback and a live ref (the
        datasets sheet's discipline: refs keep the collector off, discard
        keeps the set clean)."""
        task = self._run_locked(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(on_done)

    def release_tab(self) -> None:
        """The host's release door (task 7.2): no callback survives the tab."""
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()

    def _show_notice(
        self, body: str, icon: QMessageBox.Icon = QMessageBox.Icon.Warning
    ) -> None:
        """Modeless notice box on the shared loop (PR-010 posture; the live
        ref drops on ``finished``). Warning is the standing posture (a failed
        load or write); successes pass their own icon."""
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(_TAB_TITLE)
        box.setText(body)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._notice_box = box
        box.finished.connect(self._notice_finished)
        box.show()

    def _notice_finished(self, _result: int) -> None:
        self._notice_box = None

    @staticmethod
    def _outcome(task: asyncio.Task, what: str):
        """The tolerant done-callback half: cancelled answers ``_TASK_FAILED``
        in silence, a raised failure is journalled and answers ``_TASK_FAILED``
        too; success is the task's own value (the sentinel is never a legal
        value of either frame's coroutines)."""
        if task.cancelled():
            return _TASK_FAILED
        try:
            return task.result()
        except Exception as exc:  # noqa: BLE001 — the reader sees the reason
            logging.getLogger(_FRAME_LOGGER).error(
                "D&D: %s не удалось: %s", what, exc, exc_info=True
            )
            return _TASK_FAILED


class DndCharacterTabFrame(_LockedFrame):
    """The «D&D» tab: five reference pickers, the level, the LSS sheet id.

    Each field writes the moment it changes — the module's tab has no save
    button and a half-edited field must not be a trap. A stored link whose
    source has been disconnected is re-shown as its snapshot with the
    «источник не подключён» mark and re-saves the same triple verbatim:
    reading never rewrites, losing the source never drops the value (spec
    «Снял чекбокс — карточка не немеет»).
    """

    def __init__(
        self,
        *,
        character_id: int,
        service: "DndCharacterExtensionService",
        dataset_index: "DatasetIndexService",
        record_labels: Mapping[str, str],
        run_locked: Callable[[Coroutine], asyncio.Task],
        import_service: "CharacterImportService | None" = None,
        document_builder: "CharacterDocumentBuilder | None" = None,
        generation_open: "Callable[[int, str], None] | None" = None,
        generation_deps: "GenerationDeps | None" = None,
        parent=None,
    ) -> None:
        super().__init__(run_locked, parent)
        self._character_id = character_id
        self._service = service
        self._index = dataset_index
        self._importer = import_service
        self._document_builder = document_builder
        # Вход ИИ-дозаполнения (add-dnd-lss-generation task 7.3): opener
        # даёт façade (он один поднимает лист-задачу на стеке), двери несут
        # общий AI-гейт с общей подсказкой. Без opener'а (частичная
        # композиция) кнопка не печатается.
        self._generation_open = generation_open
        self._generation_deps = generation_deps
        self._top_up_button: QPushButton | None = None
        self._loading = False
        self._saved_sheet = ""
        self._slot_combos: dict[str, QComboBox] = {}
        # Live refs of the import flow's boxes (PR-010 posture: until
        # ``finished`` Qt's garbage must not take a shown box away).
        self._overwrite_confirm_box: QMessageBox | None = None
        self._report_box: QMessageBox | None = None
        #: slot → the Russian caption (the same descriptor labels the rows
        #: print — one knowledge, one place).
        self._slot_labels = {
            slot: record_labels[type_key] for slot, _s, type_key in LINK_SLOTS
        }

        form = QFormLayout(self)
        for slot, _section, _type_key in LINK_SLOTS:
            label = self._slot_labels[slot]
            combo = QComboBox(self)
            combo.setObjectName(f"ddDndSlot_{slot}")
            combo.setAccessibleName(label)
            combo.currentIndexChanged.connect(
                lambda _index, _slot=slot: self._on_slot_changed(_slot)
            )
            self._slot_combos[slot] = combo
            form.addRow(label + ":", combo)

        self._level = QComboBox(self)
        self._level.setObjectName("ddDndLevel")
        self._level.setAccessibleName("Уровень")
        # index 0 = unset, index N shows N (1…20) — the combo itself is the
        # 1…20 gate, the service validates again at the door.
        self._level.addItem(UNSET_ITEM)
        for value in range(1, LEVEL_MAX + 1):
            self._level.addItem(str(value))
        self._level.currentIndexChanged.connect(self._on_level_changed)
        form.addRow("Уровень:", self._level)

        sheet_row = QHBoxLayout()
        self._sheet = QLineEdit(self)
        self._sheet.setObjectName("ddDndSheetId")
        self._sheet.setAccessibleName("Идентификатор листа LSS")
        self._sheet.setPlaceholderText("id цифрового листа Long Story Short")
        self._sheet.textChanged.connect(self._on_sheet_text_changed)
        self._sheet.editingFinished.connect(self._on_sheet_edited)
        sheet_row.addWidget(self._sheet)
        self._open = QPushButton("Открыть в браузере", self)
        self._open.setObjectName("ddDndSheetOpen")
        self._open.clicked.connect(self._on_open_sheet)
        self._open.setVisible(False)  # until a stored/typed value proves one
        sheet_row.addWidget(self._open)
        form.addRow("Лист LSS:", sheet_row)

        if self._importer is not None or self._document_builder is not None or self._generation_open is not None:
            # The file doors (task 9.4 + add-dnd-lss-generation task 5.3):
            # without a composed door (a partial composition) the tab prints
            # no dead buttons — the module's no-dead-action posture, one
            # floor lower. Each door prints its own button only when its
            # service arrived.
            file_row = QHBoxLayout()
            if self._importer is not None:
                overwrite = QPushButton(IMPORT_OVERWRITE_TEXT, self)
                overwrite.setObjectName("ddDndImportOverwrite")
                overwrite.clicked.connect(self._on_overwrite_clicked)
                file_row.addWidget(overwrite)
                save_raw = QPushButton(SAVE_RAW_TEXT, self)
                save_raw.setObjectName("ddDndSaveRaw")
                save_raw.clicked.connect(self._on_save_raw_clicked)
                file_row.addWidget(save_raw)
            if self._document_builder is not None:
                export = QPushButton(EXPORT_FOR_LSS_TEXT, self)
                export.setObjectName("ddDndExportLss")
                export.clicked.connect(self._on_export_clicked)
                file_row.addWidget(export)
            if (
                self._generation_open is not None
                and self._document_builder is not None
            ):
                # «Дозаполнить ИИ» (task 7.3): сборка текущего документа —
                # дверь сборщика, остальное делает лист-задача. Гейт — общий
                # AI-гейт, неактивная кнопка несёт общую подсказку (task 7.5).
                top_up = QPushButton(TOP_UP_AI_TEXT, self)
                top_up.setObjectName("ddDndTopUpAi")
                top_up.clicked.connect(self._on_top_up_clicked)
                file_row.addWidget(top_up)
                self._top_up_button = top_up
                self._apply_generation_gate()
            file_row.addStretch()
            form.addRow("Файл LSS:", file_row)

        self.request_refresh()

    # ── вход ИИ-дозаполнения (add-dnd-lss-generation task 7.3/7.5) ───────────

    def _apply_generation_gate(self) -> None:
        if self._top_up_button is None or self._generation_deps is None:
            return
        available = bool(self._generation_deps.available())
        self._top_up_button.setEnabled(available)
        self._top_up_button.setToolTip(
            "" if available else self._generation_deps.hint()
        )

    def showEvent(self, event) -> None:
        # Гейт перечитывается на каждом показе таба: настройка LLM и описание
        # мира меняются посреди живой сессии.
        self._apply_generation_gate()
        super().showEvent(event)

    def _on_top_up_clicked(self) -> None:
        if self._generation_open is None or self._document_builder is None:
            return
        if self._generation_deps is not None and not self._generation_deps.available():
            return
        self._start_locked(
            self._document_builder.build(self._character_id),
            self._on_top_up_document,
        )

    def _on_top_up_document(self, task: asyncio.Task) -> None:
        outcome = self._outcome(task, "сборка документа для дозаполнения ИИ")
        if outcome is _TASK_FAILED:
            if not task.cancelled():
                self._show_notice(
                    "Не удалось собрать документ персонажа для дозаполнения. "
                    "Карточка не изменена; подробности — в журнале приложения."
                )
            return
        document = str(outcome)
        if not top_up_missing_fields(document):
            # Spec scenario «Пусто дозаполнять»: генерация не запускается,
            # мастер читает пояснение.
            self._show_notice(TOP_UP_NOTHING_REFUSAL, QMessageBox.Icon.Information)
            return
        self._generation_open(self._character_id, document)

    def request_refresh(self) -> None:
        """Load the stored face and the current index through the lock."""
        self._start_locked(self._load(), self._on_loaded)

    async def _load(self):
        ext = await self._service.get_ext(self._character_id)
        snap = await self._index.snapshot()
        return ext, snap

    def _on_loaded(self, task: asyncio.Task) -> None:
        outcome = self._outcome(task, "загрузка D&D-полей")
        if outcome is _TASK_FAILED:
            if task.cancelled():
                return  # the released tab answers nothing
            self._show_notice(
                "Не удалось загрузить D&D-поля персонажа. Подробности — в "
                "журнале приложения; повторите, закрыв и открыв карточку."
            )
            return
        ext, snap = outcome
        self._fill(ext, snap)

    def _fill(self, ext: "DdCharacterExt", snap: "IndexSnapshot") -> None:
        """Publish the frame: every picker rebuilt, the stored link selected
        — its unavailable form appended, never dropped."""
        self._loading = True
        try:
            for slot, section, _type_key in LINK_SLOTS:
                combo = self._slot_combos[slot]
                combo.clear()
                combo.addItem(UNSET_ITEM, None)
                for dataset_id in snap.ids:
                    title = snap.titles.get(dataset_id, dataset_id)
                    for entry in snap.entries(section, dataset_id):
                        combo.addItem(
                            f"{entry.name} · {title}",
                            (dataset_id, entry.entry_id, entry.name),
                        )
                link = ext.links[slot]
                if link.is_set:
                    wanted = (link.source_key, link.ref_id, link.snapshot_name)
                    # Not ``findData``: its QVariant round-trip does not
                    # compare Python tuples reliably (verified on this Qt —
                    # equal ``itemData`` values, ``findData`` answers −1).
                    # The honest scan compares the objects as they are.
                    index = next(
                        (
                            i
                            for i in range(combo.count())
                            if combo.itemData(i) == wanted
                        ),
                        -1,
                    )
                    if index < 0:
                        # The source is gone (or the record is): the stored
                        # triple re-enters the picker as the annotated item —
                        # visible AND re-savable verbatim.
                        combo.addItem(
                            f"{link.snapshot_name} — {SOURCE_UNAVAILABLE_NOTE}",
                            wanted,
                        )
                        index = combo.count() - 1
                    combo.setCurrentIndex(index)
                else:
                    combo.setCurrentIndex(0)
            level = ext.level
            self._level.setCurrentIndex(
                0 if level is None or not 1 <= level <= LEVEL_MAX else level
            )
            self._saved_sheet = ext.lss_sheet_id
            self._sheet.setText(ext.lss_sheet_id)
        finally:
            self._loading = False

    # ── writes (each change is one locked operation) ─────────────────────────

    def _on_slot_changed(self, slot: str) -> None:
        if self._loading:
            return
        data = self._slot_combos[slot].currentData()
        link: ReferenceLink = (
            ReferenceLink(*data) if data is not None else ReferenceLink("", "", "")
        )
        self._start_locked(
            self._service.set_reference_link(self._character_id, slot, link),
            lambda task, what=self._slot_labels[slot]: self._on_write_done(task, what),
        )

    def _on_level_changed(self) -> None:
        if self._loading:
            return
        index = self._level.currentIndex()
        level = None if index <= 0 else index
        self._start_locked(
            self._service.set_level(self._character_id, level),
            lambda task: self._on_write_done(task, "уровень"),
        )

    def _on_sheet_text_changed(self, text: str) -> None:
        # The button shows only while the id is filled (spec «Пустой
        # идентификатор листа SHALL скрывать кнопку») — the visibility
        # follows the keystrokes, the WRITE waits for editingFinished.
        self._open.setVisible(bool(text.strip()))

    def _on_sheet_edited(self) -> None:
        if self._loading:
            return
        sheet_id = self._sheet.text().strip()
        if sheet_id == self._saved_sheet:
            return  # focus left an untouched field — no transaction
        self._saved_sheet = sheet_id
        self._start_locked(
            self._service.set_lss_sheet_id(self._character_id, sheet_id),
            lambda task: self._on_write_done(task, "идентификатор листа LSS"),
        )

    def _on_open_sheet(self) -> None:
        QDesktopServices.openUrl(QUrl(lss_sheet_url(self._sheet.text())))

    def _on_write_done(self, task: asyncio.Task, what: str) -> None:
        if self._outcome(task, f"сохранение поля «{what}»") is _TASK_FAILED and (
            not task.cancelled()
        ):
            self._show_notice(
                f"Не удалось сохранить поле «{what}». Значение в поле осталось, "
                "повторите изменение; подробности — в журнале приложения."
            )

    # ── the LSS file doors (task 9.4; spec dnd-character-import) ─────────────

    def _on_overwrite_clicked(self) -> None:
        """«Перезаписать из файла LSS…»: pick the file, then the target is
        THIS card's character — the explicit person, never a name match
        (spec «сопоставления по имени нет»). The service answers
        NEEDS_CONFIRMATION for the question box; the re-request carries the
        very bytes of the first read, not a re-read of a file the master may
        have edited in between (the datasets importer's discipline)."""
        path, _selected = QFileDialog.getOpenFileName(
            self,
            IMPORT_OVERWRITE_TEXT,
            "",
            CHARACTER_FILE_FILTER,
            # L1 (NRI-0014): always the Russian Qt panel, never the native one.
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return  # the отвод is a no-op — the service was never approached
        try:
            content = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self._show_notice(f"Не удалось прочитать файл «{path}»: {exc}")
            return
        self._start_locked(
            self._importer.import_character(content, character_id=self._character_id),
            lambda task, _bytes=content: self._on_precheck_done(task, _bytes),
        )

    def _on_precheck_done(self, task: asyncio.Task, content: str) -> None:
        """The unconfirmed request answered: the report's errors refuse
        first, only a clean document earns the question box (the master is
        never asked to confirm an import that would fail anyway)."""
        outcome = self._outcome(task, "предпроверка импорта персонажа")
        if outcome is _TASK_FAILED:
            if not task.cancelled():
                self._show_notice(
                    "Не удалось проверить файл персонажа. Подробности — в "
                    "журнале приложения; повторите выбор файла."
                )
            return
        if outcome.status is CharacterImportStatus.NEEDS_CONFIRMATION:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(IMPORT_OVERWRITE_TEXT)
            box.setText(outcome.message)
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            box.setDefaultButton(QMessageBox.StandardButton.No)
            self._overwrite_confirm_box = box
            box.finished.connect(
                lambda result, _bytes=content: self._on_overwrite_answered(result, _bytes)
            )
            box.show()
            return
        # Unreachable by contract (an unconfirmed target never gets past the
        # gate) — but the honest answer is printed, not swallowed.
        self._report_import_outcome(outcome)

    def _on_overwrite_answered(self, result: int, content: str) -> None:
        """Yes re-requests the very bytes under confirmation; any other
        answer is the spec's бездействие (scenario «Перезапись требует
        подтверждения» already held its promise: nothing was touched)."""
        self._overwrite_confirm_box = None
        if result != QMessageBox.StandardButton.Yes:
            return
        self._start_locked(
            self._importer.import_character(
                content, character_id=self._character_id, confirmed=True
            ),
            self._on_import_done,
        )

    def _on_import_done(self, task: asyncio.Task) -> None:
        outcome = self._outcome(task, "импорт персонажа из файла LSS")
        if outcome is _TASK_FAILED:
            if not task.cancelled():
                self._show_notice(
                    "Импорт персонажа не завершился. Подробности — в журнале "
                    "приложения; поля карточки остались как были."
                )
            return
        self._report_import_outcome(outcome)

    def _report_import_outcome(self, outcome: "CharacterImportOutcome") -> None:
        """Every branch gets its box (the datasets sheet's tree, restated
        for the card): refusal with the report lines, success with the
        warnings that accompanied it, the reload of the tab after a write."""
        # Lazy: the refusal box is the only branch that needs the sheet's
        # rendering helper; the tab must not drag the sheet module in to open.
        from app.dd.presentation.datasets_sheet import report_lines

        if outcome.status is CharacterImportStatus.BLOCKED:
            lines = (
                "\n".join(report_lines(outcome.report))
                if outcome.report is not None
                else ""
            )
            body = f"Импорт отклонён — отчёт проверки:\n{lines}" if lines else outcome.message
            self._show_notice(body)
            return
        if outcome.status is CharacterImportStatus.NEEDS_CONFIRMATION:
            # The same belt as above: a confirmed request does not ask twice.
            self._show_notice(outcome.message)
            return
        body = outcome.message
        warnings = outcome.report.warnings if outcome.report is not None else ()
        if warnings:
            body += "\nПредупреждения:\n" + "\n".join(
                f"{issue.path} — {issue.message}" for issue in warnings
            )
        self._show_notice(body, QMessageBox.Icon.Information)
        # The tab's own face just changed wholesale (fields, level, blocks) —
        # reload it through the lock; the kernel card body repaints on reopen
        # (its fields are the kernel's, not this tab's surface).
        self.request_refresh()

    def _on_save_raw_clicked(self) -> None:
        """«Сохранить исходный файл…»: the stored snapshot goes back to disk
        byte-for-byte (spec scenario «Файл можно забрать обратно») — never a
        reassembly from our fields."""
        path, _selected = QFileDialog.getSaveFileName(
            self,
            SAVE_RAW_TEXT,
            "character.json",
            CHARACTER_FILE_FILTER,
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        self._start_locked(
            self._importer.save_raw_document(self._character_id, path),
            self._on_save_raw_done,
        )

    def _on_save_raw_done(self, task: asyncio.Task) -> None:
        outcome = self._outcome(task, "сохранение исходного файла персонажа")
        if outcome is _TASK_FAILED:
            if not task.cancelled():
                self._show_notice(
                    "Не удалось записать файл на диск. Подробности — в журнале "
                    "приложения; повторите выбор места сохранения."
                )
            return
        if outcome is False:
            self._show_notice(
                "Для этого персонажа ещё не импортирован файл LSS — сохранить "
                "нечего; импортируйте файл через «Перезаписать из файла LSS…»."
            )
            return
        self._show_notice(
            "Исходный файл сохранён на диск байт-в-байт, как он был импортирован.",
            QMessageBox.Icon.Information,
        )

    # ── the LSS export door (add-dnd-lss-generation task 5.3) ────────────────

    def _on_export_clicked(self) -> None:
        """«Экспорт для LSS…»: the document is collected from the CURRENT
        card state (the builder's door, design Д4) — not from the stored raw
        file, which is «Сохранить исходный файл…»'s whole subject. The file
        panel is the system door (DontUseNativeDialog, L1/NRI-0014); the
        отвод is a no-op: no document is built, nothing on disk or in the
        card moves (spec scenario «Сохранение отменено»)."""
        path, _selected = QFileDialog.getSaveFileName(
            self,
            EXPORT_FOR_LSS_TEXT,
            "character.json",
            CHARACTER_FILE_FILTER,
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        self._start_locked(
            self._document_builder.export_document(self._character_id, path),
            self._on_export_done,
        )

    def _on_export_done(self, task: asyncio.Task) -> None:
        outcome = self._outcome(task, "экспорт персонажа для LSS")
        if outcome is _TASK_FAILED:
            if not task.cancelled():
                self._show_notice(
                    "Не удалось собрать и записать файл для LSS. Карточка и "
                    "сохранённый файл персонажа не изменены; подробности — в "
                    "журнале приложения; повторите выбор места сохранения."
                )
            return
        self._show_notice(
            "Файл для LSS записан: документ собран из текущего состояния "
            "карточки, а не из сохранённого исходного файла.",
            QMessageBox.Icon.Information,
        )


@dataclass(frozen=True)
class _SpellCandidate:
    """One spell the «Заклинания» tab can bind right now: the pair it will
    store, the name it will snapshot, the origin it prints."""

    source_key: str
    slug: str
    name: str
    origin: str


class DndSpellsTabFrame(_LockedFrame):
    """The «Заклинания» tab: bindings, manual add from the connected
    dictionaries, removal (task 8.3; spec «Таб “Заклинания” с привязками»).

    A binding is the pair «source + slug» plus the name snapshot — the row
    resolves its origin label through the two read doors (the SRD sets'
    spell-slug lists first, the game's grimoires second) and prints
    «источник не подключён» when neither answers (spec: the same mark as the
    D&D-tab links). The candidate list is capped and filterable: an SRD set
    alone carries hundreds of slugs, and a wall of buttons is not a working
    surface."""

    #: Rows rendered from the candidate list before the filter is asked for.
    CANDIDATE_ROW_LIMIT = 50

    def __init__(
        self,
        *,
        character_id: int,
        service: "DndCharacterExtensionService",
        dataset_index: "DatasetIndexService",
        grimoire_index: "GrimoireIndexService | None",
        run_locked: Callable[[Coroutine], asyncio.Task],
        parent=None,
    ) -> None:
        super().__init__(run_locked, parent)
        self._character_id = character_id
        self._service = service
        self._index = dataset_index
        self._grimoire = grimoire_index
        self._links: tuple[DdSpellLink, ...] = ()
        self._snap: "IndexSnapshot | None" = None
        self._gsnap = _empty_grimoire_snapshot()
        self._candidates: tuple[_SpellCandidate, ...] = ()

        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setObjectName("ddSpellsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget(scroll)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)

        content_layout.addWidget(self._header("Привязанные заклинания"))
        # The two hosts are built once and rebuilt in place: the filter keeps
        # its text across a write-reload (the reader's needle survives their
        # own add).
        self._links_host = QWidget(content)
        self._links_host.setObjectName("ddSpellsLinksHost")
        self._links_layout = QVBoxLayout(self._links_host)
        self._links_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._links_host)

        content_layout.addWidget(self._header("Добавить из подключённых словарей"))
        self._filter = QLineEdit(content)
        self._filter.setObjectName("ddSpellsFilter")
        self._filter.setAccessibleName("Фильтр заклинаний")
        self._filter.setPlaceholderText("Фильтр по имени…")
        self._filter.textChanged.connect(lambda _text: self._render_candidates())
        content_layout.addWidget(self._filter)
        self._candidates_host = QWidget(content)
        self._candidates_host.setObjectName("ddSpellsCandidatesHost")
        self._candidates_layout = QVBoxLayout(self._candidates_host)
        self._candidates_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._candidates_host)
        content_layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.request_refresh()

    def request_refresh(self) -> None:
        self._start_locked(self._read_state(), self._on_loaded)

    # ── state (one locked read: links + both dictionary doors) ──────────────

    async def _read_state(self):
        links = await self._service.get_spell_links(self._character_id)
        snap = await self._index.snapshot()
        gsnap = (
            await self._grimoire.snapshot()
            if self._grimoire is not None
            else _empty_grimoire_snapshot()
        )
        return tuple(links), snap, gsnap

    def _on_loaded(self, task: asyncio.Task) -> None:
        outcome = self._outcome(task, "загрузка привязок заклинаний")
        if outcome is _TASK_FAILED:
            if task.cancelled():
                return  # the released tab answers nothing
            self._show_notice(
                "Не удалось загрузить привязки заклинаний. Подробности — в "
                "журнале приложения; повторите, закрыв и открыв карточку."
            )
            return
        self._links, self._snap, self._gsnap = outcome
        self._render()

    # ── rendering ────────────────────────────────────────────────────────────

    @staticmethod
    def _clear(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _header(self, caption: str) -> QLabel:
        label = QLabel(caption)
        label.setObjectName("ddSpellsHeader")
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    def _render(self) -> None:
        self._clear(self._links_layout)
        if self._links:
            for link in self._links:
                self._links_layout.addWidget(self._link_row(link))
        else:
            hint = QLabel("Пока нет ни одного привязанного заклинания.")
            hint.setObjectName("ddSpellsEmpty")
            hint.setWordWrap(True)
            self._links_layout.addWidget(hint)
        self._render_candidates()

    def _link_row(self, link: "DdSpellLink") -> QWidget:
        """One binding: name + origin (or the dead-source mark) + «Снять»."""
        row = QWidget(self)
        row.setObjectName("ddSpellsRow")
        name = link.snapshot_name or link.slug
        origin = self._origin_of(link)
        caption = (
            f"{name} · {origin}" if origin else f"{name} — {SOURCE_UNAVAILABLE_NOTE}"
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(caption)
        label.setObjectName("ddSpellsRowName")
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        button = QPushButton("Снять", row)
        button.setObjectName("ddSpellsRemove")
        button.clicked.connect(
            lambda _checked=False, _link=link: self._on_remove(_link)
        )
        layout.addWidget(button)
        return row

    def _origin_of(self, link: "DdSpellLink") -> str:
        """The label naming which connected dictionary holds the binding
        right now; empty = neither door answers, and the caption carries the
        «источник не подключён» mark instead (spec: the same mark as the
        «D&D»-tab links)."""
        if self._snap is not None and link.slug in self._snap.slugs.get(
            link.source_key, ()
        ):
            return self._snap.titles.get(link.source_key, link.source_key)
        if self._gsnap.spell(link.source_key, link.slug) is not None:
            return self._gsnap.titles.get(link.source_key, link.source_key)
        return ""

    def _collect_candidates(self, needle: str) -> tuple[_SpellCandidate, ...]:
        """The bindable spells of the connected dictionaries (the SRD sets'
        slugs first, the grimoires' spells after), already-bound pairs
        removed, the filter applied to name and slug — the spec's «ручное
        добавление из подключённых словарей» in list form."""
        lowered = needle.strip().lower()
        bound = {(link.source_key, link.slug) for link in self._links}
        candidates: list[_SpellCandidate] = []
        if self._snap is not None:
            for dataset_id in self._snap.ids:
                title = self._snap.titles.get(dataset_id, dataset_id)
                for slug in self._snap.slugs.get(dataset_id, ()):
                    if (dataset_id, slug) in bound:
                        continue
                    name = self._humanize(slug)
                    if lowered and lowered not in name.lower() and lowered not in slug:
                        continue
                    candidates.append(_SpellCandidate(dataset_id, slug, name, title))
        for grimoire_id in self._gsnap.ids:
            title = self._gsnap.titles.get(grimoire_id, grimoire_id)
            for slug, spell in self._gsnap.spells.get(grimoire_id, {}).items():
                if (grimoire_id, slug) in bound:
                    continue
                if lowered and lowered not in spell.name.lower() and lowered not in slug:
                    continue
                candidates.append(_SpellCandidate(grimoire_id, slug, spell.name, title))
        return tuple(candidates)

    @staticmethod
    def _humanize(slug: str) -> str:
        """The SRD name of a slug — the reference source's mechanical
        humanization, borrowed through its door so both surfaces spell the
        same spell the same way (one knowledge, one place)."""
        from app.dd.presentation.reference_source import humanize_spell_slug

        return humanize_spell_slug(slug)

    def _render_candidates(self) -> None:
        layout = self._candidates_layout
        self._clear(layout)
        self._candidates = self._collect_candidates(self._filter.text())
        if not self._candidates:
            hint = QLabel(
                "Нет подключённых словарей или ничего не нашлось по фильтру."
            )
            hint.setObjectName("ddSpellsNoCandidates")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            return
        shown = self._candidates[: self.CANDIDATE_ROW_LIMIT]
        for candidate in shown:
            button = QPushButton(
                button_caption(f"Добавить: {candidate.name} · {candidate.origin}"),
                self,
            )
            button.setObjectName("ddSpellsCandidate")
            button.clicked.connect(
                lambda _checked=False, _candidate=candidate: self._on_add(_candidate)
            )
            layout.addWidget(button)
        hidden = len(self._candidates) - len(shown)
        if hidden > 0:
            cap = QLabel(
                f"Показаны первые {self.CANDIDATE_ROW_LIMIT}; ещё {hidden} — "
                "уточните фильтр."
            )
            cap.setObjectName("ddSpellsCandidateCap")
            layout.addWidget(cap)

    # ── writes (write + reload inside ONE locked coroutine) ──────────────────

    def _on_add(self, candidate: _SpellCandidate) -> None:
        link: DdSpellLink = DdSpellLink(
            source_key=candidate.source_key,
            slug=candidate.slug,
            snapshot_name=candidate.name,
        )
        self._start_locked(
            self._add_link(link),
            lambda task: self._on_write(task, "привязка заклинания"),
        )

    async def _add_link(self, link: "DdSpellLink"):
        await self._service.add_spell_link(self._character_id, link)
        return await self._read_state()

    def _on_remove(self, link: "DdSpellLink") -> None:
        self._start_locked(
            self._remove_link(link),
            lambda task: self._on_write(task, "снятие привязки заклинания"),
        )

    async def _remove_link(self, link: "DdSpellLink"):
        await self._service.remove_spell_link(
            self._character_id, link.source_key, link.slug
        )
        return await self._read_state()

    def _on_write(self, task: asyncio.Task, what: str) -> None:
        outcome = self._outcome(task, what)
        if outcome is _TASK_FAILED:
            if not task.cancelled():
                self._show_notice(
                    f"Не удалось выполнить действие ({what}). Повторите; "
                    "подробности — в журнале приложения."
                )
            return
        self._links, self._snap, self._gsnap = outcome
        self._render()
