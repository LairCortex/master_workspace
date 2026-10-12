"""Построитель блоков форматированного редактора (add-dnd-lss-generation,
task 5.2; spec dnd-character-export «Совместимость экспорта с приёмом LSS»).

Два лица одного обещания:

* **узлы** — построентая структура печатает только doc/paragraph/text/formula
  (ни HTML, ни blockquote никогда), формульные spans становятся узлами
  ``formula`` с ``attrs.formula``, а скобки не-форматного написания остаются
  текстом;
* **round-trip** — текст карточки → блок → ``editor_doc_to_text`` читает его
  обратно тем же текстом, с точностью до формульной нотации (spec scenario
  «Файл проходит гейты формата»: блок — валидный узел редактора).
"""
from __future__ import annotations

import json

from app.dd.domain.character_blocks import FORMULA_SPAN_RE, text_to_editor_doc
from app.dd.domain.character_editor import editor_doc_to_text


def _texts_and_formulas(doc: dict) -> tuple[list[str], list[str]]:
    """Все текстовые и формульные значения дерева одним проходом — тестам
    не нужна раскладка узлов, только их содержимое."""
    texts: list[str] = []
    formulas: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text":
                texts.append(node.get("text", ""))
            if node.get("type") == "formula":
                formulas.append(node["attrs"]["formula"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(doc)
    return texts, formulas


# ── узлы ─────────────────────────────────────────────────────────────────────


def test_plain_line_is_one_paragraph_of_text():
    doc = text_to_editor_doc("Сильный, но молчалив.")
    assert doc == {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Сильный, но молчалив."}]}
        ],
    }


def test_lines_become_paragraphs_in_order():
    doc = text_to_editor_doc("первая\nвторая")
    paragraphs = doc["content"]
    assert [p["type"] for p in paragraphs] == ["paragraph", "paragraph"]
    assert editor_doc_to_text(doc)[0] == "первая\nвторая"


def test_empty_line_is_an_empty_paragraph():
    doc = text_to_editor_doc("а\n\nб")
    assert doc["content"][1] == {"type": "paragraph"}
    texts, formulas = _texts_and_formulas(doc)
    assert formulas == []
    assert "".join(texts) == "аб"


def test_formula_span_becomes_formula_node():
    doc = text_to_editor_doc("КД = [DEX] + [PROF]")
    texts, formulas = _texts_and_formulas(doc)
    assert formulas == ["[DEX]", "[PROF]"]
    assert texts == ["КД = ", " + "]
    paragraph = doc["content"][0]
    assert [node["type"] for node in paragraph["content"]] == [
        "text",
        "formula",
        "text",
        "formula",
    ]
    # узел живёт в attrs.formula — так его читает конвертер (Д7)
    assert paragraph["content"][1] == {"type": "formula", "attrs": {"formula": "[DEX]"}}


def test_bare_formula_line_has_no_text_nodes():
    doc = text_to_editor_doc("[AC]")
    assert doc["content"][0]["content"] == [
        {"type": "formula", "attrs": {"formula": "[AC]"}}
    ]


def test_non_format_brackets_stay_text():
    doc = text_to_editor_doc("[заметка] [a1] [STRx] [2STR] [-X] []")
    texts, formulas = _texts_and_formulas(doc)
    assert formulas == []
    assert texts == ["[заметка] [a1] [STRx] [2STR] [-X] []"]


def test_underscore_variable_is_a_formula():
    _, formulas = _texts_and_formulas(text_to_editor_doc("спасбросок: [SPELL_SAVE_DC]"))
    assert formulas == ["[SPELL_SAVE_DC]"]


def test_no_html_and_no_blockquote_anywhere():
    doc = text_to_editor_doc("<b>жирный</b> > цитата\n- пункт")
    kinds = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "type" in node:
                kinds.add(node["type"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(doc)
    assert kinds <= {"doc", "paragraph", "text", "formula"}


def test_span_regex_is_the_whole_notation():
    assert FORMULA_SPAN_RE.findall("[STR]+1d8-[DEX]") == ["[STR]", "[DEX]"]


# ── round-trip «текст карточки → блок → чтение» ─────────────────────────────


def test_roundtrip_plain_text_is_exact():
    text = "Грог молчалив.\n\nЛюбит камень и тишину.\nОсобенность: [STR] и [CON] высокие."
    doc = text_to_editor_doc(text)
    read, issues = editor_doc_to_text(doc)
    assert issues == []
    assert read == text


def test_roundtrip_json_round_trip_keeps_the_text():
    # документ доезжает в файле JSON-строкой — сериализация ничего не ломает
    doc = json.loads(json.dumps(text_to_editor_doc("[PROF] к восприятию"), ensure_ascii=False))
    read, issues = editor_doc_to_text(doc)
    assert issues == []
    assert read == "[PROF] к восприятию"


def test_roundtrip_empty_text_is_a_readable_empty_block():
    doc = text_to_editor_doc("")
    read, issues = editor_doc_to_text(doc)
    assert issues == []
    assert read == ""


def test_roundtrip_trailing_and_leading_newlines_survive():
    text = "\nпосле пустой\nперед пустой\n"
    read, _issues = editor_doc_to_text(text_to_editor_doc(text))
    assert read == text
