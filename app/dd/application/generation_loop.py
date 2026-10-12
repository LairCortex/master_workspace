"""Круг генерации «генерация → валидатор → перегенерация» (add-dnd-lss-generation, tasks 1.1–1.3).

Qt-free ядро модуля (design Д1): один механизм круга для всех каналов —
датасетов, заклинаний и персонажей. Канал описан протоколом
:class:`GenerationChannel` (``build_prompt``/``parse``/``validate``), а
:class:`run_rounds` проводит документ через круг: ответ модели извлекается,
отдаётся существующему валидатору канала, а при ошибках — с обратной связью
«прежний ответ + полный список ошибок» — уходит на перегенерацию.

Правила круга (spec dnd-generation «Круг генерации с обратной связью
валидатора»):

- автоматических кругов-исправлений — не более двух (:data:`AUTO_ROUND_LIMIT`);
- в обратную связь идут ТОЛЬКО ошибки (``severity=ERROR``) — предупреждения
  документ не перегенирируют и мастеру их показывает предпросмотр;
- после лимита круг останавливается и отдаёт последний ответ «как есть» с
  отчётом: ручной «Ещё круг» — повторный вызов раннера поверх сохранённого
  результата (:paramref:`run_rounds.previous`), доступен неограниченно;
- сбой канала LLM — не паника: русское сообщение ``LlmError`` возвращается в
  результате, задача остаётся открытой с перезапуском секции (spec «Ошибки
  канала LLM»), частичных ответов прерванного запроса не бывает.

Терпимое извлечение JSON-документа (:func:`extract_json_document`, task 1.2)
— общий помощник каналов: fence и обрамляющий текст прощаются, провал
становится обычной ошибкой круга («не JSON») и уходит в обратную связь.
Вызов провайдера — одиночный, с мышлением и авто-бюджетом вывода
(:func:`make_llm_answer`, design Д8); фазы повторов пробрасываются насквозь.
"""
from __future__ import annotations

import json
import re
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from app.dd.domain.lss_checks import CODE_INVALID_JSON
from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport
from app.infrastructure.llm.base_provider import BaseLlmProvider
from app.infrastructure.llm.errors import LlmError

#: Автоматических кругов-исправлений после первого ответа (spec: «не более
#: двух»; первый ответ автоматическим кругом не считается).
AUTO_ROUND_LIMIT = 2

#: Путь отчёта для находок без места в документе — они относятся к сырому
#: ответу модели (прецедент «<файл>» у валидатора датасетов).
ANSWER_PATH = "<ответ модели>"

#: Пара промптов канала: (system, user) для первого запроса круга.
Prompt = tuple[str, str]

#: Ответ канала: ``await ask(system, user, on_phase=…)`` → сырой текст ответа.
#: Реализация на ``BaseLlmProvider`` — :func:`make_llm_answer`; тесты подают
#: стаб-каналы с той же формой.
AnswerFn = Callable[..., Awaitable[str]]


class DocumentExtractionError(ValueError):
    """Ответ не содержит JSON-документа (task 1.2).

    Ошибка извлечения — обычная ошибка круга: раннер превращает её в ISSUE
    ``INVALID_JSON``, которая уходит в обратную связь перегенерации вместе с
    ошибками валидатора.
    """


class GenerationChannel(Protocol):
    """Один канал генерации модуля: секция датасета, гримуар, персонаж.

    Контракт — форма, не поведение: круг одинаков для всех каналов, канал
    знает только свои промпты, извлечение и валидатор.
    """

    def build_prompt(self, context: Any) -> Prompt:
        """(system, user) для ПЕРВОГО запроса круга на этом входе."""

    def parse(self, answer: str) -> str:
        """Извлечь текст документа из ответа модели.

        Провал — исключение ``ValueError`` (обычно
        :class:`DocumentExtractionError`): раннер засчитывает его как ошибку
        круга «не JSON» и ведёт в обратную связь.
        """

    def validate(self, document: str, context: Any) -> ValidationReport:
        """Существующий валидатор канала; артефакт круга — текст документа."""


@dataclass(frozen=True)
class GenerationRoundResult:
    """Что ответил один вызов :func:`run_rounds` (task 1.1).

    Лист-задача по полям решает предпросмотр: ``error_message`` — русская
    ошибка канала (секцию можно перезапустить), ``ok`` — документ готов к
    принятию, иначе — отчёт с ошибками и кнопка «Ещё круг»
    (:paramref:`run_rounds.previous` = этот результат).
    """

    #: последний сырой ответ канала ('' — если канал не ответил)
    answer: str = ""
    #: текст последнего успешно извлечённого документа (None — пока не было)
    document: str | None = None
    #: отчёт валидатора к документу (к ошибке извлечения — «не JSON»)
    report: ValidationReport = ValidationReport()
    #: завершённых запросов к каналу за этот вызов раннера
    attempts: int = 0
    #: русское сообщение сбоя канала LLM; None — канал жив
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        """Сбой канала и ошибки валидатора — единственный отказ круга."""
        return self.error_message is None and not self.report.errors


def format_round_feedback(answer: str, report: ValidationReport) -> str:
    """Обратная связь круга (spec): прежний ответ + полный список ошибок.

    Только ``severity=ERROR`` — предупреждения в перегенерацию не отправляются
    (spec «Предупреждения не запускают круг»); каждая ошибка — кодом, путём и
    русским сообщением.
    """
    lines = "\n".join(
        f"- {issue.code} · {issue.path} · {issue.message}" for issue in report.errors
    )
    return (
        "Проверка отклонила предыдущий ответ. Ошибки (код · путь · сообщение):\n"
        f"{lines}\n\n"
        "Прежний ответ:\n"
        f"{answer}\n\n"
        "Выдай исправленный документ целиком, без пояснений вокруг него."
    )


async def run_rounds(
    channel: GenerationChannel,
    context: Any,
    ask: AnswerFn,
    *,
    previous: GenerationRoundResult | None = None,
    max_auto: int = AUTO_ROUND_LIMIT,
    on_phase: Callable[[str], None] | None = None,
) -> GenerationRoundResult:
    """Провести документ через круг; возвращает всегда, не бросает сбой канала.

    Первый запрос — ``build_prompt(context)``; каждый следующий — прежний
    ответ + ошибки (:func:`format_round_feedback`). Ручной «Ещё круг» —
    повторный вызов с ``previous`` = сохранённый результат: промпт собирается
    поверх прежнего ответа, лимит считается заново на вызов (клик мастера
    ничем не ограничен). ``on_phase`` (``in_flight``/``waiting``) доходит до
    провайдера без изменений (design Д8).
    """
    system, user = channel.build_prompt(context)
    answer = previous.answer if previous is not None else ""
    document = previous.document if previous is not None else None
    report = previous.report if previous is not None else ValidationReport()
    if previous is not None and previous.answer:
        user = format_round_feedback(previous.answer, previous.report)
    attempts = 0
    while True:
        try:
            answer = await ask(system, user, on_phase=on_phase)
        except LlmError as exc:
            # spec «Ошибки канала LLM»: русское сообщение вместо обрыва
            # задачи; незавершённый круг не порождает частичных ответов.
            return GenerationRoundResult(
                answer=answer, document=document, report=report,
                attempts=attempts, error_message=str(exc),
            )
        attempts += 1
        try:
            document = channel.parse(answer)
        except ValueError as exc:
            # task 1.2: «не JSON» — обычная ошибка круга, уходит в фидбек.
            document = None
            report = ValidationReport.of([
                CheckIssue(
                    code=CODE_INVALID_JSON,
                    severity=Severity.ERROR,
                    path=ANSWER_PATH,
                    message=str(exc),
                )
            ])
        else:
            report = channel.validate(document, context)
        if not report.errors:
            return GenerationRoundResult(
                answer=answer, document=document, report=report, attempts=attempts
            )
        if attempts > max_auto:
            # spec «Лимит автоматических кругов»: последний ответ «как есть»
            # с отчётом — дальше только ручная «Ещё круг».
            return GenerationRoundResult(
                answer=answer, document=document, report=report, attempts=attempts
            )
        user = format_round_feedback(answer, report)


def make_llm_answer(provider: BaseLlmProvider) -> AnswerFn:
    """Одиночный вызов существующего канала LLM (design Д8, task 1.3).

    Мышление включено, бюджет вывода — авто-пробуемый провайдером
    (``max_tokens=None``); фазы повторов идут ``on_phase`` как есть.
    """

    async def ask(
        system_prompt: str,
        user_prompt: str,
        on_phase: Callable[[str], None] | None = None,
    ) -> str:
        return await provider.generate(
            system_prompt,
            user_prompt,
            max_tokens=None,
            on_phase=on_phase,
            with_thinking=True,
        )

    return ask


# ── терпимое извлечение JSON-документа (task 1.2) ────────────────────────────

#: Markdown-fence типового артефакта моделей: ```json … ``` или ``` … ```.
_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*\n?(.*?)```", re.DOTALL)
#: Пары открывающая → закрывающая для сбалансированного скана.
_OPENERS = {"{": "}", "[": "]"}


def extract_json_document(answer: str) -> str:
    """Вынуть JSON-документ (объект или массив) из ответа модели.

    Прощает fence, языковую метку внутри него и обрамляющий текст до/после;
    провал — :class:`DocumentExtractionError` с русским сообщением, который
    круг считает обычной ошибкой «не JSON».
    """
    text = answer.strip()
    if text:
        if _document_value(text) is not None:
            return text
        for fenced in _FENCE_RE.finditer(text):
            candidate = fenced.group(1).strip()
            if candidate and _document_value(candidate) is not None:
                return candidate
        sliced = _first_document_slice(text)
        if sliced is not None:
            return sliced
    raise DocumentExtractionError(
        "ответ модели не содержит JSON-документа: выдай только документ, "
        "без обрамляющего текста"
    )


def _document_value(candidate: str) -> Any:
    """JSON-значение кандидата, если это объект/массив; иначе None.

    Скаляр («42», «"текст"») документом не считается: все три канала пишут
    либо массив записей, либо объект-документ.
    """
    try:
        value = json.loads(candidate)
    except ValueError:
        return None
    return value if isinstance(value, (dict, list)) else None


def _first_document_slice(text: str) -> str | None:
    """Первый сбалансированный объект/массив, парсящийся как документ."""
    for start, char in enumerate(text):
        if char not in _OPENERS:
            continue
        end = _balanced_end(text, start)
        if end is None:
            continue
        candidate = text[start:end]
        if _document_value(candidate) is not None:
            return candidate
    return None


def _balanced_end(text: str, start: int) -> int | None:
    """Индекс за скобкой, закрывающей ``text[start]``; None — мусор.

    Скан знает о JSON-строках: кавычки со спас-последовательностями и скобки
    внутри строк (типовой артефакт — «}» в тексте описания) баланс не ломают.
    """
    stack: list[str] = []
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in _OPENERS:
            stack.append(char)
        elif char in _OPENERS.values():
            if not stack or _OPENERS[stack.pop()] != char:
                return None
            if not stack:
                return index + 1
    return None
