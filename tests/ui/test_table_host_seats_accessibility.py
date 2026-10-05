"""Закрепляющий accessibility-пин посадки «Стола» (nri-0017-accessibility-completers,
tasks 5.1–5.2 = TB3-пин П4; the behavior itself is NRI-0016 TB3-ремонт).

Nothing here introduces behavior. Since NRI-0016 a seating row is a real
``QCheckBox`` whose ``toggled`` drives the pre-existing ``seat()``/``drop_seat()``
calls under the panel's ``_seats_loading`` guard (``panel.py:_on_seat_toggled``),
and the whole file only adds the tree-side face of that one contract, offscreen,
in the NRI-0012 pattern (``QAccessible.queryAccessibleInterface`` +
``actionInterface().doAction("Press")``):

* 5.1 — activating the row's checkbox through ``doAction("Press")`` reaches the
  mock host as exactly one ``seat()``, a repeat Press is the reverse transition
  (one ``drop_seat()``), and neither drawing a seated row nor repainting the list
  afterwards echoes a call (the guard, observed through the host's journal);
* 5.2 — временная подмена: the activation is the SAME code path a mouse click
  takes. The pin wraps a counter around the single shared slot
  ``TableHostPanel._on_seat_toggled``: one mouse click counts one invocation, one
  ``doAction("Press")`` counts one invocation of that same slot, and muting the
  slot silences both input kinds — so the Press cannot be a second,
  accessibility-only seat branch that would drift away from the mouse contract.

Qt 6.10 detail pinned by the waits below: ``QAccessibleButton::doAction("Press")``
on a checkable button runs ``QAbstractButton::animateClick()`` — the button goes
down immediately and the check state (and with it ``toggled``, the slot the panel
listens to) lands only when the animation timer releases it. Therefore every
assertion after a Press pumps BOTH event loops: the Qt one for the release timer,
the asyncio one for the ``drop_seat`` coroutine the handler schedules.

PR-022-ремонт (live raw-дерево 2026-10-04): the live cocoa tree showed ZERO
AXCheckBox nodes because the rows were item-view CELL widgets — a QListView's
accessibility interface publishes only its virtual cells, so the offscreen
pointer-query above stayed green on a face AppKit never enumerated. The rows
are plain child widgets of the desk now; three pins below catch exactly that
class of regression: the checkbox must sit in the widget hierarchy with no
QAbstractItemView above it, it must answer the ``Toggle`` action (Qt 6.10's
cocoa turns an AXPress on a CheckBox role into Toggle — the PR-001 family),
and it must live in the Tab chain with Space driving the seat.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QCheckBox

from app.presentation.views.table_host.panel import TableHostPanel
from tests.ui.test_table_host_panel_close import FakeHost

ROWS = [(11, "Лист A"), (12, "Лист B"), (13, "Лист C")]
_NAMES = dict(ROWS)


# ── helpers ─────────────────────────────────────────────────────────────────

def _panel(qtbot, host: FakeHost) -> TableHostPanel:
    panel = TableHostPanel(host, list_ipv4=lambda: ["10.0.0.8"])
    qtbot.addWidget(panel)
    panel.show()
    return panel


def _seat_box(panel: TableHostPanel, instance_id: int) -> QCheckBox:
    """The row's checkbox, addressed by the instance its row was built for —
    the instance's name is the checkbox's accessible name (PR-022-ремонт)."""
    for box in panel.seat_boxes():
        if box.accessibleName() == _NAMES[instance_id]:
            return box
    raise AssertionError(f"no seating row for instance {instance_id}")


def _press(box: QCheckBox) -> None:
    """The tree's own activation of the checkbox — QAccessible only, never a
    synthetic ``click()``/``setChecked()``, so the pin really travels the
    accessibility action channel. PR-022/PR-001 family: cocoa 6.10 translates
    an AXPress on a CheckBox role into the Toggle action, so BOTH action names
    must be exposed for the live press to land."""
    iface = QAccessible.queryAccessibleInterface(box)
    assert iface is not None, "the seating checkbox is absent from the tree"
    assert iface.role() == QAccessible.Role.CheckBox
    actions = iface.actionInterface()
    assert actions is not None, "the checkbox carries no action interface"
    assert "Press" in actions.actionNames(), (
        "the row checkbox exposes no Press action — the tree cannot actuate seating"
    )
    assert "Toggle" in actions.actionNames(), (
        "the row checkbox exposes no Toggle action — Qt 6.10 cocoa sends "
        "Toggle for an AXPress on a CheckBox, a Press-only control is a "
        "silent no-op in the live tree (PR-001/PR-022 family)"
    )
    actions.doAction("Press")


def _spy_seat_slot(monkeypatch, *, forward: bool = True) -> list[tuple[int, bool]]:
    """Counter around the panel's ONE seat slot.

    Installed on the class BEFORE ``set_instances``, which binds
    ``partial(self._on_seat_toggled, instance_id)`` per row — so every row's
    ``toggled`` connection runs through the counter. Forwarding keeps the real
    contract alive (the guard still swallows the loading fire inside the slot);
    ``forward=False`` mutes the slot, which is the negative half of the pin: with
    the single slot muted, neither the mouse nor the tree may reach the host.
    """
    original = TableHostPanel._on_seat_toggled
    seen: list[tuple[int, bool]] = []

    def spy(self, instance_id: int, checked: bool) -> None:
        seen.append((instance_id, checked))
        if forward:
            original(self, instance_id, checked)

    monkeypatch.setattr(TableHostPanel, "_on_seat_toggled", spy)
    return seen


# ── 5.1 the checkbox is in the tree and Press seats / unseats ───────────────

def test_seat_row_checkbox_is_a_pressable_checkbox_in_the_tree(qtbot):
    host = FakeHost(seated=(11,))
    host.start_fake()
    panel = _panel(qtbot, host)
    panel.set_instances(ROWS)

    box = _seat_box(panel, 12)
    iface = QAccessible.queryAccessibleInterface(box)
    assert iface is not None, "the seating checkbox is absent from the tree"
    assert iface.role() == QAccessible.Role.CheckBox
    actions = iface.actionInterface()
    assert actions is not None
    assert "Press" in actions.actionNames()
    # drawing the rows (row 11 arrives checked) touched nobody — the guard.
    assert host.calls == []
    host.stop_fake()


async def test_ax_press_seats_and_the_repeat_press_is_the_reverse_jump(qtbot, wait_for):
    host = FakeHost()
    host.start_fake()
    panel = _panel(qtbot, host)
    panel.set_instances(ROWS)
    assert host.calls == []

    _press(_seat_box(panel, 12))
    # animateClick releases on a Qt timer → exactly one toggled → one seat().
    await wait_for(lambda: host.calls == [("seat", 12)])
    assert panel.checked_seat_ids() == [12]

    # one repeat Press = the reverse transition, again a single call
    _press(_seat_box(panel, 12))
    await wait_for(lambda: host.calls == [("seat", 12), ("drop_seat", 12)])
    assert panel.checked_seat_ids() == []

    # no echo around either transition: the journal has nothing else in it
    assert len(host.calls) == 2
    host.stop_fake()


async def test_press_on_a_row_drawn_seated_drops_it_once(qtbot, wait_for):
    # The reverse direction entered from the checked side: the row was drawn
    # checked out of seated_ids, the tree's Press must be one drop_seat.
    host = FakeHost(seated=(11,))
    host.start_fake()
    panel = _panel(qtbot, host)
    panel.set_instances(ROWS)
    assert _seat_box(panel, 11).isChecked()
    assert host.calls == []

    _press(_seat_box(panel, 11))
    await wait_for(lambda: host.calls == [("drop_seat", 11)])
    assert panel.checked_seat_ids() == []
    assert len(host.calls) == 1
    host.stop_fake()


async def test_repainting_the_seating_never_echoes_a_press(qtbot, wait_for):
    """The ``_seats_loading`` guard, read from the tree side: drawing a checked
    row fires ``toggled`` on purpose and must stay inside the guard, and so does
    the repaint that follows a user's activation (main.py
    ``_refresh_table_host_panel`` re-renders from ``seated_ids``)."""
    host = FakeHost(seated=(11,))
    host.start_fake()
    panel = _panel(qtbot, host)
    panel.set_instances(ROWS)
    assert host.calls == []

    _press(_seat_box(panel, 12))
    await wait_for(lambda: host.calls == [("seat", 12)])

    # production repaint: 12 is now drawn checked, 11 stays checked — silent
    host.seated_value = {11, 12}
    panel.set_instances(ROWS)

    assert [c for c in host.calls if c[0] == "seat"] == [("seat", 12)]
    assert ("drop_seat", 11) not in host.calls
    assert panel.checked_seat_ids() == [11, 12]

    # …and the panel is not stuck in the loading state: the next Press seats again
    _press(_seat_box(panel, 13))
    await wait_for(lambda: ("seat", 13) in host.calls)
    assert panel.checked_seat_ids() == [11, 12, 13]
    host.stop_fake()


def test_ax_press_on_a_stopped_table_reaches_no_one(qtbot):
    # the other half of the same guard, through the tree: the checkbox flips
    # visually (the row widget is still a normal QCheckBox) but the stopped
    # table is left alone — the mouse half is pinned in
    # tests/ui/test_table_host_panel_close.py.
    host = FakeHost()
    panel = _panel(qtbot, host)
    panel.set_instances(ROWS)

    _press(_seat_box(panel, 12))
    qtbot.waitUntil(lambda: _seat_box(panel, 12).isChecked(), timeout=3000)
    assert host.calls == []


# ── 5.2 временная подмена: Press === the mouse path, one handler per press ──

async def test_one_ax_press_is_one_invocation_of_the_shared_slot(
    qtbot, wait_for, monkeypatch
):
    host = FakeHost()
    host.start_fake()
    seen = _spy_seat_slot(monkeypatch)  # installed before the rows bind their slots
    panel = _panel(qtbot, host)
    panel.set_instances(ROWS)
    QApplication.processEvents()  # settle the row geometry before the mouse clicks
    # nothing was checked during the load of an unseated table → no fire at all
    assert seen == []

    # the mouse, exactly as NRI-0016 leaves it: one click, one shared-slot call
    QTest.mouseClick(_seat_box(panel, 11), Qt.MouseButton.LeftButton)
    assert seen == [(11, True)]
    assert host.calls == [("seat", 11)]

    # the tree, a moment later — the very same counter, and it moved by one
    _press(_seat_box(panel, 12))
    await wait_for(lambda: seen == [(11, True), (12, True)])
    assert host.calls == [("seat", 11), ("seat", 12)]

    # a reversed activation is one more invocation, not two (no echo Press→toggled)
    _press(_seat_box(panel, 12))
    await wait_for(
        lambda: len(seen) == 3 and ("drop_seat", 12) in host.calls
    )
    assert seen == [(11, True), (12, True), (12, False)]
    assert host.calls == [("seat", 11), ("seat", 12), ("drop_seat", 12)]
    host.stop_fake()


async def test_the_host_is_reachable_only_through_that_slot(
    qtbot, wait_for, monkeypatch
):
    """Negative half of the подмена pin: with the single shared slot muted, BOTH
    the mouse and the accessibility Press leave the mock host untouched — proof
    that Press drives the existing handler rather than a parallel seat logic."""
    host = FakeHost()
    host.start_fake()
    seen = _spy_seat_slot(monkeypatch, forward=False)
    panel = _panel(qtbot, host)
    panel.set_instances(ROWS)
    QApplication.processEvents()  # settle the row geometry before the mouse clicks

    QTest.mouseClick(_seat_box(panel, 11), Qt.MouseButton.LeftButton)
    assert seen == [(11, True)]
    assert host.calls == []

    _press(_seat_box(panel, 12))
    await wait_for(lambda: seen == [(11, True), (12, True)])
    assert host.calls == []
    # the boxes themselves did flip — both activations reached the widget, the
    # host just never heard about it because the only door was muted
    assert panel.checked_seat_ids() == [11, 12]
    host.stop_fake()


# ── PR-022-ремонт: the class of the live-tree loss, pinned offscreen ────────

def test_seat_checkbox_is_a_plain_child_widget_not_an_item_view_cell(qtbot):
    """The PR-022 regression class: a checkbox drawn inside an item-view cell
    is invisible to the live accessibility enumeration (the view publishes
    only virtual cells), however real it is to a pointer-side QAccessible
    query. The box must therefore sit in the panel's own widget hierarchy —
    no QAbstractItemView may stand between it and the panel."""
    host = FakeHost()
    panel = _panel(qtbot, host)
    panel.set_instances(ROWS)

    for box in panel.seat_boxes():
        ancestor = box.parentWidget()
        while ancestor is not panel:
            assert ancestor is not None, "the seat checkbox left the panel"
            assert not isinstance(ancestor, QAbstractItemView), (
                "a seating checkbox sits inside an item view — the live "
                "cocoa tree will publish cells, not this checkbox (PR-022)"
            )
            ancestor = ancestor.parentWidget()


async def test_the_toggle_action_is_the_press_cocoa_sends_and_seats_once(
    qtbot, wait_for
):
    """Qt 6.10 cocoa answers an AXPress on a CheckBox role with the Toggle
    action (qcocoaaccessibility translateAction — the PR-001 mechanism). The
    live press therefore arrives as Toggle: it must seat EXACTLY once, no
    double flip through a role-default bare ``checked`` write."""
    host = FakeHost()
    host.start_fake()
    panel = _panel(qtbot, host)
    panel.set_instances(ROWS)

    box = _seat_box(panel, 12)
    iface = QAccessible.queryAccessibleInterface(box)
    iface.actionInterface().doAction("Toggle")
    await wait_for(lambda: host.calls == [("seat", 12)])
    assert panel.checked_seat_ids() == [12]

    # the reverse through the same channel, still one call per action
    iface.actionInterface().doAction("Toggle")
    await wait_for(lambda: host.calls == [("seat", 12), ("drop_seat", 12)])
    assert len(host.calls) == 2
    host.stop_fake()


async def test_the_seat_lives_in_the_tab_chain_and_space_drives_it(
    qtbot, wait_for
):
    """PR-022's keyboard half: Tab from the port spin must reach a seating
    checkbox (the old cell checkbox was skipped — Tab landed on the item view)
    and Space on the focused box is the seat action."""
    host = FakeHost()
    host.start_fake()
    panel = _panel(qtbot, host)
    panel.set_instances(ROWS)

    walk = panel.port_spin
    for _ in range(25):
        walk = walk.nextInFocusChain()
        if isinstance(walk, QCheckBox):
            break
    else:
        raise AssertionError("Tab chain from the port spin never reaches a seat")
    assert walk in panel.seat_boxes(), "the first checkbox is not a seating box"

    walk.setFocus()
    assert panel.focusWidget() is walk
    expected_id = {name: iid for iid, name in _NAMES.items()}[walk.accessibleName()]
    QTest.keyClick(walk, Qt.Key.Key_Space)
    await wait_for(lambda: host.calls == [("seat", expected_id)])
    host.stop_fake()
