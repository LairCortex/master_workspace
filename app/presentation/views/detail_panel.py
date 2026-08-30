"""Detail panel — shows components of the selected event."""
from __future__ import annotations

from typing import Any

from app.presentation.utils.date_utils import format_game_date

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from app.presentation.theme.catalog import attach_theme, set_role, title
from app.presentation.utils.image_utils import load_entity_original, load_entity_preview
from app.presentation.views.clickable_label import ClickableLabel
from app.presentation.views.image_viewer_dialog import ImageViewerDialog


def _truncate(text: str, max_len: int = 120) -> str:
    """Truncate text to max_len, adding ellipsis."""
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def rating_to_color(rating: int, runtime=None) -> QColor:
    """Map rating 1-20 to a subtle background color.

    1  → the ``color.rating.low`` endpoint (neutral grey in the tokens)
    20 → ``color.rating.high`` (muted red tint in the tokens)
    Intermediate values interpolate smoothly between the token endpoints.
    The gradient and the 80..220 alpha ramp are the pre-token behaviour —
    only the endpoints moved into the theme (W2b D4), so changing a token
    changes the UI without touching any screen.

    With no runtime (or invalid tokens) the content paint is left out —
    a screen never paints an invented color outside the theme (like D7).
    """
    t = max(0.0, min(1.0, (rating - 1) / 19.0))  # 0.0 … 1.0

    tokens = runtime.tokens if runtime is not None else None
    if not tokens:
        return QColor(0, 0, 0, 0)
    low = QColor(tokens.get("color.rating.low", {}).get(runtime.theme, ""))
    high = QColor(tokens.get("color.rating.high", {}).get(runtime.theme, ""))
    if not (low.isValid() and high.isValid()):
        return QColor(0, 0, 0, 0)

    r = int(low.red() + t * (high.red() - low.red()))
    g = int(low.green() + t * (high.green() - low.green()))
    b = int(low.blue() + t * (high.blue() - low.blue()))
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

    # Emitted when the thumbnail is clicked — opens the full-size viewer
    # (design D10/task 5.3). Only wired when a thumbnail is actually shown.
    image_clicked = Signal()

    def __init__(
        self,
        name: str,
        summary_html: str,
        thumbnail: QPixmap | None = None,
        rating: int = 1,
        parent: QWidget | None = None,
        runtime=None,
    ) -> None:
        super().__init__(parent)
        self._runtime = runtime
        # Store rating color for paintEvent — stylesheet/palette approaches
        # don't work reliably inside QListWidget item widgets. Endpoints come
        # from the theme tokens; the card chrome behind it is the card role.
        self._rating = rating
        self._bg_color = rating_to_color(rating, runtime)
        set_role(self, "card")
        # A plain QWidget paints the card role's surface/border from an
        # ancestor sheet only with styled-background on (unlike a QLabel, and
        # chrome roots get it in ``attach_theme``). Without it the card had no
        # frame at all, so the related-list rows were separated by nothing but
        # the rating tint (W2b review).
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(8)

        if thumbnail and not thumbnail.isNull():
            thumb_label = ClickableLabel()
            thumb_label.setPixmap(thumbnail)
            thumb_label.setFixedSize(100, 100)
            thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
            thumb_label.clicked.connect(self.image_clicked)
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

    def retheme(self) -> None:
        """Re-read the token endpoints after a live theme switch."""
        self._bg_color = rating_to_color(self._rating, self._runtime)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        """Paint the card chrome first (tokens), then the rating tint.

        The tint stops at the card's own border: painting the whole
        ``rect()`` wiped the 1px card frame and left the related-list rows
        separated by nothing but the tint (W2b review).
        """
        super().paintEvent(event)  # card role: surface/border from the sheet
        if self._bg_color.alpha() == 0:
            return  # off-skin: nothing to paint over the card chrome (D7)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(self._bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 3, 3)
        painter.end()


class DetailPanel(QWidget):
    entity_clicked = Signal(str, int)  # entity_type, entity_id

    def __init__(
        self,
        detail_vm,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._vm = detail_vm
        self._theme = theme
        self._current_event_id: int | None = None
        self._item_widgets: list[_EntityItemWidget] = []
        self._init_ui()
        self._apply_theme()

    def _apply_theme(self) -> None:
        """One attach point: the chrome container carries the whole sheet (D1)."""
        if self._theme is not None:
            # Rating tints read token endpoints → repaint after a live swap.
            attach_theme(self.chrome, self._theme, on_retheme=self._on_theme_changed)
            self._theme.apply()

    def _on_theme_changed(self) -> None:
        # deleteLater from a list ``clear()`` may land between switches —
        # drop wrappers whose C++ side died instead of aborting the loop.
        alive: list[_EntityItemWidget] = []
        for widget in self._item_widgets:
            try:
                widget.retheme()
            except RuntimeError:
                continue
            alive.append(widget)
        self._item_widgets = alive

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.chrome = QWidget()
        self.chrome.setObjectName("detailPanelChrome")  # identifier, not style
        outer.addWidget(self.chrome)
        layout = QVBoxLayout(self.chrome)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.title_label = title("")
        layout.addWidget(self.title_label)

        self.date_label = QLabel("")
        layout.addWidget(self.date_label)

        self.tabs = QTabWidget()
        self.org_list = QListWidget()
        self.char_list = QListWidget()
        self.item_list = QListWidget()
        self.loc_list = QListWidget()
        # The four related lists: catalog list role (surface/border/selection
        # from tokens) — the OS-palette mid-border inline sheets are gone (W2b).
        for lst in (self.org_list, self.char_list, self.item_list, self.loc_list):
            set_role(lst, "list")

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
        sd = format_game_date(event.start_date)
        ed = format_game_date(event.end_date, "∞")
        self.date_label.setText(f"{sd} — {ed}")
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
        # ``clear()`` destroys the item widgets together with the items — the
        # retheme bookkeeping must not keep the dead wrappers either (W2b fix,
        # not only until the next ``_fill_list`` prunes).
        self._prune_item_widgets()

    def _prune_item_widgets(self) -> None:
        """Drop item widgets whose Qt side is gone (or parentless/orphaned)."""
        alive: list[_EntityItemWidget] = []
        for w in self._item_widgets:
            try:
                if w.parent() is not None:
                    alive.append(w)
            except RuntimeError:  # wrapper destroyed by a list clear/close
                pass
        self._item_widgets = alive

    def _fill_list(self, list_widget: QListWidget, entities: list, entity_type: str) -> None:
        # ``clear()`` destroys the old item widgets; the reference list is
        # pruned of every dead wrapper so a live theme re-render can never
        # touch a deleted one.
        list_widget.clear()
        self._prune_item_widgets()
        for entity in entities:
            name = getattr(entity, "name", str(entity))
            summary = _build_summary(entity, entity_type)

            # Rating
            rating_val = getattr(entity, "rating", 1)
            if not isinstance(rating_val, int):
                rating_val = 1

            # Thumbnail for entities with an image (file-backed, design D10)
            thumbnail = load_entity_preview(entity, slot_size=100)

            widget = _EntityItemWidget(
                name, summary, thumbnail=thumbnail, rating=rating_val,
                runtime=self._theme,
            )
            self._item_widgets.append(widget)
            widget.image_clicked.connect(lambda e=entity: self._open_image_viewer(e))
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

    def _open_image_viewer(self, entity: Any) -> None:
        original = load_entity_original(entity)
        preview = load_entity_preview(entity, slot_size=4096)
        ImageViewerDialog(original, preview, parent=self, theme=self._theme).exec()
