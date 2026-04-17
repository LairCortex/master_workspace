"""LLM orchestration — prompt assembly and sequential generation queue."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.infrastructure.llm.base_provider import BaseLlmProvider

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


@dataclass
class GenerationRequest:
    field_id: str
    entity_type: str
    world_prompt: str
    field_prompt: str
    field_label: str
    current_text: str
    max_tokens: int = 512
    future: asyncio.Future | None = None


class LlmService:
    """Builds prompts, queues generation requests, delegates to provider."""

    def __init__(self, provider: BaseLlmProvider) -> None:
        self._provider = provider
        self._queue: asyncio.Queue[GenerationRequest] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._active_count = 0

    @property
    def provider(self) -> BaseLlmProvider:
        return self._provider

    @provider.setter
    def provider(self, value: BaseLlmProvider) -> None:
        self._provider = value

    @property
    def queue_size(self) -> int:
        return self._queue.qsize() + (1 if self._active_count else 0)

    def start_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.ensure_future(self._worker_loop())

    def stop_worker(self) -> None:
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()

    async def generate_for_field(
        self,
        field_id: str,
        entity_type: str,
        world_prompt: str,
        field_prompt: str,
        field_label: str,
        current_text: str,
        max_tokens: int = 512,
    ) -> str:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        request = GenerationRequest(
            field_id=field_id,
            entity_type=entity_type,
            world_prompt=world_prompt,
            field_prompt=field_prompt,
            field_label=field_label,
            current_text=current_text,
            max_tokens=max_tokens,
            future=future,
        )
        await self._queue.put(request)
        self.start_worker()
        return await future

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

    async def _worker_loop(self) -> None:
        while True:
            request = await self._queue.get()
            self._active_count = 1
            try:
                system_prompt, user_prompt = self.build_prompts(
                    request.entity_type,
                    request.world_prompt,
                    request.field_prompt,
                    request.field_label,
                    request.current_text,
                )
                import logging
                log = logging.getLogger("llm.prompt")
                log.info("=== SYSTEM PROMPT ===\n%s", system_prompt)
                log.info("=== USER PROMPT ===\n%s", user_prompt)
                result = await self._provider.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=request.max_tokens,
                )
                if request.future and not request.future.done():
                    request.future.set_result(result)
            except Exception as exc:
                if request.future and not request.future.done():
                    request.future.set_exception(exc)
            finally:
                self._active_count = 0
                self._queue.task_done()
