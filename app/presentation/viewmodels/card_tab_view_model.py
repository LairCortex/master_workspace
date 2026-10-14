"""The Qt face of card grouping tabs, shared by both card islands.

add-dnd-game-face task 7.1/7.2: the event-dialog island and the entity-card
island expose the SAME grouping-tab contract to QML — the strip model, the
active group, the field a refused save revealed, and the body slot the module
overlay rides. This mixin owns that Qt face once (the four signals, the three
QML ``Property`` faces and the shared slots); the Qt-free bookkeeping is
``CardGroupState`` in :mod:`app.presentation.card_tab_groups`.

Each ViewModel inherits it, calls :meth:`_init_card_tabs` from its ``__init__``,
and keeps the genuinely per-island half at its own seat: the validity rule
(``valid`` / ``saveEnabled``) and ``requestSave`` — on a refusal the VM names
its first offending field and calls :meth:`reveal_field` (spec «Ошибка
указывает дорогу»). Keeping ``requestSave`` out of the mixin is deliberate:
the two save gates are different rules, not one rule with two spellings.

The mixin is a ``QObject`` subclass, so each ViewModel gains the signals and
properties without duplication, and PySide's same-class notify rule holds
(every notify signal and its ``Property`` are declared right here)."""
from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from app.presentation.card_tab_groups import CardGroupState


class CardTabsMixin(QObject):
    """Grouping-tab state for one card island (see module docstring)."""

    groupsChanged = Signal()
    activeGroupChanged = Signal()
    invalidatedFieldChanged = Signal()
    #: The QML body slot the module-tab overlay is placed over; the island
    #: republishes it whenever the scene geometry moves (task 7.2).
    bodyRectChanged = Signal(float, float, float, float)
    #: The declarative module blocks of the «Основное» screen (dd-card-redesign
    #: task 4.2, design Д2): the host pushes serialized frames in, the QML
    #: anchors paint them at the declared positions.
    moduleBlocksChanged = Signal()
    #: Kernel field names the attached module hides («characteristics»,
    #: «backstory») — the rows leave the scroll, the stored data survives
    #: (spec «Ядреные тексты персонажа при модуле скрыты»).
    hiddenFieldsChanged = Signal()
    #: One control edit inside a module block: ``(block id, field, value)``.
    #: The host routes it to the owning source's handler; the VM is the
    #: single QML→Python door, it interprets nothing (design Д2).
    moduleBlockWriteRequested = Signal(str, str, object)

    def _init_card_tabs(self, kernel_groups: list[dict[str, str]]) -> None:
        """Set the kernel strip; called from each ViewModel's ``__init__``.
        Since dd-card-redesign Д1 every card passes the single «Основное»
        group (:func:`app.presentation.card_tab_groups.kernel_card_groups`) —
        the one-screen 0.19.1 view; external sources may later add tabs and
        wake the strip."""
        self._groups = CardGroupState(kernel_groups)
        self._invalidated_field = ""
        #: Last body rect the QML page published (DND-LIVE-1): the island
        #: publishes during its load, BEFORE the dialog builds the host that
        #: listens — the host replays this stamp when it subscribes late and
        #: a sheet opening at its final size never republishes.
        self._last_body_rect: tuple[float, float, float, float] | None = None
        # Task 4.2: the module-block channel starts empty — while no source
        # has collected anything the card is bit-for-bit the 0.19.1 screen
        # (the anchors paint nothing, nothing is hidden).
        self._module_blocks: list[dict] = []
        self._hidden_fields: list[str] = []

    # ── QML-facing face ──────────────────────────────────────────────────────

    groups = Property(
        "QVariant", lambda self: self._groups.entries(), notify=groupsChanged
    )
    #: The external tail alone (entries past the kernel head). The islands
    #: build their module placeholder pages from this, so no usage site needs
    #: to know which keys the kernel declared (dd-card-redesign Д1: the kernel
    #: is the single «Основное» screen, everything after it is a guest).
    moduleGroups = Property(
        "QVariant",
        lambda self: self._groups.entries()[self._groups.kernel_count():],
        notify=groupsChanged,
    )
    #: How many entries the kernel declared — 1 since dd-card-redesign Д1.
    #: ``groups.length > kernelCount`` is the islands' «a guest brought tabs»
    #: condition: the strip shows and the relations band stitches only then.
    kernelCount = Property(
        int, lambda self: self._groups.kernel_count(), notify=groupsChanged
    )
    activeGroup = Property(
        int, lambda self: self._groups.active, notify=activeGroupChanged
    )
    #: The active group's key ("" while the strip is empty). The islands bind
    #: page visibility on the key, not on the bare index, so a page never has
    #: to mirror the kernel/module child ordering of the strip.
    activeGroupKey = Property(
        str,
        lambda self: self._groups.key_at(self._groups.active) or "",
        notify=activeGroupChanged,
    )
    #: The field a refused save revealed (spec «Ошибка указывает дорогу»):
    #: the island highlights the field whose name matches this value; the
    #: next accepted save clears it. Empty string = no offender.
    invalidatedField = Property(
        str, lambda self: self._invalidated_field, notify=invalidatedFieldChanged
    )
    #: The serialized module blocks (design Д2 ``ModuleBlock.to_dict`` data)
    #: for the two anchors; the QML filters by ``anchor``. Empty list = the
    #: kernel screen unchanged (the empty-channel pin).
    moduleBlocks = Property(
        "QVariant", lambda self: self._module_blocks, notify=moduleBlocksChanged
    )
    #: Kernel field names hidden by the attached module (the rows' visibility
    #: bindings read it); empty = nothing hidden, the 0.19.1 posture.
    hiddenFields = Property(
        "QStringList", lambda self: self._hidden_fields, notify=hiddenFieldsChanged
    )

    @Slot(int)
    def selectGroup(self, index: int) -> None:  # noqa: N802
        if self._groups.set_active(index):
            self.activeGroupChanged.emit()

    @Slot(str, str, "QVariant")
    def writeModuleBlock(  # noqa: N802
        self, block: str, field: str, value: object
    ) -> None:
        """One control commit inside a module block; relayed verbatim to the
        host's handler (the VM owns no block semantics, design Д2)."""
        self.moduleBlockWriteRequested.emit(block, field, value)

    @Slot(float, float, float, float)
    def reportBodyRect(  # noqa: N802
        self, x: float, y: float, width: float, height: float
    ) -> None:
        self._last_body_rect = (x, y, width, height)
        self.bodyRectChanged.emit(x, y, width, height)

    # ── Python-facing face (dialog facade + the VM's requestSave) ────────────

    def active_group_key(self) -> str | None:
        return self._groups.key_at(self._groups.active)

    def last_body_rect(self) -> tuple[float, float, float, float] | None:
        """The last rect published by the QML page (None until it publishes
        the first time). The stamp is in the QML root's coordinates, exactly
        as the page reported it — the host maps it the same way it maps a
        live ``bodyRectChanged``."""
        return self._last_body_rect

    def set_external_groups(self, entries: list[dict[str, str]]) -> None:
        """Replace the module tail of the strip (task 7.2). Kernel entries
        keep their order and head the strip; a shortened strip whose active
        index fell off returns the reader to the first group."""
        entries_changed, active_changed = self._groups.set_external_groups(
            [dict(entry) for entry in entries]
        )
        if entries_changed:
            self.groupsChanged.emit()
        if active_changed:
            self.activeGroupChanged.emit()

    def set_module_frame(self, blocks: list[dict], hidden_fields: list[str]) -> None:
        """Replace the module-block channel (task 4.2, host-only door). Both
        halves are diffed: a frame identical to the current one emits
        nothing, so a republish after a write moves only what changed (the
        QML bindings re-evaluate exactly where a signal fired)."""
        blocks_changed = list(blocks) != self._module_blocks
        hidden_changed = list(hidden_fields) != self._hidden_fields
        self._module_blocks = list(blocks)
        self._hidden_fields = list(hidden_fields)
        if blocks_changed:
            self.moduleBlocksChanged.emit()
        if hidden_changed:
            self.hiddenFieldsChanged.emit()

    def reveal_field(self, field: str) -> None:
        """Open the tab hosting ``field`` and mark it (a field no group owns
        marks nothing and moves nothing — the reveal is absent-safe)."""
        index = self._groups.group_index_for_field(field)
        if index is None:
            return  # the mark only lands where a tab can show the field
        if self._groups.set_active(index):
            self.activeGroupChanged.emit()
        if field != self._invalidated_field:
            self._invalidated_field = field
            self.invalidatedFieldChanged.emit()

    def clear_invalidated_field(self) -> None:
        if self._invalidated_field:
            self._invalidated_field = ""
            self.invalidatedFieldChanged.emit()
