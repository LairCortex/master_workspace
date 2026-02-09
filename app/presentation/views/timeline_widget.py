"""Timeline widget — list of events on the left panel with date range filter."""
from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtCore import QDate, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDateEdit, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from app.presentation.utils.date_utils import format_game_date
from app.presentation.views.custom_date_edit import CustomDateEdit


class TimelineWidget(QWidget):
    event_selected = Signal(int)
    event_double_clicked = Signal(int)  # event_id
    add_event_requested = Signal()
    filter_changed = Signal(object, object)  # (start_date | None, end_date | None)

    def __init__(self, timeline_vm, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = timeline_vm
        self._filter_active = False
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header
        header = QHBoxLayout()
        title = QLabel("Таймлайн событий")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        header.addWidget(title)
        header.addStretch()

        self.add_button = QPushButton("+")
        self.add_button.setFixedSize(30, 30)
        self.add_button.setToolTip("Добавить событие")
        self.add_button.clicked.connect(self.add_event_requested.emit)
        header.addWidget(self.add_button)
        layout.addLayout(header)

        # Date range filter
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(4)

        filter_layout.addWidget(QLabel("С:"))
        self.filter_start = CustomDateEdit()
        self.filter_start.setDate(QDate(100, 1, 1))
        filter_layout.addWidget(self.filter_start, 1)

        filter_layout.addWidget(QLabel("По:"))
        self.filter_end = CustomDateEdit()
        self.filter_end.setDate(QDate.currentDate())
        filter_layout.addWidget(self.filter_end, 1)

        self.filter_button = QPushButton("▶")
        self.filter_button.setFixedSize(30, 30)
        self.filter_button.setToolTip("Применить фильтр по датам")
        self.filter_button.clicked.connect(self._on_apply_filter)
        filter_layout.addWidget(self.filter_button)

        self.clear_filter_button = QPushButton("✕")
        self.clear_filter_button.setFixedSize(30, 30)
        self.clear_filter_button.setToolTip("Сбросить фильтр")
        self.clear_filter_button.clicked.connect(self._on_clear_filter)
        self.clear_filter_button.setEnabled(False)
        filter_layout.addWidget(self.clear_filter_button)

        layout.addLayout(filter_layout)

        # Event list
        self.list_widget = QListWidget()
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setStyleSheet(
            "QListWidget { font-size: 13px; }"
            "QListWidget::item { border-bottom: 1px solid palette(mid); padding: 4px 6px; }"
            "QListWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }"
        )
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.list_widget, 1)

    def update_events(self, events: Sequence[Any]) -> None:
        self.list_widget.clear()
        for i, event in enumerate(events):
            start = format_game_date(event.start_date)
            end = format_game_date(event.end_date, "∞")
            text = f"{start} — {end}\n{event.name}"
            item = QListWidgetItem(text)
            item.setData(256, event)  # Qt.UserRole = 256
            item.setSizeHint(QSize(0, 52))
            self.list_widget.addItem(item)

    def _on_row_changed(self, row: int) -> None:
        self.event_selected.emit(row)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        event = item.data(256)
        if event and hasattr(event, "id"):
            self.event_double_clicked.emit(event.id)

    def _on_apply_filter(self) -> None:
        start = self.filter_start.date().toPython()
        end = self.filter_end.date().toPython()
        self._filter_active = True
        self.clear_filter_button.setEnabled(True)
        self.filter_changed.emit(start, end)

    def _on_clear_filter(self) -> None:
        self._filter_active = False
        self.clear_filter_button.setEnabled(False)
        self.filter_changed.emit(None, None)
