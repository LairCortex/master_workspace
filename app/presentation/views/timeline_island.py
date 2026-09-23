"""Timeline panel island facade — the QQuickWidget shell of the event scale.

simplify-event-timeline-flat-list (design D4): the scale is a FLAT list now
— one event, one row — so the panel keeps its external contract — the class
name ``TimelineWidget``, the public methods (``update_events``/
``set_selected``/``scroll_to_event``) and the W3 id-contract signals — so
``window.timeline_widget`` and the wiring channels
(``event_selected``/``event_double_clicked``/``add_event_requested``/
``add_entity_requested``/``event_types_requested``/``window_changed``) all
stay textually unchanged. The ladder-era channels (``event_dates_moved``,
``event_create_requested``, jump/cover/hide-empty) left with the gestures
they transported. Inside, the header and the flat list are QML: one
``QQuickWidget`` island (built on the launcher's pattern — SizeRootToView,
``assert Ready``, deferred teardown) loading ``TimelineRoot.qml``.

Context contract of the island (the root must declare exactly this surface,
mirrored by the test stubs):

* context properties — ``vm`` (the TimelineViewModel: the root binds
  ``vm.rowModel`` and calls the sync invokable ``scrollToEvent``, never an
  async entry), ``islandPalette`` (the QmlPalette token bridge) and
  ``tooltipBridge`` (the shared tooltip shim);
* root properties the facade WRITES — ``windowText`` (chip caption, whose
  single writer stays the facade: ``_set_window_caption``) and ``selectedId``
  (int, ``-1`` = none — the delegate washes on ``selectedId == model.eventId``);
* root signal the facade EMITS — ``scrollToIndex(int)``: the island owns
  geometry, every reveal from the Python side is a scroll request by row
  index (the invokable answers with indices);
* root signals the facade CONNECTS — ``addRequested()``,
  ``addMenuRequested(real x, real y)``, ``datePopupRequested(real x, real y,
  real width, real height)`` (the chip's scene rect — the chip is the only
  popover opener), ``eventClicked(int)``, ``eventDoubleClicked(int)`` and
  ``selectionMissed()`` (a click past every row: no id-contract signal, the
  selection is dropped through the ViewModel so every layer clears).

All popups stay native: the «+» menu is a ``QMenu`` built here, and the
«Выбор даты» popover lives in :mod:`timeline_date_popup` — the one
widgets-popover exception. The panel holds no event copy: rows reach QML
only through ``vm.row_model``, so ``update_events`` is the knob mirror it
always was.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from PySide6.QtCore import QPoint, QRect, QSize, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QWidget

from app.domain.enums.entity_type import EntityType
from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH
from app.presentation.qml.island import IslandDialogMixin
from app.presentation.qml.tooltip_shim import install_island_tooltips
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.views.timeline_date_popup import (
    _DateWindowPopup, window_chip_text,
)

ROOT_QML = str(Path(QML_IMPORT_PATH) / "TimelineRoot.qml")

# ── «+» menu (spec «Меню „плюс“»): 6 items, 5 create actions + types entry ──
#: ``(caption, entity_type)`` pairs; the entity type is the payload of
#: ``add_entity_requested`` (``None`` = the event item, which emits
#: ``add_event_requested`` instead), before the «Типы событий…» separator.
# The menu's captions are this dialog's UI copy; the entity type payloads are
# the registry's canonical keys (wave 3, A4) so no string id drifts here.
ADD_MENU_ITEMS: tuple[tuple[str, str | None], ...] = (
    ("Новое событие", None),
    ("Новый персонаж", EntityType.CHARACTER.value),
    ("Новая локация", EntityType.LOCATION.value),
    ("Новая организация", EntityType.ORGANIZATION.value),
    ("Новый предмет", EntityType.ITEM.value),
)

#: Window knob normalized: ``None`` and ``(None, None)`` both mean «Все дни».
_NO_WINDOW: tuple = (None, None)

#: Stand for «this VM's window knob is no window at all» (a test double's
#: attribute shape). Distinct from ``None``, which is the real «Все дни»
#: window — the caption must still land on «Все дни» for that one.
_UNREADABLE_KNOB = object()


def _normalized_window(window) -> tuple:
    """Normalize the window knob: ``None`` means «Все дни» == (None, None)."""
    if window is None:
        return _NO_WINDOW
    start, end = window
    return (start, end)


def _window_knob_readable(window) -> bool:
    """Whether the VM's window knob is a window at all.

    The real ViewModel only ever stores ``None`` (or «Все дни») and a
    two-date pair; test stand-ins expose attributes of every shape, and a
    knob this predicate rejects must neutralize the caption mirror rather
    than crash it (the old widget tolerated them exactly this way).
    """
    if window is None:
        return True
    return isinstance(window, tuple) and len(window) == 2


class TimelineWidget(IslandDialogMixin, QWidget):
    island_context_names = {"vm": "_vm"}
    """Left-panel timeline: a QML flat-list island under the panel facade.

    The header chrome (title, «Выбор даты» chip, «+») lives in the island;
    this facade keeps the panel's public surface and drives the system
    popups. The ViewModel is the single mutation point: apply paths write
    its knobs, ``vm.row_model`` remodels, and the QML list follows the
    model — the facade mirrors only the captions the island chrome reads.
    """

    event_selected = Signal(int)  # event_id (W3 id-contract)
    event_double_clicked = Signal(int)  # event_id
    add_event_requested = Signal()
    add_entity_requested = Signal(str)  # entity_type: character/location/organization/item
    event_types_requested = Signal()  # «Типы событий…» from the «+» menu
    window_changed = Signal(object, object)  # window bounds ((date|pair|None) x2)

    def __init__(
        self,
        timeline_vm,
        parent: QWidget | None = None,
        theme=None,
        *,
        root_qml: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = timeline_vm
        # QML chrome is skinned by the token bridge only, but the bridge still
        # needs a runtime: an unset argument falls back to the process default.
        self._theme = theme if theme is not None else get_default_theme()
        # Applied window as the popover reads it back on reopen: bounds are bare
        # dates or (date, is_bc) pairs — whatever `_on_window_range` received.
        self._window_range: tuple = (None, None)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # The island shares the one process-wide engine (kept referenced so it
        # never dies under a live island), but NOT its root context: a
        # QQuickWidget on the shared engine reports the ENGINE context from
        # ``rootContext()``, so names written there belong to every island —
        # and the last writer's bridge is nulled for all of them when its own
        # dialog dies (a closed chars-list left the tape on the off-skin
        # whites). The panel therefore binds through a child context of its
        # own, the detail-panel/world-snapshot seam.
        #
        # Creation order still matters at teardown: children die in creation
        # order, so the island widget is built FIRST and the context holding
        # the bridge after it — the scene never outlives-observes a destroyed
        # palette (the deferred ``closeEvent`` below covers the same hazard
        # when the panel is closed with a QML handler on the stack).
        # Context contract: the QSS-``palette`` name is shadowed by Qt Quick
        # Controls, hence ``islandPalette`` (LauncherRoot.qml contract); the VM
        # binds as ``vm`` (TimelineRoot.qml), aliasing its own attribute name.
        # A child context of the shared engine — not its root (see above).
        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        self._root_qml = root_qml  # facade tests inject a stub root
        self._palette = QmlPalette(self._theme, parent=self)
        self.setup_island()
        outer.addWidget(self.quick)

        self._wire_island()

        # The chrome mirrors ride the ViewModel's change signal too: writes
        # that land on ``vm.window`` without passing through the facade (the
        # search path resets «Все дни» through the VM) still move the chip
        # caption on the same beat the rows re-model (mirrors are idempotent,
        # so the wiring-fed paths are unaffected).
        changed = getattr(self._vm, "events_changed", None)
        if changed is not None:
            try:
                changed.connect(self._sync_from_vm)
            except (TypeError, AttributeError):
                pass  # a stand-in VM's signal look-alike never fires anyway

        # «Типы событий…» joins the «+» context menu (member action so
        # tests can enumerate it; the menu's own exec result drives the emit,
        # mirroring the five create items — the action itself stays unconnected
        # to avoid a double signal when Qt triggers it from the menu).
        self.event_types_action = QAction("Типы событий…", self)
        self.event_types_action.setObjectName("eventTypesAction")

        # Live window popover for the «Выбор даты» chip: top-level, skinned
        # through the app-wide popup sheet; parented to the panel for
        # lifetime only.
        self.window_popup = _DateWindowPopup(self)
        self.window_popup.range_applied.connect(self._on_window_range)

        # Seed the chrome surface from the ViewModel's knob: the chip caption
        # (the old header built it itself). A stand-in VM whose knob no window
        # predicate recognizes keeps the chrome on the «Все дни» default.
        vm_window = getattr(self._vm, "window", None)
        if _window_knob_readable(vm_window):
            self._set_window_caption(vm_window)

    # ── island -> facade wiring (the root's declared contract surface) ──────

    def _wire_island(self) -> None:
        root = self._root
        root.addRequested.connect(self.add_event_requested.emit)
        root.addMenuRequested.connect(self._show_add_menu)
        root.datePopupRequested.connect(self._on_date_popup_requested)
        root.eventClicked.connect(self._on_event_clicked)
        root.eventDoubleClicked.connect(self.event_double_clicked.emit)
        root.selectionMissed.connect(self._on_selection_missed)

    def _on_event_clicked(self, event_id: int) -> None:
        """A user click selects: the root's ``selectedId`` mirrors the click
        (the retired QListWidget painted its own selection; here the wash
        lives on the property, so the facade writes it), then the external
        signal fires exactly as before."""
        self._root.setProperty("selectedId", int(event_id))
        self.event_selected.emit(event_id)

    def _on_selection_missed(self) -> None:
        """A click past every row (spec «Клик-промах сбрасывает выбор»): the
        wash drops immediately, the selection drops THROUGH the ViewModel —
        one clear for every layer (rows, VM, detail panel) with no id-contract
        signal leaving the facade (a miss is not a selection)."""
        self._root.setProperty("selectedId", -1)
        select = getattr(self._vm, "select_event_by_id", None)
        if callable(select):
            try:
                select(None)
            except TypeError:
                pass  # a stand-in VM whose look-alike refuses the None

    def _scene_to_global(self, x: float, y: float) -> QPoint:
        """Map an island scene point (reported by QML) to global coordinates."""
        return self.quick.mapToGlobal(QPoint(int(x), int(y)))

    # ── system menus (design D4: native QMenu, Python-side) ─────────────────

    def _show_add_menu(self, x: float, y: float) -> None:
        """The «+» menu (5 create items + «Типы событий…»), exec at the
        reported scene point. A pick dispatches exactly like the old button's
        menu; closing it without a choice (Esc, a click past the items) emits
        nothing."""
        menu = QMenu(self)
        create_actions: dict = {}
        for caption, entity_type in ADD_MENU_ITEMS:
            create_actions[menu.addAction(caption)] = entity_type
        menu.addSeparator()
        menu.addAction(self.event_types_action)

        picked = menu.exec(self._scene_to_global(x, y))
        if picked is None:
            return  # Esc/промах — cancel without emit
        if picked is self.event_types_action:
            self.event_types_requested.emit()
            return
        if picked in create_actions:
            entity_type = create_actions[picked]
            if entity_type is None:
                self.add_event_requested.emit()
            else:
                self.add_entity_requested.emit(entity_type)

    # ── «Выбор даты» chip popover ────────────────────────────────────────────

    def _on_date_popup_requested(
        self, x: float, y: float, width: float, height: float
    ) -> None:
        """Drop the live range popover under the chip's reported rectangle.

        The chip is the popover's only opener: the popover re-seeds with the
        applied window (pre-fill only — the window itself lands when a tap
        inside the popover completes the range)."""
        top_left = self._scene_to_global(x, y)
        rect = QRect(top_left, QSize(max(int(width), 0), max(int(height), 0)))
        self.window_popup.open_at(rect, self._window_range)

    # ── knob mirroring (VM is the single mutation point) ─────────────────────

    def _view_knobs(self):
        """The ViewModel's window knob, or :data:`_UNREADABLE_KNOB` when the VM
        is a stand-in (test doubles expose attributes of shapes no window has).
        ``None`` stays meaningful: it IS the «Все дни» window."""
        window = getattr(self._vm, "window", None)
        if not _window_knob_readable(window):
            return _UNREADABLE_KNOB
        return window

    def _set_window_caption(self, window) -> None:
        """The ONE writer of the chip caption and the popover's pre-fill seed.

        Every path that moves the window — popover apply, an external reset
        mirrored through the ViewModel's signal — lands the caption here (the
        island chrome reads it as ``windowText``), so the chip never reads
        «Все дни» under an active window. ``None`` bounds are «Все дни»
        (:func:`_normalized_window`)."""
        start, end = _normalized_window(window)
        self._window_range = (start, end)
        self._root.setProperty("windowText", window_chip_text(start, end))

    def _sync_from_vm(self) -> None:
        """Reflect the ViewModel's chrome-facing window knob into the island.

        The rows reach QML through ``vm.row_model`` directly, so a sync is
        just the caption mirror the chip reads (an external window reset —
        search picking an event outside the window — pulls the caption back
        together with the list, as before)."""
        window = self._view_knobs()
        if window is _UNREADABLE_KNOB:
            return
        self._set_window_caption(window)

    # ── public panel API ─────────────────────────────────────────────────────

    def update_events(self, events: Sequence[Any]) -> None:
        """Refresh the list; selection survives while the event stays visible.

        The list holds NO event copy: the VM's own re-model path (load/knob
        setters) already re-projected ``vm.row_model``, so every wiring call
        site — which passes the very ``vm.events`` it just loaded — is served
        by the knob mirror below. The argument stays in the signature because
        the wiring's contract is textually unchanged."""
        self._sync_from_vm()

    def set_selected(self, event_id: int | None) -> None:
        """Highlight ``event_id`` (idempotent); revealed if not already visible.

        An external selection first mirrors the ViewModel's knob: an id
        arriving from search while the row sits outside the window (the VM's
        ``select_event_by_id`` already reset it to «Все дни») must find the
        list re-projected before the highlight lands."""
        self._sync_from_vm()
        self._root.setProperty("selectedId", -1 if event_id is None else int(event_id))
        if event_id is not None:
            self._reveal(self._scroll_target(event_id))

    def scroll_to_event(self, event_id: int) -> None:
        """Scroll the list just enough to reveal the event's row."""
        self._reveal(self._scroll_target(event_id))

    def _scroll_target(self, event_id: int) -> int:
        """The landing index from the VM invokable (``-1`` = keep scroll, the
        old no-op 1:1); a stand-in VM without the invokable lands nowhere."""
        scroll = getattr(self._vm, "scrollToEvent", None)
        if not callable(scroll):
            return -1
        index = scroll(event_id)
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            return -1
        return index

    def _reveal(self, index: int) -> None:
        """Ask the island to show a row index (``-1`` reveals nothing)."""
        if index >= 0:
            self._root.scrollToIndex.emit(index)

    # ── window channel ───────────────────────────────────────────────────────

    def _on_window_range(self, start, end) -> None:
        """Popover live-apply: chip caption + the panel's single signal — the
        unchanged ``window_changed`` wiring channel.

        The popover applies ``(date, is_bc)`` pairs (task 3.3), and from task
        4.2 the pairs ride the channel whole: the chip caption, the VM's
        window and the core's filter all read eras off the same pair (the
        bare-date contract stays a legal input — a date without a pair is
        «н.э.», see :func:`split_date_era`)."""
        self._set_window_caption((start, end))
        self.window_changed.emit(start, end)

    # ── island lifecycle — IslandDialogMixin (release deferred per above) ──

    def island_source(self) -> str:
        # ``root_qml`` exists for the facade tests only: until the production
        # root ships, an injected stub declares the contract; a missing file
        # (assert-on-missing) is the same honest failure the launcher ships.
        return self._root_qml or ROOT_QML

    def load_island_scene(self, quick) -> None:
        super().load_island_scene(quick)
        # Shared tooltip bridge: parented to the island, exposed as
        # ``tooltipBridge`` for the root's HoverHandlers (after the context
        # exists; the hand-written order preserved).
        self._tooltip_bridge = install_island_tooltips(self.quick, self._context)
