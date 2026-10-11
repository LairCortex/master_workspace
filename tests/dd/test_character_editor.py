"""The formatted-editor document converter (add-dnd-game-face task 9.2,
design Д7; spec dnd-character-import «Черты и заметки доезжают текстом»,
«неизвестные типы узлов не порождаются»).

What is pinned:

* the whitelist prints — paragraphs and text as text, ``formula``/``roller``
  as the formula string verbatim (``[STR]+2`` survives untouched),
  ``resource`` as «<имя>», ``divider`` as an empty line, ``spoiler*`` with
  its marker removed, task lists carrying «[x]/[ ]»;
* nothing unknown is silent: an unrecognised node contributes its children's
  text plus one ``CHAR_EDITOR_NODE`` warning, ``blockquote`` the same path
  with ``CHAR_EDITOR_BLOCKQUOTE``; the node type itself never reaches the
  output — the text lives on, the node does not;
* the three legal block shapes: a plain string comes back untouched, a list
  or a ``doc`` converts through the same walk, anything else keeps its JSON
  bytes visible behind a warning («ни один текстовый блок не потерян молча»).
"""
from __future__ import annotations

import json

from app.dd.domain.character_editor import (
    CODE_CHAR_EDITOR_BLOCKQUOTE,
    CODE_CHAR_EDITOR_NODE,
    editor_doc_to_text,
)
from app.dd.domain.validation_report import Severity


def _text(value: str) -> dict:
    return {"type": "text", "text": value}


def _doc(*blocks: object) -> dict:
    return {"type": "doc", "content": list(blocks)}


def _codes(issues) -> list[str]:
    return [issue.code for issue in issues]


# ── the three legal shapes ─────────────────────────────────────────────────


def test_plain_string_block_returns_untouched_and_silent():
    text, issues = editor_doc_to_text("обычная строка\nбез конвертации")
    assert text == "обычная строка\nбез конвертации"
    assert issues == []


def test_top_level_list_walks_its_blocks():
    text, issues = editor_doc_to_text([{"type": "paragraph", "content": [_text("а")]}])
    assert text == "а"
    assert issues == []


def test_unreadable_block_shape_keeps_its_json_bytes():
    text, issues = editor_doc_to_text(42)
    assert text == json.dumps(42)
    assert _codes(issues) == [CODE_CHAR_EDITOR_NODE]
    assert issues[0].severity is Severity.WARNING
    assert "сохранено как JSON" in issues[0].message


# ── the whitelist ──────────────────────────────────────────────────────────


def test_paragraphs_print_as_lines():
    doc = _doc(
        {"type": "paragraph", "content": [_text("первый абзац")]},
        {"type": "paragraph", "content": [_text("второй")]},
    )
    text, issues = editor_doc_to_text(doc)
    assert text == "первый абзац\nвторой"
    assert issues == []


def test_formula_and_roller_survive_verbatim():
    doc = _doc(
        {
            "type": "paragraph",
            "content": [
                {"type": "formula", "attrs": {"formula": "[STR]+2"}},
                _text(" · "),
                {"type": "roller", "attrs": {"formula": "1d8+3"}},
                _text(" · "),
                {"type": "roller", "attrs": {"label": "атака топором"}},
                _text(" · "),
                {"type": "roller", "attrs": {"text": "d6"}},
                _text(" · "),
                {"type": "roller", "attrs": {}},
            ],
        }
    )
    text, issues = editor_doc_to_text(doc)
    assert text == "[STR]+2 · 1d8+3 · атака топором · d6 · "
    assert issues == []


def test_formula_falls_back_to_text_attr_and_drops_non_strings():
    doc = _doc(
        {
            "type": "paragraph",
            "content": [
                {"type": "formula", "text": "2d6"},
                {"type": "formula", "attrs": {"formula": 7}},
            ],
        }
    )
    text, issues = editor_doc_to_text(doc)
    assert text == "2d6"
    assert issues == []


def test_resource_prints_its_angle_name():
    doc = _doc(
        {
            "type": "paragraph",
            "content": [
                {"type": "resource", "attrs": {"name": "Ярость"}},
                _text(" "),
                {"type": "resource", "attrs": {}},
            ],
        }
    )
    text, _issues = editor_doc_to_text(doc)
    assert text == "<Ярость> <ресурс>"


def test_divider_prints_an_empty_line_and_hard_breaks_split():
    doc = _doc(
        {"type": "paragraph", "content": [_text("до")]},
        {"type": "divider"},
        {"type": "paragraph", "content": [_text("перелом"), {"type": "hardBreak"}, _text("после")]},
    )
    text, _issues = editor_doc_to_text(doc)
    assert text == "до\n\nперелом\nпосле"


def test_spoiler_prints_its_expanded_text_without_a_marker():
    doc = _doc(
        {
            "type": "spoiler",
            "content": [{"type": "paragraph", "content": [_text("спрятанное")]}],
        }
    )
    text, issues = editor_doc_to_text(doc)
    assert text == "спрятанное"
    assert issues == []


def test_task_list_carries_checkbox_markers():
    doc = _doc(
        {
            "type": "taskList",
            "content": [
                {
                    "type": "taskItem",
                    "attrs": {"checked": True},
                    "content": [_text("сделано")],
                },
                {
                    "type": "taskItem",
                    "attrs": {"checked": False},
                    "content": [_text("ещё нет")],
                },
            ],
        }
    )
    text, issues = editor_doc_to_text(doc)
    assert text == "- [x] сделано\n- [ ] ещё нет"
    assert issues == []


def test_bullet_and_ordered_lists_number_and_indent():
    doc = _doc(
        {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [_text("раз")]},
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [_text("два")]},
                        {"type": "paragraph", "content": [_text("двa продолжение")]},
                    ],
                },
            ],
        },
        {
            "type": "orderedList",
            "content": [{"type": "listItem", "content": [_text("пункт")]}],
        },
    )
    text, issues = editor_doc_to_text(doc)
    assert text == "- раз\n- два\n  двa продолжение\n1. пункт"
    assert issues == []


# ── nothing unknown is silent ──────────────────────────────────────────────


def test_unknown_block_node_keeps_children_text_and_warns():
    doc = _doc(
        {
            "type": "statBlock",
            "content": [{"type": "paragraph", "content": [_text("цифры")]}, _text("хвост")],
        }
    )
    text, issues = editor_doc_to_text(doc)
    assert "цифры" in text and "хвост" in text
    assert _codes(issues) == [CODE_CHAR_EDITOR_NODE]
    assert "statBlock" in issues[0].message
    assert "doc.content[0]" == issues[0].path


def test_unknown_inline_node_keeps_children_and_warns_once():
    doc = _doc(
        {
            "type": "paragraph",
            "content": [{"type": "mystery", "content": [_text("дети")]}],
        }
    )
    text, issues = editor_doc_to_text(doc)
    assert text == "дети"
    assert _codes(issues) == [CODE_CHAR_EDITOR_NODE]
    assert "mystery" in issues[0].message


def test_blockquote_is_cut_its_text_survives_under_its_own_code():
    doc = _doc(
        {
            "type": "blockquote",
            "content": [{"type": "paragraph", "content": [_text("цитата")]}, _text("")],
        },
        {
            "type": "paragraph",
            "content": [{"type": "blockquote", "content": [_text("внутри")]}],
        },
    )
    text, issues = editor_doc_to_text(doc)
    assert text.split() == ["цитата", "внутри"]
    assert _codes(issues) == [CODE_CHAR_EDITOR_BLOCKQUOTE, CODE_CHAR_EDITOR_BLOCKQUOTE]


def test_unreadable_nodes_are_skipped_with_a_warning_each():
    doc = _doc(
        "не узел",
        {"type": "bulletList", "content": ["не элемент"]},
        {"type": "paragraph", "content": ["не inline"]},
    )
    text, issues = editor_doc_to_text(doc)
    assert text == ""
    assert _codes(issues) == [CODE_CHAR_EDITOR_NODE] * 3


def test_bare_inline_node_at_block_position_prints_its_line():
    doc = _doc({"type": "text", "text": "одна строка"})
    text, issues = editor_doc_to_text(doc)
    assert text == "одна строка"
    assert issues == []


def test_bare_task_item_at_block_position_prints_its_line():
    doc = _doc(
        {"type": "taskItem", "attrs": {"checked": True}, "content": [_text("галочка")]},
        {"type": "listItem", "content": [_text("пункт")]},
    )
    text, issues = editor_doc_to_text(doc)
    assert text == "галочка\nпункт"
    assert issues == []


def test_empty_text_nodes_contribute_nothing():
    doc = _doc(
        {"type": "paragraph", "content": [{"type": "text"}]},
        {"type": "paragraph"},
    )
    text, issues = editor_doc_to_text(doc)
    assert text == "\n"
    assert issues == []
