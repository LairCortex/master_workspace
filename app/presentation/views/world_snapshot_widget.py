"""World Snapshot widget — visual overview of the game world at a specific date."""
from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtCore import QDate, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDateEdit, QFrame, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.presentation.views.detail_panel import rating_to_color
from app.presentation.utils.image_utils import base64_to_thumbnail


# ── Icon helpers ──────────────────────────────────────────────────────────

def _colored_circle(color: QColor, size: int = 16) -> QIcon:
    """Create a small colored circle icon."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pm)


def _text_icon(emoji: str, size: int = 20) -> QIcon:
    """Render an emoji/character into a QIcon."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setFont(QFont("Segoe UI Emoji, Apple Color Emoji, Noto Color Emoji", int(size * 0.7)))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, emoji)
    p.end()
    return QIcon(pm)


# Pre-built icons (created lazily on first use)
_ICONS: dict[str, QIcon] = {}


def _icon(key: str) -> QIcon:
    if key not in _ICONS:
        mapping = {
            "location": ("📍", QColor(70, 130, 180)),
            "organization": ("👥", QColor(180, 130, 70)),
            "character": ("👤", QColor(100, 180, 100)),
            "item": ("🗡", QColor(180, 180, 100)),
            "event": ("📅", QColor(130, 100, 180)),
            "no_location": ("🌐", QColor(120, 120, 120)),
            "no_org": ("👤", QColor(120, 120, 120)),
        }
        emoji, color = mapping.get(key, ("•", QColor(150, 150, 150)))
        _ICONS[key] = _text_icon(emoji)
    return _ICONS[key]


# ── World Snapshot Widget ─────────────────────────────────────────────────

class WorldSnapshotWidget(QWidget):
    """Shows the state of the game world at a given date as a tree."""

    entity_clicked = Signal(str, int)  # (entity_type, entity_id)
    snapshot_requested = Signal(object)  # date | None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # ── Title ──
        title = QLabel("🌍  Обзор мира")
        title.setStyleSheet("font-weight: bold; font-size: 15px;")
        layout.addWidget(title)

        # ── Date picker bar ──
        date_bar = QHBoxLayout()
        date_bar.setSpacing(6)

        date_bar.addWidget(QLabel("Дата:"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setMinimumDate(QDate(100, 1, 1))
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        date_bar.addWidget(self.date_edit, 1)

        self.show_button = QPushButton("Показать")
        self.show_button.setStyleSheet(
            "QPushButton { background-color: #2d5a88; color: white; padding: 4px 12px;"
            " border-radius: 3px; font-weight: bold; }"
            "QPushButton:hover { background-color: #3a6fa0; }"
        )
        self.show_button.clicked.connect(self._on_show)
        date_bar.addWidget(self.show_button)

        self.clear_button = QPushButton("Сброс")
        self.clear_button.setEnabled(False)
        self.clear_button.clicked.connect(self._on_clear)
        date_bar.addWidget(self.clear_button)

        layout.addLayout(date_bar)

        # ── Separator ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # ── Tree ──
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(24)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.setStyleSheet(
            "QTreeWidget { font-size: 13px; }"
            "QTreeWidget::item { padding: 3px 0px; }"
        )
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.tree, 1)

        # ── Stats bar ──
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("font-size: 11px; color: #999;")
        layout.addWidget(self.stats_label)

        # ── Empty state ──
        self._show_empty("Выберите дату и нажмите «Показать»")

    # ── Public API ──

    def populate(self, events: Sequence[Any]) -> None:
        """Build the world tree from a list of events active at the given date."""
        self.tree.clear()
        self.clear_button.setEnabled(True)

        if not events:
            self._show_empty("На эту дату нет активных событий")
            return

        # ── Collect all unique entities from events ──
        locations: dict[int, Any] = {}
        characters: dict[int, Any] = {}
        organizations: dict[int, Any] = {}
        items: dict[int, Any] = {}

        for ev in events:
            for loc in getattr(ev, "locations", []):
                locations[loc.id] = loc
            for ch in getattr(ev, "characters", []):
                characters[ch.id] = ch
            for org in getattr(ev, "organizations", []):
                organizations[org.id] = org
            for it in getattr(ev, "items", []):
                items[it.id] = it

        # ── Events section ──
        events_node = QTreeWidgetItem(self.tree)
        events_node.setText(0, f"📅  Активные события ({len(events)})")
        events_node.setFont(0, QFont("", -1, QFont.Weight.Bold))
        events_node.setExpanded(False)
        for ev in events:
            ev_item = QTreeWidgetItem(events_node)
            ev_item.setText(0, f"{ev.start_date} — {ev.end_date}  |  {ev.name}")
            ev_item.setIcon(0, _icon("event"))
            ev_item.setData(0, Qt.ItemDataRole.UserRole, ("event", ev.id))

        # ── Build location → org → character → items hierarchy ──
        # Figure out which characters belong to which location/org
        char_locs: dict[int, list[int]] = {}  # char_id → [loc_ids]
        char_orgs: dict[int, list[int]] = {}  # char_id → [org_ids]
        char_items_map: dict[int, list[int]] = {}  # char_id → [item_ids]

        for ch_id, ch in characters.items():
            char_locs[ch_id] = [
                loc.id for loc in getattr(ch, "locations", []) if loc.id in locations
            ]
            char_orgs[ch_id] = [
                org.id for org in getattr(ch, "organizations", []) if org.id in organizations
            ]
            char_items_map[ch_id] = [
                it.id for it in getattr(ch, "items", []) if it.id in items
            ]

        # Characters placed into locations
        placed_char_ids: set[int] = set()

        for loc_id, loc in sorted(locations.items(), key=lambda x: x[1].name):
            loc_node = self._make_entity_node(self.tree, loc, "location", "📍")
            loc_node.setExpanded(True)

            # Find orgs tied to this location
            loc_org_ids = {
                org.id for org in getattr(loc, "organizations", []) if org.id in organizations
            }

            # Characters grouped by org within this location
            chars_in_loc = [
                ch_id for ch_id, locs_list in char_locs.items() if loc_id in locs_list
            ]

            # Group by org
            org_chars: dict[int, list[int]] = {}  # org_id → [char_ids]
            no_org_chars: list[int] = []

            for ch_id in chars_in_loc:
                placed_char_ids.add(ch_id)
                ch_org_ids = [oid for oid in char_orgs.get(ch_id, []) if oid in loc_org_ids or True]
                if ch_org_ids:
                    for oid in ch_org_ids:
                        org_chars.setdefault(oid, []).append(ch_id)
                else:
                    no_org_chars.append(ch_id)

            # Render org groups
            for org_id, ch_ids in sorted(org_chars.items(), key=lambda x: organizations[x[0]].name):
                org = organizations[org_id]
                org_node = self._make_entity_node(loc_node, org, "organization", "👥")
                org_node.setExpanded(True)
                for ch_id in sorted(ch_ids, key=lambda x: -getattr(characters[x], "rating", 1)):
                    self._add_character_branch(org_node, characters[ch_id], items, char_items_map)

            # Render characters without org
            for ch_id in sorted(no_org_chars, key=lambda x: -getattr(characters[x], "rating", 1)):
                self._add_character_branch(loc_node, characters[ch_id], items, char_items_map)

            # Items at location but not held by any character
            loc_item_ids = {it.id for it in getattr(loc, "items", []) if it.id in items}
            held_items = set()
            for ch_id in chars_in_loc:
                held_items.update(char_items_map.get(ch_id, []))
            loose_items = loc_item_ids - held_items
            for it_id in sorted(loose_items):
                self._make_entity_node(loc_node, items[it_id], "item", "🗡")

        # ── Characters without a known location ──
        unplaced = set(characters.keys()) - placed_char_ids
        if unplaced:
            no_loc_node = QTreeWidgetItem(self.tree)
            no_loc_node.setText(0, "🌐  Без локации")
            no_loc_node.setFont(0, QFont("", -1, QFont.Weight.Bold))
            no_loc_node.setIcon(0, _icon("no_location"))
            no_loc_node.setExpanded(True)

            for ch_id in sorted(unplaced, key=lambda x: -getattr(characters[x], "rating", 1)):
                self._add_character_branch(no_loc_node, characters[ch_id], items, char_items_map)

        # ── Stats ──
        target = self.date_edit.date().toPython()
        self.stats_label.setText(
            f"Дата: {target}  |  "
            f"Событий: {len(events)}  |  "
            f"Персонажей: {len(characters)}  |  "
            f"Организаций: {len(organizations)}  |  "
            f"Локаций: {len(locations)}  |  "
            f"Предметов: {len(items)}"
        )

    # ── Tree node helpers ──

    def _make_entity_node(
        self,
        parent: QTreeWidget | QTreeWidgetItem,
        entity: Any,
        entity_type: str,
        emoji: str,
    ) -> QTreeWidgetItem:
        """Create a tree item for an entity with rating coloring and thumbnail."""
        rating = getattr(entity, "rating", 1)
        if not isinstance(rating, int):
            rating = 1
        name = getattr(entity, "name", str(entity))

        node = QTreeWidgetItem(parent)
        label = f"{emoji}  {name}"
        if rating > 1:
            label += f"  [{rating}/20]"
        node.setText(0, label)
        node.setData(0, Qt.ItemDataRole.UserRole, (entity_type, entity.id))

        # Rating color
        color = rating_to_color(rating)
        node.setBackground(0, QBrush(color))

        # Bold for high-rating entities
        if rating >= 15:
            f = node.font(0)
            f.setBold(True)
            node.setFont(0, f)

        # Thumbnail for entities with images
        img_b64 = getattr(entity, "image", None)
        if img_b64 and isinstance(img_b64, str):
            pm = base64_to_thumbnail(img_b64, size=24)
            if not pm.isNull():
                node.setIcon(0, QIcon(pm))
        else:
            node.setIcon(0, _icon(entity_type))

        # Tooltip with extra info
        tooltip_parts = [f"<b>{name}</b> ({entity_type})"]
        tooltip_parts.append(f"Рейтинг: {rating}/20")
        desc = getattr(entity, "description", None)
        if desc:
            chars_text = getattr(desc, "characteristics", "")
            if chars_text and chars_text.strip():
                snippet = chars_text.strip()[:200]
                tooltip_parts.append(f"<i>{snippet}</i>")
        node.setToolTip(0, "<br>".join(tooltip_parts))

        return node

    def _add_character_branch(
        self,
        parent: QTreeWidgetItem,
        char: Any,
        all_items: dict[int, Any],
        char_items_map: dict[int, list[int]],
    ) -> None:
        """Add a character node with its items as children."""
        ch_node = self._make_entity_node(parent, char, "character", "👤")
        ch_node.setExpanded(True)

        item_ids = char_items_map.get(char.id, [])
        for it_id in sorted(item_ids):
            if it_id in all_items:
                self._make_entity_node(ch_node, all_items[it_id], "item", "🗡")

    # ── Slots ──

    def _on_show(self) -> None:
        target = self.date_edit.date().toPython()
        self.snapshot_requested.emit(target)

    def _on_clear(self) -> None:
        self.tree.clear()
        self.clear_button.setEnabled(False)
        self.stats_label.setText("")
        self._show_empty("Выберите дату и нажмите «Показать»")

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and isinstance(data, tuple) and len(data) == 2:
            entity_type, entity_id = data
            if entity_type != "event":
                self.entity_clicked.emit(entity_type, entity_id)

    def _show_empty(self, text: str) -> None:
        self.tree.clear()
        placeholder = QTreeWidgetItem(self.tree)
        placeholder.setText(0, text)
        placeholder.setForeground(0, QBrush(QColor(150, 150, 150)))
        f = placeholder.font(0)
        f.setItalic(True)
        placeholder.setFont(0, f)
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        self.stats_label.setText("")
