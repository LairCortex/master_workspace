"""Synchronous, render-ready state for the entity-preview QML island.

NRI-0022 (tasks 4.1–4.5) built this VM as the single shown entity; NRI-0025
(task 2.1, design Д2) split it: the per-card render moved whole into
:class:`EntityCardViewModel` (one instance per visible card) and this class
owns the LIST — the column's ``panes`` (pinned cards in pin order, the live
card last) plus the empty-live-area flag. The lifecycle rules of the slots
(limit, order, storage) stay the connector's (design Д1): the column only
paints the frame ``show_slots`` hands in.

The island emits back only gestures: a selection request (relation row /
mention link — the same ``(type, id)`` bus the panel's single click feeds,
design D2), the new pin toggle (by pair, never by index — the index can go
stale between press and answer, design Д2), and an image open request
carrying the pane that raised it, so the facade builds the viewer from that
pane's entity at the same 4096 slot.

Since the 2026-10-03 scroll-reset fix the frames carry slot identity: cards
of unchanged pairs are reused across ``show_slots`` calls (revs included),
an unchanged frame re-presentation notifies nothing, and the island keeps
each pinned pane's scroll offset across the frames that do change (see the
``show_slots`` docstring and the island's ``slotScrollMemory``).

No session, no ORM, no async here: the wiring feeds entities in and reads the
request signals out. The derived age line follows the game's «now» (NRI-0021
Д2/Д5 posture, design Д2): ONE subscription lives here and re-counts the age
of every card on the broadcast, and the island's release detaches it.

Since island group 4 (NRI-0025 task 4.1) the pane list is the island's ONLY
face — the transitional single-card scalar mirror the pre-rewrite QML bound
retired with the rewrite; the column's fully empty caption («Карточка») is a
painting-side literal of the zero-pane band, per spec «Пустая колонка
подписана одним словом».
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QObject, Property, Signal, Slot

from app.presentation.utils.mention_html import parse_mention_link
from app.presentation.viewmodels.entity_card_view_model import (
    EntityCardViewModel,
    content_fingerprint,
)

__all__ = ["MAX_PINNED_CARDS", "EntityPreviewViewModel"]

#: The pin-capacity of the column (spec preview-pins «до трёх закреплённых»).
#: The ONE owner of the number and of the live card's pin state (checkpoint
#: docs/qa/2026-10-02-preview-pins-layout.md п.5): the island reads only the
#: resulting ``pinState`` word and never counts pins or branches on the cap.
MAX_PINNED_CARDS = 3

#: The pin acts freely. In a pinned pane: the press removes the pin. In the
#: live pane: the press seats the card as the next pin, freeing the live area.
PIN_STATE_UNPIN = "unpin"
#: The live card's pair already sits in a pinned pane (spec «Закреплённая
#: сущность не закрепляется вторично») — the island answers «Уже закреплена».
PIN_STATE_DUPLICATE = "duplicate"
#: The column already holds ``MAX_PINNED_CARDS`` pins (spec «Четвёртое
#: закрепление невозможно») — the island answers the capacity wording.
PIN_STATE_LIMIT = "limit"


class EntityPreviewViewModel(QObject):
    """The column's card list; all composition rules live in the cards."""

    contentChanged = Signal()
    #: The preview's half of the one selection bus (design D2): a relation row
    #: or a mention link was activated — the wiring loads and shows that entity
    #: and tries the middle-column highlight; the preview never loads itself.
    entityRequested = Signal(str, int)
    #: The pin of a pane was activated (NRI-0025 design Д2/Д3): the pair plus
    #: the card's current pinned state — the connector toggles accordingly and
    #: answers with a fresh frame. By pair, never by index.
    pinToggleRequested = Signal(str, int, bool)
    #: The picture of a pane was activated; the pane identifies itself so the
    #: facade builds the viewer from THAT card's entity (task 2.2).
    imageRequested = Signal(str, int, bool)

    def __init__(self, now_vm=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._now_vm = now_vm
        self._cards: list[EntityCardViewModel] = []
        # The construction stamp feeding every card's ``rev`` (the island's
        # scroll memory validates a remembered offset against it — 2026-10-03
        # fix): a card built now is a different construction than its
        # same-pair predecessor, a reused card keeps the rev it was born with.
        self._rev_seq = 0
        if now_vm is not None:
            now_vm.nowChanged.connect(self._on_now_changed)

    # ── QML-facing properties — the multi-view face (design Д2) ─────────────

    panes = Property(
        "QVariant", lambda self: [card.pane() for card in self._cards],
        notify=contentChanged,
    )
    #: The live area has no card. With at least one pin the island paints the
    #: hint block below them; with no pins at all it is the whole-column empty
    #: state instead (``panes`` empty) — spec «Пустая живая область без
    #: заголовка» / «Пустая колонка подписана одним словом».
    liveEmpty = Property(bool, lambda self: self._live_card() is None, notify=contentChanged)

    # ── Python-side reads (the facade builds the viewer from these) ────────

    def pane_entity(self, entity_type: str, entity_id: int, pinned: bool) -> Any:
        """The loaded entity behind one pane (``None`` when no such pane is
        shown) — the facade's viewer build reads the requesting pane through
        here, so a duplicate pair answers per its pinned flag (task 2.2)."""
        for card in self._cards:
            if (
                card.pinned == pinned
                and card.entity_type == entity_type
                and card.entity_id == entity_id
            ):
                return card.entity
        return None

    # ── feeding (the wiring's two frame entry points, design Д1) ───────────

    def show_slots(
        self,
        pins: Sequence[tuple[str, Any]],
        live: tuple[str, Any] | None,
    ) -> None:
        """Paint one full frame: pinned cards in pin order, the live pair (if
        any) last. A re-show replaces the values (spec «Сохранение карточки
        обновляет предпросмотр», per copy); the connector owns which pairs
        belong in the frame, this VM only renders what it is handed — with
        one exception the checkpoint prescribes (п.5): the live card's
        ``pinState`` is counted HERE, so the capacity rule and the duplicate
        rule have exactly one owner next to ``MAX_PINNED_CARDS``.

        Slot identity (bug docs/qa/2026-10-03-preview-scroll-reset.md): a
        slot is the ``(pinned, type, id)`` triple, a construction is that
        triple plus the row whose rendered fingerprint still matches. A
        frame re-presenting an unchanged slot REUSES the whole card — its rev
        survives, which is what tells the island the remembered scroll offset
        belongs to current content; a slot whose row really changed (a save
        refreshed the row in place, a pin transition, a pin-word change)
        rebuilds with a fresh rev and repaints from the top, its neighbours
        untouched. A frame answering an unchanged one (every slot reused,
        order intact) emits NOTHING: with no notify the QML scene — and every
        pane's scroll — physically survives."""
        previous = {
            (card.pinned, card.entity_type, card.entity_id): card
            for card in self._cards
        }
        cards: list[EntityCardViewModel] = []
        rebuilt = False
        pinned_pairs: set[tuple[str, int]] = set()
        for index, (entity_type, entity) in enumerate(pins):
            card, reused = self._slot_card(
                previous, True, entity_type, entity, index, PIN_STATE_UNPIN
            )
            rebuilt = rebuilt or not reused
            pinned_pairs.add((entity_type, card.entity_id))
            cards.append(card)
        if live is not None:
            live_pair = (live[0], int(getattr(live[1], "id", 0) or 0))
            card, reused = self._slot_card(
                previous,
                False,
                live[0],
                live[1],
                len(pins),
                self._live_pin_state(live_pair, pinned_pairs),
            )
            rebuilt = rebuilt or not reused
            cards.append(card)
        # Pin order is part of the frame: even an all-reused reshuffle moves
        # cards between slots and must repaint (and re-announce) the list.
        changed = rebuilt or [
            (card.pinned, card.entity_type, card.entity_id) for card in cards
        ] != [
            (card.pinned, card.entity_type, card.entity_id) for card in self._cards
        ]
        self._cards = cards
        if changed:
            self.contentChanged.emit()

    def _slot_card(
        self,
        previous: dict[tuple[bool, str, int], EntityCardViewModel],
        pinned: bool,
        entity_type: str,
        entity: Any,
        slot_index: int,
        pin_state: str,
    ) -> tuple[EntityCardViewModel, bool]:
        """The card for one slot: the previous construction when the slot is
        unchanged (same pair, same row object whose rendered fields still
        carry the same fingerprint, same authored pin word — only the
        position may move, and it moves with the slot flags), a fresh render
        otherwise. Object identity alone cannot stamp the content: the save
        path's session identity map mutates the row IN PLACE mid-transaction
        (pinned by the e2e save tests), so the very same object can arrive
        with new values — the fingerprint of the rendered fields is what
        separates a real edit from a re-presentation."""
        pair = (entity_type, int(getattr(entity, "id", 0) or 0))
        card = previous.get((pinned,) + pair)
        if (
            card is not None
            and card.entity is entity
            and card.pin_state == pin_state
            and card.content_fingerprint == content_fingerprint(entity_type, entity)
        ):
            card.slot_index = slot_index
            return card, True
        self._rev_seq += 1
        return (
            EntityCardViewModel(
                entity_type,
                entity,
                self._now_vm,
                pinned=pinned,
                slot_index=slot_index,
                pin_state=pin_state,
                rev=self._rev_seq,
            ),
            False,
        )

    @staticmethod
    def _live_pin_state(
        live_pair: tuple[str, int], pinned_pairs: set[tuple[str, int]]
    ) -> str:
        """The live pane's pin state — the whole four-name decision minus the
        pinned half (a pinned card's pin always acts, ``PIN_STATE_UNPIN``).
        The duplicate outranks the capacity word on purpose: the spec pins
        the capacity scenario over a «четвёртая сущность» (a NEW entity) and
        the duplicate scenario without any count qualifier, so only this
        order satisfies both readings (preview-pins, 2026-10-02)."""
        if live_pair in pinned_pairs:
            return PIN_STATE_DUPLICATE
        if len(pinned_pairs) >= MAX_PINNED_CARDS:
            return PIN_STATE_LIMIT
        return PIN_STATE_UNPIN

    def clear(self) -> None:
        """Back to the self-explaining empty state (delete / new game / the
        next start all funnel through here via the wiring)."""
        self._cards = []
        self.contentChanged.emit()

    # ── QML-facing slots (the island's outgoing gestures) ──────────────────

    @Slot(str, int)
    def requestEntity(self, entity_type: str, entity_id: int) -> None:
        """A relation row was activated (mouse click or accessibility Press —
        the library row runs both through this one slot). Which pane raised
        it is the connector's live-area rule, not the payload's."""
        self.entityRequested.emit(entity_type, entity_id)

    @Slot(str)
    def requestLink(self, link: str) -> None:
        """``onLinkActivated`` receiver: a generated mention anchor navigates;
        any other href (external URL, stale fragment) is a silent no-op, so a
        broken mention of a deleted entity can never break the preview."""
        target = parse_mention_link(link)
        if target is None:
            return
        self.entityRequested.emit(target[0], target[1])

    @Slot(str, int, bool)
    def requestPinToggle(self, entity_type: str, entity_id: int, pinned: bool) -> None:
        """The pane's pin was activated; ``pinned`` is the card's CURRENT
        state and the connector toggles it (design Д2: by pair, the index
        would go stale between press and answer)."""
        self.pinToggleRequested.emit(entity_type, entity_id, pinned)

    @Slot(str, int, bool)
    def requestImageFor(self, entity_type: str, entity_id: int, pinned: bool) -> None:
        """A pane's picture was activated (the group-4 delegate names itself);
        a pair that is not in a matching pane is a silent no-op."""
        if self.pane_entity(entity_type, entity_id, pinned) is not None:
            self.imageRequested.emit(entity_type, entity_id, pinned)

    # ── «now» following (NRI-0021 Д2/Д5 posture, one subscription for all) ──

    def detach_now_listener(self) -> None:
        """Stop following the game's «now» (island teardown; idempotent)."""
        if self._now_vm is not None:
            self._now_vm.nowChanged.disconnect(self._on_now_changed)
            self._now_vm = None

    def _on_now_changed(self) -> None:
        # One broadcast re-counts every card's age (design Д2: the single
        # subscription lives here precisely so pins do not multiply owners);
        # an empty column has nothing to repaint — no emit. The cards are
        # re-counted in place (same constructions, same revs), so the
        # island's scroll memory puts every pinned pane back exactly where
        # the reader left it (2026-10-03 fix).
        if not self._cards:
            return
        for card in self._cards:
            card.recount_age()
        self.contentChanged.emit()

    # ── internal reads ───────────────────────────────────────────────────────

    def _live_card(self) -> EntityCardViewModel | None:
        """The bottom card when it is the live one (frames are built live
        last, so a trailing unpinned card IS the live area)."""
        if self._cards and not self._cards[-1].pinned:
            return self._cards[-1]
        return None
