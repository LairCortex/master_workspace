"""AI assist buttons: per-field ``AiAssistButton`` and the per-dialog
``EntityGenerateButton`` (start/cancel a generation wave for all fields)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QTextEdit, QWidget,
)

#: Hints shared by field buttons and the entity button (same wording in both).
NOT_CONFIGURED_MESSAGE = (
    "AI-ассистент не настроен.\n"
    "Настройте LLM в меню LLM → Настройка LLM…\n"
    "(укажите endpoint, модель и при необходимости ключ API)."
)
NO_WORLD_PROMPT_MESSAGE = (
    "Не задан промт мира.\n"
    "Перейдите в меню LLM → Настройка LLM… и опишите ваш мир."
)

#: Shared button styles. W2a: e2e assertions read the ``aiState`` dynamic
#: property instead of grepping these rgba substrings; migrating the colors
#: themselves to tokens is W2b work.
ACTIVE_STYLE = (
    "QPushButton { background: rgba(91,155,213,0.25); border: 1px solid rgba(91,155,213,0.5);"
    " border-radius: 4px; font-size: 14px; }"
    "QPushButton:hover { background: rgba(91,155,213,0.45); }"
)
DISABLED_STYLE = (
    "QPushButton { background: rgba(128,128,128,0.15); border: 1px solid rgba(128,128,128,0.3);"
    " border-radius: 4px; font-size: 14px; color: rgba(128,128,128,0.6); }"
)

#: State marker of both AI buttons (W2a D5): tests select by marker, never by
#: the rgba colors above. Read it only through ``ai_state_is``.
AI_STATE_PROPERTY = "aiState"
AI_STATE_ACTIVE = "active"
AI_STATE_DISABLED = "disabled"


def ai_state_is(widget: QWidget, state: str) -> bool:
    """True when ``widget`` carries the ``aiState`` marker equal to ``state``.

    This is the marker check the e2e selectors use, kept in one place. The
    C++ original (``QObject::testProperty``) is protected and PySide6 does not
    expose it, so the check is spelled out: the marker must be present among
    the widget's dynamic properties and compare equal to ``state`` (a missing
    marker is ``False``, not ``None == state`` games).
    """
    declared = {bytes(name).decode() for name in widget.dynamicPropertyNames()}
    return AI_STATE_PROPERTY in declared and widget.property(AI_STATE_PROPERTY) == state


class AiAssistButton(QPushButton):
    """Square button placed next to a text field; triggers LLM generation.

    The host dialog adds the button to the field's row layout (see
    ``_make_ai_row`` in EventDialog / EntityCardDialog), so the button
    follows the field with the layout — no manual positioning.
    """

    generate_requested = Signal(str, str, str, str)  # entity_type, field_name, field_label, current_text

    _ACTIVE_STYLE = ACTIVE_STYLE
    _DISABLED_STYLE = DISABLED_STYLE

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

    @property
    def current_text(self) -> str:
        "Current field text (mentions preserved for MentionTextEdit targets)."
        return self._get_current_text()

    def update_llm_state(self, status: str, has_world_prompt: bool) -> None:
        self._llm_status = status
        self._has_world_prompt = has_world_prompt
        is_active = status == "ready" and has_world_prompt
        self.setStyleSheet(self._ACTIVE_STYLE if is_active else self._DISABLED_STYLE)
        # W2a e2e marker: tests switch on this property, not rgba substrings
        # (the colors themselves migrate in W2b).
        self.setProperty(AI_STATE_PROPERTY, AI_STATE_ACTIVE if is_active else AI_STATE_DISABLED)

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
            QMessageBox.information(self, "AI-ассистент", NOT_CONFIGURED_MESSAGE)
            return

        if not self._has_world_prompt:
            QMessageBox.information(self, "AI-ассистент", NO_WORLD_PROMPT_MESSAGE)
            return

        current_text = self._get_current_text()
        self.generate_requested.emit(
            self._entity_type,
            self._field_name,
            self._field_label,
            current_text,
        )


class EntityGenerateButton(QPushButton):
    """24×24 ✓ button in the top-right corner of the dialog form.

    Starts the LLM generation wave for every AI field of the dialog and,
    while the wave is running, becomes its cancel:

    - idle: ✨ — click emits ``batch_requested`` (when the assistant is
      ready) or shows the same hint as the field buttons (not ready);
    - wave in flight: ⏹ — click emits ``batch_cancel_requested``;
    - a single field generation is in flight: truly disabled, no signals.
    """

    batch_requested = Signal()
    batch_cancel_requested = Signal()

    IDLE_ICON = "\u2728"  # ✨
    CANCEL_ICON = "\u23f9"  # ⏹
    IDLE_TOOLTIP = "Сгенерировать сущность (все поля)"
    CANCEL_TOOLTIP = "Отменить генерацию"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(self.IDLE_ICON, parent)
        self._llm_status: str = "not_configured"
        self._has_world_prompt: bool = False
        self._wave_in_flight: bool = False
        self._single_in_flight: bool = False

        self.setFixedSize(QSize(24, 24))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._on_clicked)

        self.update_llm_state("not_configured", False)

    @property
    def is_cancelling(self) -> bool:
        return self._wave_in_flight

    def update_llm_state(self, status: str, has_world_prompt: bool) -> None:
        self._llm_status = status
        self._has_world_prompt = has_world_prompt
        self._refresh()

    def set_wave_running(self, running: bool) -> None:
        """A batch wave is running: the button becomes the cancel control."""
        self._wave_in_flight = running
        self._refresh()

    def set_single_in_flight(self, running: bool) -> None:
        """A single field generation is running: at most one wave per dialog."""
        self._single_in_flight = running
        self._refresh()

    def _refresh(self) -> None:
        if self._wave_in_flight:
            self.setText(self.CANCEL_ICON)
            self.setToolTip(self.CANCEL_TOOLTIP)
            self.setStyleSheet(ACTIVE_STYLE)
            self.setProperty(AI_STATE_PROPERTY, AI_STATE_ACTIVE)
            self.setEnabled(True)
            return

        self.setText(self.IDLE_ICON)
        self.setToolTip(self.IDLE_TOOLTIP)
        if self._single_in_flight:
            self.setStyleSheet(DISABLED_STYLE)
            self.setProperty(AI_STATE_PROPERTY, AI_STATE_DISABLED)
            self.setEnabled(False)
            return

        is_ready = self._llm_status == "ready" and self._has_world_prompt
        self.setStyleSheet(ACTIVE_STYLE if is_ready else DISABLED_STYLE)
        # W2a e2e marker (see AiAssistButton.update_llm_state), colors — W2b.
        self.setProperty(AI_STATE_PROPERTY, AI_STATE_ACTIVE if is_ready else AI_STATE_DISABLED)
        # Clickable even when not ready: the click shows the hint message
        # (same behavior as the field buttons).
        self.setEnabled(True)

    def _on_clicked(self) -> None:
        if self._wave_in_flight:
            self.batch_cancel_requested.emit()
            return
        if self._single_in_flight:
            return
        if self._llm_status != "ready":
            QMessageBox.information(self, "AI-ассистент", NOT_CONFIGURED_MESSAGE)
            return
        if not self._has_world_prompt:
            QMessageBox.information(self, "AI-ассистент", NO_WORLD_PROMPT_MESSAGE)
            return
        self.batch_requested.emit()
