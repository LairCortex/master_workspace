"""Detail panel — shows components of the selected event."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from app.presentation.utils.image_utils import base64_to_thumbnail


def _truncate(text: str, max_len: int = 120) -> str:
    """Truncate text to max_len, adding ellipsis."""
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def rating_to_color(rating: int) -> QColor:
    """Map rating 1-20 to a subtle background color.

    1  → grey (transparent, neutral)
    20 → muted red tint
    Intermediate values interpolate smoothly.
    Colors are kept at low opacity/saturation so text stays readable.
    """
    t = max(0.0, min(1.0, (rating - 1) / 19.0))  # 0.0 … 1.0

    # Grey (#3a3a3a) → muted dark red (#8c2020)
    r = int(58 + t * (140 - 58))
    g = int(58 - t * (58 - 32))
    b = int(58 - t * (58 - 32))
    return QColor(r, g, b, int(80 + t * 140))  # alpha 80..220


def _build_summary(entity: Any, entity_type: str) -> str:
    """Build a short summary string from entity fields (no name, no dates)."""
    parts: list[str] = []

    # Rating badge
    rating_val = getattr(entity, "rating", None)
    if isinstance(rating_val, int) and rating_val >= 1:
        parts.append(f"<b>Рейтинг:</b> {rating_val}/20")

    desc = getattr(entity, "description", None)
    if desc:
        chars = getattr(desc, "characteristics", None)
        if chars and chars.strip():
            parts.append(f"<b>Хар-ки:</b> {_truncate(chars)}")
        backstory = getattr(desc, "backstory", None)
        if backstory and backstory.strip():
            parts.append(f"<b>Предыстория:</b> {_truncate(backstory)}")

    if entity_type in ("character",):
        personality = getattr(entity, "personality", None)
        if personality and personality.strip():
            parts.append(f"<b>Личность:</b> {_truncate(personality)}")

    if entity_type in ("organization", "character", "location"):
        tasks = getattr(entity, "tasks", None)
        if tasks and tasks.strip():
            parts.append(f"<b>Задачи:</b> {_truncate(tasks)}")

    # Related counts
    counts: list[str] = []
    for attr, label in [
        ("characters", "персонажей"),
        ("organizations", "организаций"),
        ("items", "предметов"),
        ("locations", "локаций"),
    ]:
        col = getattr(entity, attr, None)
        if col is not None and len(col) > 0:
            counts.append(f"{len(col)} {label}")
    if counts:
        parts.append(f"<b>Связи:</b> {', '.join(counts)}")

    return "<br>".join(parts) if parts else "<i>нет данных</i>"


class _EntityItemWidget(QWidget):
    """Custom widget rendered inside a QListWidgetItem: optional thumbnail + name + summary."""

    def __init__(
        self,
        name: str,
        summary_html: str,
        thumbnail: QPixmap | None = None,
        rating: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # Store rating color for paintEvent — stylesheet/palette approaches
        # don't work reliably inside QListWidget item widgets.
        self._bg_color = rating_to_color(rating)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(8)

        if thumbnail and not thumbnail.isNull():
            thumb_label = QLabel()
            thumb_label.setPixmap(thumbnail)
            thumb_label.setFixedSize(100, 100)
            thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            outer.addWidget(thumb_label)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: bold; font-size: 13px; background: transparent;")
        text_col.addWidget(name_label)

        info_label = QLabel(summary_html)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("font-size: 11px; background: transparent;")
        text_col.addWidget(info_label)
        text_col.addStretch()

        outer.addLayout(text_col, 1)

    def paintEvent(self, event) -> None:  # noqa: N802
        """Draw rounded-rect background with the rating color."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(self._bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 4, 4)
        painter.end()
        super().paintEvent(event)


class DetailPanel(QWidget):
    entity_clicked = Signal(str, int)  # entity_type, entity_id

    def __init__(self, detail_vm, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = detail_vm
        self._current_event_id: int | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        layout.addWidget(self.title_label)

        self.date_label = QLabel("")
        layout.addWidget(self.date_label)

        self.tabs = QTabWidget()
        self.org_list = QListWidget()
        self.char_list = QListWidget()
        self.item_list = QListWidget()
        self.loc_list = QListWidget()

        self.tabs.addTab(self.org_list, "Организации")
        self.tabs.addTab(self.char_list, "Персонажи")
        self.tabs.addTab(self.item_list, "Предметы")
        self.tabs.addTab(self.loc_list, "Локации")

        self.org_list.itemDoubleClicked.connect(lambda item: self._on_entity_click("organization", item))
        self.char_list.itemDoubleClicked.connect(lambda item: self._on_entity_click("character", item))
        self.item_list.itemDoubleClicked.connect(lambda item: self._on_entity_click("item", item))
        self.loc_list.itemDoubleClicked.connect(lambda item: self._on_entity_click("location", item))

        layout.addWidget(self.tabs)

    def show_event(self, event: Any) -> None:
        self._current_event_id = getattr(event, "id", None)
        self.title_label.setText(event.name)
        self.date_label.setText(f"{event.start_date} — {event.end_date}")
        self._fill_list(self.org_list, event.organizations, "organization")
        self._fill_list(self.char_list, event.characters, "character")
        self._fill_list(self.item_list, event.items, "item")
        self._fill_list(self.loc_list, event.locations, "location")

    def clear(self) -> None:
        self._current_event_id = None
        self.title_label.setText("")
        self.date_label.setText("")
        self.org_list.clear()
        self.char_list.clear()
        self.item_list.clear()
        self.loc_list.clear()

    def _fill_list(self, list_widget: QListWidget, entities: list, entity_type: str) -> None:
        list_widget.clear()
        for entity in entities:
            name = getattr(entity, "name", str(entity))
            summary = _build_summary(entity, entity_type)

            # Rating
            rating_val = getattr(entity, "rating", 1)
            if not isinstance(rating_val, int):
                rating_val = 1

            # Thumbnail for entities with image
            thumbnail = None
            img_b64 = getattr(entity, "image", None)
            if img_b64 and isinstance(img_b64, str):
                thumbnail = base64_to_thumbnail(img_b64, size=100)

            widget = _EntityItemWidget(name, summary, thumbnail=thumbnail, rating=rating_val)
            widget.adjustSize()

            item = QListWidgetItem()
            item.setData(256, {"type": entity_type, "id": getattr(entity, "id", None)})
            # Height: at least 60, or 108 if thumbnail present
            height = widget.sizeHint().height() + 8
            min_h = 108 if (thumbnail and not thumbnail.isNull()) else 60
            item.setSizeHint(QSize(0, max(height, min_h)))
            list_widget.addItem(item)
            list_widget.setItemWidget(item, widget)

    def _on_entity_click(self, entity_type: str, item: QListWidgetItem) -> None:
        data = item.data(256)
        if data and data.get("id"):
            self.entity_clicked.emit(entity_type, data["id"])
