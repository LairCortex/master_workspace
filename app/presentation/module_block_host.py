"""Hosting of the declarative ``module_blocks`` channel inside a card island.

dd-card-redesign task 4.2 (design Д2): a module hands the card descriptor
blocks for two anchor positions of the kernel scroll; this host is the one
Python seat that collects them and carries them to the island view model —

* collected at ``populate`` (the target id is known then; a fresh card asks
  with the empty id, which is exactly how a module answers «hide my kernel
  texts, paint nothing yet» for a record that does not exist yet);
* frames of several visible sources merge in source order, first source wins
  a duplicated block id — the kernel owns no module semantics beyond that;
* a frame's ``handler_factory(wiring, dialog, republish)`` is called exactly
  once per collection; the handler receives every ``(block, field, value)``
  commit for its own blocks (relayed verbatim from the VM, design Д2) and can
  push a refreshed frame through ``republish`` without re-collecting;
* teardown (:meth:`release`, from the dialog's ``_release_island``) calls the
  handler's ``release()`` — the norm «a released island answers NOTHING», no
  module listener may outlive the card.

Every source door, factory call, write and release is tolerant: a source that
raises is journalled and skipped (the external-surface posture — one broken
module never eats the card), and a source without the door at all is simply
passed over, so the empty-channel profile needs no module-side stub.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject

from app.presentation.modules.protocol import CardTabTarget, ModuleBlock

_LOGGER = "app.module_blocks"


@dataclass
class _SourceBlocks:
    """One source's current frame plus its built handler (task-private)."""

    blocks: list[ModuleBlock]
    hidden_fields: tuple[str, ...]
    handler: Any = None
    block_ids: tuple[str, ...] = field(default_factory=tuple)


class ModuleBlockHost(QObject):
    """One card's module-block carrier (owned by the dialog facade).

    ``vm`` is the card's island view model (it owns the block/hidden-field
    channel through ``CardTabsMixin``); ``dialog`` is the window handed to the
    handler factory (file dialogs and notices parent to it); ``sources`` is
    the composition's external source list, ``wiring`` the connector."""

    def __init__(
        self,
        dialog,
        vm,
        sources: Sequence[Any],
        wiring: Any = None,
        *,
        target_key: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent if parent is not None else dialog)
        self._dialog = dialog
        self._vm = vm
        self._sources = tuple(sources)
        self._wiring = wiring
        self._target_key = target_key
        self._entries: list[_SourceBlocks] = []
        self._released = False
        vm.moduleBlockWriteRequested.connect(self._on_write)

    # ── collection (called at populate, when the target id is known) ────────

    def refresh(self, target_id: str | None) -> None:
        """Rebuild the channel for one target record.

        Unlike the tab strip, a fresh card (``None`` → the empty id) IS
        collected: the module's answer for a record that does not exist yet
        is the honest «no blocks, these kernel fields are hidden» frame
        (spec «Пустой новый персонаж … с пустыми разделами»)."""
        self._release_handlers()
        if self._released:
            return
        target = CardTabTarget(key=self._target_key, source_id=target_id or "")
        for source in self._sources:
            # The source's own visibility gates every surface read elsewhere
            # (the protocol's «visible»); a hidden source decorates no card.
            if not getattr(source, "visible", True):
                continue
            door = getattr(source, "module_blocks", None)
            if not callable(door):
                continue  # a source without the door decorates nothing
            frame = self._source_frame(door, target)
            if frame is None:
                continue
            # The entry lands in the list BEFORE its handler is built: the
            # republish door below is bound to the ENTRY, never to the
            # source-list index (the live defect: a doorless source ahead of
            # this one shifted the index, so every handler republish aimed at
            # a slot past the end of the compact entries list and was
            # silently dropped — blocks never reached the card).
            entry = _SourceBlocks(
                blocks=list(frame.blocks),
                hidden_fields=tuple(frame.hidden_fields),
                block_ids=tuple(block.id for block in frame.blocks),
            )
            self._entries.append(entry)
            if frame.handler_factory is not None:
                entry.handler = self._build_handler(frame.handler_factory, entry)
        self._publish()

    def _source_frame(self, door, target: CardTabTarget):
        try:
            return door(target)
        except Exception as exc:  # noqa: BLE001 — one bad source never eats the card
            logging.getLogger(_LOGGER).warning(
                "Внешний источник не смог описать модульные блоки: %s", exc
            )
            return None

    def _build_handler(self, factory, entry: _SourceBlocks):
        try:
            handler = factory(self._wiring, self._dialog, self._publisher(entry))
        except Exception as exc:  # noqa: BLE001 — a failed handler drops its frame's writes
            logging.getLogger(_LOGGER).warning(
                "Обработчик модульных блоков не собран: %s", exc
            )
            return None
        if not all(
            callable(getattr(handler, name, None))
            for name in ("handle_write", "release")
        ):
            logging.getLogger(_LOGGER).warning(
                "Обработчик модульных блоков не отвечает утиному контракту — блоки без записи"
            )
            return None
        return handler

    def _publisher(self, entry: _SourceBlocks):
        """The ``republish(blocks, hidden_fields)`` door handed to one
        source's handler: it replaces THAT source's frame and re-publishes
        the merged channel — no re-collection, no second factory call.
        The door holds the entry itself, so it lands on the handler's own
        frame whichever way the collection order shifted, and goes quiet
        once the entry left the list (a refresh re-collected it) or the
        island released."""

        def republish(blocks, hidden_fields) -> None:
            if self._released or not any(entry is held for held in self._entries):
                return  # the card is gone — a late module callback answers nothing
            entry.blocks = list(blocks)
            entry.hidden_fields = tuple(hidden_fields)
            entry.block_ids = tuple(block.id for block in entry.blocks)
            self._publish()

        return republish

    def _publish(self) -> None:
        blocks: list[dict] = []
        seen_ids: set[str] = set()
        hidden: list[str] = []
        for entry in self._entries:
            for block in entry.blocks:
                if block.id in seen_ids:
                    continue  # first source wins a duplicated id
                seen_ids.add(block.id)
                blocks.append(block.to_dict())
            for name in entry.hidden_fields:
                if name not in hidden:
                    hidden.append(name)
        self._vm.set_module_frame(blocks, hidden)

    # ── the write channel (QML → VM signal → handler) ────────────────────────

    def _on_write(self, block_id: str, field: str, value: object) -> None:
        for entry in self._entries:
            if entry.handler is None or block_id not in entry.block_ids:
                continue
            try:
                entry.handler.handle_write(block_id, field, value)
            except Exception as exc:  # noqa: BLE001 — a refused write never kills the card
                logging.getLogger(_LOGGER).warning(
                    "Модульный блок %s не принял запись: %s", block_id, exc
                )
            return
        logging.getLogger(_LOGGER).debug(
            "Запись в модульный блок %s без обработчика — пропущена", block_id
        )

    # ── lifecycle ────────────────────────────────────────────────────────────

    def release(self) -> None:
        """Island teardown: the handlers retire their subscriptions first,
        then the channel goes quiet. Idempotent (the teardown can be
        scheduled from more than one close route)."""
        if self._released:
            return
        self._released = True
        try:
            self._vm.moduleBlockWriteRequested.disconnect(self._on_write)
        except RuntimeError:
            pass  # the VM already died with the dialog — nothing to detach
        self._release_handlers()

    def _release_handlers(self) -> None:
        entries, self._entries = self._entries, []
        for entry in entries:
            if entry.handler is None:
                continue
            try:
                entry.handler.release()
            except Exception as exc:  # noqa: BLE001 — teardown never raises
                logging.getLogger(_LOGGER).warning(
                    "Обработчик модульных блоков не отпустил подписки: %s", exc
                )
