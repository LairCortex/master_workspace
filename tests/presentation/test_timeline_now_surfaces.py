"""Offscreen contract of the timeline's «сейчас» surfaces (NRI-0021 group 5).

The production root QML over a REAL ViewModel and the REAL widget VM:

* task 5.1 — the delegate paints the delivered ``isNow`` flag as an OUTLINE
  from the accent derivation (border against the selection's fill), exactly
  one row, and a «now» edit MOVES the outline without a model reset (which
  would rewind the view's head — the spec forbids the edit from scrolling);
* task 5.2 — the «Сейчас» header button (crosshair glyph beside the caption
  since the 2026-09-30 icon pass) resolves by ``objectName``, sits
  beside the window chip, is named by its text (stock Button, no re-annotation),
  reads its availability from ``vm.nowScrollEnabled`` and answers a press
  with the VM's scroll request on the island's own ``scrollToIndex`` channel;
* task 5.3 — the chip popover opens its empty window on the GAME's «сейчас»
  page (never the system day), falling back to year 1 when no «now» is served.

Pattern of ``test_timeline_accessibility`` (real root, seeded VM) plus the
color probes of ``test_e2e_timeline_theme``; the row-flags math itself is
pinned Qt-free in ``test_timeline_rows``/``test_viewmodels``.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.domain.game_calendar import (
    MIN_YEAR,
    MonthDay,
    current_calendar,
    reset_current_calendar,
    set_current_calendar,
)
from app.presentation.viewmodels.now_date_view_model import NowDateViewModel
from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views.timeline_island import TimelineWidget
from tests.presentation.qml_helpers import click_item, find_item, island_rows, track


@pytest.fixture(autouse=True)
def _default_months():
    """Captions and calendar pages come from the active calendar; pin the
    «Стандартный» preset around every unit."""
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


def _evt(eid: int, start: date, end: date | None = None, name: str | None = None):
    return SimpleNamespace(
        id=eid, name=name or f"event-{eid}", start_date=start, end_date=end,
        event_type=None, description=None,
    )


class _Service:
    def __init__(self, events=()):
        self._events = list(events)

    async def get_all_events(self):
        return list(self._events)


# Jan 5 and Mar 7 of 1200: the «now» on Jan 5 marks the FIRST row.
EVENTS = [
    _evt(1, date(1200, 1, 5), date(1200, 1, 5), "Старт"),
    _evt(2, date(1200, 3, 7), None, "Пророчество"),
]
NOW = MonthDay(1200, 1, 5)


def _island(qtbot, events=EVENTS, now_vm=None):
    """The production facade on the REAL root (the accessibility suite's
    seeded-VM pattern) with the optional game-«now» widget VM."""
    vm = TimelineViewModel(_Service(events), now_vm=now_vm)
    vm._all_events = list(events)
    vm.events = list(events)
    vm._rebuild_rows()
    panel = TimelineWidget(vm)
    qtbot.addWidget(panel)
    panel.resize(320, 240)
    panel.show()
    QApplication.processEvents()
    assert panel.quick.status() == panel.quick.Status.Ready, panel.quick.errors()
    return panel, vm


def _retire(panel, qtbot) -> None:
    """The production exit path (close → deferred island release), so the
    scene — and the «now» subscription — die inside their own test."""
    panel.close()
    qtbot.waitUntil(lambda: panel.quick.source().isEmpty(), timeout=2000)


def _outline(row_item):
    """The delegate's outline node (the delegate's own objectName contract)."""
    return next(i for i in row_item.childItems() if i.objectName() == "rowNowOutline")


def _visible_outlines(panel) -> list[bool]:
    return [
        bool(_outline(row).property("visible"))
        for row in island_rows(panel.quick, "eventRow")
    ]


def _grid_page(grid) -> tuple[int, int]:
    return grid._year_spin.value(), grid._month_combo.currentIndex() + 1


def _pixel(panel, item, fx: float, fy: float) -> QColor:
    """The grabbed pixel under a fractional point of an item (the
    ``test_e2e_timeline_theme`` probe idiom — border colors are paint, not
    introspectable QQuickItem properties)."""
    image = panel.quick.grab().toImage()
    scene = item.mapToScene(QPointF(item.width() * fx, item.height() * fy))
    scale = image.width() / max(panel.quick.width(), 1)
    x = min(max(int(scene.x() * scale), 0), image.width() - 1)
    y = min(max(int(scene.y() * scale), 0), image.height() - 1)
    return image.pixelColor(x, y)


# ── task 5.1 — the delegate paints the delivered flag as an outline ──────────


def test_only_the_today_row_wears_the_outline(qtbot):
    panel, _vm = _island(qtbot, now_vm=NowDateViewModel(NOW))
    rows = island_rows(panel.quick, "eventRow")
    assert len(rows) == 2
    # The first in sort order — the row the core marked — is the outlined one.
    assert [bool(_outline(row).property("visible")) for row in rows] == [True, False]
    _retire(panel, qtbot)


def test_the_outline_is_an_accent_derivation_never_a_fill(qtbot):
    """Design Д6: border against the selection's fill. Painted truth first:
    the outlined row's body keeps the field's canvas colour (an outline never
    fills), only its edge line is painted — and on the outlined row alone.
    The line is the compiler's ``color.accent.hover`` composite over the
    field (±2 raster rounding, the ``_is_wash`` convention), never the
    ``color.accent`` itself that fills the selected row."""
    panel, _vm = _island(qtbot, now_vm=NowDateViewModel(NOW))
    rows = island_rows(panel.quick, "eventRow")
    tokens = panel._palette.tokens
    canvas = QColor(tokens["color.bg.canvas"])

    # far-right pixel column, clear of the elided caption (theme suite rule)
    assert _pixel(panel, rows[0], 0.97, 0.5) == canvas  # body paints nothing
    edge_now = _pixel(panel, rows[0], 0.97, 0.5 / 24)   # the 1-px top border
    edge_plain = _pixel(panel, rows[1], 0.97, 0.5 / 24)
    assert edge_plain == canvas  # the plain row wears no line
    assert edge_now != canvas    # the today row's line really painted

    hover = QColor(tokens["color.accent.hover"])
    alpha = hover.alphaF()
    wanted = QColor(
        round(hover.red() * alpha + canvas.red() * (1 - alpha)),
        round(hover.green() * alpha + canvas.green() * (1 - alpha)),
        round(hover.blue() * alpha + canvas.blue() * (1 - alpha)),
    )
    assert max(
        abs(edge_now.red() - wanted.red()),
        abs(edge_now.green() - wanted.green()),
        abs(edge_now.blue() - wanted.blue()),
    ) <= 2
    # The mandated visual difference: the outline token is NOT the fill token.
    assert wanted != QColor(tokens["color.accent"])
    _retire(panel, qtbot)


def test_the_outline_block_reads_the_hover_derivation_not_the_fill_token():
    """Source-level token contract of the delegate (the same grep-grade idiom
    as the accessibility convention guards): the rowNowOutline block binds
    the accent DERIVATION ``color.accent.hover``; the raw ``color.accent`` —
    the selection's fill — stays out of the outline block. NRI-0023 task 11.4
    (A2) adds the second half: over the selection the line flips to the
    delegate's ONE contrast foreground (``accentFgColor`` — the caption's own
    switch), and the flip is the border colour only: the block still never
    fills, never reads the fill token."""
    from pathlib import Path

    from app.presentation.qml.engine import QML_IMPORT_PATH

    source = (
        Path(QML_IMPORT_PATH) / "TimelineRowDelegate.qml"
    ).read_text(encoding="utf-8")
    block = source.split('objectName: "rowNowOutline"', 1)[1].split("\n    }", 1)[0]
    assert '"color.accent.hover"' in block
    assert '"color.accent"' not in block
    # 11.4: the selected-row branch is the accent foreground, the fill itself
    # never enters the block, and the geometry stays a 1-px border on a
    # transparent body.
    assert "row.selectedRow" in block and "accentFgColor" in block
    assert 'color: "transparent"' in block
    assert "border.width: 1" in block


def test_the_outline_flips_to_the_contrast_family_when_selected(qtbot):
    """NRI-0023 task 11.4 (spec scenario «Обводка видна на выбранной строке»,
    audit A2): selecting the today-row must not erase its outline — orange
    over orange is what the live audit caught. On this skinned (process
    default theme) island the selected edge pixel answers ``color.accent.fg``
    verbatim, measurably far from the accent fill it now rides, while an
    unselected row still wears the plain canvas (no line). The both-themes
    pixel half is pinned in tests/ui/test_e2e_timeline_theme.py."""
    panel, _vm = _island(qtbot, now_vm=NowDateViewModel(NOW))
    tokens = panel._palette.tokens
    accent = QColor(tokens["color.accent"])
    accent_fg = QColor(tokens["color.accent.fg"])
    assert accent != accent_fg  # the flip is meaningful in this theme

    rows = island_rows(panel.quick, "eventRow")
    outline = _outline(rows[0])
    assert outline.property("visible") is True
    panel.set_selected(1)
    # the render-pass beat the embedded scene graph needs before a pixel is
    # truth (the test_e2e_timeline_theme qWait convention)
    QTest.qWait(50)
    QApplication.processEvents()

    # body still paints nothing under the outline (an outline never fills:
    # the far-right body pixel is the accent FILL, not a second color)
    edge = _pixel(panel, rows[0], 0.97, 0.5 / 24.0)
    distance = max(abs(edge.red() - accent.red()),
                   abs(edge.green() - accent.green()),
                   abs(edge.blue() - accent.blue()))
    assert distance > 20, (edge.name(), accent.name())
    for chan in ("red", "green", "blue"):
        assert abs(getattr(edge, chan)() - getattr(accent_fg, chan)()) <= 2, edge.name()
    _retire(panel, qtbot)


def test_now_edit_moves_the_outline_without_scrolling(qtbot):
    """Spec «Смена „сейчас“ SHALL не прокручивать список сама»: the flag
    re-delivery is a scoped repaint (no model reset, no scroll request), and
    the outline simply moves to the new today-row."""
    now_vm = NowDateViewModel(NOW)
    panel, vm = _island(qtbot, now_vm=now_vm)
    scrolls = track(panel._root.scrollToIndex)
    assert _visible_outlines(panel) == [True, False]

    now_vm.applyNow(MonthDay(1200, 3, 7), False)
    QApplication.processEvents()

    assert _visible_outlines(panel) == [False, True]
    assert scrolls == []  # the edit alone never asks the view to move
    # …and the delivery was in-place: the membership and texts stayed put,
    # only the flag moved (a reset would have rewound the view's head).
    assert [row.property("caption") for row in island_rows(panel.quick, "eventRow")] == [
        "05 Январь 1200 — 05 Январь 1200 · Старт",
        "07 Март 1200 — ∞ · Пророчество",
    ]
    assert [row.is_now for row in vm.rows] == [False, True]
    _retire(panel, qtbot)


def test_the_hour_moves_neither_the_outline_nor_the_scroll_target(qtbot):
    """NRI-0023 task 9.1 pin (spec «Час меняет только подпись»): setting an
    hour on the game-«now» leaves the today-outline and the «Сейчас»
    target on the day they were computed from — the derived surfaces read
    the coordinate, and the ``nowChanged`` broadcast that triggers them
    stays silent for an hour-only edit."""
    now_vm = NowDateViewModel(NOW)
    panel, vm = _island(qtbot, now_vm=now_vm)
    assert _visible_outlines(panel) == [True, False]

    now_vm.applyNow(NOW, False, 20)  # тот же день, выставлен час 20
    QApplication.processEvents()

    assert _visible_outlines(panel) == [True, False]
    assert [row.is_now for row in vm.rows] == [True, False]

    button = find_item(panel.quick, "nowButton")
    scrolls = track(panel._root.scrollToIndex)
    click_item(panel.quick, button)
    QApplication.processEvents()

    assert scrolls == [(1,)]  # цель прокрутки от часа не сдвинулась
    assert vm.rows[scrolls[0][0]].event_id == 2
    _retire(panel, qtbot)


# ── task 5.2 — the «Сейчас» header button ─────────────────────────────────────


def test_header_button_resolves_by_object_name_beside_the_chip(qtbot):
    panel, _vm = _island(qtbot, now_vm=NowDateViewModel(NOW))
    button = find_item(panel.quick, "nowButton")  # the objectName contract
    chip = find_item(panel.quick, "windowChip")
    add = find_item(panel.quick, "addButton")

    # A stock text Button: the caption IS its accessibility name, the usage
    # site adds no annotation (nri-0012 contract, guard-pinned by
    # tests/test_qml_accessibility_conventions.py).
    assert button.property("text") == "Сейчас"
    assert button.property("iconName") == "crosshair"
    # The chip's dropdown caret is its trailing Lucide chevron, never caption
    # text (live fix 2026-09-30 A1).
    assert chip.property("trailingIconName") == "chevron-down"
    # «рядом с чипом окна» — left of the chip, before the «+» on the band.
    scene_x = [
        item.mapToScene(QPointF(0, 0)).x() for item in (button, chip, add)
    ]
    assert scene_x == sorted(scene_x)
    # «Все дни» contains every date — the button lives by default.
    assert bool(button.property("enabled")) is True
    _retire(panel, qtbot)


def test_button_availability_follows_the_filter_window(qtbot):
    """Spec «Кнопка вне окна»: the QML binding rides the VM's notify — a
    window that excludes «сейчас» disables the button, the «Все дни» reset
    returns its life without any island-side re-wiring."""
    panel, vm = _island(qtbot, now_vm=NowDateViewModel(NOW))
    button = find_item(panel.quick, "nowButton")

    vm.window = (date(1300, 1, 1), date(1300, 12, 31))  # «сейчас» 1200 — вне
    QApplication.processEvents()
    assert bool(button.property("enabled")) is False

    vm.window = None
    QApplication.processEvents()
    assert bool(button.property("enabled")) is True
    _retire(panel, qtbot)


def test_press_requests_the_scroll_to_the_row_after_now(qtbot):
    """The press only enters the sync slot; the VM's index lands on the
    island's single ``scrollToIndex`` channel — and neither the window chip
    nor the selection moved on the way."""
    panel, vm = _island(qtbot, now_vm=NowDateViewModel(NOW))
    button = find_item(panel.quick, "nowButton")
    scrolls = track(panel._root.scrollToIndex)

    click_item(panel.quick, button)
    QApplication.processEvents()

    assert scrolls == [(1,)]  # track() collects emit-argument tuples
    assert vm.rows[scrolls[0][0]].event_id == 2
    assert panel._root.property("windowText") == "Все дни"  # окно не сдвинулось
    assert panel._root.property("selectedId") == -1  # выбор не сдвинулся
    _retire(panel, qtbot)


def test_button_without_a_game_now_is_disabled_and_inert(qtbot):
    """A VM built without the widget (bare unit-built panel): the button
    stays disabled and even its press cannot invent a scroll target."""
    panel, _vm = _island(qtbot, now_vm=None)
    button = find_item(panel.quick, "nowButton")
    scrolls = track(panel._root.scrollToIndex)

    assert bool(button.property("enabled")) is False
    click_item(panel.quick, button)
    QApplication.processEvents()
    assert scrolls == []  # requestNowScroll answered -1 → _reveal no-op
    _retire(panel, qtbot)


# ── task 5.3 — the chip popover opens on the game-«now» page ─────────────────


CHIP_RECT = (20.0, 30.0, 140.0, 24.0)  # a plausible chip rect in scene px


def test_chip_popover_opens_the_empty_window_on_the_game_now(qtbot):
    """The island injects the VM's «сейчас» pair into the popover: an empty
    window pages BOTH grids onto the game date — not the system day, not
    «январь, год 1», and an empty window still selects nothing."""
    now_vm = NowDateViewModel(MonthDay(44, 2, 3))  # ≠ системный день
    panel, _vm = _island(qtbot, now_vm=now_vm)

    panel._root.datePopupRequested.emit(*CHIP_RECT)
    popup = panel.window_popup
    today = date.today()
    for grid in (popup.start_calendar, popup.end_calendar):
        assert _grid_page(grid) == (44, 2)
        assert (44, 2) != (today.year, today.month)
        assert _grid_page(grid) != (MIN_YEAR, 1)
        assert grid.selection() is None
    popup.close()
    _retire(panel, qtbot)


def test_chip_popover_without_a_game_now_falls_back_to_year_one(qtbot):
    """The island-side half of the «иначе год 1» convention: a VM that serves
    no «сейчас» seeds the popover with nothing — the system day is gone from
    the rule entirely."""
    panel, _vm = _island(qtbot, now_vm=None)

    panel._root.datePopupRequested.emit(*CHIP_RECT)
    popup = panel.window_popup
    assert _grid_page(popup.start_calendar) == (MIN_YEAR, 1)
    assert _grid_page(popup.end_calendar) == (MIN_YEAR, 1)
    popup.close()
    _retire(panel, qtbot)


# ── teardown — the subscription never outlives the panel (DEFECT-1) ──────────


def test_closing_the_island_detaches_the_now_subscription(qtbot):
    """Design Д2/Д6: the widget VM is the SEARCH island's context property and
    can outlive this panel — the release path retires the timeline's
    ``nowChanged`` subscription, so a later edit reaches neither layer."""
    now_vm = NowDateViewModel(NOW)
    panel, vm = _island(qtbot, now_vm=now_vm)
    assert vm._now_vm is now_vm

    panel.close()
    qtbot.waitUntil(lambda: panel.quick.source().isEmpty(), timeout=2000)

    assert vm._now_vm is None  # the detach ran in _release_island
    now_vm.applyNow(MonthDay(1200, 3, 7), False)  # invisible to the dead panel
    assert [row.is_now for row in vm.rows] == [True, False]  # stale by design
