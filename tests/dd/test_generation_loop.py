"""Круг генерации: Qt-free ядро и канал LLM (add-dnd-lss-generation, tasks 1.1–1.3).

Механизм круга проверяется на стаб-канале (успех с первого/второго ответа,
лимит двух автоматических исправлений, ручная «Ещё круг», предупреждения не
запускают круг); терпимое извлечение JSON — на типовых артефактах моделей;
одиночный вызов ``BaseLlmProvider`` с ``with_thinking=True`` и ``max_tokens=None``
— через ``httpx.MockTransport`` (сеть тестов не требует сети, PR-поза
``tests/infrastructure/test_llm_providers.py``).
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.dd.application.generation_loop import (
    DocumentExtractionError,
    GenerationChannel,
    GenerationRoundResult,
    extract_json_document,
    format_round_feedback,
    make_llm_answer,
    run_rounds,
)
from app.dd.domain.lss_checks import CODE_INVALID_JSON
from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport
from app.infrastructure.http import AppHttpClient
from app.infrastructure.llm.config import LlmConfig
from app.infrastructure.llm.remote_provider import (
    OUTPUT_BUDGET_SHARE,
    PROBE_MAX_OUTPUT_TOKENS,
    RemoteLlmProvider,
)


# ── стаб-канал и стаб-ответ канала ───────────────────────────────────────────


class StubChannel:
    """Стаб-канал: промты фиксированы, parse — тождество (или подставной
    экстрактор), валидатор отвечает настроенным отчётом по тексту документа."""

    def __init__(self, reports=None, default_report=None, parser=None):
        self.system = "СИСТЕМА"
        self.user = "ЗАПРОС"
        self.reports = reports or {}
        self.default_report = (
            default_report if default_report is not None else ValidationReport()
        )
        self.parser = parser
        self.contexts: list = []

    def build_prompt(self, context):
        return (self.system, self.user)

    def parse(self, answer):
        if self.parser is not None:
            return self.parser(answer)
        return answer

    def validate(self, document, context):
        self.contexts.append(context)
        return self.reports.get(document, self.default_report)


class ScriptedAsk:
    """Стаб-ответ канала: отвечает по скрипту, записывает промты и on_phase."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.systems: list[str] = []
        self.users: list[str] = []
        self.phases: list = []

    @property
    def calls(self) -> int:
        return len(self.users)

    async def __call__(self, system_prompt, user_prompt, on_phase=None):
        self.systems.append(system_prompt)
        self.users.append(user_prompt)
        self.phases.append(on_phase)
        return self.answers.pop(0)


def _issue(code: str, severity: Severity, path: str, message: str) -> CheckIssue:
    return CheckIssue(code=code, severity=severity, path=path, message=message)


def _report(*issues: CheckIssue) -> ValidationReport:
    return ValidationReport.of(list(issues))


# ── task 1.1: механизм круга ──────────────────────────────────────────────────


def test_channel_protocol_stubs_are_inert():
    """Контракт протокола — форма, не поведение: тела заглушек безмолвны
    (прецедент tests/test_dd_module_isolation.py)."""
    assert GenerationChannel.build_prompt(None, None) is None
    assert GenerationChannel.parse(None, "") is None
    assert GenerationChannel.validate(None, "", None) is None


async def test_success_first_round_makes_one_request():
    """Документ прошёл валидатор с первого ответа — второго запроса нет."""
    channel = StubChannel()
    ask = ScriptedAsk(["ГОТОВО"])
    phases: list = []
    sink = phases.append
    result = await run_rounds(channel, {"ctx": 1}, ask, on_phase=sink)
    assert result.ok
    assert result.document == "ГОТОВО"
    assert result.attempts == 1
    assert result.error_message is None
    assert ask.users == ["ЗАПРОС"]
    assert ask.systems == ["СИСТЕМА"]
    # контекст дошёл и в build_prompt-канал, и в валидатор
    assert channel.contexts == [{"ctx": 1}]
    # on_phase пробрасывается ответчику как есть (фазы покажет лист)
    assert ask.phases[0] is sink


async def test_success_on_second_round_feedback_carries_answer_and_errors():
    """Первый ответ отклонён, второе исправление прошло — круг успешен."""
    first = _report(
        _issue("FEAT_NAME", Severity.ERROR, "sections.feats[0]", "пустое имя"),
        _issue("WARN_X", Severity.WARNING, "sections.feats[1]", "секрет-текст"),
    )
    channel = StubChannel(reports={"A1": first})
    ask = ScriptedAsk(["A1", "A2"])
    result = await run_rounds(channel, None, ask)
    assert result.ok
    assert result.document == "A2"
    assert result.attempts == 2
    assert ask.calls == 2
    assert ask.systems == ["СИСТЕМА", "СИСТЕМА"]
    feedback = ask.users[1]
    # обратная связь: прежний ответ + ошибка (код · путь · сообщение)...
    assert "A1" in feedback
    assert "FEAT_NAME" in feedback
    assert "sections.feats[0]" in feedback
    assert "пустое имя" in feedback
    # ...предупреждения в перегенерацию НЕ отправляются
    assert "WARN_X" not in feedback
    assert "секрет-текст" not in feedback


async def test_limit_two_auto_rounds_then_result_as_is():
    """После двух автоматических исправлений круг останавливается и отдаёт
    последний ответ «как есть» с отчётом; ручной «Ещё круг» — повторный вызов
    поверх сохранённого результата."""
    bad = _report(_issue("E1", Severity.ERROR, "root", "сломано"))
    channel = StubChannel(default_report=bad)
    ask = ScriptedAsk(["A1", "A2", "A3"])
    result = await run_rounds(channel, None, ask)
    assert ask.calls == 3  # первый ответ + ровно два автоматических исправления
    assert not result.ok
    assert result.attempts == 3
    assert result.answer == "A3" and result.document == "A3"
    assert [i.code for i in result.report.errors] == ["E1"]
    assert result.error_message is None  # лимит — не сбой канала
    assert "A2" in ask.users[2]  # каждый исправительный запрос — поверх прежнего

    # ручная «Ещё круг»: неограниченно, поверх сохранённого последнего ответа
    ask_manual = ScriptedAsk(["A4"])
    result_manual = await run_rounds(StubChannel(), None, ask_manual, previous=result)
    assert result_manual.ok and result_manual.attempts == 1
    assert "A3" in ask_manual.users[0] and "сломано" in ask_manual.users[0]


async def test_manual_round_after_channel_error_restares_from_scratch():
    """Перезапуск секции после сбоя канала: прежнего ответа нет — промт
    собирается заново, а не фидбеком поверх пустоты."""
    previous = GenerationRoundResult(error_message="Сервер LLM недоступен")
    ask = ScriptedAsk(["ГОТОВО"])
    result = await run_rounds(StubChannel(), None, ask, previous=previous)
    assert ask.users == ["ЗАПРОС"]
    assert result.ok  # ошибка канала не переезжает в перезапуск
    assert result.document == "ГОТОВО"


async def test_warnings_do_not_trigger_round():
    """Документ без ошибок, но с предупреждениями — круг завершён,
    предупреждения видны мастеру в отчёте."""
    warn = _report(_issue("W1", Severity.WARNING, "sections.races[0]", "вне SRD"))
    channel = StubChannel(default_report=warn)
    ask = ScriptedAsk(["A1"])
    result = await run_rounds(channel, None, ask)
    assert ask.calls == 1
    assert result.ok
    assert result.attempts == 1
    assert [i.code for i in result.report.warnings] == ["W1"]


async def test_max_auto_knob_counts_fix_rounds():
    """max_auto из design Д1 — живая настройка: с ним = 1 круг чинит один раз."""
    bad = _report(_issue("E1", Severity.ERROR, "root", "сломано"))
    channel = StubChannel(default_report=bad)
    ask = ScriptedAsk(["A1", "A2"])
    result = await run_rounds(channel, None, ask, max_auto=1)
    assert ask.calls == 2
    assert not result.ok and result.attempts == 2


def test_format_round_feedback_lists_errors_only():
    """Формат фидбека (spec): код · путь · сообщение, ошибки целиком,
    без предупреждений."""
    report = _report(
        _issue("C1", Severity.ERROR, "p1", "м1"),
        _issue("C2", Severity.ERROR, "p2", "м2"),
        _issue("W1", Severity.WARNING, "p3", "м3"),
    )
    feedback = format_round_feedback("ОТВЕТ", report)
    assert "- C1 · p1 · м1" in feedback
    assert "- C2 · p2 · м2" in feedback
    assert "W1" not in feedback and "м3" not in feedback
    assert feedback.index("ОТВЕТ") > feedback.index("- C1")  # ошибки, потом ответ


# ── task 1.2: терпимое извлечение JSON-документа ─────────────────────────────


def test_extraction_whole_document_passes_through():
    """Чистый JSON возвращается как есть (снята только обрамляющая пустота)."""
    assert extract_json_document('  {"a": 1}\n') == '{"a": 1}'
    assert extract_json_document('[{"id": "x"}]') == '[{"id": "x"}]'


def test_extraction_fenced_document():
    """```json-фенс — самый частый артефакт моделей."""
    assert extract_json_document('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json_document("```\n[1, 2]\n```") == "[1, 2]"
    assert (
        extract_json_document('Вот документ:\n```json\n{"a": {"b": [1, 2]}}\n```\nУдачи!')
        == '{"a": {"b": [1, 2]}}'
    )


def test_extraction_unclosed_fence_still_found():
    """Модель забыла закрывающий фенс — скан достаёт документ из-под метки."""
    assert extract_json_document('```json\n{"a": 1}') == '{"a": 1}'


def test_extraction_document_between_prose():
    """Обрамляющий текст без фенса: объект/массив вырезаются по балансу скобок."""
    assert extract_json_document('Документ: {"a": 1} — как-то так') == '{"a": 1}'
    assert (
        extract_json_document('[{"id": "f1"}, {"id": "f2"}] — готово')
        == '[{"id": "f1"}, {"id": "f2"}]'
    )


def test_extraction_braces_and_quotes_inside_strings_survive():
    """«}» и спасенные кавычки внутри строк — баланс не ломается (типовой
    текст описания с скобкой)."""
    inner = {"текст": 'сказал "}" и ушёл'}
    answer = "Вот: " + json.dumps(inner, ensure_ascii=False) + " — понятненько"
    assert json.loads(extract_json_document(answer)) == inner


def test_extraction_fenced_non_document_falls_back_to_scan():
    """Фенс с прозой не документ — следующий кандидат ищется дальше."""
    answer = 'Сначала план:\n```\nтам просто текст\n```\nА документ вот: {"a": 1}'
    assert extract_json_document(answer) == '{"a": 1}'


@pytest.mark.parametrize(
    "answer",
    [
        "начало { \"a\": 1",  # незакрытая скобка
        'текст {"a": 1] конец',  # рассогласованные пары
        "просто текст без всякого документа",
        '"просто скалярная строка"',
        "42",
        "   ",
        "",
    ],
)
def test_extraction_failure_raises_not_json(answer):
    """Провал — DocumentExtractionError (он же ValueError): обычная ошибка круга."""
    with pytest.raises(DocumentExtractionError):
        extract_json_document(answer)


def test_not_json_document_error_is_value_error():
    assert issubclass(DocumentExtractionError, ValueError)


async def test_not_json_answer_becomes_regular_round_error():
    """Провал извлечения входит в обратную связь круга как ошибка INVALID_JSON
    с прежним ответом — второй ответ спасает круг."""
    channel = StubChannel(
        parser=extract_json_document,
        reports={'{"a": 1}': ValidationReport()},
    )
    ask = ScriptedAsk(["извини, не могу", '```json\n{"a": 1}\n```'])
    result = await run_rounds(channel, None, ask)
    assert ask.calls == 2
    feedback = ask.users[1]
    assert CODE_INVALID_JSON in feedback
    assert "извини, не могу" in feedback
    assert result.ok
    assert result.document == '{"a": 1}'
    assert result.attempts == 2


# ── task 1.3: одиночные вызовы BaseLlmProvider + фазы повторов ───────────────


def _provider(handler):
    """RemoteLlmProvider поверх MockTransport (без сети), повторы — мгновенно."""
    http = AppHttpClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    config = LlmConfig(base_url="https://llm.test/v1", model="test-model")
    return RemoteLlmProvider(config, http, backoffs=(0.0, 0.0)), http


def _ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _server_error(status: int, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": message}})


async def test_llm_channel_single_call_with_thinking_and_auto_budget():
    """Одиночный вызов (design Д8): max_tokens=None → авто-бюджет провайдера,
    with_thinking=True → переключатель в запросе; промты доходят как есть."""
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return _ok('{"a": 1}')

    provider, http = _provider(handler)
    channel = StubChannel()
    ask = make_llm_answer(provider)
    try:
        result = await run_rounds(channel, None, ask)
    finally:
        await http.close()
    assert result.ok
    assert result.document == '{"a": 1}'
    assert result.attempts == 1
    # max_tokens=None означает сначала дешёвую пробу бюджета вывода
    assert payloads[0]["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS
    request_payload = payloads[1]
    assert request_payload["chat_template_kwargs"] == {"enable_thinking": True}
    assert request_payload["max_tokens"] == int(PROBE_MAX_OUTPUT_TOKENS * OUTPUT_BUDGET_SHARE)
    assert request_payload["messages"][0] == {"role": "system", "content": "СИСТЕМА"}
    assert request_payload["messages"][1] == {"role": "user", "content": "ЗАПРОС"}


async def test_llm_channel_error_survives_round_with_russian_message():
    """Сбой канала не завершает задачу с паникой: русское сообщение сохраняется,
    штатные повторы видны фазами, документ не выдуман."""

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _server_error(500, "сервер упал")

    provider, http = _provider(handler)
    ask = make_llm_answer(provider)
    phases: list[str] = []
    try:
        result = await run_rounds(StubChannel(), None, ask, on_phase=phases.append)
    finally:
        await http.close()
    assert not result.ok
    assert result.error_message == "Ошибка LLM (статус 500): сервер упал"
    assert result.attempts == 0  # ни одного завершённого ответа — нечего показывать
    assert result.document is None
    # три попытки с паузами между ними — фазы повторов дошли до листа
    assert phases == ["in_flight", "waiting", "in_flight", "waiting", "in_flight"]
    # первый запрос — проба бюджета, штатных повторов у неё нет
    assert len(calls) == 4


async def test_llm_channel_network_error_message_preserved():
    """Сеть легла — тот же постур: русское «Сервер LLM недоступен» в результате."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет связи")

    provider, http = _provider(handler)
    ask = make_llm_answer(provider)
    try:
        result = await run_rounds(StubChannel(), None, ask)
    finally:
        await http.close()
    assert not result.ok
    assert result.error_message == "Сервер LLM недоступен"
    assert result.attempts == 0


async def test_llm_error_mid_round_keeps_last_answer_for_the_sheet():
    """Обрыв на исправительном запросе: последний полный ответ с отчётом
    сохраняется (задача открыта, секцию можно перезапустить), а частичных
    ответов прерванного запроса не появляется."""

    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return _ok("проба")  # бюджет-проба
        if state["n"] == 2:
            return _ok("битый ответ")  # первый ответ канала — с ошибкой валидатора
        return _server_error(502, "шлюз лёг")

    provider, http = _provider(handler)
    ask = make_llm_answer(provider)
    bad = _report(_issue("E1", Severity.ERROR, "data", "нет поля"))
    try:
        result = await run_rounds(StubChannel(default_report=bad), None, ask)
    finally:
        await http.close()
    assert not result.ok
    assert result.error_message == "Ошибка LLM (статус 502): шлюз лёг"
    # прощальный полный ответ и его отчёт — живы для предпросмотра/перезапуска
    assert result.answer == "битый ответ" and result.document == "битый ответ"
    assert [i.code for i in result.report.errors] == ["E1"]
    assert result.attempts == 1
    # проба + первый ответ + три попытки исправительного запроса
    assert state["n"] == 5
