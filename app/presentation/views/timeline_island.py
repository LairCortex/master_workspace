"""Timeline panel island facade — the QQuickWidget shell of the event scale.

Change port-event-timeline-qml-island-q2-5a (tasks 3.1–3.4, designs D1/D4/D5):
the panel keeps its external contract — the class name ``TimelineWidget``,
every public method (``update_events``/``set_selected``/``scroll_to_event``/
``jump_prev_event``/``jump_next_event``/``cover_window_for_span``) and every
W3 id-contract signal — so ``window.timeline_widget`` and the whole wiring
stay textually unchanged (D1). Inside, the header and the tape are QML: one
``QQuickWidget`` island (built on the launcher's pattern — SizeRootToView,
``assert Ready``, deferred teardown) loading ``TimelineRoot.qml``.

Context contract of the island (designs D1/D6/D9; the group-4 root must
declare exactly this surface, mirrored by the test stubs):

* context properties — ``vm`` (the TimelineViewModel: the root binds
  ``vm.rowModel``, calls the sync invokables ``stickyInfo``/``zoomStep``/
  ``drill``, never an async entry), ``islandPalette`` (the QmlPalette token
  bridge, D8) and ``tooltipBridge`` (the shared tooltip shim, D9);
* root properties the facade WRITES — ``windowText`` (chip caption, whose
  single writer stays the facade: ``_set_window_caption``), ``hideEmpty``
  (toggle mirror/seed) and ``selectedId`` (int, ``-1`` = none — the delegate
  washes on ``selectedId == model.eventId``, D2);
* root signal the facade EMITS — ``scrollToIndex(int)``: the island owns
  geometry, every reveal/jump landing from the Python side is an scroll
  request by row index (D7: invokables answer with indices);
* root signals the facade CONNECTS — ``addRequested()``,
  ``addMenuRequested(real x, real y)``, ``datePopupRequested(int gapIndex,
  real x, real y, real width, real height)`` (chip click with ``gapIndex =
  -1``, collapsed-gap click with the delegate's own row index; ``x/y/width/
  height`` — the CHIP's scene rect), ``hideEmptyToggled(bool)``,
  ``eventClicked(int)``, ``eventDoubleClicked(int)``, ``inlineCreateCommitted(
  int dayIndex, string name)``, ``dropMenuRequested(int eventId, int
  targetIndex, real x, real y)`` (release of the card drag on a foreign day,
  cursor in scene coords) and ``jumpRequested(int step)`` (header jump
  buttons, -1 forward-up / +1 forward-down).

All popups stay native (D5): the «+» and drop menus are ``QMenu`` built here
from the core's verdicts, and the «Выбор даты» popover lives in
:mod:`timeline_date_popup` — the one widgets-popover exception. The
panel-internal old channels (the list's local re-model, the memo palette
farm) died with the widgets widget (tasks 1.3/D10): rows reach QML only
through ``vm.row_model``, so ``update_events`` degrades to the knob mirror
it always was and holds no event copy.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Sequence

from PySide6.QtCore import QPoint, QRect, QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH
from app.presentation.qml.tooltip_shim import install_island_tooltips
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.views.timeline_date_popup import (
    _DateWindowPopup, window_chip_text,
)
from app.presentation.views.timeline_rows import (
    DayHeaderRow, DropAction, EmptyDayRow, EventRow, GapCollapsedRow,
    ScaleUnit, apply_drop_action, drop_actions,
)

ROOT_QML = str(Path(QML_IMPORT_PATH) / "TimelineRoot.qml")

# ── drop release-menu captions (W5 D5, migrated with the menu) ───────────────
#: Menu captions keyed by the core's actions, enumerated in the spec's order:
#: «Перенести» / «Расширить вниз до этого дня» / «Начать раньше в этом дне».
#: Presence per target day stays the core's ``drop_actions`` call.
DROP_CAPTIONS: dict = {
    DropAction.MOVE: "Перенести",
    DropAction.EXTEND_DOWN: "Расширить вниз до этого дня",
    DropAction.START_EARLIER: "Начать раньше в этом дне",
}
#: Menu item order (mirrors the spec's listing of the actions).
DROP_ACTION_ORDER = (DropAction.MOVE, DropAction.EXTEND_DOWN, DropAction.START_EARLIER)

# ── «+» menu (task 3.3, spec «Меню „плюс“»), migrated 1:1 ────────────────────
#: ``(caption, entity_type)`` pairs; the entity type is the payload of
#: ``add_entity_requested`` (``None`` = the event item, which emits
#: ``add_event_requested`` instead), before the «Типы событий…» separator.
ADD_MENU_ITEMS: tuple[tuple[str, str | None], ...] = (
    ("Новое событие", None),
    ("Новый персонаж", "character"),
    ("Новая локация", "location"),
    ("Новая организация", "organization"),
    ("Новый предмет", "item"),
)

#: Target-row kinds a drop gesture may land on (the list's
#: ``_update_drag_target`` acceptance, kept as the facade's defensive twin:
#: collapsed gaps, period rungs and off-tape indices stay cancel).
_VALID_DROP_TARGETS = (DayHeaderRow, EventRow, EmptyDayRow)

#: Window knob normalized: ``None`` and ``(None, None)`` both mean «Все дни».
_NO_WINDOW: tuple[date | None, date | None] = (None, None)


def _normalized_window(window) -> tuple[date | None, date | None]:
    """Normalize the window knob: ``None`` means «Все дни» == (None, None)."""
    if window is None:
        return _NO_WINDOW
    start, end = window
    return (start, end)


class TimelineWidget(QWidget):
    """Left-panel timeline: a QML day-ladder island under the panel facade.

    The header chrome (window chip, hide-empty toggle, «+», jump pair) lives
    in the island; this facade keeps the panel's public surface and drives
    the system popups. The ViewModel is the single mutation point exactly as
    before (D7): apply paths write its knobs, ``vm.row_model`` remodels, and
    the QML list follows the model — the facade mirrors only the captions the
    island chrome reads.
    """

    event_selected = Signal(int)  # event_id (W3 id-contract)
    event_double_clicked = Signal(int)  # event_id
    add_event_requested = Signal()
    add_entity_requested = Signal(str)  # entity_type: character/location/organization/item
    event_types_requested = Signal()  # W4 6.2: «Типы событий…» from the «+» menu
    window_changed = Signal(object, object)  # window pair (start|None, end|None)
    event_dates_moved = Signal(object, object, object)  # (event_id, start, end|None)
    # Inline creation from an empty day (task 6.1): the island's Enter reports
    # ``(dayIndex, name)``; the day resolves here and the wiring turns the
    # committed pair into ``vm.create_event_at``.
    event_create_requested = Signal(object, str)  # (day, name)

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
        self._window_range: tuple[date | None, date | None] = (None, None)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # The island shares the one process-wide engine (kept referenced so it
        # never dies under a live island). Creation order matters at teardown:
        # children die in creation order, so the island widget is built FIRST
        # and the palette it binds to is parented AFTER it — the context never
        # outlives-observes a destroyed palette (the launcher solved the same
        # hazard through its ``done()`` release; the panel has no dialog done,
        # so ordering plus the deferred ``closeEvent`` below cover it).
        engine = setup_qml_shell(QApplication.instance(), self._theme)
        self._engine = engine
        self.quick = QQuickWidget(engine, self)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.quick.rootContext().setContextProperty("vm", self._vm)
        self._palette = QmlPalette(self._theme, parent=self)
        # The QSS-``palette`` name is shadowed by Qt Quick Controls, hence
        # ``islandPalette`` (LauncherRoot.qml context contract).
        self.quick.rootContext().setContextProperty("islandPalette", self._palette)
        # Shared tooltip bridge (D9): parented to the island, exposed as
        # ``tooltipBridge`` for the root's HoverHandlers.
        self._tooltip_bridge = install_island_tooltips(self.quick)
        # ``root_qml`` exists for the group-3 facade tests only: TimelineRoot
        # itself lands with task 4.1, and until then the production default
        # must stay a plain module constant (assert-on-missing is the same
        # honest failure the launcher ships with).
        self.quick.setSource(QUrl.fromLocalFile(root_qml if root_qml else ROOT_QML))
        assert self.quick.status() == QQuickWidget.Status.Ready, self.quick.errors()
        outer.addWidget(self.quick)

        self._root = self.quick.rootObject()
        self._wire_island()

        # The chrome mirrors ride the ViewModel's change signal too: the
        # island's OWN descent paths (drill clicks, Alt-wheel zoom steps)
        # write the VM's knobs through its sync invokables and never touch
        # the facade — without this connection the chip caption would stay
        # on the pre-descent window until the next external update
        # (mirrors are idempotent, so the wiring-fed paths are unaffected).
        changed = getattr(self._vm, "events_changed", None)
        if changed is not None:
            try:
                changed.connect(self._sync_from_vm)
            except (TypeError, AttributeError):
                pass  # a stand-in VM's signal look-alike never fires anyway

        # W4 6.2: «Типы событий…» joins the «+» context menu (member action so
        # tests can enumerate it; the menu's own exec result drives the emit,
        # mirroring the five create items — the action itself stays unconnected
        # to avoid a double signal when Qt triggers it from the menu).
        self.event_types_action = QAction("Типы событий…", self)
        self.event_types_action.setObjectName("eventTypesAction")

        # Live window popover for the «Выбор даты» chip and the collapsed-gap
        # pre-fill: top-level, skinned through the app-wide popup sheet;
        # parented to the panel for lifetime only.
        self.window_popup = _DateWindowPopup(self)
        self.window_popup.range_applied.connect(self._on_window_range)

        # Jump shortcuts (D4/D8): active only while focus is inside the panel;
        # Alt+Up/Alt+Down are free in the rest of the app (task 3.4).
        jump_prev_shortcut = QShortcut(QKeySequence("Alt+Up"), self)
        jump_prev_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        jump_prev_shortcut.activated.connect(self.jump_prev_event)
        jump_next_shortcut = QShortcut(QKeySequence("Alt+Down"), self)
        jump_next_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        jump_next_shortcut.activated.connect(self.jump_next_event)

        # Seed the chrome surface from the ViewModel's knobs: the chip caption
        # and the toggle mirror (the old header built these two itself). A
        # stand-in VM whose knobs no ladder recognizes keeps the chrome on the
        # «Все дни»/off defaults — exactly what the old header showed it.
        vm_window = getattr(self._vm, "window", None)
        if vm_window is None or (isinstance(vm_window, tuple) and len(vm_window) == 2):
            self._set_window_caption(vm_window)
        # Mirror a REAL bool only: test doubles expose truthy stand-in
        # attributes for every knob, and «off by default» must survive them.
        vm_hide = getattr(self._vm, "hide_empty", False)
        self._root.setProperty("hideEmpty", vm_hide is True)

    # ── island -> facade wiring (the root's declared contract surface) ──────

    def _wire_island(self) -> None:
        root = self._root
        root.addRequested.connect(self.add_event_requested.emit)
        root.addMenuRequested.connect(self._show_add_menu)
        root.datePopupRequested.connect(self._on_date_popup_requested)
        root.hideEmptyToggled.connect(self._on_hide_empty_toggled)
        root.eventClicked.connect(self._on_event_clicked)
        root.eventDoubleClicked.connect(self.event_double_clicked.emit)
        root.inlineCreateCommitted.connect(self._on_inline_create_committed)
        root.dropMenuRequested.connect(self._on_drop_menu_requested)
        root.jumpRequested.connect(self._on_jump_requested)

    def _on_event_clicked(self, event_id: int) -> None:
        """A user click selects: the root's ``selectedId`` mirrors the click
        (the retired QListWidget painted its own selection; here the wash
        lives on the property, so the facade writes it), then the external
        signal fires exactly as before."""
        self._root.setProperty("selectedId", int(event_id))
        self.event_selected.emit(event_id)

    def _scene_to_global(self, x: float, y: float) -> QPoint:
        """Map an island scene point (reported by QML) to global coordinates."""
        return self.quick.mapToGlobal(QPoint(int(x), int(y)))

    def _row_at(self, index: int):
        """The ladder row behind a reported row index (out-of-range → ``None``)."""
        rows = getattr(self._vm, "rows", None)
        if isinstance(rows, list) and isinstance(index, int) \
                and not isinstance(index, bool) and 0 <= index < len(rows):
            return rows[index]
        return None

    # ── system menus (task 3.3, design D5: native QMenu, Python-side) ───────

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

    def _on_drop_menu_requested(
        self, event_id: int, target_index: int, x: float, y: float
    ) -> None:
        """The drop-release menu at the cursor (W5 task 5.2, migrated 1:1).

        The items are exactly the core's ``drop_actions`` verdict for this
        event and target day; the target must be a materialized day (the list
        gesture's acceptance keeps its defensive twin here — a collapsed gap
        or an off-tape index cancels silently). Choosing an item applies
        :func:`apply_drop_action` and commits through the single
        ``event_dates_moved`` channel — one write, one rebuild downstream;
        Esc/release-past-items is a cancel: no signal, nothing touched."""
        target = self._row_at(target_index)
        if not isinstance(target, _VALID_DROP_TARGETS):
            return
        source = self._find_event(event_id)
        if source is None:
            return  # the sample no longer holds the record — nothing to write

        actions = drop_actions(source, target.date)
        menu = QMenu(self)
        item_actions: dict = {}
        for action in DROP_ACTION_ORDER:
            if actions.get(action):
                item_actions[menu.addAction(DROP_CAPTIONS[action])] = action
        picked = menu.exec(self._scene_to_global(x, y))
        if picked is None or picked not in item_actions:
            return  # «Закрытие меню без действия … не SHALL менять ничего»
        start, end = apply_drop_action(source, item_actions[picked], target.date)
        self.event_dates_moved.emit(source.id, start, end)

    def _find_event(self, event_id: int):
        """The record behind an id — from the VM's sample, never a panel copy
        (uniqueness invariant, task 1.3)."""
        sample = getattr(self._vm, "all_events", None)
        if sample is None:
            sample = getattr(self._vm, "events", None) or ()
        for record in sample:
            if getattr(record, "id", None) == event_id:
                return record
        return None

    # ── island-reported interactions ────────────────────────────────────────

    def _on_jump_requested(self, step: int) -> None:
        """Header jump button (D6): the facade's jump path, exactly the
        keyboard/shortcut entry points' twin."""
        if step < 0:
            self.jump_prev_event()
        elif step > 0:
            self.jump_next_event()

    def _on_inline_create_committed(self, day_index: int, name: str) -> None:
        """Enter on the island's inline field (task 4.4 contract): resolve the
        clicked day from its row index and forward ``(day, name)`` like the
        old inline editor did. A blank name commits nothing (the old field
        refused it; the QML field hides itself on Esc, spec «Пустое поле не
        создаёт»)."""
        name = (name or "").strip()
        if not name:
            return
        row = self._row_at(day_index)
        day = getattr(row, "date", None)
        if not isinstance(day, date):
            return
        self.event_create_requested.emit(day, name)

    # ── «Выбор даты» chip / gap popover (task 3.2) ──────────────────────────

    def _on_date_popup_requested(
        self,
        gap_index: int,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        """Drop the live range popover under the chip's reported rectangle.

        Chip clicks report ``gap_index = -1`` and the popover re-seeds with
        the applied window (the old ``_on_window_chip_clicked`` twin); a
        collapsed-gap click reports its own row index and the popover re-seeds
        with the gap bounds (spec «Схлопнутый провал кликабелен для окна»),
        still positioned under the chip. Pre-fill only — the window itself
        lands when a tap inside the popover completes the range."""
        seed = self._window_range
        row = self._row_at(gap_index)
        if isinstance(row, GapCollapsedRow):
            seed = (row.date, row.end)
        top_left = self._scene_to_global(x, y)
        rect = QRect(top_left, QSize(max(int(width), 0), max(int(height), 0)))
        self.window_popup.open_at(rect, seed)

    # ── knob mirroring (VM is the single mutation point, design D7) ──────────

    def _view_knobs(self) -> tuple | None:
        """The ViewModel's ladder knobs, or ``None`` while the VM is a stand-in
        (test doubles expose MagicMock attributes no ladder recognizes)."""
        level = getattr(self._vm, "level", None)
        window = getattr(self._vm, "window", None)
        hide_empty = getattr(self._vm, "hide_empty", None)
        if not isinstance(level, ScaleUnit):
            return None
        if window is not None and (
            not isinstance(window, tuple) or len(window) != 2
        ):
            return None
        if not isinstance(hide_empty, bool):
            return None
        return level, window, hide_empty

    def _set_window_caption(self, window) -> None:
        """The ONE writer of the chip caption and the popover's pre-fill seed.

        Every path that moves the window — popover apply, an external descent
        mirrored through :meth:`update_events` — lands the caption here (the
        island chrome reads it as ``windowText``), so the chip never reads
        «Все дни» under an active window. ``None`` bounds are «Все дни»
        (:func:`_normalized_window`)."""
        start, end = _normalized_window(window)
        self._window_range = (start, end)
        self._root.setProperty("windowText", window_chip_text(start, end))

    def _sync_from_vm(self) -> None:
        """Reflect the ViewModel's chrome-facing knobs into the island.

        The old list needed its knobs re-fed before every rebuild; here the
        rows reach QML through ``vm.row_model`` directly, so a sync is just
        the caption + toggle mirror the header chrome reads (an external
        window reset — search descending the ladder past the chip — pulls the
        caption back together with the tape, as before)."""
        knobs = self._view_knobs()
        if knobs is None:
            return
        _level, window, hide_empty = knobs
        self._set_window_caption(window)
        self._root.setProperty("hideEmpty", hide_empty)

    # ── public panel API (1:1 with the migrated widgets widget) ─────────────

    def update_events(self, events: Sequence[Any]) -> None:
        """Refresh the tape; selection survives while the event stays visible.

        The tape holds NO event copy anymore (task 1.3/D10): the VM's own
        re-model path (load/knob setters) already re-projected
        ``vm.row_model``, so every wiring call site — which passes the very
        ``vm.events`` it just loaded — is served by the knob mirror below.
        The argument stays in the signature because the wiring's contract is
        textually unchanged (D1)."""
        self._sync_from_vm()

    def set_selected(self, event_id: int | None) -> None:
        """Highlight ``event_id`` (idempotent); revealed if not already visible.

        An external selection first mirrors the ViewModel's knobs: an id
        arriving from search while the VM has descended the ladder (its
        ``select_event_by_id`` already moved ``level``/``window``) must find
        the cards that descent just modelled (spec «Внешний выбор с крупной
        ступени спускает лестницу»)."""
        self._sync_from_vm()
        self._root.setProperty("selectedId", -1 if event_id is None else int(event_id))
        if event_id is not None:
            self._reveal(self._scroll_target(event_id))

    def scroll_to_event(self, event_id: int) -> None:
        """Scroll the tape just enough to reveal the event's first card."""
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

    # ── ladder-aware jump commands ─────────────────────────────────────────

    def _descend_for_jump(self) -> None:
        """Period rungs own no event cards — drop the VM's ladder to DAY and
        re-model before retrying the jump; a no-op when DAY is already current
        or the VM is a test stand-in."""
        self._vm.level = ScaleUnit.DAY
        self._sync_from_vm()

    def _jump_target(self, step: int) -> int:
        """The VM's jump verdict (index, or ``-1`` for "no other event"; a
        stand-in VM that answers non-indices also yields ``-1``)."""
        jump = getattr(self._vm, "jump", None)
        if not callable(jump):
            return -1
        index = jump(step)
        if isinstance(index, bool) or not isinstance(index, int):
            return -1
        return index

    def jump_prev_event(self) -> None:
        """Scroll to the nearest event card before the reading position."""
        self._jump(-1)

    def jump_next_event(self) -> None:
        """Scroll to the nearest event card after the reading position."""
        self._jump(1)

    def _jump(self, step: int) -> None:
        """One jump command, «jump никогда не выбирает» (D4, task 3.4): the VM
        answers with an index only — no selection, no signal — and a miss
        descends the ladder once (the old ``_descend_for_jump`` retry) before
        giving up silently."""
        index = self._jump_target(step)
        if index < 0:
            self._descend_for_jump()
            index = self._jump_target(step)
        self._reveal(index)

    # ── hide toggle + window channels (tasks 7.1–7.3, migrated 1:1) ─────────

    def _on_hide_empty_toggled(self, checked: bool) -> None:
        """Header toggle (task 7.3, spec «Скрытие дат без событий»): the write
        goes through the ViewModel — the single mutation point — and its knobs
        are mirrored back. Session-only state: nothing is persisted."""
        self._vm.hide_empty = bool(checked)
        self._sync_from_vm()

    def _on_window_range(self, start, end) -> None:
        """Popover live-apply: chip caption + the panel's single signal — the
        unchanged ``window_changed`` wiring channel (task 3.2)."""
        self._set_window_caption((start, end))
        self.window_changed.emit(start, end)

    def cover_window_for_span(self, start: date, end: date | None) -> None:
        """Widen the ACTIVE «Выбор даты» window so ``[start, end|start]``
        lands inside it (task 5.3, spec «Унос за окно расширяет окно»).

        The wiring calls this *before* a drop commit writes the new dates, so
        the moved event can never land outside the visible tape. No-op
        without a window. The expansion rides the existing window path
        (:meth:`_on_window_range`) so caption and ``window_changed`` stay in
        lockstep."""
        wn_start, wn_end = self._window_range
        if wn_start is None or wn_end is None:
            return
        span_end = start if end is None else end
        if start >= wn_start and span_end <= wn_end:
            return
        self._on_window_range(min(start, wn_start), max(span_end, wn_end))

    # ── teardown (the launcher's deferred release, D1) ──────────────────────

    def _release_island(self) -> None:
        self.quick.setSource(QUrl())

    def closeEvent(self, event) -> None:  # Qt API name
        """Release the island against its VM/palette context properties.

        A QML-originated handler may still be on the stack when the panel
        closes (e.g. a menu path closing the window it lives in), and
        destroying the scene synchronously there is fatal; the one-shot timer
        bound to ``self`` runs when the JS stack has unwound and never after
        the panel is gone. If the whole window is torn down without a close
        event, the creation order above (island before palette) keeps the
        same invariant at child destruction."""
        QTimer.singleShot(0, self, self._release_island)
        super().closeEvent(event)
