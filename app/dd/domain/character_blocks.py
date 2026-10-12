"""Построитель текстовых блоков форматированного редактора (add-dnd-lss-generation, task 5.2).

Зеркало ``editor_doc_to_text``: plain-текст карточки (то, что мастер читает и
правит) превращается в значение текстового блока документа LSS — документ
форматированного редактора (design Д4, spec dnd-character-export «Совместимость
экспорта с приёмом LSS»). Узлы печатаются только из закрытого whitelist'a
конвертера: ``doc``/``paragraph``/``text``/``formula`` — никакого HTML и никаких
``blockquote`` построитель не порождает никогда.

Формульная нотация формата — латиницей заглавные переменные в квадратных
скобках (``[STR]``, ``[PROF]``): ровно такие spans собираются в узлы
``formula`` с ``attrs.formula`` (spec «формулы — латиницей заглавными
переменными»). Любые другие скобки — ``[заметка на русском]``, ``[a1]``, ``[STRx]``
— остаются текстом: узел формулы порождается только там, где формат его
ожидает, и round-trip с конвертером остаётся точным.

Round-trip (:func:`editor_doc_to_text` из соседнего модуля) — текстовый
эквивалент: ``\\n`` разбивает на абзацы, каждый абзац читается обратно своей
строкой; формульные узлы конвертер печатает их же нотацией. Общий с каналом
персонажа (task 6.x): тот же построитель, та же нотация.

Qt-free, storage-free: строка → структура, никакого I/O.
"""
from __future__ import annotations

import re
from typing import Any

#: Span формулы: «[» + заглавная латинская буква + заглавные латинские буквы /
#: подчёркивания + «]» — переменные формата (STR, DEX, PROF, SPELL_SAVE_DC…).
#: Строчные буквы, кириллица и цифры внутри скобок текстом формулой не становятся.
FORMULA_SPAN_RE = re.compile(r"\[[A-Z][A-Z_]*\]")


def _inline_nodes(line: str) -> list[dict[str, Any]]:
    """Строка → inline-узлы абзаца: текст между формульными spans остаётся
    текстом, каждый span — узел ``formula`` со своей нотацией внутри
    ``attrs.formula`` (именно так узел читает ``editor_doc_to_text``)."""
    nodes: list[dict[str, Any]] = []
    position = 0
    for match in FORMULA_SPAN_RE.finditer(line):
        if match.start() > position:
            nodes.append({"type": "text", "text": line[position : match.start()]})
        nodes.append({"type": "formula", "attrs": {"formula": match.group()}})
        position = match.end()
    if position < len(line):
        nodes.append({"type": "text", "text": line[position:]})
    return nodes


def text_to_editor_doc(text: str) -> dict[str, Any]:
    """Plain-текст текстового блока → документ форматированного редактора.

    Каждая строка — отдельный ``paragraph``; пустая строка — пустой абзац
    (пустой строкой и читается). Ничего, кроме doc/paragraph/text/formula,
    не порождается (spec: без HTML и ``blockquote``)."""
    paragraphs: list[dict[str, Any]] = []
    for line in text.split("\n"):
        content = _inline_nodes(line)
        paragraphs.append(
            {"type": "paragraph", "content": content} if content else {"type": "paragraph"}
        )
    return {"type": "doc", "content": paragraphs}
