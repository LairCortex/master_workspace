"""LLM setup wizard — QML island (R3 pack 2) in the old QDialog facade.

The dialog keeps its public contract (``saved``, ``get_connection``,
``get_world_prompt``, ``get_field_prompts``, ``page_count``,
``finish_saving``) and stays the effect boundary: the island only shows the
view model and emits synchronous requests (design D2/D4). The connection
check itself is directed by the LLM view model through its injected provider
factory (nri-0011, design D2) — the facade only displays the outcome.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QVBoxLayout, QWidget

from app.infrastructure.llm.config import LlmConfig
from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH
from app.presentation.qml.island import IslandDialogMixin
from app.presentation.theme import get_default_theme
from app.presentation.viewmodels.llm_setup_view_model import LlmSetupViewModel
from app.presentation.viewmodels.llm_viewmodel import LlmViewModel

ROOT_QML = str(Path(QML_IMPORT_PATH) / "LlmSetupRoot.qml")


class LlmSetupDialog(IslandDialogMixin, QDialog):
    island_context_names = {"llmSetupVm": "vm"}

    def island_source(self) -> str:
        return ROOT_QML

    saved = Signal(object, str, dict)  # (LlmConfig, world_prompt, field_prompts_dict)

    def __init__(
        self,
        config: LlmConfig,
        world_prompt: str = "",
        field_prompts: dict[str, dict[str, str]] | None = None,
        llm_vm: LlmViewModel | None = None,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройка AI-ассистента (LLM)")
        self.setMinimumSize(620, 480)
        self._theme = theme if theme is not None else get_default_theme()
        self._llm_vm = llm_vm
        self._saving = False

        initial = config or LlmConfig()
        self.vm = LlmSetupViewModel(
            endpoint=initial.base_url,
            model=initial.model,
            api_key=initial.api_key,
            world_prompt=world_prompt,
            field_prompts=field_prompts,
            parent=self,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        # Context lives on the dialog, not on the view (IslandDialogMixin):
        # during teardown the QML root must die with ``quick`` before its
        # context is invalidated.
        self.setup_island()
        layout.addWidget(self.quick)

        self.vm.checkRequested.connect(lambda: asyncio.ensure_future(self._on_check()))
        self.vm.saveRequested.connect(self._on_save)

    # ---- closing is blocked while the async save runs (spec D4) ----

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
        self.vm.set_saving(False)
        if success:
            self.accept()
        else:
            QMessageBox.warning(
                self,
                "Настройка LLM",
                "Не удалось сохранить настройки. Попробуйте ещё раз.",
            )

    # ---- values ----

    def get_connection(self) -> LlmConfig:
        return LlmConfig(
            base_url=self.vm.endpoint.strip(),
            model=self.vm.model.strip(),
            api_key=self.vm.apiKey.strip(),
        )

    def get_world_prompt(self) -> str:
        return self.vm.worldPrompt.strip()

    def get_field_prompts(self) -> dict[str, dict[str, str]]:
        return self.vm.field_prompts_dict()

    @property
    def page_count(self) -> int:
        return self.vm.pageCount

    # ---- effects the island only asks for ----

    async def _on_check(self) -> None:
        """Run a minimal test request (1 token) against the entered settings.

        The check itself lives on the LLM view model (nri-0011, design D2);
        the facade only drives it and shows the outcome with the old texts.
        """
        config = self.get_connection()
        if not config.is_complete:
            return

        self.vm.set_check_running("Проверка соединения…")
        error = await self._llm_vm.check_connection(config)
        if error is None:
            self.vm.set_check_result("Соединение установлено", "ok")
        else:
            self.vm.set_check_result(f"Ошибка: {error}", "error")

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
        self.vm.set_saving(True)
        self.saved.emit(config, self.get_world_prompt(), self.get_field_prompts())
        # The dialog accepts itself in finish_saving() once the application
        # has finished the async save.

    # Island lifecycle (context, deferred release) — IslandDialogMixin.
