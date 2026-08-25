"""Left palette: one button per field type (9 types, task 6.3)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget

from app.domain.enums.field_type import FieldType

#: (FieldType, RU button label) in palette order
_ITEMS: list[tuple[FieldType, str]] = [
    (FieldType.HEADING, "Заголовок"),
    (FieldType.STATIC_TEXT, "Свободный текст"),
    (FieldType.SHORT_TEXT, "Короткий текст"),
    (FieldType.LONG_TEXT, "Длинный текст"),
    (FieldType.NUMBER, "Число"),
    (FieldType.DATE, "Дата"),
    (FieldType.DROPDOWN, "Список"),
    (FieldType.CHECKBOX, "Чекбокс"),
    (FieldType.PORTRAIT, "Портрет"),
]


class ItemsPalette(QFrame):
    field_type_clicked = Signal(FieldType)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        self._buttons: dict[FieldType, QPushButton] = {}
        for field_type, label in _ITEMS:
            button = QPushButton(label)
            button.setFixedWidth(150)
            button.clicked.connect(lambda _=False, ft=field_type: self.field_type_clicked.emit(ft))
            layout.addWidget(button)
            self._buttons[field_type] = button
        layout.addStretch(1)

    def button_for(self, field_type: FieldType) -> QPushButton:
        return self._buttons[field_type]
