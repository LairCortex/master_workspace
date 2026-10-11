"""The formatted-editor document converter (add-dnd-game-face task 9.2,
design Д7; spec dnd-character-import «раскладывание полное»).

A text block of an LSS character document is a formatted-editor document — a
node tree in ProseMirror's «type/content/attrs» shape. The converter walks a
CLOSED whitelist (Д7): ``paragraph``/``text``/lists print text, ``formula``
and ``roller`` print their formula string as it stands (the ``[STR]``
notation survives verbatim — spec scenario «Черты и заметки доезжают
текстом»), ``resource`` prints «<имя ресурса>», ``divider`` prints an empty
line, ``spoiler*`` prints its expanded text, ``taskList`` prints lines with
«[x]/[ ]» checkbox markers.

Nothing unknown reaches the output silently: an unrecognised node contributes
its CHILDREN's text and one warning (the node type itself is never produced —
spec «неизвестные типы узлов не порождаются»), ``blockquote`` takes the same
path with its own code (our converter never produces one either way). A node
that is not a node at all, and a block value that is not a document, keep
their bytes visible (JSON text) instead of vanishing: «ни один текстовый блок
не потерян молча» covers the shapes we do not know, too.

Qt-free and storage-free: text and issues out, no I/O.
"""
from __future__ import annotations

import json
from typing import Any

from app.dd.domain.validation_report import CheckIssue, Severity

# --- issue codes (stable machine contract) ---------------------------------
CODE_CHAR_EDITOR_NODE = "CHAR_EDITOR_NODE"
CODE_CHAR_EDITOR_BLOCKQUOTE = "CHAR_EDITOR_BLOCKQUOTE"

#: The inline node types the whitelist knows (everything else at inline
#: position is «unknown» — children kept, wrapper dropped, one warning).
_INLINE_TYPES = frozenset({"text", "formula", "roller", "resource", "hardBreak"})


def _issue(code: str, path: str, message: str) -> CheckIssue:
    return CheckIssue(code=code, severity=Severity.WARNING, path=path, message=message)


def _attr(node: dict[str, Any], name: str) -> Any:
    """One attribute, ProseMirror's ``attrs`` first with a tolerant
    top-level fallback (hand-written golden fixtures and older exports
    disagree about where attributes live)."""
    attrs = node.get("attrs")
    if isinstance(attrs, dict) and name in attrs:
        return attrs[name]
    return node.get(name)


def _content(node: dict[str, Any]) -> list[Any]:
    content = node.get("content")
    return content if isinstance(content, list) else []


def _inline_children(node: dict[str, Any], issues: list[CheckIssue], path: str) -> str:
    return "".join(
        _inline(child, issues, f"{path}.content[{index}]")
        for index, child in enumerate(_content(node))
    )


def _inline(node: Any, issues: list[CheckIssue], path: str) -> str:
    if not isinstance(node, dict):
        issues.append(
            _issue(
                CODE_CHAR_EDITOR_NODE,
                path,
                "нечитаемый inline-узел пропущен (не является объектом)",
            )
        )
        return ""
    kind = node.get("type")
    if kind == "text":
        text = node.get("text")
        return text if isinstance(text, str) else ""
    if kind == "formula":
        value = _attr(node, "formula")
        if not isinstance(value, str):
            value = _attr(node, "text")
        return value if isinstance(value, str) else ""
    if kind == "roller":
        for key in ("formula", "label", "text"):
            value = _attr(node, key)
            if isinstance(value, str) and value:
                return value
        return ""
    if kind == "resource":
        name = _attr(node, "name")
        return f"<{name}>" if isinstance(name, str) and name else "<ресурс>"
    if kind == "hardBreak":
        return "\n"
    if kind == "blockquote":
        issues.append(
            _issue(
                CODE_CHAR_EDITOR_BLOCKQUOTE,
                path,
                "blockquote вырезан при конвертации: текст детей сохранён как есть",
            )
        )
        return _inline_children(node, issues, path)
    issues.append(
        _issue(
            CODE_CHAR_EDITOR_NODE,
            path,
            f"неизвестный тип inline-узла {kind!r}: текст детей сохранён, узел не порождается",
        )
    )
    return _inline_children(node, issues, path)


def _item_lines(item: Any, issues: list[CheckIssue], path: str) -> list[str]:
    """One list/task item: its block children when it has them, its inline
    content otherwise (the editor allows both shapes)."""
    if not isinstance(item, dict):
        issues.append(
            _issue(
                CODE_CHAR_EDITOR_NODE,
                path,
                "нечитаемый элемент списка пропущен (не является объектом)",
            )
        )
        return []
    blocks = [
        child
        for child in _content(item)
        if isinstance(child, dict) and child.get("type") not in _INLINE_TYPES
    ]
    if blocks:
        lines: list[str] = []
        for index, block in enumerate(blocks):
            lines.extend(_block_lines(block, issues, f"{path}.content[{index}]"))
        return lines
    return _inline_children(item, issues, path).split("\n")


def _list_lines(
    node: dict[str, Any], issues: list[CheckIssue], path: str, marker: str
) -> list[str]:
    lines: list[str] = []
    content = _content(node)
    for index, item in enumerate(content):
        if marker == "ordered":
            prefix = f"{index + 1}. "
        elif marker == "task":
            checked = _attr(item, "checked") if isinstance(item, dict) else None
            prefix = "- [x] " if checked else "- [ ] "
        else:
            prefix = "- "
        item_lines = _item_lines(item, issues, f"{path}.content[{index}]")
        for position, line in enumerate(item_lines):
            lines.append(prefix + line if position == 0 else "  " + line)
    return lines


def _children_block_lines(
    node: dict[str, Any], issues: list[CheckIssue], path: str
) -> list[str]:
    lines: list[str] = []
    for index, child in enumerate(_content(node)):
        lines.extend(_block_lines(child, issues, f"{path}.content[{index}]"))
    return lines


def _block_lines(node: Any, issues: list[CheckIssue], path: str) -> list[str]:
    if not isinstance(node, dict):
        issues.append(
            _issue(
                CODE_CHAR_EDITOR_NODE,
                path,
                "нечитаемый блочный узел пропущен (не является объектом)",
            )
        )
        return []
    kind = node.get("type")
    if kind == "doc":
        return _children_block_lines(node, issues, path)
    if kind == "paragraph":
        return _inline_children(node, issues, path).split("\n")
    if kind in ("bulletList", "unorderedList"):
        return _list_lines(node, issues, path, "bullet")
    if kind == "orderedList":
        return _list_lines(node, issues, path, "ordered")
    if kind in ("taskList", "task_list"):
        return _list_lines(node, issues, path, "task")
    if kind in ("taskItem", "listItem"):
        return _item_lines(node, issues, path)
    if kind == "divider":
        return [""]
    if isinstance(kind, str) and kind.startswith("spoiler"):
        # Д7: «spoiler* → развернутый текст» — the marker never survives.
        return _children_block_lines(node, issues, path)
    if kind in _INLINE_TYPES:
        # A bare inline node at block position is its text on its own line.
        return _inline(node, issues, path).split("\n")
    if kind == "blockquote":
        issues.append(
            _issue(
                CODE_CHAR_EDITOR_BLOCKQUOTE,
                path,
                "blockquote вырезан при конвертации: текст детей сохранён как есть",
            )
        )
        return _children_block_lines(node, issues, path)
    issues.append(
        _issue(
            CODE_CHAR_EDITOR_NODE,
            path,
            f"неизвестный тип блочного узла {kind!r}: текст детей сохранён, узел не порождается",
        )
    )
    return _children_block_lines(node, issues, path)


def editor_doc_to_text(document: object) -> tuple[str, list[CheckIssue]]:
    """Convert one text-block value to plain text.

    Accepts the block's three legal shapes: an already-plain string (returns
    it untouched), a list of block nodes, or a node (a ``doc`` in practice).
    Anything else keeps its JSON bytes visible behind a warning instead of
    dying silently. The returned issues carry converter-relative paths
    (``doc.…``) — the import flow re-anchors them under the block name.
    """
    issues: list[CheckIssue] = []
    if isinstance(document, str):
        return document, []
    if isinstance(document, list):
        lines: list[str] = []
        for index, child in enumerate(document):
            lines.extend(_block_lines(child, issues, f"doc[{index}]"))
        return "\n".join(lines), issues
    if isinstance(document, dict):
        return "\n".join(_block_lines(document, issues, "doc")), issues
    issues.append(
        _issue(
            CODE_CHAR_EDITOR_NODE,
            "<блок>",
            "содержимое текстового блока не читается как документ редактора — "
            "сохранено как JSON",
        )
    )
    return json.dumps(document, ensure_ascii=False), issues
