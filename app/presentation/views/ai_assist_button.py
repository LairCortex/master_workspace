"""AI assist button — sits to the right of a field in the same row; triggers LLM generation."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QTextEdit, QWidget,
)


class AiAssistButton(QPushButton):
    """Square button placed next to a text field; triggers LLM generation.

    The host dialog adds the button to the field's row layout (see
    ``_make_ai_row`` in EventDialog / EntityCardDialog), so the button
    follows the field with the layout — no manual positioning.
    """

    generate_requested = Signal(str, str, str, str)  # entity_type, field_name, field_label, current_text

    _ACTIVE_STYLE = (
        "QPushButton { background: rgba(91,155,213,0.25); border: 1px solid rgba(91,155,213,0.5);"
        " border-radius: 4px; font-size: 14px; }"
        "QPushButton:hover { background: rgba(91,155,213,0.45); }"
    )
    _DISABLED_STYLE = (
        "QPushButton { background: rgba(128,128,128,0.15); border: 1px solid rgba(128,128,128,0.3);"
        " border-radius: 4px; font-size: 14px; color: rgba(128,128,128,0.6); }"
    )

    def __init__(
        self,
        target_widget: QWidget,
        entity_type: str,
        field_name: str,
        field_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("\u2728", parent or target_widget)
        self._target = target_widget
        self._entity_type = entity_type
        self._field_name = field_name
        self._field_label = field_label
        self._llm_status: str = "not_configured"
        self._has_world_prompt: bool = False
        self._generating: bool = False

        self.setFixedSize(QSize(24, 24))
        self.setToolTip("AI-ассистент")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._on_clicked)

        # The indeterminate progress bar stays an overlay on the field itself
        # (repositioned on its resize/move); the button is layout-managed.
        self._progress = QProgressBar(target_widget)
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.hide()

        self._target.installEventFilter(self)
        self._reposition_progress()
        self.update_llm_state("not_configured", False)

    @property
    def entity_type(self) -> str:
        return self._entity_type

    @property
    def field_name(self) -> str:
        return self._field_name

    @property
    def field_label(self) -> str:
        return self._field_label

    @property
    def is_generating(self) -> bool:
        return self._generating

    def update_llm_state(self, status: str, has_world_prompt: bool) -> None:
        self._llm_status = status
        self._has_world_prompt = has_world_prompt
        is_active = status == "ready" and has_world_prompt
        self.setStyleSheet(self._ACTIVE_STYLE if is_active else self._DISABLED_STYLE)

    def set_generating(self, generating: bool) -> None:
        self._generating = generating
        if generating:
            # Disable in place: hiding a layout-managed button would make
            # the row reflow while generation is in flight.
            self.setEnabled(False)
            self._progress.show()
            self._set_target_readonly(True)
        else:
            self._progress.hide()
            self.setEnabled(True)
            self._set_target_readonly(False)

    def set_result_text(self, text: str) -> None:
        if isinstance(self._target, QTextEdit):
            self._target.setPlainText(text)
        elif isinstance(self._target, QLineEdit):
            self._target.setText(text)
        self.set_generating(False)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._target and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
        ):
            self._reposition_progress()
        return False

    def _reposition_progress(self) -> None:
        """Stretch the progress overlay across the field's bottom edge."""
        tr = self._target.rect()
        self._progress.setFixedWidth(tr.width())
        self._progress.move(tr.left(), tr.bottom() - 4)

    def _set_target_readonly(self, readonly: bool) -> None:
        if isinstance(self._target, QTextEdit):
            self._target.setReadOnly(readonly)
        elif isinstance(self._target, QLineEdit):
            self._target.setReadOnly(readonly)

    def _get_current_text(self) -> str:
        if isinstance(self._target, QTextEdit):
            if hasattr(self._target, "getContent"):
                return self._target.getContent()
            return self._target.toPlainText()
        if isinstance(self._target, QLineEdit):
            return self._target.text()
        return ""

    def _on_clicked(self) -> None:
        if self._generating:
            return

        if self._llm_status != "ready":
            QMessageBox.information(
                self,
                "AI-ассистент",
                "AI-ассистент не настроен.\n"
                "Настройте LLM в меню LLM → Настройка LLM…\n"
                "(укажите endpoint, модель и при необходимости ключ API).",
            )
            return

        if not self._has_world_prompt:
            QMessageBox.information(
                self,
                "AI-ассистент",
                "Не задан промт мира.\n"
                "Перейдите в меню LLM → Настройка LLM… и опишите ваш мир.",
            )
            return

        current_text = self._get_current_text()
        self.generate_requested.emit(
            self._entity_type,
            self._field_name,
            self._field_label,
            current_text,
        )
