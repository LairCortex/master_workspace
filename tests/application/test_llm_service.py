"""Tests for LlmService — prompt assembly, queue, error handling."""
from __future__ import annotations

import asyncio

import pytest

from app.application.services.llm_service import LlmService
from app.infrastructure.llm.base_provider import BaseLlmProvider


class FakeProvider(BaseLlmProvider):
    def __init__(self):
        self._ready = True
        self.calls: list[tuple[str, str, int]] = []

    def is_ready(self) -> bool:
        return self._ready

    async def load_model(self) -> None:
        self._ready = True

    async def unload_model(self) -> None:
        self._ready = False

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 512) -> str:
        self.calls.append((system_prompt, user_prompt, max_tokens))
        return f"result for: {user_prompt[:20]}"


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def service(provider):
    return LlmService(provider)


def test_build_prompts_all_parts():
    system, user = LlmService.build_prompts(
        entity_type="character",
        world_prompt="Мир фэнтези",
        field_prompt="Напиши предысторию",
        field_label="Предыстория",
        current_text="Давным-давно",
    )
    assert "Мир фэнтези" in system
    assert "Напиши предысторию" in user
    assert "Предыстория" in user
    assert "Давным-давно" in user
    assert "Персонаж" in user


def test_build_prompts_empty_field_prompt():
    system, user = LlmService.build_prompts(
        entity_type="organization",
        world_prompt="Dark world",
        field_prompt="",
        field_label="Характеристики",
        current_text="Высокий",
    )
    assert "Dark world" in system
    assert "Характеристики" in user
    assert "Высокий" in user
    assert "Организация" in user


def test_build_prompts_empty_current_text():
    system, user = LlmService.build_prompts(
        entity_type="event",
        world_prompt="Sci-fi",
        field_prompt="Короткое имя",
        field_label="Название",
        current_text="",
    )
    assert "Текущий текст" not in user
    assert "Короткое имя" in user
    assert "Название" in user


def test_build_prompts_only_field_label():
    system, user = LlmService.build_prompts(
        entity_type="item",
        world_prompt="World",
        field_prompt="",
        field_label="Задачи",
        current_text="",
    )
    assert "Задачи" in user
    assert "Предмет" in user


@pytest.mark.asyncio
async def test_generate_for_field_calls_provider(service, provider):
    result = await service.generate_for_field(
        field_id="org.name",
        entity_type="organization",
        world_prompt="Fantasy",
        field_prompt="Имя организации",
        field_label="Название",
        current_text="",
    )
    assert len(provider.calls) == 1
    sys_p, usr_p, _ = provider.calls[0]
    assert "Fantasy" in sys_p
    assert "Имя организации" in usr_p
    assert "result for:" in result


@pytest.mark.asyncio
async def test_queue_sequential_execution(provider):
    order: list[int] = []

    class OrderedProvider(BaseLlmProvider):
        def is_ready(self): return True
        async def load_model(self): pass
        async def unload_model(self): pass

        async def generate(self, system_prompt, user_prompt, max_tokens=512):
            import re
            m = re.search(r"MARKER(\d+)", user_prompt)
            idx = int(m.group(1)) if m else 0
            await asyncio.sleep(0.01)
            order.append(idx)
            return f"done-{idx}"

    svc = LlmService(OrderedProvider())
    t1 = asyncio.ensure_future(
        svc.generate_for_field("f1", "event", "w", "MARKER1", "Поле1", "", 10)
    )
    t2 = asyncio.ensure_future(
        svc.generate_for_field("f2", "event", "w", "MARKER2", "Поле2", "", 10)
    )
    r1, r2 = await asyncio.gather(t1, t2)
    assert order == [1, 2]
    assert r1 == "done-1"
    assert r2 == "done-2"


@pytest.mark.asyncio
async def test_generate_error_propagated():
    class ErrorProvider(BaseLlmProvider):
        def is_ready(self): return True
        async def load_model(self): pass
        async def unload_model(self): pass

        async def generate(self, system_prompt, user_prompt, max_tokens=512):
            raise RuntimeError("generation failed")

    svc = LlmService(ErrorProvider())
    with pytest.raises(RuntimeError, match="generation failed"):
        await svc.generate_for_field("f1", "organization", "w", "p", "Название", "")
