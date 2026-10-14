"""The «Личность» tab of a character card (dd-card-redesign task 5.3; spec
dnd-character-mechanics «Вкладка „Личность“ — набор полей»).

Three families of fields, two storages (design Д6 — no second store):

* **Предыстория** — the dataset LINK of LINK_SLOTS, the class link's whole
  mechanism restated (UNSET item, «имя · датасет» captions, the dead triple
  re-shown as «имя — источник не подключён» and re-savable verbatim);
* **Мировоззрение** — the fixed nine of the domain table plus «не задано»,
  the combo itself is the gate (manual input is structurally impossible,
  spec «ручного ввода нет»), written through ``set_alignment``;
* the six one-line and eight multi-line texts — ordinary text without
  value gates, stored as stable Russian block names in the existing
  ``text_blocks`` column through the service's one-key doors. The long
  fields commit on focus-out (a multi-line field has no Enter to commit
  on), the short ones on editingFinished; an untouched field losing focus
  is no transaction.

The frame keeps the module tab's posture: writes are immediate (no tab of
its own is staged for the card's Save), each is one locked operation, the
frame does NOT reload after a write — it remembers what it saved (the old
«D&D» tab's discipline: a reload would trample the master's in-flight
typing), and a failed write leaves the painted value with a modeless box.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.dd.domain.character import LINK_SLOTS, ReferenceLink
from app.dd.domain.character_mechanics import (
    ALIGNMENTS,
    PERSONALITY_LONG_FIELDS,
    PERSONALITY_SHORT_FIELDS,
)
from app.dd.presentation.character_tab_frames import (
    SOURCE_UNAVAILABLE_NOTE,
    UNSET_ITEM,
    UNSAVED_CHARACTER_REFUSAL,
    _LockedFrame,
    _TASK_FAILED,
)

if TYPE_CHECKING:
    from app.dd.application.dataset_index_service import (
        DatasetIndexService,
        IndexSnapshot,
    )
    from app.dd.application.dnd_character_extension_service import (
        DndCharacterExtensionService,
    )

#: The unset alignment item (spec: «плюс состояние „не задано“» — the
#: absence, never a tenth alignment).
ALIGNMENT_UNSET_ITEM = "— не задано"

BACKGROUND_SLOT = "background"


class _CommitOnBlurEdit(QPlainTextEdit):
    """A multi-line field with a commit trigger: Enter writes a line break,
    so the module's commit point is the focus leaving the field."""

    def __init__(self, on_commit: Callable[[], None], parent=None) -> None:
        super().__init__(parent)
        self._on_commit = on_commit

    def focusOutEvent(self, event) -> None:  # noqa: N802 — Qt naming
        super().focusOutEvent(event)
        self._on_commit()


class DndPersonalityTabFrame(_LockedFrame):
    """Background link, alignment, the «Личность» text fields."""

    def __init__(
        self,
        *,
        character_id: int | None,
        service: "DndCharacterExtensionService",
        dataset_index: "DatasetIndexService",
        record_labels: Mapping[str, str],
        run_locked: Callable[[Coroutine], asyncio.Task],
        parent=None,
    ) -> None:
        super().__init__(run_locked, parent)
        self._character_id = character_id
        self._service = service
        self._index = dataset_index
        # The background combo's caption rides the declared descriptor
        # (record_labels is keyed by the external TYPE key, LINK_SLOTS'
        # third field names it for the background slot).
        self._background_label = next(
            record_labels[type_key]
            for slot, _section, type_key in LINK_SLOTS
            if slot == BACKGROUND_SLOT
        )
        self._loading = False
        # What the frame believes is stored for the text fields (kept in
        # step with the writes it commits; never a full reload — see the
        # module docstring). The background combo needs no such memory:
        # currentIndexChanged fires only on a real change.
        self._blocks: dict[str, str] = {}

        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setObjectName("ddPersonalityScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget(scroll)
        # The Qt6 default growth (AllNonFixedFieldsGrow) already stretches
        # the line edits and the multi-line editors to the form's width.
        form = QFormLayout(content)

        self._background = QComboBox(content)
        self._background.setObjectName("ddPersonalityBackground")
        self._background.setAccessibleName(self._background_label)
        self._background.currentIndexChanged.connect(self._on_background_changed)
        form.addRow(self._background_label + ":", self._background)

        self._alignment = QComboBox(content)
        self._alignment.setObjectName("ddPersonalityAlignment")
        self._alignment.setAccessibleName("Мировоззрение")
        # index 0 is «не задано», index N the (N-1)-th alignment — the combo
        # is the nine-plus-absence gate, the service validates again.
        self._alignment.addItem(ALIGNMENT_UNSET_ITEM)
        for value in ALIGNMENTS:
            self._alignment.addItem(value)
        self._alignment.currentIndexChanged.connect(self._on_alignment_changed)
        form.addRow("Мировоззрение:", self._alignment)

        #: ascii key → the Russian block name it stores under (the tables
        #: are disjoint by construction, one map serves both families).
        self._captions: dict[str, str] = {}
        for key, caption in PERSONALITY_SHORT_FIELDS:
            self._captions[key] = caption
        for key, caption in PERSONALITY_LONG_FIELDS:
            self._captions[key] = caption

        self._short: dict[str, QLineEdit] = {}
        for key, caption in PERSONALITY_SHORT_FIELDS:
            field = QLineEdit(content)
            field.setObjectName(f"ddPersonalityShort_{key}")
            field.setAccessibleName(caption)
            field.editingFinished.connect(
                lambda _key=key, _field=field: self._commit(_key, _field.text())
            )
            self._short[key] = field
            form.addRow(caption + ":", field)

        self._long: dict[str, _CommitOnBlurEdit] = {}
        for key, caption in PERSONALITY_LONG_FIELDS:
            editor = _CommitOnBlurEdit(
                lambda _key=key: self._commit(_key), content
            )
            editor.setObjectName(f"ddPersonalityLong_{key}")
            editor.setAccessibleName(caption)
            editor.setFixedHeight(80)
            self._long[key] = editor
            form.addRow(caption, editor)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.request_refresh()

    # ── load ──────────────────────────────────────────────────────────────────

    def request_refresh(self) -> None:
        # The character half of the read rides the id; the unsaved card (the
        # empty id, checkpoint-2 audit) reads the dataset snapshot alone so
        # the background combo honestly lists its candidates, and prints the
        # stored-empty face for everything else. No service door is knocked.
        self._start_locked(self._read_all(), self._on_loaded)

    async def _read_all(self):
        snap = await self._index.snapshot()
        if self._character_id is None:
            from app.dd.domain.character import empty_ext
            from app.dd.domain.character_mechanics import empty_mechanics

            return empty_ext().links[BACKGROUND_SLOT], empty_mechanics().alignment, {}, snap
        ext = await self._service.get_ext(self._character_id)
        mechanics = await self._service.get_mechanics(self._character_id)
        blocks = await self._service.get_text_blocks(self._character_id)
        return ext.links[BACKGROUND_SLOT], mechanics.alignment, blocks, snap

    def _on_loaded(self, task: asyncio.Task) -> None:
        outcome = self._outcome(task, "загрузка «Личности»")
        if outcome is _TASK_FAILED:
            if task.cancelled():
                return  # the released tab answers nothing
            self._show_notice(
                "Не удалось загрузить поля «Личности». Подробности — в "
                "журнале приложения; повторите, закрыв и открыв карточку."
            )
            return
        link, alignment, blocks, snap = outcome
        self._blocks = dict(blocks)
        self._fill(link, alignment, snap)

    def _fill(
        self,
        link: ReferenceLink,
        alignment: "str | None",
        snap: "IndexSnapshot",
    ) -> None:
        """Publish the stored face. The text fields print verbatim (no
        gates, no normalization); the background combo rebuilds and re-enters
        a dead triple as the annotated item (the class picker's rule)."""
        self._loading = True
        try:
            combo = self._background
            combo.clear()
            combo.addItem(UNSET_ITEM, None)
            for dataset_id in snap.ids:
                title = snap.titles.get(dataset_id, dataset_id)
                for entry in snap.entries("backgrounds", dataset_id):
                    combo.addItem(
                        f"{entry.name} · {title}",
                        (dataset_id, entry.entry_id, entry.name),
                    )
            if link.is_set:
                wanted = (link.source_key, link.ref_id, link.snapshot_name)
                # The honest scan, not findData (the old tab's verified Qt
                # fact: QVariant does not compare Python tuples reliably).
                index = next(
                    (i for i in range(combo.count()) if combo.itemData(i) == wanted),
                    -1,
                )
                if index < 0:
                    combo.addItem(
                        f"{link.snapshot_name} — {SOURCE_UNAVAILABLE_NOTE}",
                        wanted,
                    )
                    index = combo.count() - 1
                combo.setCurrentIndex(index)
            else:
                combo.setCurrentIndex(0)
            self._alignment.setCurrentIndex(
                0
                if alignment is None or alignment not in ALIGNMENTS
                else ALIGNMENTS.index(alignment) + 1
            )
            for key, field in self._short.items():
                field.setText(self._blocks.get(self._captions[key], ""))
            for key, editor in self._long.items():
                editor.setPlainText(self._blocks.get(self._captions[key], ""))
        finally:
            self._loading = False

    # ── writes (immediate, the module tab's posture) ──────────────────────────

    def _refuse_unsaved(self) -> None:
        """The checkpoint-2 posture of a not-yet-saved character: the tab
        stands with empty sections, a write attempt names the save and the
        widget goes back to the stored empty face (the _loading belt keeps
        the combo rollback from re-entering this refusal)."""
        self._show_notice(UNSAVED_CHARACTER_REFUSAL)
        self._loading = True
        try:
            self._background.setCurrentIndex(0)
            self._alignment.setCurrentIndex(0)
        finally:
            self._loading = False

    def _on_background_changed(self) -> None:
        if self._loading:
            return
        if self._character_id is None:
            self._refuse_unsaved()
            return
        data = self._background.currentData()
        link = (
            ReferenceLink(*data) if data is not None else ReferenceLink("", "", "")
        )
        self._start_locked(
            self._service.set_reference_link(
                self._character_id, BACKGROUND_SLOT, link
            ),
            lambda task: self._on_write_done(task, self._background_label),
        )

    def _on_alignment_changed(self) -> None:
        if self._loading:
            return
        if self._character_id is None:
            self._refuse_unsaved()
            return
        index = self._alignment.currentIndex()
        alignment = None if index <= 0 else ALIGNMENTS[index - 1]
        self._start_locked(
            self._service.set_alignment(self._character_id, alignment),
            lambda task: self._on_write_done(task, "мировоззрение"),
        )

    def _commit(self, key: str, text: "str | None" = None) -> None:
        """One field's commit: ``text`` for a short line edit
        (editingFinished), ``None`` reads the multi-line editor (focus-out).
        Ordinary text is stored ordinary (spec «обычным текстом без ворот
        значения»); an untouched field is no transaction."""
        if self._loading:
            return
        caption = self._captions[key]
        if text is None:
            text = self._long[key].toPlainText()
        if text == self._blocks.get(caption, ""):
            return  # focus left an untouched field — no transaction, no nag
        if self._character_id is None:
            # The typed text is honestly refused, not silently swallowed:
            # the notice names the save, the field goes back to empty.
            self._show_notice(UNSAVED_CHARACTER_REFUSAL)
            stored = self._blocks.get(caption, "")
            if key in self._long:
                self._long[key].setPlainText(stored)
            else:
                self._short[key].setText(stored)
            return
        self._blocks[caption] = text
        self._start_locked(
            self._service.set_text_block(self._character_id, caption, text),
            lambda task: self._on_write_done(task, caption),
        )

    def _on_write_done(self, task: asyncio.Task, what: str) -> None:
        if self._outcome(task, f"сохранение поля «{what}»") is _TASK_FAILED and (
            not task.cancelled()
        ):
            self._show_notice(
                f"Не удалось сохранить поле «{what}». Значение в поле осталось, "
                "повторите изменение; подробности — в журнале приложения."
            )
