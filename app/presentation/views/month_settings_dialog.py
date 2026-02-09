"""Dialog for configuring custom month names."""
from __future__ import annotations

from typing import Dict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from app.presentation.utils.date_utils import DEFAULT_MONTHS


class MonthSettingsDialog(QDialog):
    """Dialog with 12 input fields for custom month names."""

    saved = Signal(object)  # emits {1: "Name", 2: "Name", ...}

    def __init__(self, current_months: Dict[int, str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Названия месяцев")
        self.setMinimumWidth(380)
        self._inputs: Dict[int, QLineEdit] = {}
        self._init_ui(current_months or DEFAULT_MONTHS)

    def _init_ui(self, months: Dict[int, str]) -> None:
        layout = QVBoxLayout(self)

        hint = QLabel("Оставьте пустым для стандартного названия")
        hint.setStyleSheet("color: #888; font-style: italic; margin-bottom: 6px;")
        layout.addWidget(hint)

        form = QFormLayout()
        for i in range(1, 13):
            inp = QLineEdit()
            default = DEFAULT_MONTHS[i]
            custom = months.get(i, default)
            inp.setPlaceholderText(default)
            if custom != default:
                inp.setText(custom)
            self._inputs[i] = inp
            form.addRow(f"{i:2d}. {default}:", inp)
        layout.addLayout(form)

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
        layout.addLayout(btn_row)

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
