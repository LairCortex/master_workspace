"""The module tab plumbing and the «Заклинания» frame of a character card
(add-dnd-game-face tasks 8.2/8.3; the «D&D» tab frame retired by
dd-card-redesign task 5.5 — its lists, level and doors moved to the kernel
«Основное» screen through the block channel, its history picker to
«Личность»).

What survives here is shared by every module tab of every source:

* :class:`_LockedFrame` — the base the module tabs grow from (the encounter
  tab, «Способности», «Личность», «Заклинания»): reads and writes ride the
  connector's session lock through the injected ``run_locked`` (a second
  ``run_locked`` from inside a locked task would deadlock, so a flow that
  writes and reloads does both INSIDE one coroutine and renders from its
  result), a failed load or write is a modeless Russian box (never a nested
  loop, the PR-010 posture of every live box in this codebase), and a
  released tab answers nothing (``release_tab`` cancels the in-flight tasks);
* the shared captions and doors (the LSS file row, the browser door, the
  dead-source mark, the file filter) — printed today by the «Основное» block
  controller and the spell/feats tabs, one place each;
* :class:`DndSpellsTabFrame` — the «Заклинания» tab: bindings, manual add
  from the connected dictionaries, removal, and the spell-slot grid
  (dd-card-redesign task 5.4).

The tabs are plain Qt widgets (the card body is a QML island; a module tab
is a native widget the host overlays on the body slot), so their
accessibility follows the kernel's contract through Qt's own widget bridges:
every control is штатный (QComboBox/QLineEdit/QPushButton), a control whose
caption is not its own text carries that caption as ``accessibleName``, and
object names (``ddSpells*`` etc.) give the offscreen tests their addresses —
the same posture the module's sheets keep.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Coroutine

from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.dd.application.grimoire_index_service import GrimoireIndexSnapshot
from app.dd.domain.character import DdSpellLink
from app.dd.domain.character_mechanics import (
    SLOT_COUNT_MAX,
    SLOT_COUNT_MIN,
    SLOT_LEVEL_MAX,
    SLOT_LEVEL_MIN,
)
from app.dd.presentation.captions import button_caption

if TYPE_CHECKING:
    from app.dd.application.dataset_index_service import (
        DatasetIndexService,
        IndexSnapshot,
    )
    from app.dd.application.dnd_character_extension_service import (
        DndCharacterExtensionService,
    )
    from app.dd.application.grimoire_index_service import GrimoireIndexService

#: The caption of the «link unset» item of every reference picker.
UNSET_ITEM = "— не выбрано"

#: The three character tabs' shared refusal of the unsaved record (dd-card-
#: redesign, checkpoint-2 audit; spec «Новая карточка с пустыми разделами»):
#: the tabs stand on a fresh card, their sections are honestly empty, and
#: every write names the save that must happen first.
UNSAVED_CHARACTER_REFUSAL = (
    "Персонаж ещё не сохранён — раздел заработает после сохранения карточки."
)

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

#: The two file doors of the LSS row (task 9.4; spec dnd-character-import
#: «Перезаписать из файла LSS…» из карточки) — printed since dd-card-redesign
#: by the «Основное» doors block. Captions name the action and
#: the format; the creation half of the spec's two entries lives on the
#: module's menu (:attr:`app.dd.presentation.section.
#: DndWindowSection.character_import_requested`) — a fresh card has no id
#: and no module tab to hang this row on.
IMPORT_OVERWRITE_TEXT = "Перезаписать из файла LSS…"
SAVE_RAW_TEXT = "Сохранить исходный файл…"
#: The browser door (spec dnd-character-extension «пустой идентификатор
#: скрывает кнопку браузера»): shown while the stored sheet id says one.
#: Public: since dd-card-redesign the «Основное» doors row of the block
#: controller prints it, the old «D&D» tab is retired.
OPEN_IN_BROWSER_TEXT = "Открыть в браузере"
#: The third file door, half of add-dnd-lss-generation task 5.3 (spec
#: dnd-character-export «Кнопка „Экспорт для LSS…“»): the document is rebuilt
#: from the CURRENT card state (name, links, level, blocks, spell slugs) —
#: never a copy of the stored raw file, which is what «Сохранить исходный
#: файл…» is for. The door works without any AI configuration (the builder
#: never touches the network).
EXPORT_FOR_LSS_TEXT = "Экспорт для LSS…"
#: Вход ИИ-дозаполнения (add-dnd-lss-generation task 7.3): тот же лист
#: персонажа в режиме дозаполнения, открывается с «Основного» карточки.
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
        """The host's release door (task 7.2): no callback survives the tab.

        The cancel rides one ``call_soon`` tick: a read that has not taken
        its first step yet would otherwise be cancelled as a never-started
        task, orphaning its coroutine object — the collector then prints a
        never-awaited RuntimeWarning for a cancellation this release asked
        for on purpose. One tick later the task has started (and the wrapper
        disposes of the coroutine honestly, see ``ApplicationWiring
        ._run_locked``) or has finished whole. A loop that is no longer
        running (teardown races) gets the direct cancel — the previous
        posture, nothing left to schedule onto."""
        for task in list(self._tasks):
            if task.done():
                continue
            try:
                loop = task.get_loop()
            except NotImplementedError:  # pragma: no cover — taskless future
                loop = None
            if loop is not None and loop.is_running():
                loop.call_soon(task.cancel)
            else:
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
    dictionaries, removal (task 8.3; spec «Таб “Заклинания” с привязками»)
    and, under the binding list, the spell-slot grid of levels 1…9
    (dd-card-redesign task 5.4; spec dnd-character-mechanics «Ячейки
    заклинаний — сетка уровней»).

    A binding is the pair «source + slug» plus the name snapshot — the row
    resolves its origin label through the two read doors (the SRD sets'
    spell-slug lists first, the game's grimoires second) and prints
    «источник не подключён» when neither answers (spec: the same mark as the
    D&D-tab links). The candidate list is capped and filterable: an SRD set
    alone carries hundreds of slugs, and a wall of buttons is not a working
    surface. The slot counts commit per field on editingFinished (the same
    immediate module-tab posture as every other module write; the numbers
    ride the mechanics column), the empty field is «не задано»."""

    #: Rows rendered from the candidate list before the filter is asked for.
    CANDIDATE_ROW_LIMIT = 50

    def __init__(
        self,
        *,
        character_id: int | None,
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
        #: stored slot counts (level → count), the commit compares against
        self._slots: dict[int, int] = {}
        self._slot_edits: dict[int, QLineEdit] = {}

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

        # The slot grid, «под списком» verbatim (spec scenario «Ячейки под
        # списком»): nine rows, an editable 0…99 per level, the empty field
        # reads «не задано». The QIntValidator is the interactive gate; the
        # commit below is the belt for anything pasted around it.
        content_layout.addWidget(self._header("Ячейки заклинаний"))
        slots_grid = QGridLayout()
        slots_grid.setObjectName("ddSpellsSlotsGrid")
        for row, level in enumerate(range(SLOT_LEVEL_MIN, SLOT_LEVEL_MAX + 1)):
            caption = QLabel(f"{level}-й уровень")
            caption.setObjectName(f"ddSpellsSlotLabel_{level}")
            slots_grid.addWidget(caption, row, 0)
            edit = QLineEdit(content)
            edit.setObjectName(f"ddSpellsSlot_{level}")
            edit.setAccessibleName(f"Ячейки {level} уровня")
            edit.setPlaceholderText("не задано")
            edit.setValidator(
                QIntValidator(SLOT_COUNT_MIN, SLOT_COUNT_MAX, edit)
            )
            edit.editingFinished.connect(
                lambda _level=level, _edit=edit: self._on_slot_edited(
                    _level, _edit.text()
                )
            )
            self._slot_edits[level] = edit
            slots_grid.addWidget(edit, row, 1)
        content_layout.addLayout(slots_grid)

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
        # The character half of the read rides the id; the unsaved card (the
        # empty id, checkpoint-2 audit) reads the dictionary doors alone so
        # the candidate wall and the slot ladder are honestly alive, while
        # no binding and no slot exists yet. No service door is knocked.
        self._start_locked(self._read_state(), self._on_loaded)

    # ── state (one locked read: links + both dictionary doors) ──────────────

    async def _read_state(self):
        if self._character_id is None:
            snap = await self._index.snapshot()
            gsnap = (
                await self._grimoire.snapshot()
                if self._grimoire is not None
                else _empty_grimoire_snapshot()
            )
            return (), {}, snap, gsnap
        links = await self._service.get_spell_links(self._character_id)
        mechanics = await self._service.get_mechanics(self._character_id)
        snap = await self._index.snapshot()
        gsnap = (
            await self._grimoire.snapshot()
            if self._grimoire is not None
            else _empty_grimoire_snapshot()
        )
        return tuple(links), dict(mechanics.spell_slots), snap, gsnap

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
        self._links, self._slots, self._snap, self._gsnap = outcome
        self._render_slots()
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

    def _render_slots(self) -> None:
        """Print the stored counts (setText fires no editingFinished — the
        commit channel is user gestures only); an absent level prints the
        empty field, the placeholder says «не задано»."""
        for level, edit in self._slot_edits.items():
            count = self._slots.get(level)
            edit.setText("" if count is None else str(count))

    def _on_slot_edited(self, level: int, text: str) -> None:
        """One field's commit: the whole map is rewritten with this level's
        new value (empty drops it — «не задано»); an untouched field is no
        transaction, a number past the validator's 0…99 is refused here,
        the belt under the interactive gate (the service gates once more)."""
        if self._character_id is None:
            self._show_notice(UNSAVED_CHARACTER_REFUSAL)
            return
        stripped = text.strip()
        updated = dict(self._slots)
        if stripped == "":
            updated.pop(level, None)
        else:
            try:
                count = int(stripped)
            except ValueError:
                count = -1
            if not SLOT_COUNT_MIN <= count <= SLOT_COUNT_MAX:
                self._show_notice(
                    "Ячейки заклинаний — целое число от 0 до 99 (или пусто). "
                    "Значение не сохранено."
                )
                return
            updated[level] = count
        if updated == dict(self._slots):
            return
        self._start_locked(
            self._set_slots(updated),
            lambda task: self._on_write(task, "сохранение ячеек заклинаний"),
        )

    async def _set_slots(self, slots: dict[int, int]):
        await self._service.set_spell_slots(self._character_id, slots)
        return await self._read_state()

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
        if self._character_id is None:
            self._show_notice(UNSAVED_CHARACTER_REFUSAL)
            return
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
        if self._character_id is None:
            self._show_notice(UNSAVED_CHARACTER_REFUSAL)
            return
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
        self._links, self._slots, self._snap, self._gsnap = outcome
        self._render_slots()
        self._render()
