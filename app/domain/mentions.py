"""Qt-free mention marker grammar. Storage format: @[display](type:id)."""
from __future__ import annotations

import re
from typing import NamedTuple

_MENTION_RE = re.compile(r"@\[([^\]]+)\]\((\w+):(\d+)\)")


class MentionMatch(NamedTuple):
    display: str
    type: str
    id: int
    start: int
    end: int


def parse(text: str) -> list[MentionMatch]:
    """Extract mention markers: display, type, numeric id, span."""
    hits: list[MentionMatch] = []
    for m in _MENTION_RE.finditer(text or ""):
        hits.append(
            MentionMatch(
                display=m.group(1),
                type=m.group(2),
                id=int(m.group(3)),
                start=m.start(),
                end=m.end(),
            )
        )
    return hits


def strip_brackets(name: str) -> str:
    """Remove all '[' and ']' then strip; empty result becomes '?'."""
    cleaned = (name or "").replace("[", "").replace("]", "").strip()
    return cleaned if cleaned else "?"


def rewrite_display_name(text: str, type: str, id: int, new_name: str) -> str:
    """Replace display of markers matching type+id; other bytes unchanged."""
    display = strip_brackets(new_name)
    parts: list[str] = []
    last = 0
    for m in parse(text):
        parts.append(text[last:m.start])
        if m.type == type and m.id == id:
            parts.append(f"@[{display}]({type}:{id})")
        else:
            parts.append(text[m.start:m.end])
        last = m.end
    parts.append((text or "")[last:])
    return "".join(parts)
