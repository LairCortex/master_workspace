"""Tests for LlmService — prompt assembly, parallel execution, errors."""
from __future__ import annotations

import asyncio
import re

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

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 512, on_phase=None) -> str:
        self.calls.append((system_prompt, user_prompt, max_tokens))
        return f"result for: {user_prompt[:20]}"


class SlowProvider(BaseLlmProvider):
    """Sleeps inside generate so concurrent execution is measurable."""

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.started: list[float] = []
        self.finished: list[float] = []

    def is_ready(self) -> bool:
        return True

    async def load_model(self) -> None:
        pass

    async def unload_model(self) -> None:
        pass

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 512, on_phase=None) -> str:
        loop = asyncio.get_running_loop()
        marker = re.search(r"MARKER(\d+)", user_prompt)
        idx = int(marker.group(1)) if marker else 0
        self.started.append(loop.time())
        await asyncio.sleep(self.delay)
        self.finished.append(loop.time())
        return f"done-{idx}"


class ErrorProvider(BaseLlmProvider):
    def is_ready(self) -> bool:
        return True

    async def load_model(self) -> None:
        pass

    async def unload_model(self) -> None:
        pass

    async def generate(self, system_prompt, user_prompt, max_tokens=512, on_phase=None):
        raise RuntimeError("generation failed")


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def service(provider):
    return LlmService(provider)


# ── prompt assembly ────────────────────────────────────────────────────────


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


# ── parallel execution ─────────────────────────────────────────────────────


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


async def test_generate_for_field_returns_provider_result():
    """The caller of generate_for_field gets exactly the provider's answer."""
    provider = FakeProvider()
    service = LlmService(provider)
    result = await service.generate_for_field(
        field_id="org.tasks",
        entity_type="organization",
        world_prompt="Fantasy",
        field_prompt="Задачи организации",
        field_label="Задачи",
        current_text="",
    )
    assert result == f"result for: {provider.calls[0][1][:20]}"
    assert result != provider.calls[0][1]  # not an echo of the input prompt


async def test_generate_for_field_runs_requests_in_parallel():
    """Two slow requests overlap and finish in well under 2× a single run."""
    single_provider = SlowProvider()
    single_service = LlmService(single_provider)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    await single_service.generate_for_field(
        "f1", "event", "world", "MARKER1", "Поле1", ""
    )
    t_single = loop.time() - t0

    parallel_provider = SlowProvider()
    parallel_service = LlmService(parallel_provider)
    t0 = loop.time()
    r1, r2 = await asyncio.gather(
        parallel_service.generate_for_field("f1", "event", "world", "MARKER1", "Поле1", ""),
        parallel_service.generate_for_field("f2", "event", "world", "MARKER2", "Поле2", ""),
    )
    t_parallel = loop.time() - t0

    # each caller receives the answer of its own request
    assert r1 == "done-1"
    assert r2 == "done-2"
    # both requests were actually in flight at the same time
    assert max(parallel_provider.started) < min(parallel_provider.finished)
    # < 2× the single-request time (a sequential queue would take ~2×)
    assert t_parallel < 1.75 * t_single



# ── helpers ────────────────────────────────────────────────────────────────


class HangingProvider(BaseLlmProvider):
    """Each generate suspends on a shared gate until the test releases it."""

    def __init__(self):
        self.reached: list[str] = []
        self.gate = asyncio.Event()

    def is_ready(self) -> bool:
        return True

    async def load_model(self) -> None:
        pass

    async def unload_model(self) -> None:
        pass

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 512, on_phase=None) -> str:
        marker = re.search(r"MARKER(\d+)", user_prompt)
        idx = int(marker.group(1)) if marker else 0
        self.reached.append(str(idx))
        await self.gate.wait()
        return f"done-{idx}"


class PhasedHangProvider(BaseLlmProvider):
    """Reports its next phase via on_phase, then suspends until cancelled.

    Mirrors RemoteLlmProvider, which calls the hook with "in_flight" before
    every POST and "waiting" before every retry backoff.
    """

    def __init__(self, phases: list[str]):
        self.phases = list(phases)
        self.reported: list[str] = []

    def is_ready(self) -> bool:
        return True

    async def load_model(self) -> None:
        pass

    async def unload_model(self) -> None:
        pass

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 512, on_phase=None) -> str:
        phase = self.phases.pop(0) if self.phases else "in_flight"
        if on_phase is not None:
            on_phase(phase)
        self.reported.append(phase)
        await asyncio.Event().wait()  # suspended — only a cancel can end us
        raise AssertionError("unreachable")


async def _spin(count: int) -> None:
    for _ in range(count):
        await asyncio.sleep(0)


async def wait_until(cond, ticks: int = 300) -> None:
    for _ in range(ticks):
        if cond():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not met in time")


# ── registry and cancellation ──────────────────────────────────────────────


async def test_cancel_all_cancels_only_own_owners_requests():
    """cancel_all(owner) touches only that owner's requests — a request in
    flight for owner B survives owner A's cancellation."""
    provider = HangingProvider()
    service = LlmService(provider)
    owner_a, owner_b = object(), object()

    task_a = asyncio.ensure_future(
        service.generate_for_field("fa", "event", "w", "MARKER1", "Поле А", "", owner=owner_a)
    )
    task_b = asyncio.ensure_future(
        service.generate_for_field("fb", "event", "w", "MARKER2", "Поле Б", "", owner=owner_b)
    )
    await wait_until(lambda: len(provider.reached) == 2)
    assert service.any_active(owner_a)
    assert service.any_active(owner_b)

    service.cancel_all(owner_a)
    with pytest.raises(asyncio.CancelledError):
        await task_a

    provider.gate.set()
    result_b = await task_b  # owner B is not touched by owner A's cancel
    assert result_b == "done-2"
    await _spin(2)
    assert not service.any_active(owner_a)
    assert not service.any_active(owner_b)


async def test_cancel_during_backoff_wait():
    """A request sitting in the retry-backoff (not sent to LLM) is cancelled
    by cancel_all, and the phase is visible to any_in_flight/count_in_flight."""
    provider = PhasedHangProvider(["waiting"])
    service = LlmService(provider)
    owner = object()

    task = asyncio.ensure_future(
        service.generate_for_field("f1", "event", "w", "MARKER1", "Поле", "", owner=owner)
    )
    await wait_until(lambda: provider.reported)
    assert service.any_active(owner)
    # only between retry attempts — nothing is in flight right now
    assert not service.any_in_flight(owner)
    assert service.count_in_flight(owner) == 0

    service.cancel_all(owner)
    with pytest.raises(asyncio.CancelledError):
        await task
    await _spin(2)
    assert not service.any_active(owner)


async def test_in_flight_phase_counts():
    provider = PhasedHangProvider(["in_flight"])
    service = LlmService(provider)
    owner = object()

    task = asyncio.ensure_future(
        service.generate_for_field("f1", "event", "w", "MARKER1", "Поле", "", owner=owner)
    )
    await wait_until(lambda: provider.reported)
    assert service.any_in_flight(owner)
    assert service.count_in_flight(owner) == 1

    service.cancel_all(owner)
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_count_in_flight_counts_only_in_flight_phase():
    provider = PhasedHangProvider(["in_flight", "waiting"])
    service = LlmService(provider)
    owner = object()

    task_1 = asyncio.ensure_future(
        service.generate_for_field("f1", "event", "w", "MARKER1", "Поле 1", "", owner=owner)
    )
    task_2 = asyncio.ensure_future(
        service.generate_for_field("f2", "event", "w", "MARKER2", "Поле 2", "", owner=owner)
    )
    await wait_until(lambda: len(provider.reported) == 2)
    assert service.count_in_flight(owner) == 1
    assert service.any_active(owner)

    service.cancel_all(owner)
    with pytest.raises(asyncio.CancelledError):
        await task_1
    with pytest.raises(asyncio.CancelledError):
        await task_2
    await _spin(2)
    assert not service.any_active(owner)
    assert service.count_in_flight(owner) == 0


async def test_registry_entry_removed_on_completion():
    provider = HangingProvider()
    service = LlmService(provider)
    owner = object()

    task = asyncio.ensure_future(
        service.generate_for_field("f1", "event", "w", "MARKER1", "Поле", "", owner=owner)
    )
    await wait_until(lambda: provider.reached)
    assert service.any_active(owner)

    provider.gate.set()
    result = await task
    assert result == "done-1"
    await _spin(1)
    assert not service.any_active(owner)
    assert service.count_in_flight(owner) == 0


async def test_cancelled_request_does_not_succeed_or_error():
    """A cancelled request neither returns a result nor raises an LlmError —
    only CancelledError, so no generation_finished/generation_error follows."""
    provider = HangingProvider()
    service = LlmService(provider)
    owner = object()

    task = asyncio.ensure_future(
        service.generate_for_field("f1", "event", "w", "MARKER1", "Поле", "", owner=owner)
    )
    await wait_until(lambda: provider.reached)
    service.cancel_all(owner)

    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


# ── errors ─────────────────────────────────────────────────────────────────


async def test_generate_error_propagated():
    svc = LlmService(ErrorProvider())
    with pytest.raises(RuntimeError, match="generation failed"):
        await svc.generate_for_field("f1", "organization", "w", "p", "Название", "")
