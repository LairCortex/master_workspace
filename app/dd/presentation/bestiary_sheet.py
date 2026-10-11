"""The «Бестиарий» sheet (add-dnd-game-face task 10.1; spec dnd-bestiary
«Бестиарий — список с входом из меню модуля»).

The module's own browsing screen over the game's monsters: one row per
monster (caption «имя · рейтинг N»), a name filter, a create entry and a
row click opening the editable card. Empty bestiary — the spec's scenario
«Список пуст и подсказывает»: an explanation plus the same create button,
never a dead screen.

Window class: the sheet contract — ``QDialog(parent=MainWindow)`` shown by
the façade through ``ApplicationWiring.open_sheet`` (attached native sheet,
no Qt modality), the widget-side :class:`SheetFrame` chrome («Бестиарий»
caption + «Закрыть» = the Esc outcome), fixed default size, the row area
scrolling beyond it. Unlike the reference sheet a row click does NOT close
this sheet: the monster card is the module's own sheet, the stack depth is
штатно unlimited, and the master returns to the list they were filtering
(the reference sheet closed because the navigation target — the preview
column — hides under any sheet; the card is a sheet too, closing gains
nothing).

Accessibility (island contract, AGENTS window norm): every control is
штатный and addressable without coordinates — the filter is one labeled
line edit, each row and both create entries are QPushButtons whose caption
IS their accessibility name; the rows replace cleanly on every rebuild.

Async posture mirrors the reference sheet: the whole list loads through the
connector's ``run_locked`` (the table read rides the game's session), the
in-flight task is held as a live ref and cancelled in :meth:`done`. The
service answers the list; the filter is applied at render time over the
loaded rows (the list is small by product shape — the repo's note), so the
filter field never starts a second query race.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Coroutine

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.dd.domain.monster import DdMonster
from app.dd.presentation.captions import button_caption
from app.presentation.views.sheet_frame import SheetFrame

#: Header caption and menu entry of the sheet — one threaded name (the
#: «Справочник…» precedent).
DD_BESTIARY_SHEET_TITLE = "Бестиарий"

#: The spec's empty-state sentence: the screen explains what it is AND how to
#: fill it (scenario «видно объяснение и кнопку создания»).
DD_BESTIARY_EMPTY_TEXT = (
    "Бестиарий пуст. Создайте первого монстра — он появится здесь, в поиске "
    "и в упоминаниях."
)
#: The neutral answer when monsters EXIST but the filter leaves none (the
#: reference sheet's rule: the empty-explaining text would lie about a full
#: bestiary).
DD_BESTIARY_NO_MATCH_TEXT = "Ничего не найдено."
#: Placeholder of the name filter (case-insensitive substring, the search's
#: own matching rule).
DD_BESTIARY_FILTER_PLACEHOLDER = "Фильтр по имени…"
#: Caption of both create entries (top row and empty state — one action, one
#: caption, one accessibility name).
DD_BESTIARY_CREATE_TEXT = "Создать монстра"


def monster_row_caption(monster: DdMonster) -> str:
    """The row caption: name and rating — the two fields the list promises
    without opening the card (the blocks belong to the card's tabs)."""
    return f"{monster.name} · рейтинг {monster.rating}"


class DndBestiarySheet(SheetFrame):
    """Filter + rows + create entry over the game's bestiary."""

    def __init__(
        self,
        service: object,
        run_locked: Callable[[Coroutine], asyncio.Task],
        open_card: Callable[[int | None], None],
        parent: QWidget | None = None,
        theme: object | None = None,
    ) -> None:
        super().__init__(DD_BESTIARY_SHEET_TITLE, parent, theme)
        self._service = service
        self._run_locked = run_locked
        self._open_card = open_card
        self._monsters: list[DdMonster] = []
        self._load_task: asyncio.Task | None = None
        self.setMinimumSize(480, 420)

        body = QWidget(self)
        body.setObjectName("bestiaryBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self._filter = QLineEdit(body)
        self._filter.setObjectName("bestiaryFilter")
        self._filter.setPlaceholderText(DD_BESTIARY_FILTER_PLACEHOLDER)
        # The placeholder paints, it does not name (task 12.1, widget-side
        # name rule — same fix as the reference sheet's filter).
        self._filter.setAccessibleName("Фильтр по имени")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(lambda _text: self._render_rows())
        top.addWidget(self._filter, 1)
        # Create lives in the header row too: after a filtered browse the
        # action stays one click away, not behind a cleared filter.
        self._create_button = QPushButton(DD_BESTIARY_CREATE_TEXT, body)
        self._create_button.setObjectName("bestiaryCreate")
        self._create_button.clicked.connect(lambda: self._open_card(None))
        top.addWidget(self._create_button)
        layout.addLayout(top)

        self._scroll = QScrollArea(body)
        self._scroll.setObjectName("bestiaryScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._list_host = QWidget(self._scroll)
        self._list_host.setObjectName("bestiaryList")
        list_layout = QVBoxLayout(self._list_host)
        list_layout.setContentsMargins(0, 0, 8, 0)
        list_layout.setSpacing(2)
        list_layout.addStretch(1)
        self._scroll.setWidget(self._list_host)
        layout.addWidget(self._scroll, 1)

        self._empty_label = QLabel(DD_BESTIARY_EMPTY_TEXT, body)
        self._empty_label.setObjectName("bestiaryEmptyHint")
        self._empty_label.setWordWrap(True)
        self._empty_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._empty_label.hide()
        layout.addWidget(self._empty_label, 1)

        self._empty_create_button = QPushButton(DD_BESTIARY_CREATE_TEXT, body)
        self._empty_create_button.setObjectName("bestiaryEmptyCreate")
        self._empty_create_button.clicked.connect(lambda: self._open_card(None))
        self._empty_create_button.hide()
        empty_row = QHBoxLayout()
        empty_row.addStretch(1)
        empty_row.addWidget(self._empty_create_button)
        empty_row.addStretch(1)
        layout.addLayout(empty_row)

        self.add_content(body, 1)

    # ── loading (the service's door, under the connector's lock) ─────────────

    def request_refresh(self) -> None:
        """Load the whole bestiary through the service (the façade calls this
        right after the first show and after every card save). Re-requesting
        while a load is in flight keeps the living task (the datasets sheet's
        race rule)."""
        if self._load_task is not None and not self._load_task.done():
            return
        self._load_task = self._run_locked(self._load())

    async def _load(self) -> None:
        self._monsters = await self._service.list_monsters()
        self._render_rows()

    # ── rendering ─────────────────────────────────────────────────────────────

    def _render_rows(self) -> None:
        """Rebuild the visible rows from the loaded list under the current
        filter (case-insensitive substring of the name). No monster at all —
        the spec's explanation + create button; rows exist but none matches —
        the neutral hint only (the top-row create button stays reachable)."""
        layout = self._list_host.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # detached NOW, destroyed later: a stale row must not live in
                # the tree (or under the a11y reader) while deleteLater waits
                widget.setParent(None)
                widget.deleteLater()
        if not self._monsters:
            self._scroll.hide()
            self._empty_label.setText(DD_BESTIARY_EMPTY_TEXT)
            self._empty_label.show()
            self._empty_create_button.show()
            return
        needle = self._filter.text().strip().lower()
        hits = [
            monster
            for monster in self._monsters
            if not needle or needle in monster.name.lower()
        ]
        self._empty_label.setText(DD_BESTIARY_NO_MATCH_TEXT)
        self._empty_label.setVisible(not hits)
        self._empty_create_button.hide()
        self._scroll.setVisible(bool(hits))
        for monster in hits:
            # Escape on the caption (captions module): a monster name with a
            # literal '&' must print and name whole («Датасеты D&D…»).
            button = QPushButton(
                button_caption(monster_row_caption(monster)), self._list_host
            )
            button.setObjectName("bestiaryRow")
            button.setFlat(True)
            # Left-aligned whole-row press: the caption is the accessible
            # name, the press is the navigation — one control per row.
            button.setStyleSheet("text-align: left;")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked, monster_id=monster.id: self._open_card(monster_id)
            )
            layout.insertWidget(layout.count() - 1, button)
        layout.setStretch(layout.count() - 1, 1)

    # ── teardown ───────────────────────────────────────────────────────────────

    def done(self, result: int) -> None:
        # A closed sheet never repaints itself: the in-flight list load dies
        # with it (the reference sheet's cancellation discipline).
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        self._load_task = None
        super().done(result)
