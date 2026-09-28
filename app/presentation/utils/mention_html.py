"""Mention markers as render-ready HTML links (NRI-0022, task 4.5).

The storage grammar (``@[display](type:id)``) lives in ``app.domain.mentions``;
this module is the single generator turning it into the inline anchors the
read-only surfaces show: the preview island (and any later summary) renders the
result in a RichText ``Text`` and intercepts ``onLinkActivated`` — the anchor
href is the compact ``nri://<type>/<id>`` pair the same module parses back
(:func:`parse_mention_link`), so generator and reader can never drift apart.

Being the one generator is the point (design D1, task 4.5 «те же ссылки, что
сводки DetailPanel»): escaping and the href shape are decided once, plain text
is HTML-escaped (user text is data, never markup), and a line break keeps its
meaning as ``<br>`` for the RichText label.
"""
from __future__ import annotations

import html

from app.domain import entity_registry
from app.domain.mentions import parse

#: Scheme of the generated anchors — anything else a click carries (a stray
#: external URL, a hand-typed marker fragment) is not a mention navigation.
MENTION_LINK_SCHEME = "nri://"


def build_mention_html(text: str) -> str:
    """Storage text -> RichText HTML: escaped plain runs + mention anchors.

    Line breaks become ``<br>`` (RichText collapses raw newlines); the mention
    display is escaped like any other text and loses its brackets exactly the
    way the editable chips do (the marker grammar already stored the clean
    display, ``domain.mentions.strip_brackets`` ran at insertion time)."""
    text = text or ""
    parts: list[str] = []
    last = 0
    for hit in parse(text or ""):
        parts.append(_escaped(text[last:hit.start]))
        parts.append(
            f'<a href="{MENTION_LINK_SCHEME}{hit.type}/{hit.id}">'
            f"{html.escape(hit.display, quote=True)}</a>"
        )
        last = hit.end
    parts.append(_escaped(text[last:]))
    return "".join(parts)


def parse_mention_link(link: str) -> tuple[str, int] | None:
    """An activated href -> ``(type key, id)``, or ``None`` for any other link.

    Strict on both halves: the type must be a registry key and the id an int —
    a stale hand-written or truncated href navigates nowhere instead of
    emitting a half-parsed selection (the same posture the registry keeps for
    unknown type keys)."""
    if not link or not link.startswith(MENTION_LINK_SCHEME):
        return None
    type_key, _, raw_id = link[len(MENTION_LINK_SCHEME):].partition("/")
    if entity_registry.resolve(type_key) is None:
        return None
    try:
        return type_key, int(raw_id)
    except ValueError:
        return None


def _escaped(chunk: str) -> str:
    return html.escape(chunk).replace("\n", "<br>")
