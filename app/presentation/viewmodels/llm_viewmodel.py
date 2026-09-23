"""LLM ViewModel — connection config, status, world/field prompts, generation proxy."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal

from app.application.services.llm_service import LlmService
from app.application.services.llm_status import LlmStatus
from app.domain import entity_registry
from app.infrastructure.llm.base_provider import BaseLlmProvider
from app.infrastructure.llm.config import LlmConfig, LlmConfigManager
from app.infrastructure.llm.errors import LlmError


@dataclass(frozen=True)
class GenerationTarget:
    """Everything one field generation needs to know (audit B1, design D6).

    Replaces the six positional parameters of the former
    ``request_generation``/``_launch`` pair: one immutable value built by
    the AI generation controller from a dialog's button (or its emitted
    signal) and consumed whole by :meth:`LlmViewModel.request_generation`.
    """

    field_id: str  # "{entity_type}.{field_name}" — the delivery-signal key
    entity_type: str
    field_name: str
    field_label: str
    current_text: str
    owner: Any = None  # host dialog (delivery/registration scoping)


def _default_field_prompts() -> dict[str, dict[str, str]]:
    # generated field set comes from the entity registry (wave 3, finding A4)
    return {
        desc.key: {f: "" for f in desc.llm_fields}
        for desc in map(entity_registry.descriptor, entity_registry.LLM_TYPES)
    }


class LlmViewModel(QObject):
    model_status_changed = Signal(str)
    generation_started = Signal(str)
    #: (owner, field_id, text) / (owner, field_id, reason). The owner (the
    #: host dialog) is delivered with the signal: every dialog's handlers
    #: filter on ``owner is dialog``, so a nested card of the same entity
    #: type (same field_id) cannot receive another dialog's result.
    generation_finished = Signal(object, str, str)
    generation_error = Signal(object, str, str)

    def __init__(
        self,
        llm_service: LlmService,
        config_manager: LlmConfigManager,
        provider_factory: Callable[[LlmConfig], BaseLlmProvider],
        parent: QObject | None = None,
    ) -> None:
        """``provider_factory`` comes from the composition root (nri-0011, D2):
        the ViewModel never names a concrete provider class itself.
        """
        super().__init__(parent)
        self._service = llm_service
        self._config_manager = config_manager
        self._provider_factory = provider_factory
        self._world_prompt: str = ""
        self._field_prompts: dict[str, dict[str, str]] = _default_field_prompts()

        loaded = config_manager.load()
        self._config: LlmConfig = loaded if loaded is not None else LlmConfig()
        self._service.provider = self._provider_factory(self._config)
        self._status: str = (
            LlmStatus.READY if self._config.is_complete else LlmStatus.NOT_CONFIGURED
        )

    def apply_config(self, config: LlmConfig) -> None:
        """Apply a new connection config: recreate provider, update status.

        Readiness depends only on the stored config values (no network).
        """
        self._config = config
        self._service.provider = self._provider_factory(config)
        self.set_status(LlmStatus.READY if config.is_complete else LlmStatus.NOT_CONFIGURED)

    async def check_connection(self, config: LlmConfig) -> str | None:
        """Probe the entered settings with a throwaway provider (nri-0011, D2).

        Checks are owned by the ViewModel, not the dialog: the provider is
        built through the injected factory, used once and dropped. Returns
        ``None`` on success, otherwise the displayable error text (every
        provider failure is an ``LlmError`` whose ``str`` is user-facing).
        """
        provider = self._provider_factory(config)
        try:
            await provider.check_connection()
        except LlmError as exc:
            return str(exc)
        return None

    @property
    def config(self) -> LlmConfig:
        return self._config

    @property
    def status(self) -> str:
        return self._status

    def set_status(self, status: str) -> None:
        if self._status != status:
            self._status = status
            self.model_status_changed.emit(status)

    @property
    def world_prompt(self) -> str:
        return self._world_prompt

    @world_prompt.setter
    def world_prompt(self, value: str) -> None:
        self._world_prompt = value

    @property
    def has_world_prompt(self) -> bool:
        return bool(self._world_prompt.strip())

    @property
    def field_prompts(self) -> dict[str, dict[str, str]]:
        return self._field_prompts

    @field_prompts.setter
    def field_prompts(self, value: dict[str, dict[str, str]] | None) -> None:
        merged = _default_field_prompts()
        for etype, fields in (value or {}).items():
            if etype in merged:
                for fname, prompt in fields.items():
                    if fname in merged[etype]:
                        merged[etype][fname] = prompt
        self._field_prompts = merged

    def get_field_prompt(self, entity_type: str, field_name: str) -> str:
        return self._field_prompts.get(entity_type, {}).get(field_name, "")

    def is_generation_available(self) -> bool:
        return self._status == LlmStatus.READY and self.has_world_prompt

    async def request_generation(self, target: GenerationTarget) -> None:
        log = logging.getLogger(__name__)

        field_prompt = self.get_field_prompt(target.entity_type, target.field_name)
        self.generation_started.emit(target.field_id)
        log.info(
            "Generation requested: %s (prompt=%r)",
            target.field_id, field_prompt[:50] if field_prompt else "",
        )
        try:
            result = await self._service.generate_for_field(
                field_id=target.field_id,
                entity_type=target.entity_type,
                world_prompt=self._world_prompt,
                field_prompt=field_prompt,
                field_label=target.field_label,
                current_text=target.current_text,
                owner=target.owner,
            )
            log.info("Generation finished: %s (%d chars)", target.field_id, len(result))
            self.generation_finished.emit(target.owner, target.field_id, result)
        except Exception as exc:
            log.error("Generation error: %s — %s", target.field_id, exc)
            self.generation_error.emit(target.owner, target.field_id, str(exc))

    def world_prompt_to_json(self) -> str:
        return json.dumps(self._world_prompt, ensure_ascii=False)

    def world_prompt_from_json(self, raw: str) -> None:
        try:
            self._world_prompt = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            self._world_prompt = ""

    def field_prompts_to_json(self) -> str:
        return json.dumps(self._field_prompts, ensure_ascii=False)

    def field_prompts_from_json(self, raw: str) -> None:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                self.field_prompts = data
        except (json.JSONDecodeError, TypeError):
            self._field_prompts = _default_field_prompts()
