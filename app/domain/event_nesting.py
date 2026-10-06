"""Two-level event nesting as one judge for the card and the import (NRI-0027, design Д5).

Exactly two levels is a single rule with two doors: the event card
(``EventService._guard_parent``, NRI-0023 task 3.2) refuses a parent that is
the edited event itself, does not exist, or is itself a sub-event, and the
xlsx pre-analysis (NRI-0027) must refuse the very same links with the very
same Russian reason.  The judge and the wordings live here once — principle
«one knowledge, one place»: no second copy of the rule or of its phrasing
may appear at a usage site.

Pure domain code: no Qt, no ORM, no session.  The judge takes the three
plain booleans about the parent the caller has already looked up, and the
wordings are returned as data; raising and rendering stay with the caller.
"""
from __future__ import annotations

#: Refusal code: the parent is missing (card: an unknown id; import: a name
#: found neither among the file's rows nor among the game's events).
CODE_NOT_FOUND = "not_found"

#: Refusal code: the parent exists but is itself a sub-event — attaching to
#: it would open a third level.
CODE_IS_SUBEVENT = "is_subevent"

#: Refusal code: the event points at itself as its parent.
CODE_SELF_PARENT = "self_parent"

#: Russian user-facing wording per refusal code — verbatim the historical
#: ``EventService`` ``ValueError`` texts, regression-pinned by the event
#: service and event card tests.  ``not_found`` carries the parent slot;
#: the other two codes are whole sentences.
PARENT_REFUSAL_MESSAGES: dict[str, str] = {
    CODE_NOT_FOUND: "родительское событие {parent_id} не найдено",
    CODE_IS_SUBEVENT: "родительское событие не может быть подсобытием",
    CODE_SELF_PARENT: "событие не может быть родителем самого себя",
}


def parent_refusal_code(
    parent_found: bool,
    parent_is_child: bool,
    is_self: bool,
) -> str | None:
    """The one two-level verdict for a parent link (design Д5).

    ``parent_found`` — the parent record exists; ``parent_is_child`` — that
    parent has a parent of its own; ``is_self`` — parent and child are the
    same event.  Returns a ``CODE_*`` string, or ``None`` when the link is
    allowed.  The evaluation order reproduces the historical
    ``EventService._guard_parent``: self first, then existence, then the
    sub-event ban — so a bypassed pair hears the same refusal as before.
    """
    if is_self:
        return CODE_SELF_PARENT
    if not parent_found:
        return CODE_NOT_FOUND
    if parent_is_child:
        return CODE_IS_SUBEVENT
    return None


def parent_refusal_message(code: str, parent_id: int | None = None) -> str:
    """Russian user-facing text of a refusal code.

    ``parent_id`` fills the ``not_found`` slot; the whole-sentence codes
    ignore it.  An unknown code raises ``KeyError`` — callers judge through
    :func:`parent_refusal_code`, never invent codes at a usage site.
    """
    return PARENT_REFUSAL_MESSAGES[code].format(parent_id=parent_id)
