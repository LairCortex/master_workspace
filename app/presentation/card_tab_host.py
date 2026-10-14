"""Hosting of the external ``CardTabSpec`` tabs inside a card island.

add-dnd-game-face task 7.2 (design Д10): the kernel draws the tab strip and
owns the lifecycle; ``CardTabSpec.factory(wiring, source_id)`` builds the
content and returns the widget the strip hosts. A module tab is therefore a
native widget this host:

* collects from the registered external sources whenever the card's target
  id becomes known (populate) — and on a fresh card with the empty id, so a
  module may stand its tabs up before the record exists (a source that
  cannot live without one simply answers nothing for the empty id);
* overlays the widget on the body slot the QML page publishes through the
  view model (the strip, the header and the action row stay visible around
  it — spec: the module tab switches like any other tab);
* releases it when the island releases (the norm «a released island answers
  NOTHING»): the module's duck ``release_tab()`` retires the tab's own
  subscriptions first, then the widget leaves the window.

A source or a factory that raises is skipped with a journal entry — one
broken module tab must never take the card down (the tolerant-doors rule of
the external surfaces).
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QObject, QPoint, QRect, QSize
from PySide6.QtWidgets import QWidget

from app.presentation.modules.protocol import CardTabSpec, CardTabTarget


class CardTabHost(QObject):
    """One card's additional-tab carrier (owned by the dialog facade).

    ``vm`` is the card's island view model (it owns the groups state, the
    active-group and body-rect channels); ``dialog`` is the window the tab
    widgets are parented to; ``sources`` is the composition's external
    source list as carried to the card by the connector."""

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
        self._target_id = ""
        self._widgets: dict[str, QWidget] = {}
        self._body_rect: QRect | None = None
        self._released = False
        vm.activeGroupChanged.connect(self._sync)
        vm.bodyRectChanged.connect(self._remember_body_rect)
        # DND-LIVE-1: the QML page publishes its body slot while the island
        # loads — before this host exists (both dialogs build it after
        # ``setup_island``). A sheet that opens at its final size never
        # republishes, so a host subscribing after the last emit would place
        # nothing. The VM keeps the last stamp; replay it now.
        cached_rect = vm.last_body_rect()
        if cached_rect is not None:
            self._remember_body_rect(*cached_rect)

    # ── collection (called at populate, when the target id is known) ────────

    def refresh(self, target_id: str | None) -> None:
        """Rebuild the module tail of the strip for one target record.

        A fresh card (``None`` → the empty id) is collected too: a new
        character card opens with the module tabs already standing and their
        sections empty (spec dnd-character-extension «Новая карточка с
        пустыми разделами»), and so does a new event («Пустое событие тоже
        с двумя табами»). Whether the empty id gets tabs at all is each
        source's own answer; a module that is off (its «visible» gate) or
        answers nothing leaves the kernel strip standing alone — the
        «module off ⇒ no module tabs» route needs no special casing here."""
        self._release_widgets(release_tab=True)
        self._target_id = target_id or ""
        entries: list[dict[str, str]] = []
        target = CardTabTarget(key=self._target_key, source_id=self._target_id)
        for source in self._sources:
            # The source's own visibility condition (the reference toggle,
            # protocol «visible») gates its records everywhere else, so a
            # hidden source's tabs must not surface on the card either.
            if not getattr(source, "visible", True):
                continue
            for spec in self._source_tabs(source, target):
                if spec.key in self._widgets:
                    continue  # first source wins a duplicated key
                widget = self._build(spec)
                if widget is None:
                    continue
                widget.setParent(self._dialog)
                widget.setVisible(False)
                self._widgets[spec.key] = widget
                entries.append({"key": spec.key, "title": spec.title})
        self._vm.set_external_groups(entries)
        self._sync()

    # ── the common-save door (add-dnd-game-face task 11.1, spec dnd-encounters
    #    «сохранение — общим сохранением карточки события») ────────────────────

    def save_hooks(self) -> tuple:
        """The module tabs' staged writes, as the connector runs them.

        Each hosted widget that stages edits answers it with a duck door
        ``save_tab()`` — a zero-argument callable returning a coroutine the
        connector awaits INSIDE its locked save task (the frame's own
        ``run_locked`` would re-enter the lock; the door's contract lives at
        the widget, design Д10). Widgets that write every change as it
        happens (the character tabs) carry no door and contribute nothing
        here. The tuple order is the tab order.
        """
        hooks = []
        for widget in self._widgets.values():
            save_tab = getattr(widget, "save_tab", None)
            if callable(save_tab):
                hooks.append(save_tab)
        return tuple(hooks)

    def _source_tabs(self, source: Any, target: CardTabTarget) -> tuple[CardTabSpec, ...]:
        try:
            return tuple(source.card_tabs(target) or ())
        except Exception as exc:  # noqa: BLE001 — one bad source never eats the card
            logging.getLogger("app.card_tabs").warning(
                "Внешний источник не смог описать табы карточки: %s", exc
            )
            return ()

    def _build(self, spec: CardTabSpec) -> QWidget | None:
        try:
            widget = spec.factory(self._wiring, self._target_id)
        except Exception as exc:  # noqa: BLE001 — a failed tab drops out, not the card
            logging.getLogger("app.card_tabs").warning(
                "Модульный таб %s не собран: %s", spec.key, exc
            )
            return None
        if not isinstance(widget, QWidget):
            logging.getLogger("app.card_tabs").warning(
                "Модульный таб %s вернул не QWidget: %r", spec.key, type(widget).__name__
            )
            return None
        return widget

    # ── overlay placement (body slot published by the QML page) ─────────────

    def _remember_body_rect(self, x: float, y: float, width: float, height: float) -> None:
        top_left = self._dialog.mapFromGlobal(
            self._dialog.quick.mapToGlobal(QPoint(int(x), int(y)))
        )
        self._body_rect = QRect(top_left, QSize(max(int(width), 0), max(int(height), 0)))
        self._sync()

    def _sync(self) -> None:
        """Show the active module tab over the body slot, hide the others."""
        active_key = self._vm.active_group_key()
        for key, widget in self._widgets.items():
            if key != active_key or self._body_rect is None:
                widget.hide()
                continue
            widget.setGeometry(self._body_rect)
            widget.show()
            widget.raise_()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def release(self) -> None:
        """Island teardown (the dialog's ``_release_island`` calls this):
        every module tab releases its own subscriptions, then leaves the
        window — no module listener survives the card. Idempotent: the
        island teardown can be scheduled from more than one close route.
        """
        if self._released:
            return
        self._released = True
        for channel, receiver in (
            (self._vm.activeGroupChanged, self._sync),
            (self._vm.bodyRectChanged, self._remember_body_rect),
        ):
            try:
                channel.disconnect(receiver)
            except RuntimeError:
                pass  # the VM already died with the dialog — nothing to detach
        self._release_widgets(release_tab=True)

    def _release_widgets(self, *, release_tab: bool) -> None:
        widgets, self._widgets = self._widgets, {}
        for widget in widgets.values():
            if release_tab:
                release = getattr(widget, "release_tab", None)
                if callable(release):
                    try:
                        release()
                    except Exception as exc:  # noqa: BLE001 — teardown never raises
                        logging.getLogger("app.card_tabs").warning(
                            "Модульный таб не отпустил подписки: %s", exc
                        )
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
