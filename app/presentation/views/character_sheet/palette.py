"""Character-sheet palette: pointer + the closed field-type catalog (D7).

A vertical column of exclusive checkable tools. There is deliberately no
font-family picker anywhere — every field uses one bundled font, only the size
is adjustable (in the property panel). Placement is one-shot (pick a type,
click a page, the tool resets to the pointer).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.presentation.viewmodels.character_sheet_viewmodel import (
    TOOL_PLACE_CHECKBOX,
    TOOL_PLACE_DROPDOWN,
    TOOL_PLACE_IMAGE,
    TOOL_PLACE_LABEL,
    TOOL_PLACE_LINE,
    TOOL_PLACE_NUMBER,
    TOOL_PLACE_RECT,
    TOOL_PLACE_TEXT,
    TOOL_PLACE_TEXTAREA,
    TOOL_POINTER,
)

# (label, tool) — pointer first, then the A-playable catalog in the order
# of the spec (design D7: pointer + 9 types).
_BUTTONS: tuple[tuple[str, str], ...] = (
    ("Указатель", TOOL_POINTER),
    ("Подпись", TOOL_PLACE_LABEL),
    ("Поле", TOOL_PLACE_TEXT),
    ("Область", TOOL_PLACE_TEXTAREA),
    ("Чекбокс", TOOL_PLACE_CHECKBOX),
    ("Число", TOOL_PLACE_NUMBER),
    ("Список", TOOL_PLACE_DROPDOWN),
    ("Картинка", TOOL_PLACE_IMAGE),
    ("Рамка", TOOL_PLACE_RECT),
    ("Линия", TOOL_PLACE_LINE),
)


class SheetPalette(QWidget):
    """Emits ``tool_requested(tool)`` when the user picks a tool."""

    tool_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        # tool -> its button (per instance); ``set_active_tool`` mirrors the
        # VM's tool through it
        self._buttons: dict[str, QToolButton] = {}

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)

        self.pointer_button = self._add_button("Указатель", TOOL_POINTER)
        self.label_button = self._add_button("Подпись", TOOL_PLACE_LABEL)
        self.text_button = self._add_button("Поле", TOOL_PLACE_TEXT)
        self.textarea_button = self._add_button("Область", TOOL_PLACE_TEXTAREA)
        self.checkbox_button = self._add_button("Чекбокс", TOOL_PLACE_CHECKBOX)
        self.number_button = self._add_button("Число", TOOL_PLACE_NUMBER)
        self.dropdown_button = self._add_button("Список", TOOL_PLACE_DROPDOWN)
        self.image_button = self._add_button("Картинка", TOOL_PLACE_IMAGE)
        self.rect_button = self._add_button("Рамка", TOOL_PLACE_RECT)
        self.line_button = self._add_button("Линия", TOOL_PLACE_LINE)
        self.pointer_button.setChecked(True)

        self._layout.addStretch(1)

    def _add_button(self, text: str, tool: str) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        button.setCheckable(True)
        button.setMinimumHeight(32)
        button.setToolTip(f"Инструмент: {text.lower()}")
        button.clicked.connect(lambda _checked=False, t=tool: self.tool_requested.emit(t))
        self.group.addButton(button)
        self._layout.addWidget(button)
        self._buttons[tool] = button
        return button

    def set_active_tool(self, tool: str) -> None:
        """Mirror the VM's tool (design D7 one-shot placement).

        After a placement the VM resets the tool to the pointer and emits
        ``tool_changed`` — the buttons must follow, otherwise the palette
        keeps showing the place tool as active while the canvas already
        selects instead of placing.
        """
        if tool not in self._buttons:
            return
        self.group.blockSignals(True)
        try:
            for t, button in self._buttons.items():
                button.setChecked(t == tool)
        finally:
            self.group.blockSignals(False)
