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
from app.presentation.modules.protocol import ExternalCardSource
from app.presentation.viewmodels.entity_card_view_model import (
    EntityCardViewModel,
    content_fingerprint,
)

__all__ = ["MAX_PINNED_CARDS", "EntityPreviewViewModel"]


def slot_id_of(entity: Any) -> Any:
    """The id half of a frame pair (add-dnd-game-face task 6.1/6.2): the
    stamped ``source_id`` of an external card record (a string forever, design
    Д4), the int row id of a kernel entity. The ONE reader of the id half —
    slot reuse, frame equality, fullsize keys and the pin gestures all go
    through it, so a string pair cannot be squashed by an ``int()`` cast on
    any one of those paths."""
    if isinstance(entity, ExternalCardSource):
        return entity.source_id
    return int(getattr(entity, "id", 0) or 0)

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
    """The column's card list; all composition rules live in the cards.

    Since NRI-0028 the VM also owns the fullsize expansion (Д1–Д3): one card
    may fill the column while the rest of the frame hides. The frames stay
    whole (``show_slots`` is never filtered), ``panes`` answers the
    filtration, and ``ApplicationWiring``, the storage and ``game_settings``
    never learn of the mode — it is the column's own view state."""

    contentChanged = Signal()
    #: The preview's half of the one selection bus (design D2): a relation row
    #: or a mention link was activated — the wiring loads and shows that entity
    #: and tries the middle-column highlight; the preview never loads itself.
    entityRequested = Signal(str, int)
    #: The same gesture for an EXTERNAL pair (add-dnd-game-face design Д4,
    #: the search bar's task-3.4 precedent): the mention link carried a
    #: string/composite source id — it rides its own str channel so the
    #: kernel int channel never squashes it; the connector seats the read-
    #: only card in the live area. Since task 6.1 the external relation rows
    #: of an external card raise the very same channel via requestEntity.
    externalEntityRequested = Signal(str, str)
    #: The pin of a pane was activated (NRI-0025 design Д2/Д3): the pair plus
    #: the card's current pinned state — the connector toggles accordingly and
    #: answers with a fresh frame. By pair, never by index.
    pinToggleRequested = Signal(str, int, bool)
    #: The pin channel's string-id twin (add-dnd-game-face task 6.2): an
    #: external pane presses here, so the kernel int signal never squashes
    #: a composite source id; the connector's one handler serves both.
    externalPinToggleRequested = Signal(str, str, bool)
    #: The picture of a pane was activated; the pane identifies itself so the
    #: facade builds the viewer from THAT card's entity (task 2.2).
    imageRequested = Signal(str, int, bool)
    #: …and its external twin (task 6.1): the picture of an external card,
    #: built by the facade from the record's own ``picture_path``.
    externalImageRequested = Signal(str, str, bool)

    def __init__(
        self,
        now_vm=None,
        parent: QObject | None = None,
        external_sources: Sequence[Any] = (),
    ) -> None:
        super().__init__(parent)
        self._now_vm = now_vm
        # add-dnd-game-face (design Д1): the external entity sources from the
        # composition root, stored whole. The kernel builds only kernel cards
        # today; the external-card slice (group 6) assembles ExternalCardSource
        # records through them. Empty by default — the pre-change column.
        self._external_sources: tuple[Any, ...] = tuple(external_sources)
        self._cards: list[EntityCardViewModel] = []
        # The construction stamp feeding every card's ``rev`` (the island's
        # scroll memory validates a remembered offset against it — 2026-10-03
        # fix): a card built now is a different construction than its
        # same-pair predecessor, a reused card keeps the rev it was born with.
        self._rev_seq = 0
        # NRI-0028 Д1: the one card expanded to fill the column, keyed by the
        # slot identity the frames already speak — side plus pair, the same
        # ``(pinned, type, id)`` triple as ``slotKey``/``_slot_card``. None
        # while the column paints its usual equal division. Pure view state:
        # the connector, the storage and the frames know nothing of it (Д2).
        self._fullsize_key: tuple[bool, str, Any] | None = None
        if now_vm is not None:
            now_vm.nowChanged.connect(self._on_now_changed)

    # ── QML-facing properties — the multi-view face (design Д2) ─────────────

    @property
    def external_sources(self) -> tuple[Any, ...]:
        """The sources the composition handed to this column."""
        return self._external_sources

    def set_external_sources(self, sources: Sequence[Any]) -> None:
        """Re-hand-out for a module joined to the LIVE composition — the same
        in-place update the connector and the search service accept; frames
        are rebuilt from the fresh list when the group 6 cards appear."""
        self._external_sources = tuple(sources)

    panes = Property(
        "QVariant", lambda self: self._pane_dicts(), notify=contentChanged,
    )
    #: One card owns the whole column right now (NRI-0028 Д1). The island
    #: hides the empty-live hint while this holds; ``panes`` answers the
    #: filtered single card meanwhile.
    fullsize = Property(
        bool, lambda self: self._fullsize_key is not None, notify=contentChanged,
    )
    #: The live area has no card. With at least one pin the island paints the
    #: hint block below them; with no pins at all it is the whole-column empty
    #: state instead (``panes`` empty) — spec «Пустая живая область без
    #: заголовка» / «Пустая колонка подписана одним словом».
    liveEmpty = Property(bool, lambda self: self._live_card() is None, notify=contentChanged)

    # ── Python-side reads (the facade builds the viewer from these) ────────

    def pane_entity(self, entity_type: str, entity_id: Any, pinned: bool) -> Any:
        """The loaded entity behind one pane (``None`` when no such pane is
        shown) — the facade's viewer build reads the requesting pane through
        here, so a duplicate pair answers per its pinned flag (task 2.2).
        Since task 6.1 an external pane answers its ``ExternalCardSource``
        record and its id half is the composite source string."""
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
        mirror: dict[tuple[str, Any], tuple[tuple[Any, ...], tuple[str, ...]]]
        | None = None,
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
        pane's scroll — physically survives.

        Fullsize relocation (NRI-0028 Д2): the frames stay whole, so the
        expansion key is reconciled against each incoming frame — see
        :meth:`_relocate_fullsize_key`.

        The optional ``mirror`` map (dd-card-redesign task 7.1/7.2, design
        Д5) carries the module's per-pair ``(sections, hidden_fields)`` the
        connector read through the source doors; a slot whose mirror changed
        is a changed slot — its card rebuilds with a fresh rev and repaints
        the sections from the top, while unchanged neighbours keep theirs
        (the reuse rule applies to the mirror exactly as to the row)."""
        key_before = self._fullsize_key
        self._fullsize_key = self._relocate_fullsize_key(key_before, pins, live)
        mirror_map = mirror or {}
        previous = {
            (card.pinned, card.entity_type, card.entity_id): card
            for card in self._cards
        }
        cards: list[EntityCardViewModel] = []
        rebuilt = False
        pinned_pairs: set[tuple[str, Any]] = set()
        for index, (entity_type, entity) in enumerate(pins):
            pair = (entity_type, slot_id_of(entity))
            card, reused = self._slot_card(
                previous,
                True,
                entity_type,
                entity,
                index,
                PIN_STATE_UNPIN,
                mirror_map.get(pair),
            )
            rebuilt = rebuilt or not reused
            pinned_pairs.add(pair)
            cards.append(card)
        if live is not None:
            live_pair = (live[0], slot_id_of(live[1]))
            card, reused = self._slot_card(
                previous,
                False,
                live[0],
                live[1],
                len(pins),
                self._live_pin_state(live_pair, pinned_pairs),
                mirror_map.get(live_pair),
            )
            rebuilt = rebuilt or not reused
            cards.append(card)
        # Pin order is part of the frame: even an all-reused reshuffle moves
        # cards between slots and must repaint (and re-announce) the list.
        # A relocated/expunged expansion key changes what ``panes`` answers
        # too (Д3), so it rides the same shared notify.
        changed = (
            rebuilt
            or self._fullsize_key != key_before
            or [
                (card.pinned, card.entity_type, card.entity_id) for card in cards
            ]
            != [
                (card.pinned, card.entity_type, card.entity_id) for card in self._cards
            ]
        )
        self._cards = cards
        if changed:
            self.contentChanged.emit()

    def _relocate_fullsize_key(
        self,
        key: tuple[bool, str, Any] | None,
        pins: Sequence[tuple[str, Any]],
        live: tuple[str, Any] | None,
    ) -> tuple[bool, str, Any] | None:
        """The one relocation rule of the expansion key against an incoming
        frame (NRI-0028 Д2): the key is in the frame — the mode stands; the
        exact key is gone but the same ``(type, id)`` pair rides the OTHER
        side of the frame — the key moves there (pinning the expanded live
        card relocates the expansion onto its pinned copy, unpinning an
        expanded pin with a live copy relocates symmetrically onto the live
        one — the mode holds the ENTITY with its display side, and holding
        the entity outranks following the slot); the key rode the LIVE side
        and the frame still has a live side — the expansion follows the
        selection with its new pair (spec «Живое раскрытие следует за
        выбором»: a new selection replaces the expanded content, the mode
        never dies on a mere selection change); otherwise the mode
        extinguishes itself — unpin without a copy, deletion and an emptied
        frame all die out through this final branch (a PINNED-side key never
        follows the live slot)."""
        if key is None:
            return None
        frame = [(True, entity_type, slot_id_of(entity)) for entity_type, entity in pins]
        if live is not None:
            frame.append((False, live[0], slot_id_of(live[1])))
        if key in frame:
            return key
        pair = (key[1], key[2])
        for side, entity_type, entity_id in frame:
            if (entity_type, entity_id) == pair:
                return (side, entity_type, entity_id)
        if not key[0]:
            for side, entity_type, entity_id in frame:
                if not side:
                    return (False, entity_type, entity_id)
        return None

    def _slot_card(
        self,
        previous: dict[tuple[bool, str, Any], EntityCardViewModel],
        pinned: bool,
        entity_type: str,
        entity: Any,
        slot_index: int,
        pin_state: str,
        mirror_entry: tuple[tuple[Any, ...], tuple[str, ...]] | None = None,
    ) -> tuple[EntityCardViewModel, bool]:
        """The card for one slot: the previous construction when the slot is
        unchanged (same pair, same row object whose rendered fields still
        carry the same fingerprint, same authored pin word — only the
        position may move, and it moves with the slot flags), a fresh render
        otherwise. Object identity alone cannot stamp the content: the save
        path's session identity map mutates the row IN PLACE mid-transaction
        (pinned by the e2e save tests), so the very same object can arrive
        with new values — the fingerprint of the rendered fields is what
        separates a real edit from a re-presentation.

        ``mirror_entry`` (task 7.2) is the pair's module mirror as the frame
        carries it — ``(sections, hidden_fields)`` or ``None`` for silence.
        It joins the reuse gate through the card's own ``mirror`` stamp: a
        mirror that moved under an unchanged row (a card save with new
        mechanics, the module switched between frames) is a changed slot and
        rebuilds with a fresh rev, exactly like changed row values do."""
        pair = (entity_type, slot_id_of(entity))
        incoming_mirror = (
            ((), ()) if mirror_entry is None else (tuple(mirror_entry[0]), tuple(mirror_entry[1]))
        )
        card = previous.get((pinned,) + pair)
        if (
            card is not None
            and card.entity is entity
            and card.pin_state == pin_state
            and card.mirror == incoming_mirror
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
                module_sections=incoming_mirror[0],
                hidden_kernel_fields=incoming_mirror[1],
            ),
            False,
        )

    @staticmethod
    def _live_pin_state(
        live_pair: tuple[str, Any], pinned_pairs: set[tuple[str, Any]]
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
        next start all funnel through here via the wiring). The fullsize
        expansion extinguishes always (NRI-0028 Д2): the mode is transient
        per column session, neither a restart nor a game switch keeps it."""
        self._cards = []
        self._fullsize_key = None
        self.contentChanged.emit()

    # ── QML-facing slots (the island's outgoing gestures) ──────────────────

    @Slot(str, "QVariant")
    def requestEntity(self, entity_type: str, entity_id: Any) -> None:
        """A relation row was activated (mouse click or accessibility Press —
        the library row runs both through this one slot). Which pane raised
        it is the connector's live-area rule, not the payload's. The id half
        decides the channel (task 6.1, design Д4): a str is a composite
        external source id and rides the string twin of the bus, an int is a
        kernel row — the same split :meth:`requestLink` performs for mention
        hrefs, so the kernel int channel never squashes an external pair."""
        if isinstance(entity_id, str):
            self.externalEntityRequested.emit(entity_type, entity_id)
        else:
            self.entityRequested.emit(entity_type, int(entity_id))

    @Slot(str)
    def requestLink(self, link: str) -> None:
        """``onLinkActivated`` receiver: a generated mention anchor navigates;
        any other href (external URL, stale fragment) is a silent no-op, so a
        broken mention of a deleted entity can never break the preview. An
        href of a registered external type (design Д4) rides the string-id
        channel — the connector answers it with the read-only card in the
        live area, the same channel a search-row click took in task 3.4."""
        target = parse_mention_link(link)
        if target is None:
            return
        if isinstance(target[1], str):
            self.externalEntityRequested.emit(target[0], target[1])
        else:
            self.entityRequested.emit(target[0], target[1])

    @Slot(str, "QVariant", bool)
    def requestPinToggle(self, entity_type: str, entity_id: Any, pinned: bool) -> None:
        """The pane's pin was activated; ``pinned`` is the card's CURRENT
        state and the connector toggles it (design Д2: by pair, the index
        would go stale between press and answer). The id half decides the
        signal (task 6.2): a string pair rides the external twin, the kernel
        int signal stays typed exactly as before."""
        if isinstance(entity_id, str):
            self.externalPinToggleRequested.emit(entity_type, entity_id, pinned)
        else:
            self.pinToggleRequested.emit(entity_type, int(entity_id), pinned)

    @Slot(str, "QVariant", bool)
    def requestImageFor(self, entity_type: str, entity_id: Any, pinned: bool) -> None:
        """A pane's picture was activated (the group-4 delegate names itself);
        a pair that is not in a matching pane is a silent no-op. Task 6.1:
        an external pane's picture rides the external twin so the facade can
        build the viewer from the record's own file path."""
        if self.pane_entity(entity_type, entity_id, pinned) is None:
            return
        if isinstance(entity_id, str):
            self.externalImageRequested.emit(entity_type, entity_id, pinned)
        else:
            self.imageRequested.emit(entity_type, int(entity_id), pinned)

    @Slot(str, "QVariant", bool)
    def requestFullsizeToggle(self, entity_type: str, entity_id: Any, pinned: bool) -> None:
        """The expand button of a pane was activated (NRI-0028 Д1): pressing
        the key that is already expanded extinguishes it, pressing another
        card's button moves the expansion there — only one card is ever
        expanded. The island raises this only from a visible pane, so the key
        always names a card of the current frame; the frame itself is never
        touched, only ``panes`` filters (Д2). The repaint rides the shared
        ``contentChanged`` like every other re-composition (Д3)."""
        key = (pinned, entity_type, entity_id)
        self._fullsize_key = None if self._fullsize_key == key else key
        self.contentChanged.emit()

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

    @staticmethod
    def _slot_triple(card: EntityCardViewModel) -> tuple[bool, str, Any]:
        """The card's slot identity — the same ``(pinned, type, id)`` triple
        ``_slot_card`` reuses cards by and the island's ``slotKey`` names."""
        return (card.pinned, card.entity_type, card.entity_id)

    def _pane_dicts(self) -> list[dict[str, Any]]:
        """The ``panes`` value: the visible cards with the two fullsize flags
        the band button needs. ``canFullsize`` is the Д3 threshold — the
        FRAME holds two or more cards, hidden ones included, counted once
        here so the island never counts; ``fullsize`` names which visible
        card is the expanded one (Д4 maps it to the button's name/tooltip
        pair and glyph). With no expansion every card of the frame shows."""
        can_fullsize = len(self._cards) >= 2
        return [
            card.pane(
                can_fullsize=can_fullsize,
                fullsize=self._fullsize_key == self._slot_triple(card),
            )
            for card in self._visible_cards()
        ]

    def _visible_cards(self) -> list[EntityCardViewModel]:
        """The frame as the island sees it (Д1/Д2): whole while no card is
        expanded, only the expanded card otherwise — the rest of the frame
        hides but never leaves ``_cards``, so the next frame reuses every
        card of the frame exactly as if nothing had happened."""
        if self._fullsize_key is None:
            return self._cards
        return [
            card
            for card in self._cards
            if self._fullsize_key == self._slot_triple(card)
        ]
