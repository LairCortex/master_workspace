"""Dialog for configuring custom month names."""
from __future__ import annotations

from typing import Dict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from app.presentation.theme.catalog import attach_theme, hint, set_role
from app.presentation.utils.date_utils import DEFAULT_MONTHS

#: Extra gap under the hint label — the pre-catalog inline style carried
#: ``margin-bottom: 6px``, which the generic hint rule does not repeat.
HINT_BOTTOM_GAP = 6


class MonthSettingsDialog(QDialog):
    """Dialog with 12 input fields for custom month names.

    W2a pilot: the chrome container is attached to the theme (one call),
    hints come from the catalog factory — no inline colors.
    """

    saved = Signal(object)  # emits {1: "Name", 2: "Name", ...}

    def __init__(
        self,
        current_months: Dict[int, str] | None = None,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Названия месяцев")
        self.setMinimumWidth(380)
        self._inputs: Dict[int, QLineEdit] = {}
        self._init_ui(current_months or DEFAULT_MONTHS)
        self._apply_theme()

    def _apply_theme(self) -> None:
        """One attach point: the chrome container carries the whole sheet (D1)."""
        if self._theme is not None:
            attach_theme(self.chrome, self._theme)
            self._theme.apply()

    def _init_ui(self, months: Dict[int, str]) -> None:
        layout = QVBoxLayout(self)
        # Like the launcher (W1): the chrome reaches the dialog edges so no
        # OS-palette band frames it.
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.chrome = QWidget()
        self.chrome.setObjectName("monthSettingsChrome")  # identifier, not style
        layout.addWidget(self.chrome)
        chrome_layout = QVBoxLayout(self.chrome)
        chrome_layout.setContentsMargins(11, 11, 11, 11)
        chrome_layout.setSpacing(6)

        chrome_layout.addWidget(hint("Оставьте пустым для стандартного названия", italic=True))
        # The first field used to sit 6px lower (the old inline hint carried
        # ``margin-bottom: 6px``); the catalog hint rule is generic, so the gap
        # is restored as layout spacing on this screen.
        chrome_layout.addSpacing(HINT_BOTTOM_GAP)

        form = QFormLayout()
        for i in range(1, 13):
            inp = QLineEdit()
            set_role(inp, "field")
            default = DEFAULT_MONTHS[i]
            custom = months.get(i, default)
            inp.setPlaceholderText(default)
            if custom != default:
                inp.setText(custom)
            self._inputs[i] = inp
            form.addRow(f"{i:2d}. {default}:", inp)
        chrome_layout.addLayout(form)

        btn_row = QHBoxLayout()
        reset_btn = QPushButton("Сбросить")
        reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        save_btn = QPushButton("Сохранить")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        chrome_layout.addLayout(btn_row)

    def _on_save(self) -> None:
        result: Dict[int, str] = {}
        for i, inp in self._inputs.items():
            text = inp.text().strip()
            result[i] = text if text else DEFAULT_MONTHS[i]
        self.saved.emit(result)
        self.accept()

    def _on_reset(self) -> None:
        for inp in self._inputs.values():
            inp.clear()
