"""LLM orchestration — prompt assembly and parallel generation.

Every request runs in its own asyncio task; there is no shared
sequential queue. Active requests are registered per owner (the host
dialog, keyed by identity) so cancellation and phase queries are
scoped to one dialog at a time.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.infrastructure.llm.base_provider import BaseLlmProvider

log = logging.getLogger("llm.service")

FIELD_CONFIG: dict[str, list[str]] = {
    "event": ["name", "characteristics", "backstory"],
    "organization": ["name", "characteristics", "backstory", "tasks"],
    "character": ["name", "characteristics", "backstory", "personality", "tasks"],
    "item": ["name", "characteristics", "backstory"],
    "location": ["name", "characteristics", "backstory", "tasks"],
}

FIELD_LABELS: dict[str, str] = {
    "name": "Название",
    "characteristics": "Характеристики",
    "backstory": "Предыстория",
    "personality": "Личность",
    "tasks": "Задачи",
}

ENTITY_LABELS: dict[str, str] = {
    "event": "Событие",
    "organization": "Организация",
    "character": "Персонаж",
    "item": "Предмет",
    "location": "Локация",
}

#: Request phase: the request has been (or is being) sent to the LLM.
PHASE_IN_FLIGHT = "in_flight"
#: Request phase: between retry attempts, waiting in backoff — not sent.
PHASE_WAITING = "waiting"


@dataclass
class GenerationRequest:
    field_id: str
    entity_type: str
    world_prompt: str
    field_prompt: str
    field_label: str
    current_text: str
    max_tokens: int = 512
    #: Owner of the request (the host dialog). Used as an identity key in
    #: the active-requests registry — two dialogs of the same entity type
    #: can be open at once (nested cards), so scope is never the field_id.
    owner: Any = None


@dataclass
class _ActiveGen:
    """Registry record for one running request."""

    task: asyncio.Task
    #: PHASE_IN_FLIGHT or PHASE_WAITING; updated by the provider's on_phase hook.
    phase: str = PHASE_IN_FLIGHT

    def set_phase(self, phase: str) -> None:
        self.phase = phase


class LlmService:
    """Builds prompts and runs generation requests in parallel.

    ``generate_for_field`` schedules one ``asyncio.Task`` per request and
    awaits its result — requests never wait on a shared queue.
    """

    def __init__(self, provider: BaseLlmProvider) -> None:
        self._provider = provider
        #: owner (identity) → {field_id → active request record}
        self._active: dict[Any, dict[str, _ActiveGen]] = {}

    @property
    def provider(self) -> BaseLlmProvider:
        return self._provider

    @provider.setter
    def provider(self, value: BaseLlmProvider) -> None:
        self._provider = value

    async def generate_for_field(
        self,
        field_id: str,
        entity_type: str,
        world_prompt: str,
        field_prompt: str,
        field_label: str,
        current_text: str,
        max_tokens: int = 512,
        owner: Any = None,
    ) -> str:
        request = GenerationRequest(
            field_id=field_id,
            entity_type=entity_type,
            world_prompt=world_prompt,
            field_prompt=field_prompt,
            field_label=field_label,
            current_text=current_text,
            max_tokens=max_tokens,
            owner=owner,
        )
        task: asyncio.Task[str] = asyncio.ensure_future(self._run(request))
        return await task

    def cancel_all(self, owner: Any) -> None:
        """Cancel every active request of the owner (in-flight and backoff-waiting).

        Cancelled tasks die with CancelledError (a BaseException): no result,
        no error conversion, no generation_finished/generation_error.
        """
        for record in list(self._active.get(owner, {}).values()):
            record.task.cancel()

    def any_in_flight(self, owner: Any) -> bool:
        """True when the owner has a request already sent (or being sent) to LLM."""
        return self.count_in_flight(owner) > 0

    def count_in_flight(self, owner: Any) -> int:
        """Number of owner requests in the in-flight phase (not backoff-waiting)."""
        return sum(
            1 for record in self._active.get(owner, {}).values()
            if record.phase == PHASE_IN_FLIGHT
        )

    def any_active(self, owner: Any) -> bool:
        """True when the owner has any active request (any phase)."""
        return bool(self._active.get(owner))

    @staticmethod
    def build_prompts(
        entity_type: str,
        world_prompt: str,
        field_prompt: str,
        field_label: str,
        current_text: str,
    ) -> tuple[str, str]:
        """Assemble system and user prompts from parts.

        Returns (system_prompt, user_prompt).
        """
        entity_label = ENTITY_LABELS.get(entity_type, entity_type)

        system_prompt = (
            f"Ты — автор контента для настольной ролевой игры. Мир: {world_prompt}\n"
            f"Правила:\n"
            f"- Отвечай ТОЛЬКО готовым текстом для поля, без вопросов, пояснений и рассуждений.\n"
            f"- Не задавай уточняющих вопросов. Додумай сам на основе контекста мира.\n"
            f"- Не добавляй заголовков, маркеров, нумерации — только текст.\n"
            f"- Пиши в стиле и тоне описанного мира."
        ) if world_prompt else ""

        parts: list[str] = [f"Создаю: {entity_label}, поле «{field_label}»."]
        if field_prompt:
            parts.append(field_prompt)
        if current_text:
            parts.append(f"Текущий текст пользователя: {current_text}")

        user_prompt = "\n".join(parts)
        return system_prompt, user_prompt

    async def _run(self, request: GenerationRequest) -> str:
        record = _ActiveGen(task=asyncio.current_task())
        self._active.setdefault(request.owner, {})[request.field_id] = record
        try:
            system_prompt, user_prompt = self.build_prompts(
                request.entity_type,
                request.world_prompt,
                request.field_prompt,
                request.field_label,
                request.current_text,
            )
            log.info("=== SYSTEM PROMPT ===\n%s", system_prompt)
            log.info("=== USER PROMPT ===\n%s", user_prompt)
            return await self._provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=request.max_tokens,
                on_phase=record.set_phase,
            )
        finally:
            self._remove(request.owner, request.field_id, record)

    def _remove(self, owner: Any, field_id: str, record: _ActiveGen) -> None:
        # The record was registered under this owner before the try-block,
        # so the owner entry always exists here.
        owner_records = self._active[owner]
        if owner_records.get(field_id) is record:
            del owner_records[field_id]
        if not owner_records:
            del self._active[owner]
