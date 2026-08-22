"""LLM ViewModel — connection status, world/field prompts, generation proxy."""
from __future__ import annotations

import json
import logging

from PySide6.QtCore import QObject, Signal

from app.application.services.llm_service import FIELD_CONFIG, LlmService

WORLD_PROMPT_KEY = "llm_world_prompt"
FIELD_PROMPTS_KEY = "llm_field_prompts"


def _default_field_prompts() -> dict[str, dict[str, str]]:
    return {etype: {f: "" for f in fields} for etype, fields in FIELD_CONFIG.items()}


class LlmViewModel(QObject):
    model_status_changed = Signal(str)
    generation_started = Signal(str)
    generation_finished = Signal(str, str)
    generation_error = Signal(str, str)
    queue_size_changed = Signal(int)

    STATUS_NOT_CONFIGURED = "not_configured"
    STATUS_READY = "ready"

    def __init__(
        self,
        llm_service: LlmService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = llm_service
        self._world_prompt: str = ""
        self._field_prompts: dict[str, dict[str, str]] = _default_field_prompts()
        self._status: str = (
            self.STATUS_READY
            if self._service.provider.is_configured()
            else self.STATUS_NOT_CONFIGURED
        )

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
    def field_prompts(self, value: dict[str, dict[str, str]]) -> None:
        merged = _default_field_prompts()
        for etype, fields in value.items():
            if etype in merged:
                for fname, prompt in fields.items():
                    if fname in merged[etype]:
                        merged[etype][fname] = prompt
        self._field_prompts = merged

    def get_field_prompt(self, entity_type: str, field_name: str) -> str:
        return self._field_prompts.get(entity_type, {}).get(field_name, "")

    def is_generation_available(self) -> bool:
        return self._status == self.STATUS_READY and self.has_world_prompt

    async def request_generation(
        self,
        field_id: str,
        entity_type: str,
        field_name: str,
        field_label: str,
        current_text: str,
    ) -> None:
        log = logging.getLogger(__name__)

        field_prompt = self.get_field_prompt(entity_type, field_name)
        self.generation_started.emit(field_id)
        self.queue_size_changed.emit(self._service.queue_size + 1)
        log.info("Generation requested: %s (prompt=%r)", field_id, field_prompt[:50] if field_prompt else "")
        try:
            result = await self._service.generate_for_field(
                field_id=field_id,
                entity_type=entity_type,
                world_prompt=self._world_prompt,
                field_prompt=field_prompt,
                field_label=field_label,
                current_text=current_text,
            )
            log.info("Generation finished: %s (%d chars)", field_id, len(result))
            self.generation_finished.emit(field_id, result)
        except Exception as exc:
            log.error("Generation error: %s — %s", field_id, exc)
            self.generation_error.emit(field_id, str(exc))
        finally:
            self.queue_size_changed.emit(self._service.queue_size)

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
