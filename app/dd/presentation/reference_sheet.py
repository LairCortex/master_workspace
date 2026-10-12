"""The «Справочник…» sheet (add-dnd-game-face, task 6.3; spec
dnd-reference-records «Справочный лист с вкладками по типам»).

The module's browsing screen over everything its external sources declare:
one tab per registered type (the six dataset record groups and «Заклинания»,
captions from the descriptors' plural names), a substring filter, one row
per record signed with its source («Святой символ · SRD 5.1 (2014)»), and a
row click seating the read-only card in the preview column through the
connector's public external door — the same posture a search-row click took
in task 3.4 (the middle column and the scale stay exactly where they were).
While no source provides rows the sheet explains itself and offers the way
into «Датасеты D&D…» (spec «При пустых подключениях лист SHALL объяснять
это и предлагать открыть лист датасетов»).

The screen is source-generic by construction: it reads only the protocol
doors (``type_descriptors`` for the tab strip, ``search`` with the empty
query for the whole record list) — what the module registers, the sheet
browses; the composition of the D&D shelf (datasets + SRD slugs + grimoire
spells, tasks 3.2/6.1) simply appears as rows. The reference toggle hiding
the source answers the same empty list, so a switched-off shelf reads as
nothing to browse — no second branch here.

Window class: a ``QDialog(parent=MainWindow)`` shown by the façade through
``ApplicationWiring.open_sheet`` — the attached native sheet of the
modal-sheets contract, the widget-side :class:`SheetFrame` chrome («Справочник…»
caption + «Закрыть» = the Esc outcome), fixed default size, the row area
scrolling beyond it. The façade keeps the SINGLE instance (a repeated menu
trigger raises the living sheet, never stacks twins) and takes it down on
detach.

Accessibility (task 6.3 «по контракту островов», AGENTS window norm): every
control is штатный and addressable without coordinates — the tab bar's tabs
carry their captions, the filter is one labeled line edit, each row is a
QPushButton whose name IS the visible caption and whose press IS the
navigation (no item-view rows, which PR-020 proved project nothing); the
empty-state button names the screen it opens.

A row click closes the sheet (reject, the Esc outcome): the spec's scenario
ends with the card visible in the right column, and the attached sheet
covers that column — a navigation that cannot be watched did not happen.
Async posture mirrors the datasets sheet: the list load runs through the
connector's ``run_locked`` (the connection list reads the settings row on
the game's session), the in-flight task is held as a live ref and cancelled
in :meth:`done`.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Coroutine

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QLabel,
    QWidget,
)

from app.dd.presentation.captions import button_caption
from app.presentation.modules.protocol import ExternalEntitySource
from app.presentation.views.sheet_frame import SheetFrame

#: Header caption and menu entry of the sheet — one name threaded through
#: windowTitle and the «Датасеты D&D…» precedent.
DD_REFERENCE_SHEET_TITLE = "Справочник…"

#: The honest explanation while no source answers a single row (spec «При
#: пустых подключениях… объяснять»): nothing is broken, the shelves are
#: simply not connected to this game yet.
DD_REFERENCE_EMPTY_TEXT = (
    "Нет ни одной записи: подключите наборы и гримуары D&D к этой игре — "
    "их классы, подклассы, виды, подвиды, предыстории, черты и заклинания "
    "появятся здесь."
)
#: Caption of the way out of the empty state — the datasets sheet's own name.
DD_REFERENCE_OPEN_DATASETS_TEXT = "Датасеты D&D…"

#: The neutral answer when rows EXIST but the filter leaves none — the
#: connection-explaining text would be a lie about a working shelf.
DD_REFERENCE_NO_MATCH_TEXT = "Ничего не найдено."

#: Placeholder of the name filter (one field for all tabs, spec «фильтр по
#: имени»; case-insensitive substring, the same matching the search uses).
DD_REFERENCE_FILTER_PLACEHOLDER = "Фильтр по имени…"


class DndReferenceSheet(SheetFrame):
    """Tabs + filter + source-signed rows over the module's sources."""

    def __init__(
        self,
        sources: tuple[ExternalEntitySource, ...],
        run_locked: Callable[[Coroutine], asyncio.Task],
        show_card: Callable[[str, str], None],
        open_datasets: Callable[[], None] | None,
        parent: QWidget | None = None,
        theme: object | None = None,
    ) -> None:
        super().__init__(DD_REFERENCE_SHEET_TITLE, parent, theme)
        self._sources = tuple(sources)
        self._run_locked = run_locked
        self._show_card = show_card
        self._open_datasets = open_datasets
        # type key → rows (the whole list, filter applied at render time).
        self._rows: dict[str, list] = {}
        self._load_task: asyncio.Task | None = None
        self.setMinimumSize(560, 480)

        body = QWidget(self)
        body.setObjectName("referenceBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        self._filter = QLineEdit(body)
        self._filter.setObjectName("referenceFilter")
        self._filter.setPlaceholderText(DD_REFERENCE_FILTER_PLACEHOLDER)
        # The placeholder paints, it does not name: a line edit carries no
        # accessible name of its own (task 12.1 — widget-side half of the
        # name rule: the caption at the point of application).
        self._filter.setAccessibleName("Фильтр по имени")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(lambda _text: self._render_current_tab())
        layout.addWidget(self._filter)

        self._tabs = QTabWidget(body)
        self._tabs.setObjectName("referenceTabs")
        for source in self._sources:
            for descriptor in source.type_descriptors:
                # Only lookup records browse here (add-dnd-game-face task
                # 10.1): the flag is exactly «this type belongs to the
                # reference shelf» — the game's own entities (the bestiary,
                # spec dnd-bestiary) live behind their own menu entries and
                # must not appear in a sheet the toggle can empty.
                if not descriptor.reference:
                    continue
                page = QWidget(self._tabs)
                page.setObjectName(f"referencePage_{descriptor.key}")
                page_layout = QVBoxLayout(page)
                page_layout.setContentsMargins(0, 0, 0, 0)
                scroll = QScrollArea(page)
                scroll.setObjectName(f"referenceScroll_{descriptor.key}")
                scroll.setWidgetResizable(True)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                list_host = QWidget(scroll)
                list_host.setObjectName(f"referenceList_{descriptor.key}")
                list_host.setLayout(QVBoxLayout(list_host))
                list_host.layout().setContentsMargins(0, 0, 8, 0)
                list_host.layout().setSpacing(2)
                list_host.layout().addStretch(1)
                scroll.setWidget(list_host)
                page_layout.addWidget(scroll)
                self._tabs.addTab(
                    page, descriptor.plural_label
                )
        self._tabs.currentChanged.connect(lambda _index: self._render_current_tab())
        layout.addWidget(self._tabs, 1)

        self._empty_label = QLabel(DD_REFERENCE_EMPTY_TEXT, body)
        self._empty_label.setObjectName("referenceEmptyHint")
        self._empty_label.setWordWrap(True)
        self._empty_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._empty_label.hide()
        layout.addWidget(self._empty_label, 1)

        # The caption goes through the button escape (captions module): it
        # carries «D&D», and a bare '&' the button family reads as a mnemonic
        # marker would print «Датасеты DD…» and answer the tree with the
        # stripped name (task 12.1).
        self._datasets_button = QPushButton(
            button_caption(DD_REFERENCE_OPEN_DATASETS_TEXT), body
        )
        self._datasets_button.setObjectName("referenceOpenDatasets")
        # The button names the screen it opens — its caption IS its
        # accessibility name (штатный QPushButton, no coordinates needed).
        # Without a composed datasets screen the façade passes ``None`` and
        # the way out is never offered (no dead button, section's posture).
        if open_datasets is not None:
            self._datasets_button.clicked.connect(self._open_datasets)
        else:
            self._datasets_button.setEnabled(False)
        self._datasets_button.hide()
        empty_row = QHBoxLayout()
        empty_row.addStretch(1)
        empty_row.addWidget(self._datasets_button)
        empty_row.addStretch(1)
        layout.addLayout(empty_row)

        self.add_content(body, 1)

    # ── loading (the sources' doors, under the connector's lock) ─────────────

    def request_refresh(self) -> None:
        """Load the record lists through the protocol doors — the façade
        calls this right after the first show (the datasets sheet's
        posture). Re-requesting while a load is in flight is the datasets
        sheet's rule too: the living task answers, no second race starts."""
        if self._load_task is not None and not self._load_task.done():
            return
        self._load_task = self._run_locked(self._load())

    async def _load(self) -> None:
        """One pass over the sources: the empty query is the protocol's
        enumeration (a substring every record contains), rows grouped by the
        descriptor keys in declaration order. A hidden source answers the
        empty list itself — the toggle's semantics live in the source, not
        in a branch here."""
        rows: dict[str, list] = {}
        browsed = set(self._tab_keys())
        for source in self._sources:
            if not source.visible:
                continue
            hits = await source.search("")
            for hit in hits:
                # A source may carry more than it browses here (the monster
                # source shares the tuple since task 10.1): rows of a type
                # without a tab stay out, and the empty-state arithmetic
                # counts only the browsed shelf — an unrelated bestiary must
                # not hide the «connect your datasets» explanation.
                if hit.key in browsed:
                    rows.setdefault(hit.key, []).append(hit)
        self._rows = rows
        self._render_current_tab()

    # ── rendering ─────────────────────────────────────────────────────────────

    def _render_current_tab(self) -> None:
        """Rebuild the visible tab's rows from the loaded list under the
        current filter (case-insensitive substring of the displayed name OR
        of the record's identifier/slug, surrounding blanks trimmed — the
        source's own ``search`` matching rule, restated here so the sheet's
        local narrowing behaves exactly like the global search). Other tabs
        stay untouched until
        shown; an empty answer for the whole sheet swaps the explanation
        block in (spec «объяснять и предлагать»); rows for the current tab
        only hide when rows of some other tab still exist."""
        index = self._tabs.currentIndex()
        if index < 0:
            return
        key = self._tab_keys()[index]
        needle = self._filter.text().strip().lower()
        hits = [
            hit
            for hit in self._rows.get(key, ())
            if not needle
            or needle in hit.name.lower()
            or needle in hit.source_id.lower()
        ]
        host = self._list_host(index)
        layout = host.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # detached NOW, destroyed later: a stale row must not live in
                # the tree (or under the a11y reader) while deleteLater waits
                widget.setParent(None)
                widget.deleteLater()
        total = sum(len(group) for group in self._rows.values())
        if total == 0:
            self._tabs.hide()
            self._filter.hide()
            self._empty_label.setText(DD_REFERENCE_EMPTY_TEXT)
            self._empty_label.show()
            self._datasets_button.setVisible(self._open_datasets is not None)
            return
        self._tabs.show()
        self._filter.show()
        self._empty_label.setText(DD_REFERENCE_NO_MATCH_TEXT)
        self._empty_label.setVisible(not hits)
        self._datasets_button.setVisible(False)
        for hit in hits:
            # The escape rides every button caption (captions module): an
            # external record name may carry a literal '&' («Тирекс & К.»)
            # and must reach both the paint and the name slot whole.
            button = QPushButton(button_caption(self._row_caption(hit)), host)
            button.setObjectName("referenceRow")
            button.setFlat(True)
            # Left-aligned whole-row press: the caption is the accessible
            # name, the press is the navigation — one control per row.
            button.setStyleSheet("text-align: left;")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked, k=hit.key, s=hit.source_id: self._row_activated(k, s)
            )
            layout.insertWidget(layout.count() - 1, button)
        layout.setStretch(layout.count() - 1, 1)

    @staticmethod
    def _row_caption(hit) -> str:
        """The row text: the name, signed with the source when the record
        names one (spec «с пометкой источника»; an empty origin paints no
        separator — the generic rendering the protocol's origin field
        prescribes)."""
        if hit.origin:
            return f"{hit.name} · {hit.origin}"
        return hit.name

    def _row_activated(self, key: str, source_id: str) -> None:
        """Row click → the read-only card in the preview column (the
        connector's public external door, task 6.3), then the sheet closes
        so the master watches the column it navigated to (module docstring
        — the navigation the spec scenario promises ends with the card
        visible)."""
        self._show_card(key, source_id)
        self.reject()

    def _tab_keys(self) -> list[str]:
        # Same filter as the tab strip (task 10.1): the index of a tab is its
        # position among the REFERENCE descriptors only.
        return [
            descriptor.key
            for source in self._sources
            for descriptor in source.type_descriptors
            if descriptor.reference
        ]

    def _list_host(self, index: int) -> QWidget:
        page = self._tabs.widget(index)
        scroll = page.findChild(QScrollArea)
        assert scroll is not None  # built whole in __init__, pages never added bare
        return scroll.widget()

    # ── teardown ───────────────────────────────────────────────────────────────

    def done(self, result: int) -> None:
        # A closed sheet never repaints itself: the in-flight list load dies
        # with it (the datasets sheet's cancellation discipline).
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        self._load_task = None
        super().done(result)
