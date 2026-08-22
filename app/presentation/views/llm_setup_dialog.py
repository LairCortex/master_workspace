"""LLM setup wizard — connection, world prompt and field prompts."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QStackedWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from app.application.services.llm_service import FIELD_CONFIG, FIELD_LABELS
from app.infrastructure.http import AppHttpClient
from app.infrastructure.llm.config import LlmConfig
from app.infrastructure.llm.errors import LlmError
from app.infrastructure.llm.remote_provider import RemoteLlmProvider

_ENTITY_LABELS: dict[str, str] = {
    "event": "События",
    "organization": "Организации",
    "character": "Персонажи",
    "item": "Предметы",
    "location": "Локации",
}

_ENTITY_ORDER = ["event", "organization", "character", "item", "location"]

_ENDPOINT_PLACEHOLDER = (
    "Базовый URL до /v1, например https://api.openai.com/v1"
    " или http://localhost:11434/v1 (Ollama)"
)

_CHECK_OK_STYLE = "color: #2e7d32;"
_CHECK_ERROR_STYLE = "color: #c62828;"


_FIELD_PLACEHOLDERS: dict[str, dict[str, str]] = {
    "event": {
        "name": "Короткое название события в духе мира",
        "characteristics": "Опиши ключевые характеристики события",
        "backstory": "Напиши предысторию не менее 20 слов",
    },
    "organization": {
        "name": "Название организации, подходящее сеттингу",
        "characteristics": "Основные характеристики организации",
        "backstory": "Предыстория организации",
        "tasks": "Текущие задачи и цели организации",
    },
    "character": {
        "name": "Имя персонажа, подходящее миру",
        "characteristics": "Внешность и ключевые черты персонажа",
        "backstory": "Предыстория персонажа не менее 20 слов",
        "personality": "Черты характера и особенности поведения",
        "tasks": "Текущие цели и задачи персонажа",
    },
    "item": {
        "name": "Название предмета в духе мира",
        "characteristics": "Описание и свойства предмета",
        "backstory": "История предмета",
    },
    "location": {
        "name": "Название локации, подходящее сеттингу",
        "characteristics": "Описание и особенности локации",
        "backstory": "История локации",
        "tasks": "Что происходит в этой локации",
    },
}


class _FieldPromptsPage(QWidget):
    """One page of the wizard for configuring field prompts of a single entity type."""

    def __init__(self, entity_type: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entity_type = entity_type
        self._inputs: dict[str, QLineEdit] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel(f"Промты полей — {_ENTITY_LABELS.get(self._entity_type, self._entity_type)}")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        hint = QLabel("Для каждого поля можно задать инструкцию для AI. Пустое поле — используется только название поля.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; margin-bottom: 8px;")
        layout.addWidget(hint)

        form = QFormLayout()
        fields = FIELD_CONFIG.get(self._entity_type, [])
        placeholders = _FIELD_PLACEHOLDERS.get(self._entity_type, {})
        for field_name in fields:
            inp = QLineEdit()
            inp.setPlaceholderText(placeholders.get(field_name, ""))
            self._inputs[field_name] = inp
            label = FIELD_LABELS.get(field_name, field_name)
            form.addRow(f"{label}:", inp)
        layout.addLayout(form)
        layout.addStretch()

    def get_prompts(self) -> dict[str, str]:
        return {name: inp.text().strip() for name, inp in self._inputs.items()}

    def set_prompts(self, prompts: dict[str, str]) -> None:
        for name, text in prompts.items():
            if name in self._inputs:
                self._inputs[name].setText(text)





class LlmSetupDialog(QDialog):
    saved = Signal(object, str, dict)  # (LlmConfig, world_prompt, field_prompts_dict)

    def __init__(
        self,
        config: LlmConfig,
        world_prompt: str = "",
        field_prompts: dict[str, dict[str, str]] | None = None,
        http: AppHttpClient | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройка AI-ассистента (LLM)")
        self.setMinimumSize(620, 480)
        self._initial_config = config or LlmConfig()
        self._world_prompt_initial = world_prompt
        self._field_prompts_initial = field_prompts or {}
        self._http = http
        self._field_pages: dict[str, _FieldPromptsPage] = {}
        self._saving = False
        self._init_ui()
        self._update_nav_buttons()
        self._update_check_button()

    def reject(self) -> None:
        if self._saving:
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self._saving:
            event.ignore()
            return
        super().closeEvent(event)

    def finish_saving(self, success: bool) -> None:
        """Called by the application after the async save has completed.

        The dialog closes only when the save is done, so a shutdown right
        after «Сохранить» cannot race with the write.
        """
        self._saving = False
        if success:
            self.accept()
        else:
            QMessageBox.warning(
                self,
                "Настройка LLM",
                "Не удалось сохранить настройки. Попробуйте ещё раз.",
            )

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)

        self._stack = QStackedWidget()

        # Page 0: connection
        self._connection_page = self._build_connection_page()
        self._stack.addWidget(self._connection_page)

        # Page 1: world prompt
        self._world_page = self._build_world_prompt_page()
        self._stack.addWidget(self._world_page)

        # Pages 2-6: field prompts per entity type
        for etype in _ENTITY_ORDER:
            page = _FieldPromptsPage(etype)
            if etype in self._field_prompts_initial:
                page.set_prompts(self._field_prompts_initial[etype])
            self._field_pages[etype] = page
            self._stack.addWidget(page)

        # Page 7: warnings
        self._warnings_page = self._build_warnings_page()
        self._stack.addWidget(self._warnings_page)

        root.addWidget(self._stack, 1)

        # Navigation
        nav = QHBoxLayout()
        self._back_btn = QPushButton("Назад")
        self._back_btn.clicked.connect(self._go_back)
        self._next_btn = QPushButton("Далее")
        self._next_btn.clicked.connect(self._go_next)
        self._save_btn = QPushButton("Сохранить и закрыть")
        self._save_btn.clicked.connect(self._on_save)
        self._save_btn.hide()
        nav.addWidget(self._back_btn)
        nav.addStretch()
        nav.addWidget(self._next_btn)
        nav.addWidget(self._save_btn)
        root.addLayout(nav)

    def _build_connection_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("Шаг 1: Подключение к LLM")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        hint = QLabel(
            "Поддерживаются любые OpenAI-совместимые серверы:\n"
            "• OpenAI: https://api.openai.com/v1\n"
            "• Ollama: http://localhost:11434/v1\n"
            "• vLLM: http://host:8000/v1\n"
            "• LM Studio: http://localhost:1234/v1"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; margin-bottom: 8px;")
        layout.addWidget(hint)

        form = QFormLayout()

        self._endpoint_edit = QLineEdit()
        self._endpoint_edit.setPlaceholderText(_ENDPOINT_PLACEHOLDER)
        self._endpoint_edit.setText(self._initial_config.base_url)
        self._endpoint_edit.textChanged.connect(self._update_check_button)
        form.addRow("Endpoint:", self._endpoint_edit)

        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText("Название модели, например gpt-4o-mini или llama3")
        self._model_edit.setText(self._initial_config.model)
        self._model_edit.textChanged.connect(self._update_check_button)
        form.addRow("Модель:", self._model_edit)

        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("Ключ API — необязательно для локальных серверов")
        self._key_edit.setText(self._initial_config.api_key)
        form.addRow("Ключ API:", self._key_edit)

        layout.addLayout(form)

        self._check_btn = QPushButton("Проверить соединение")
        self._check_btn.setMinimumHeight(36)
        self._check_btn.clicked.connect(self._on_check)
        layout.addWidget(self._check_btn)

        self._check_label = QLabel("")
        self._check_label.setWordWrap(True)
        layout.addWidget(self._check_label)

        layout.addStretch()
        return page

    def _build_world_prompt_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("Шаг 2: Описание мира")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        hint = QLabel(
            "Опишите мир, в котором вы водите: сеттинг, эпоха, стиль, ключевые особенности.\n"
            "Этот текст будет основным контекстом для всех AI-генераций."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; margin-bottom: 8px;")
        layout.addWidget(hint)

        self._world_prompt_edit = QTextEdit()
        self._world_prompt_edit.setPlaceholderText(
            "Опишите ваш мир: сеттинг, эпоха, стиль, ключевые особенности..."
        )
        self._world_prompt_edit.setPlainText(self._world_prompt_initial)
        layout.addWidget(self._world_prompt_edit, 1)
        return page

    def _build_warnings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("Информация")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        warnings = [
            "• LLM будет редактировать и дополнять ваш текст на основе описания мира.",
            "• Генерация выполняется по одному полю за раз. Если запущено несколько — "
            "они встанут в очередь и будут обработаны последовательно.",
            "• Во время генерации поле будет заблокировано, а окно нельзя будет закрыть.",
            "• Ключ API хранится в локальном файле ~/.nri_manager/llm_config.json "
            "(права 0600, только текущий пользователь).",
        ]
        for text in warnings:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("margin-bottom: 6px;")
            layout.addWidget(lbl)

        layout.addStretch()
        return page

    def _update_check_button(self, *_args) -> None:
        self._check_btn.setEnabled(bool(self._endpoint_edit.text().strip()) and bool(self._model_edit.text().strip()))

    def get_connection(self) -> LlmConfig:
        return LlmConfig(
            base_url=self._endpoint_edit.text().strip(),
            model=self._model_edit.text().strip(),
            api_key=self._key_edit.text().strip(),
        )

    async def _on_check(self) -> None:
        """Run a minimal test request (1 token) against the entered settings."""
        config = self.get_connection()
        if not config.is_complete:
            return

        self._check_btn.setEnabled(False)
        self._check_label.setStyleSheet("")
        self._check_label.setText("Проверка соединения…")

        provider = RemoteLlmProvider(config, self._http)
        try:
            await provider.check_connection()
            self._check_label.setText("Соединение установлено")
            self._check_label.setStyleSheet(_CHECK_OK_STYLE)
        except LlmError as exc:
            self._check_label.setText(f"Ошибка: {exc}")
            self._check_label.setStyleSheet(_CHECK_ERROR_STYLE)
        finally:
            self._update_check_button()

    def _go_back(self) -> None:
        idx = self._stack.currentIndex()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)
        self._update_nav_buttons()

    def _go_next(self) -> None:
        idx = self._stack.currentIndex()
        if idx < self._stack.count() - 1:
            self._stack.setCurrentIndex(idx + 1)
        self._update_nav_buttons()

    def _update_nav_buttons(self) -> None:
        idx = self._stack.currentIndex()
        last = self._stack.count() - 1
        self._back_btn.setEnabled(idx > 0)
        is_last = idx == last
        self._next_btn.setVisible(not is_last)
        self._save_btn.setVisible(is_last)

    def _on_save(self) -> None:
        if self._saving:
            return
        config = self.get_connection()
        if not config.is_complete:
            QMessageBox.warning(
                self,
                "Настройка LLM",
                "Заполните поля «Endpoint» и «Модель», чтобы сохранить подключение.",
            )
            return

        self._saving = True
        world_prompt = self._world_prompt_edit.toPlainText().strip()
        field_prompts = self.get_field_prompts()
        self.saved.emit(config, world_prompt, field_prompts)
        # The dialog accepts itself in finish_saving() once the application
        # has finished the async save.

    def get_world_prompt(self) -> str:
        return self._world_prompt_edit.toPlainText().strip()

    def get_field_prompts(self) -> dict[str, dict[str, str]]:
        return {etype: page.get_prompts() for etype, page in self._field_pages.items()}

    @property
    def page_count(self) -> int:
        return self._stack.count()
