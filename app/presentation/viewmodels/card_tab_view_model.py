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

    def _init_card_tabs(self, kernel_groups: list[dict[str, str]]) -> None:
        """Set the kernel strip; called from each ViewModel's ``__init__``
        once its type/relation shape is known (the full «Обзор · Тексты ·
        Связи» trio, or the pair for a relations-less type)."""
        self._groups = CardGroupState(kernel_groups)
        self._invalidated_field = ""
        #: Last body rect the QML page published (DND-LIVE-1): the island
        #: publishes during its load, BEFORE the dialog builds the host that
        #: listens — the host replays this stamp when it subscribes late and
        #: a sheet opening at its final size never republishes.
        self._last_body_rect: tuple[float, float, float, float] | None = None

    # ── QML-facing face ──────────────────────────────────────────────────────

    groups = Property(
        "QVariant", lambda self: self._groups.entries(), notify=groupsChanged
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

    @Slot(int)
    def selectGroup(self, index: int) -> None:  # noqa: N802
        if self._groups.set_active(index):
            self.activeGroupChanged.emit()

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
