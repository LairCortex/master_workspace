"""Qt-free mention marker grammar. Storage format: @[display](type:id).

add-dnd-game-face (design Д4, spec mentions «Единая грамматика маркеров»)
widens the id slot: the kernel era stored ``\\d+`` only — every text written
before this change quotes digits for its five kernel types and one event key-
word — and registered EXTERNAL types add string ids, composite «источник/запись»
pairs included (``@[Тёмное зрение](feat:srd51/Darkvision)``). Which shape a
marker may carry is decided BY THE TYPE (``is_admissible_id``): kernel types
stay digits-only — an external-shaped id under a kernel type never parses, so
no old text is reinterpreted and no forged marker can impersonate a row — and
external types accept the whole string alphabet. A type the registry does not
know follows the kernel half (digits): exactly the set the old grammar matched,
so unknown-type markers parse and render byte-for-byte as they always did.
"""
from __future__ import annotations

import re
from typing import NamedTuple

from app.domain import entity_registry

MENTION_ID_RE = re.compile(r"\d+|[A-Za-z0-9][A-Za-z0-9._/+-]*")

_MENTION_RE = re.compile(r"@\[([^\]]+)\]\((\w+):(\d+|[A-Za-z0-9][A-Za-z0-9._/+-]*)\)")


class MentionMatch(NamedTuple):
    display: str
    type: str
    #: the id as STORED — the grammar is textual now (design Д4): kernel rows
    #: quote their digits as a numeric string, external records quote their
    #: string/composite source id; callers convert at their own boundary
    id: str
    start: int
    end: int


def is_admissible_id(type_key: str, marker_id: str) -> bool:
    """Whether ``marker_id`` is a legal id for ``type_key`` (design Д4: the
    descriptor decides the shape). Kernel types: digits only — the reverse
    direction is barred on purpose so old texts are never re-read with the
    external grammar. Registered external types: any non-empty id the grammar
    accepts, composite ``источник/запись`` included. Unknown keys answer as
    the kernel half (digits), keeping every pre-change parse result intact."""
    if not MENTION_ID_RE.fullmatch(marker_id or ""):
        return False
    if entity_registry.is_external_key(type_key):
        return True
    return marker_id.isdigit()


def parse(text: str) -> list[MentionMatch]:
    """Extract mention markers: display, type, string id, span.

    A marker whose id the type does not admit (e.g. ``character:abc``) is not
    a marker at all: the bytes stay plain text, exactly as they were before
    the grammar knew string ids."""
    hits: list[MentionMatch] = []
    for m in _MENTION_RE.finditer(text or ""):
        marker_id = m.group(3)
        if not is_admissible_id(m.group(2), marker_id):
            continue
        hits.append(
            MentionMatch(
                display=m.group(1),
                type=m.group(2),
                id=marker_id,
                start=m.start(),
                end=m.end(),
            )
        )
    return hits


def format_marker(type: str, id: str, display: str) -> str:
    """Assemble one storage marker: brackets are stripped from the DISPLAY
    only (the target's ``name`` column is never cleaned), an empty display
    becomes ``?`` (spec «Пустой display после strip»)."""
    return f"@[{strip_brackets(display)}]({type}:{id})"


def strip_brackets(name: str) -> str:
    """Remove all '[' and ']' then strip; empty result becomes '?'."""
    cleaned = (name or "").replace("[", "").replace("]", "").strip()
    return cleaned if cleaned else "?"


def rewrite_display_name(text: str, type: str, id: int | str, new_name: str) -> str:
    """Replace display of markers matching type+id; other bytes unchanged.

    The rename path is kernel-only (external records own no rename — their
    chip display is a snapshot), hence the id arrives as a kernel int and is
    compared against the stored textual id as text."""
    display = strip_brackets(new_name)
    target = str(id)
    parts: list[str] = []
    last = 0
    for m in parse(text):
        parts.append(text[last:m.start])
        if m.type == type and m.id == target:
            parts.append(format_marker(type, m.id, display))
        else:
            parts.append(text[m.start:m.end])
        last = m.end
    parts.append((text or "")[last:])
    return "".join(parts)
