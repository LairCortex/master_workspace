"""World Snapshot widget — visual overview of the game world at a specific date."""
from __future__ import annotations

from datetime import date
from typing import Any, Sequence

from PySide6.QtCore import QDate, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.presentation.utils.date_utils import format_game_date
from app.presentation.views.custom_date_edit import CustomDateEdit
from app.presentation.views.detail_panel import rating_to_color
from app.presentation.utils.image_utils import load_entity_preview


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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Title ──
        title = QLabel("Обзор мира")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # ── Date picker bar ──
        date_bar = QHBoxLayout()
        date_bar.setSpacing(6)

        date_bar.addWidget(QLabel("Дата:"))
        self.date_edit = CustomDateEdit()
        self.date_edit.setDate(QDate.currentDate())
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

        self.show_all_button = QPushButton("Показать всё")
        self.show_all_button.clicked.connect(self._on_show_all)
        date_bar.addWidget(self.show_all_button)

        layout.addLayout(date_bar)

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
        self.tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.tree, 1)

        # ── Stats bar ──
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("font-size: 11px; color: #999;")
        self.stats_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.stats_label)

        # ── Empty state ──
        self._show_empty("Выберите дату и нажмите «Показать»")

    # ── Public API ──

    def populate(self, events: Sequence[Any], for_date: date | None) -> None:
        """Build the world tree from a list of events.
        for_date: date for stats label; None means 'show all' mode.
        """
        self.tree.clear()
        self.clear_button.setEnabled(True)

        if not events:
            self._show_empty(
                "Нет событий в игре" if for_date is None else "На эту дату нет активных событий"
            )
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

        # ── Helper: build a collapsible section ──
        def _section(label: str, icon_key: str, count: int) -> QTreeWidgetItem:
            node = QTreeWidgetItem(self.tree)
            node.setText(0, f"{label} ({count})")
            node.setFont(0, QFont("", -1, QFont.Weight.Bold))
            node.setIcon(0, _icon(icon_key))
            node.setExpanded(True)
            return node

        # ── Events section ──
        if events:
            ev_section = _section("📅  Активные события", "event", len(events))
            ev_section.setExpanded(False)
            for ev in events:
                ev_item = QTreeWidgetItem(ev_section)
                sd = format_game_date(ev.start_date)
                ed = format_game_date(ev.end_date, "∞")
                ev_item.setText(0, f"{sd} — {ed}  |  {ev.name}")
                ev_item.setIcon(0, _icon("event"))
                ev_item.setData(0, Qt.ItemDataRole.UserRole, ("event", ev.id))

        # ── Locations section ──
        if locations:
            loc_section = _section("📍  Локации", "location", len(locations))
            for loc in sorted(locations.values(), key=lambda x: x.name):
                self._make_entity_node(loc_section, loc, "location", "📍")

        # ── Organizations section ──
        if organizations:
            org_section = _section("👥  Организации", "organization", len(organizations))
            for org in sorted(organizations.values(), key=lambda x: x.name):
                self._make_entity_node(org_section, org, "organization", "👥")

        # ── Characters section ──
        if characters:
            char_section = _section("🧑  Персонажи", "character", len(characters))
            for ch in sorted(characters.values(), key=lambda x: -getattr(x, "rating", 1)):
                self._make_entity_node(char_section, ch, "character", "🧑")

        # ── Items section ──
        if items:
            item_section = _section("🗡  Предметы", "item", len(items))
            for it in sorted(items.values(), key=lambda x: -getattr(x, "rating", 1)):
                self._make_entity_node(item_section, it, "item", "🗡")

        # ── Stats ──
        if for_date is None:
            stats_text = (
                "Показано: все события  |  "
                f"Событий: {len(events)}  |  "
                f"Персонажей: {len(characters)}  |  "
                f"Организаций: {len(organizations)}  |  "
                f"Локаций: {len(locations)}  |  "
                f"Предметов: {len(items)}"
            )
        else:
            target = for_date
            stats_text = (
                f"Дата: {format_game_date(target)}  |  "
                f"Событий: {len(events)}  |  "
                f"Персонажей: {len(characters)}  |  "
                f"Организаций: {len(organizations)}  |  "
                f"Локаций: {len(locations)}  |  "
                f"Предметов: {len(items)}"
            )
        self.stats_label.setText(stats_text)

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

        # Thumbnail for entities with images (file-backed, design D10)
        pm = load_entity_preview(entity, slot_size=24)
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

    # ── Slots ──

    def _on_show(self) -> None:
        target = self.date_edit.date().toPython()
        self.snapshot_requested.emit(target)

    def _on_show_all(self) -> None:
        """Show snapshot without date filter (all events/entities)."""
        self.snapshot_requested.emit(None)

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
