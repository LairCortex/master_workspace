"""The one protocol a game-system module speaks to the kernel.

add-dnd-module-foundation (design Д2): the kernel knows a module exists as a
mechanism and nothing of its domain. The composition point ``app/main.py``
reads the game's public flag, assembles either the concrete module or the
no-op default below, and — once the window and the connector exist — calls
:meth:`GameSystemModule.attach`. Detaching (:meth:`GameSystemModule.detach`)
takes the module's composition out of the live game without a restart; both
operations are idempotent by contract of the implementation, not the loop.

add-dnd-game-face (design Д1): the seam grew one generic channel — a module
may hand the kernel :class:`ExternalEntitySource` records (types with their
own records and provider: search, card, mentions, card tabs, ladder marks).
The kernel operates on ``str`` type keys and never names a system: it hands
the sources it received to the surfaces that consume them (search service,
mention hosts, preview column, connector) and registers their descriptors in
the single entity registry. The module NEVER registers anything itself —
``register_external`` belongs to the composition root alone (guards
tests/test_dd_module_isolation.py, tests/test_architecture_layers.py).

The kernel NEVER imports ``app.dd`` from here: ``MainWindow`` and
``ApplicationWiring`` appear under ``TYPE_CHECKING`` only, so this module
stays a runtime leaf (no import cycles through the composition seam).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from app.domain.entity_registry import ExternalTypeDescriptor
    from app.presentation.views.main_window import MainWindow
    from app.presentation.wiring import ApplicationWiring


# ── the external-source vocabulary (add-dnd-game-face, design Д1/Д3) ──────
# Frozen records only: a source hands the kernel values, never live objects.
# Entity ids in this vocabulary are STRINGS forever (a record's identity is
# its key in the source's file, a design Д4 ruling — the numeric kernel id
# must never leak into or imitate an external one).


@dataclass(frozen=True)
class ExternalHit:
    """One record as the search/mention surfaces show it: which external
    type, the record's id in the source's namespace, its display name and —
    additively since the reference-records slice (task 3.2, spec «Одноимённые
    слаги из разных наборов не сливаются») — the origin label naming WHICH
    source the record came from. The kernel renders the origin generically
    (an empty string paints no label), so a source whose records all share
    one visible home may leave it empty."""

    key: str
    source_id: str
    name: str
    origin: str = ""


@dataclass(frozen=True)
class ExternalTextBlock:
    """One titled text block of an external card (stat blocks, description,
    the «текст в LSS» line — whatever the provider assembles, Д3)."""

    title: str
    text: str


@dataclass(frozen=True)
class ExternalRelation:
    """A transition row of an external card: target type key, target record,
    name snapshot (the file may change later, the snapshot stays, Д4)."""

    key: str
    source_id: str
    name: str


@dataclass(frozen=True)
class ExternalCardSource:
    """The read-only preview card a provider assembles for one record (Д3).

    ``origin`` is the «источник» line (which dataset/grimoire the record
    came from); ``picture_path`` is an absolute image file path or ``None``.
    Nothing editable lives here — the dataset file stays the truth (spec
    «Внешняя сущность read-only во всех поверхностях»).

    ``source_id`` is NOT the provider's field: the kernel stamps it at the
    preview seat (task 6.1/6.2, design Д3/Д4) so the column's frame pair —
    the (type, id) the slot identity, pin gestures and scroll memory are
    keyed by — rides the record itself, exactly like a kernel row's ``id``.
    Providers leave the default; a record that reaches the column without
    the stamp still renders, it just carries no pinnable identity."""

    name: str
    origin: str
    blocks: tuple[ExternalTextBlock, ...] = ()
    relations: tuple[ExternalRelation, ...] = ()
    picture_path: str | None = None
    source_id: str = ""


@dataclass(frozen=True)
class CardTabTarget:
    """The entity a card's additional tabs are asked for."""

    key: str
    source_id: str


# ── the module-block vocabulary (dd-card-redesign task 4.1, design Д2/Д5) ───
#
# The declarative half of the «Основное» screen: a module hands the kernel a
# list of block DESCRIPTORS at two declared anchor positions inside the card's
# own scroll, the kernel paints them with stock Theme controls and writes the
# reader's edits back as ``(block, field, value)`` triples into the module's
# handler. The kernel knows ONLY the finite kinds below — a descriptor of an
# unknown kind is refused at construction, and the AST guard
# (tests/presentation/test_module_block_protocol.py) pins the set against
# silent widening (design Д2 «виды дескрипторов ограничены перечнем», risk
# «канал разрастается в второй UI-движок»).

#: The finite set of renderable block kinds (design Д2). A new kind is a
#: protocol change with its own kernel renderer, QML tests and guard update.
#: ``textline`` joined for the LSS sheet id of «Основное» (task 4.3/5.5):
#: an editable one-line text committed on editingFinished, no validator —
#: unlike ``number`` it stores free text, unlike ``text`` the reader types it.
MODULE_BLOCK_KINDS: frozenset[str] = frozenset(
    {"combo", "number", "textline", "switch", "text", "buttons", "table"}
)

#: The subset of kinds a table cell may wear (design Д2 «table со строками
#: ячеек»): cells stay one level shallow, no nested tables or buttons.
MODULE_CELL_KINDS: frozenset[str] = frozenset({"text", "number", "switch"})

#: The anchor positions inside the kernel scroll where blocks may be placed
#: (design Д2: «после коротких полей» / «после музыки»). The kernel renders at
#: the declared anchor and nowhere else.
MODULE_BLOCK_ANCHORS: frozenset[str] = frozenset(
    {"after_short_fields", "after_music"}
)

#: Refusals (the module posture: the reader of the journal reads what is wrong).
BLOCK_KIND_REFUSAL = "вид модульного блока вне конечного перечня протокола"
CELL_KIND_REFUSAL = "вид ячейки модульного блока вне конечного перечня протокола"
BLOCK_ANCHOR_REFUSAL = "позиция модульного блока вне конечного перечня протокола"


def _validated(kind: str, allowed: frozenset[str], refusal: str) -> str:
    """The construction gate shared by blocks and cells: an unknown kind is a
    protocol violation, refused where it is built, never painted or stored."""
    if kind not in allowed:
        raise ValueError(refusal)
    return kind


@dataclass(frozen=True)
class ModuleBlockOption:
    """One choice of a ``combo`` or one action of a ``buttons`` block.
    ``id`` is what the handler receives (the combo's selected value, the
    button's field name); ``label`` is what the reader sees; ``enabled`` lets
    a single action print greyed out (the AI-gate posture) while the rest of
    the row stays live."""

    id: str
    label: str
    enabled: bool = True

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "enabled": self.enabled}


@dataclass(frozen=True)
class ModuleBlockCell:
    """One cell of a table row. ``text`` paints read-only, ``number`` is a
    committed text field (written back on editingFinished, never per
    keystroke), ``switch`` is a checkbox written back on click. ``field`` is
    the write address inside the block; for cells the kernel addresses them
    as ``"<row id>.<field>"``. Values ride plain strings (numbers serialize
    as decimal text or "" for «не задано»), booleans as ``checked``.
    ``min_value``/``max_value`` bound a number cell; a negative bound means
    unbounded (QML-friendly ints, no nulls crossing the channel). ``name``
    overrides the accessibility name of the control the cell paints (a
    tick-only switch has no caption to name itself with; the fallback is the
    printed label)."""

    field: str
    kind: str
    label: str = ""
    value: str = ""
    checked: bool = False
    enabled: bool = True
    min_value: int = -1
    max_value: int = -1
    name: str = ""

    def __post_init__(self) -> None:
        _validated(self.kind, MODULE_CELL_KINDS, CELL_KIND_REFUSAL)

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "kind": self.kind,
            "label": self.label,
            "value": self.value,
            "checked": self.checked,
            "enabled": self.enabled,
            "minValue": self.min_value,
            "maxValue": self.max_value,
            "name": self.name,
        }


@dataclass(frozen=True)
class ModuleBlockRow:
    """One row of a ``table`` block: a stable id (part of the write address)
    and its cells in column order."""

    id: str
    cells: tuple[ModuleBlockCell, ...] = ()

    def to_dict(self) -> dict:
        return {"id": self.id, "cells": [cell.to_dict() for cell in self.cells]}


@dataclass(frozen=True)
class ModuleBlock:
    """One declarative block of the kernel scroll (design Д2).

    Only the fields its kind renders carry meaning: ``combo`` reads
    ``options``/``value``; ``number`` reads ``value``/``min_value``/
    ``max_value``; ``textline`` reads ``value``/``placeholder``; ``switch``
    reads ``checked``; ``text`` reads ``value``; ``buttons`` reads
    ``actions``; ``table`` reads ``columns``/``rows``.
    ``label`` is the usage-site accessibility name of the control this block
    paints (a caption the kernel prints beside or above it); ``enabled``
    greys the whole control. The write channel is uniform: the kernel sends
    ``(id, field, value)`` into the module's handler — ``field`` is
    ``"value"`` for the value-carrying kinds and the option id for
    ``buttons``."""

    kind: str
    id: str
    label: str
    anchor: str
    value: str = ""
    checked: bool = False
    enabled: bool = True
    options: tuple[ModuleBlockOption, ...] = ()
    actions: tuple[ModuleBlockOption, ...] = ()
    columns: tuple[str, ...] = ()
    rows: tuple[ModuleBlockRow, ...] = ()
    min_value: int = -1
    max_value: int = -1
    #: The ``textline`` field's empty-state hint (e.g. the LSS sheet id's
    #: «id цифрового листа Long Story Short»); every other kind ignores it.
    placeholder: str = ""

    def __post_init__(self) -> None:
        _validated(self.kind, MODULE_BLOCK_KINDS, BLOCK_KIND_REFUSAL)
        _validated(self.anchor, MODULE_BLOCK_ANCHORS, BLOCK_ANCHOR_REFUSAL)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "anchor": self.anchor,
            "value": self.value,
            "checked": self.checked,
            "enabled": self.enabled,
            "options": [option.to_dict() for option in self.options],
            "actions": [action.to_dict() for action in self.actions],
            "columns": list(self.columns),
            "rows": [row.to_dict() for row in self.rows],
            "minValue": self.min_value,
            "maxValue": self.max_value,
            "placeholder": self.placeholder,
        }


@dataclass(frozen=True)
class ModuleSection:
    """One titled read-only block of the entity PREVIEW mirror (design Д5,
    consumed since task 7.1): a title and plain text lines, painted by the
    preview column under the kernel fields. Nothing editable lives here."""

    title: str
    lines: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"title": self.title, "lines": list(self.lines)}


@dataclass(frozen=True)
class ModuleBlockFrame:
    """One source's answer for one card target: the blocks to paint, the
    kernel field names to HIDE («characteristics»/«backstory» — the module
    replaces their screen halves while its data survives storage), and the
    optional factory of the module's write handler.

    The factory is called by the kernel host exactly once per collection with
    ``(wiring, dialog, republish)`` — ``republish(blocks, hidden_fields)``
    hands the module a fresh frame after a write without re-collecting — and
    the returned handler is a duck with two methods:
    ``handle_write(block_id, field, value)`` (called for every control edit)
    and ``release()`` (called on teardown; no listener may outlive the card).
    A frame with ``handler_factory`` set but nothing writable to show is the
    source's own affair; ``None`` means the blocks are purely decorative."""

    blocks: tuple[ModuleBlock, ...] = ()
    hidden_fields: tuple[str, ...] = ()
    handler_factory: object = None  # plain object: this module stays a leaf


@dataclass(frozen=True)
class CardTabSpec:
    """One additional card tab a source contributes (design Д10).

    The kernel draws the tab strip and the lifecycle; ``factory(wiring,
    source_id)`` builds the tab's content and returns the widget the strip
    hosts — what the module draws inside is the module's own affair."""

    key: str
    title: str
    factory: object  # Callable[[ApplicationWiring, str], QWidget] — plain
                     # object to keep this module a runtime leaf


@runtime_checkable
class ExternalEntitySource(Protocol):
    """Records the kernel does not own, plus their provider.

    The one generic seam for every outside entity (design Д1): search, the
    @-popup candidates, the read-only preview card, card tabs and ladder
    marks all answer from this face, keyed by the descriptor's ``key`` and
    the record's string ``source_id``. ``visible`` is the source's own
    condition for showing its records (the reference toggle lives here, not
    in the kernel); the kernel consults it before every surface read. All
    implementations are the module's; the kernel only ever calls."""

    @property
    def type_descriptors(self) -> tuple[ExternalTypeDescriptor, ...]:
        """The types this source provides, in the order their groups appear."""
        ...

    @property
    def visible(self) -> bool:
        """Whether the source's records may surface right now."""
        ...

    async def warm(self) -> None:
        """Warm the source's read caches (add-dnd-game-face task 6.2, design
        Д5): the connector awaits this once at game open, BEFORE restoring the
        saved pins, because the pin restore is the one flow that calls the
        SYNC doors (``card_source``) before any surface has performed an async
        read — without the warm-up a dataset-backed card would honestly
        answer ``None`` at the door and every external pin would silently
        drop at every restart. Cheap by contract (digest-guarded caches — a
        second call after a real search reconciles nothing); failures are the
        source's own silence, never a raised error at the composition."""
        ...

    async def search(self, query: str) -> tuple[ExternalHit, ...]:
        """Substring match over the source's records (the search group's rows)."""
        ...

    def card_source(self, key: str, source_id: str) -> ExternalCardSource | None:
        """The read-only card of one record; ``None`` when unavailable."""
        ...

    async def mention_candidates(self, query: str) -> tuple[ExternalHit, ...]:
        """The @-popup candidates for a query (mentionable types only)."""
        ...

    def resolve_mention(self, key: str, source_id: str) -> ExternalCardSource | None:
        """An activated mention's card; ``None`` means «Упоминание не найдено»."""
        ...

    def card_tabs(self, target: CardTabTarget) -> tuple[CardTabSpec, ...]:
        """Additional tabs this source declares for one of its records."""
        ...

    def event_marks(self, event_ids: Sequence[int]) -> Mapping[int, str]:
        """Ladder marks for kernel events (event id → caption, e.g. the
        encounter chip); events without a mark are absent from the mapping.
        The timeline core composes per-row tuples from these (design Д9)."""
        ...

    def module_blocks(self, target: CardTabTarget) -> ModuleBlockFrame:
        """The declarative blocks this source contributes to one card's
        «Основное» screen (task 4.1, design Д2): descriptors at the declared
        anchors, kernel field names to hide, and the write-handler factory.
        A source that decorates no card answers the empty
        :class:`ModuleBlockFrame` — the kernel then paints exactly the 0.19.1
        screen (spec «Ядро рисует карточки одним экраном»); the door is SYNC
        like ``card_tabs`` and failures are the source's own silence (the
        host journals and skips)."""
        ...

    def module_sections(self, key: str, source_id: str) -> tuple[ModuleSection, ...]:
        """The read-only mirror sections of one record for the preview
        column (task 4.1, design Д5; consumed since task 7.1). The stub door
        is sync, but a real source may return an AWAITABLE of the tuple when
        its sections live behind an async read (the character/encounter
        overlay rows) — the preview bridge (wiring, task 7.1) accepts both
        shapes and awaits inside its session-locked task. Empty means the
        record prints kernel fields only («без модуля предпросмотр не
        отличается»); a raising door is the bridge's silence, journalled."""
        ...


@runtime_checkable
class GameSystemModule(Protocol):
    """What the kernel may ask of any game-system module.

    ``enabled`` reports whether the module's composition is currently
    attached; ``attach`` receives the two collaborators a module may bind
    UI to (the shown ``MainWindow`` and the connector), ``detach`` removes
    the section again. A module never touches the database session or the
    unit of work directly — data flows through the collaborators it is
    handed here or through services the composition injects.

    ``external_sources`` (add-dnd-game-face, design Д1) lists the entity
    sources the module contributes; the composition reads it at game open
    (before the first window), registers the descriptors it carries, and
    hands the list to the surfaces that consume it. A module with no
    outside records returns the empty tuple.
    """

    @property
    def enabled(self) -> bool:
        """True while the module's composition is attached to the game."""
        ...

    @property
    def external_sources(self) -> tuple[ExternalEntitySource, ...]:
        """The external entity sources this module contributes."""
        ...

    def attach(self, main_window: MainWindow, wiring: ApplicationWiring) -> None:
        """Join the live composition of THIS game's window and connector."""
        ...

    def detach(self) -> None:
        """Leave the composition; a detached module holds no window."""
        ...


class NoopGameSystemModule:
    """The default composition for ordinary games: answers nothing.

    The kernel composes this stub whenever the game's D&D flag is absent,
    disabled, unreadable, ahead of the supported version, or the build runs
    in the profile without the module (design Д2/Д11) — the attach/detach
    calls then land on a mechanism that stays silent, so the rest of the
    composition never branches on "module or nothing".
    """

    def attach(self, main_window: MainWindow, wiring: ApplicationWiring) -> None:
        """No-op: there is no section to join."""

    def detach(self) -> None:
        """No-op: there is no section to leave."""

    @property
    def enabled(self) -> bool:
        """A stub is never enabled — it is the absence of a module."""
        return False

    @property
    def external_sources(self) -> tuple[ExternalEntitySource, ...]:
        """A stub contributes no external sources — the kernel-only registry."""
        return ()
