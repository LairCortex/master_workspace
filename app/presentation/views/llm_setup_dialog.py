"""LLM setup wizard — connection, world prompt and field prompts."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QStackedWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from app.application.services.llm_service import FIELD_CONFIG, FIELD_LABELS

_ENTITY_LABELS: dict[str, str] = {
    "event": "События",
    "organization": "Организации",
    "character": "Персонажи",
    "item": "Предметы",
    "location": "Локации",
}

_ENTITY_ORDER = ["event", "organization", "character", "item", "location"]

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
    saved = Signal(str, dict)  # (world_prompt, field_prompts_dict)

    def __init__(
        self,
        world_prompt: str = "",
        field_prompts: dict[str, dict[str, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройка AI-ассистента (LLM)")
        self.setMinimumSize(620, 480)
        self._world_prompt_initial = world_prompt
        self._field_prompts_initial = field_prompts or {}
        self._field_pages: dict[str, _FieldPromptsPage] = {}
        self._init_ui()
        self._update_nav_buttons()

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

        title = QLabel("Шаг 1: Подключение")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        self._connection_info = QLabel("Подключение настраивается в этом диалоге.")
        self._connection_info.setWordWrap(True)
        layout.addWidget(self._connection_info)

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
        ]
        for text in warnings:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("margin-bottom: 6px;")
            layout.addWidget(lbl)

        layout.addStretch()
        return page

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
        world_prompt = self._world_prompt_edit.toPlainText().strip()
        field_prompts: dict[str, dict[str, str]] = {}
        for etype, page in self._field_pages.items():
            field_prompts[etype] = page.get_prompts()
        self.saved.emit(world_prompt, field_prompts)
        self.accept()

    def get_world_prompt(self) -> str:
        return self._world_prompt_edit.toPlainText().strip()

    def get_field_prompts(self) -> dict[str, dict[str, str]]:
        return {etype: page.get_prompts() for etype, page in self._field_pages.items()}

    @property
    def page_count(self) -> int:
        return self._stack.count()
