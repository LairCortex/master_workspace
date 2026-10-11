"""The «Встреча» tab of the event card (add-dnd-game-face task 11.1; spec
dnd-encounters «Редактор встречи — таб „Встреча“ в карточке события»).

Design Д10: the kernel draws the strip and owns the lifecycle; the module
paints inside — a plain Qt widget the host overlays on the card's body slot,
штатные controls with object names for the offscreen tests and
``accessibleName`` captions where a control's caption is not its own text
(the character-tab frames' posture).

Unlike the character tabs (every field writes the moment it changes), the
encounter is edited STAGED and written by the card's common Save button
(spec: «сохранение — общим сохранением карточки события»): the connector
awaits the frame's :meth:`save_tab` inside its already-locked save task, so
this coroutine must NOT re-enter the lock (no ``run_locked`` here — the
service opens the one transaction the write needs).

Failure posture of the load is the character tabs' (a modeless Russian box,
the card keeps working); :meth:`release_tab` (the host's door) cancels the
in-flight load. A save while the stored face was never read is a journalled
no-op: writing what the frame does not know would delete an encounter the
master never saw.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable, Coroutine

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.dd.domain.encounter import (
    COUNT_MAX,
    EncounterEntry,
)
from app.dd.presentation.character_tab_frames import (
    UNSET_ITEM,
    _LockedFrame,
    _TASK_FAILED,
)

if TYPE_CHECKING:
    from app.dd.application.dd_encounter_service import DdEncounterService
    from app.dd.application.monster_service import DdMonsterService
    from app.dd.presentation.dd_encounter_source import DndEncounterSource

#: Journal name of the frame.
_FRAME_LOGGER = "app.dd.encounter_tab"

#: Caption of the add button (the staged row appears with it).
ADD_ROW_TEXT = "Добавить монстра"
#: Caption of the per-row removal button (staged — like everything here, it
#: reaches the storage only through the card's common Save).
REMOVE_ROW_TEXT = "Убрать"


class DndEncounterTabFrame(_LockedFrame):
    """The «Встреча» tab: «монстр × количество» rows + note, staged edits.

    The picker offers the bestiary (spec «выбор монстра из бестиария»); the
    name the composition stores is the snapshot the combo shows at write
    time. An EMPTY composition saved through the card means «no encounter»
    (task 11.1) — the service drops the overlay row and the ladder mark
    leaves with it.
    """

    def __init__(
        self,
        *,
        event_id: int,
        encounter_service: "DdEncounterService",
        monster_service: "DdMonsterService",
        source: "DndEncounterSource",
        run_locked: Callable[[Coroutine], asyncio.Task],
        parent=None,
    ) -> None:
        super().__init__(run_locked, parent)
        self._event_id = event_id
        self._encounters = encounter_service
        self._monsters_service = monster_service
        self._source = source
        # The staged rows (combo, spin) in display order — the widget list IS
        # the composition editor until the card's Save reads it.
        self._rows: list[tuple[QComboBox, QSpinBox]] = []
        # (id, name) of every bestiary monster — refreshed with each load;
        # the row picker prints exactly this list.
        self._monster_items: list[tuple[int, str]] = []
        # True once the stored face (or its honest absence) reached the
        # widgets — the precondition of ANY write (see save_tab).
        self._loaded = False
        # Still True while the first load task has not returned (the belt
        # under _loaded: a never-read tab must not write).
        self._load_pending = True

        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setObjectName("ddEncounterScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget(scroll)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)

        content_layout.addWidget(self._header("Состав встречи"))
        self._rows_host = QWidget(content)
        self._rows_host.setObjectName("ddEncounterRowsHost")
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._rows_host)
        self._empty_hint = QLabel(
            "Состава пока нет. Пустая встреча не сохраняется: без строк "
            "состава событие встречи не несёт."
        )
        self._empty_hint.setObjectName("ddEncounterEmpty")
        self._empty_hint.setWordWrap(True)
        content_layout.addWidget(self._empty_hint)

        add_row = QHBoxLayout()
        self._add = QPushButton(ADD_ROW_TEXT, content)
        self._add.setObjectName("ddEncounterAdd")
        self._add.clicked.connect(self._on_add_row)
        add_row.addWidget(self._add)
        add_row.addStretch()
        content_layout.addLayout(add_row)

        content_layout.addWidget(self._header("Заметка"))
        self._note = QPlainTextEdit(content)
        self._note.setObjectName("ddEncounterNote")
        self._note.setAccessibleName("Заметка встречи")
        content_layout.addWidget(self._note, 1)
        content_layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.request_refresh()

    @staticmethod
    def _header(caption: str) -> QLabel:
        label = QLabel(caption)
        label.setObjectName("ddEncounterHeader")
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    # ── load (one locked read: overlay + bestiary) ───────────────────────────

    def request_refresh(self) -> None:
        """Read the stored overlay and the bestiary through the lock."""
        self._start_locked(self._load(), self._on_loaded)

    async def _load(self):
        encounter = await self._encounters.get_encounter(self._event_id)
        monsters = [
            (monster.id, monster.name)
            for monster in await self._monsters_service.list_monsters()
        ]
        return encounter, monsters

    def _on_loaded(self, task: asyncio.Task) -> None:
        outcome = self._outcome(task, "загрузка встречи")
        self._load_pending = False
        if outcome is _TASK_FAILED:
            if task.cancelled():
                return  # the released tab answers nothing
            self._show_notice(
                "Не удалось загрузить встречу. Подробности — в журнале "
                "приложения; повторите, закрыв и открыв карточку."
            )
            return
        encounter, monsters = outcome
        self._fill(encounter, monsters)

    def _fill(self, encounter, monsters: list[tuple[int, str]]) -> None:
        """Publish the frame: the bestiary cached, the composition rows
        rebuilt from the stored entries, the note verbatim. A stored row
        naming a monster the bestiary no longer lists is journalled and
        dropped (the product never deletes monsters; a ghost row the picker
        cannot re-pick would only refuse the next save)."""
        self._monster_items = monsters
        # The face is built once: the host releases this frame with the tab
        # and builds a fresh one on the next open (same posture as the
        # character tabs), so the layout is empty here by construction —
        # there is no second fill to clear.
        self._rows = []
        if encounter is not None:
            for entry in encounter.entries:
                self._append_row(selected_monster=entry.monster_id, count=entry.count)
                if self._rows[-1][0].currentData() != entry.monster_id:
                    # findData missed: the monster left the bestiary.
                    logging.getLogger(_FRAME_LOGGER).warning(
                        "dd encounter: монстр %s не найден в бестиарии — "
                        "строка состава пропущена",
                        entry.monster_id,
                    )
                    self._pop_last_row()
            self._note.setPlainText(encounter.note)
        else:
            self._note.clear()
        self._loaded = True
        self._update_empty_hint()

    # ── staged row editing (no write before the card's Save) ─────────────────

    def _on_add_row(self) -> None:
        self._append_row()
        self._update_empty_hint()

    def _append_row(
        self, selected_monster: int | None = None, count: int = 1
    ) -> None:
        row = QWidget(self._rows_host)
        row.setObjectName("ddEncounterRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        combo = QComboBox(row)
        combo.setObjectName("ddEncounterMonster")
        combo.setAccessibleName("Монстр")
        combo.addItem(UNSET_ITEM, None)
        for monster_id, name in self._monster_items:
            combo.addItem(name, monster_id)
        if selected_monster is None:
            # A fresh row starts on the FIRST bestiary monster (a picked-up
            # «+» is a real intent, not a trap — UNSET stays reachable as
            # the honest zero-choice the gate refuses); on an empty bestiary
            # the combo has nothing else and the row rides on UNSET.
            combo.setCurrentIndex(1 if self._monster_items else 0)
        else:
            # A stored monster the list no longer holds stays on UNSET —
            # _fill drops that ghost row.
            index = combo.findData(selected_monster)
            combo.setCurrentIndex(0 if index < 0 else index)
        layout.addWidget(combo, 1)

        spin = QSpinBox(row)
        spin.setObjectName("ddEncounterCount")
        spin.setAccessibleName("Количество")
        spin.setRange(1, COUNT_MAX)
        spin.setValue(max(1, min(count, COUNT_MAX)))
        layout.addWidget(spin)

        remove = QPushButton(REMOVE_ROW_TEXT, row)
        remove.setObjectName("ddEncounterRemove")
        remove.clicked.connect(lambda _checked=False, _row=row: self._on_remove_row(_row))
        layout.addWidget(remove)

        self._rows.append((combo, spin))
        self._rows_layout.addWidget(row)

    def _on_remove_row(self, row: QWidget) -> None:
        for index, (combo, _spin) in enumerate(self._rows):
            if combo.parent() is row:
                self._rows.pop(index)
                row.setParent(None)
                row.deleteLater()
                self._update_empty_hint()
                return

    def _pop_last_row(self) -> None:
        """Undo the just-appended row (the ghost-monster path of _fill)."""
        self._rows.pop()
        item = self._rows_layout.takeAt(self._rows_layout.count() - 1)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()

    def _update_empty_hint(self) -> None:
        self._empty_hint.setVisible(not self._rows)

    # ── the card's Save door (connector-side, ALREADY UNDER THE LOCK) ────────

    async def save_tab(self) -> None:
        """The card's common Save writes the staged composition through this
        door: the connector calls and awaits it inside its locked save task
        (the door's contract — see the module docstring).

        An unloaded tab writes NOTHING (a journalled no-op): the frame may
        not delete an overlay it never read."""
        if not self._loaded:
            logging.getLogger(_FRAME_LOGGER).warning(
                "dd encounter: надстройка не записана — её сохранённое лицо "
                "не было прочитано (загрузка в процессе: %s)",
                self._load_pending,
            )
            return
        entries: list[EncounterEntry] = []
        for combo, spin in self._rows:
            monster_id = combo.currentData()
            entries.append(
                EncounterEntry(
                    # The UNSET row rides on as monster_id = -1: the domain
                    # gate turns it into the Russian refusal the card prints.
                    monster_id=-1 if monster_id is None else int(monster_id),
                    count=spin.value(),
                    name_snapshot=combo.currentText(),
                )
            )
        encounter = await self._encounters.save_encounter(
            self._event_id, entries, self._note.toPlainText()
        )
        self._source.apply_saved(self._event_id, encounter is not None)
