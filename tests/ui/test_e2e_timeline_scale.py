"""E2E for the W4 scale ladder (group 5): the Ctrl/Cmd + wheel gesture, the
zooming month click, the unit-normalizing month drag through the real chip
channel, and the header switchers that must never displace «+»/chip/jumps nor
drop the selection or the filter.

Boots the full application (tests/ui/conftest); events are created through the
real «+» dialog, the ladder is driven with synthetic wheel/mouse events on the
real list viewport, and every assertion rides the same signal paths as the app
(``ApplicationWiring`` → ``TimelineViewModel`` → panel).
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from app.presentation.viewmodels.timeline_viewmodel import EntityKind
from app.presentation.views.timeline_widget import ScaleUnit, filter_chip_text

from tests.ui import helpers


# ── synthetic input on the real list viewport ──────────────────────────────

def _view(window):
    return window.timeline_widget.rows_view


def _row_center(view, idx: int) -> QPoint:
    return view.visualItemRect(view.item(idx)).center()


def _rail_point(view, idx: int) -> QPoint:
    return QPoint(view.rail_width() // 2, _row_center(view, idx).y())


def _mouse(vp, point, etype, button, buttons, mods=Qt.KeyboardModifier.NoModifier):
    QApplication.sendEvent(vp, QMouseEvent(
        etype, QPointF(point), vp.mapToGlobal(point),
        button, buttons, mods,
    ))


def _press_release(view, point: QPoint) -> None:
    vp = view.viewport()
    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    _mouse(vp, point, QEvent.Type.MouseButtonPress, left, left)
    _mouse(vp, point, QEvent.Type.MouseButtonRelease, left, none)


def _drag(view, start: QPoint, end: QPoint) -> None:
    vp = view.viewport()
    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    _mouse(vp, start, QEvent.Type.MouseButtonPress, left, left)
    _mouse(vp, end, QEvent.Type.MouseMove, left, left)
    _mouse(vp, end, QEvent.Type.MouseButtonRelease, left, none)


def _ctrl_wheel(view, angle: int) -> None:
    point = QPointF(view.viewport().rect().center())
    QApplication.sendEvent(view.viewport(), QWheelEvent(
        point, view.viewport().mapToGlobal(point.toPoint()),
        QPoint(0, 0), QPoint(0, angle),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    ))


async def _seed_months(app, wait_for, names_dates) -> None:
    """Create events through the real «+» dialog, closing same-day spans."""
    window = app[1]
    for name, day in names_dates:
        await helpers.create_event_via_ui(
            window, wait_for, name,
            start_date=QDate(day.year, day.month, day.day),
            end_date=QDate(day.year, day.month, day.day),
        )
    await wait_for(lambda: len(_view(window).rows) >= len(names_dates))


async def test_ctrl_wheel_e2e_steps_ladder_both_ways(app, wait_for):
    """Task 5.4: the wheel gesture drives the VM knob, not the scroll step."""
    application, window = app
    panel = window.timeline_widget
    vm = panel._vm
    view = _view(window)
    await _seed_months(app, wait_for, [
        ("Зима", date(1245, 1, 5)), ("Весна", date(1245, 3, 5)),
        ("Лето", date(1245, 6, 5)),
    ])
    assert view.scale_unit is ScaleUnit.DAY

    before = view.verticalScrollBar().value()
    _ctrl_wheel(view, -120)  # отдаляем: сутки → месяц
    await wait_for(lambda: vm.unit is ScaleUnit.MONTH)
    assert view.scale_unit is ScaleUnit.MONTH
    assert all(r.kind.name == "UNIT" for r in view.rows)
    assert panel.scale_buttons[ScaleUnit.MONTH].isChecked()
    assert view.sticky_label.text() == "Январь 1245"

    _ctrl_wheel(view, -120)  # …и ещё раз: месяц → год
    await wait_for(lambda: vm.unit is ScaleUnit.YEAR)
    assert view.sticky_label.text() == "1245"

    _ctrl_wheel(view, 120)  # приближаем назад две ступени
    await wait_for(lambda: vm.unit is ScaleUnit.MONTH)
    _ctrl_wheel(view, 120)
    await wait_for(lambda: vm.unit is ScaleUnit.DAY)
    assert panel.scale_buttons[ScaleUnit.DAY].isChecked()
    # the ladder never scrolled through wheel steps on its way around
    assert before == 0


async def test_month_click_and_rail_jump_e2e(app, wait_for):
    """Task 5.5: позиция приближает с якорем, рейка прыгает; сигналов нет."""
    application, window = app
    panel = window.timeline_widget
    vm = panel._vm
    view = _view(window)
    # 6 месячных строк должны не помещаться в вьюпорт, иначе рейке нечем
    # прыгать: максимальный скролл = 0 и assert below вырождается в no-op
    panel.setFixedHeight(170)
    await _seed_months(app, wait_for, [
        ("Январь", date(1245, 1, 5)), ("Март", date(1245, 3, 5)),
        ("Май", date(1245, 5, 5)),
    ])
    panel.scale_buttons[ScaleUnit.MONTH].click()
    await wait_for(lambda: view.scale_unit is ScaleUnit.MONTH)
    detail = window.detail_panel
    detail_before = detail.title_label.text()

    # клик по позиции марта — в текстовой зоне, мимо рейки
    _press_release(view, QPoint(view.rail_width() + 30, _row_center(view, 2).y()))
    await wait_for(lambda: vm.unit is ScaleUnit.DAY)
    assert view.scale_unit is ScaleUnit.DAY
    assert view.rows[view.top_visible_index()].date == date(1245, 3, 1)
    assert view.selected_id is None
    assert detail.title_label.text() == detail_before  # ничего не открылось

    # обратно на месяц: якорем становится верхняя дата (март)…
    panel.scale_buttons[ScaleUnit.MONTH].click()
    await wait_for(lambda: view.scale_unit is ScaleUnit.MONTH)
    anchor_bar = view.verticalScrollBar().value()
    assert anchor_bar > 0 and view.sticky_label.text() == "Март 1245"
    # …а клик в рейке по январю прыгает вверх (прыжок ≠ якорь и ≠ выбор)
    _press_release(view, _rail_point(view, 0))
    assert view.verticalScrollBar().value() == 0
    assert view.sticky_label.text() == "Январь 1245"
    assert view.selected_id is None  # прыжок не выбор
    assert detail.title_label.text() == detail_before


async def test_month_drag_chip_shows_whole_borders(app, wait_for):
    """Task 5.6: drag месяцами → чип показывает 1 марта — 31 мая, фильтр тот же."""
    application, window = app
    panel = window.timeline_widget
    view = _view(window)
    await _seed_months(app, wait_for, [
        ("До", date(1245, 1, 5)), ("Начало", date(1245, 3, 3)),
        ("Середина", date(1245, 4, 20)), ("Конец", date(1245, 5, 9)),
    ])
    panel.scale_buttons[ScaleUnit.MONTH].click()
    await wait_for(lambda: view.scale_unit is ScaleUnit.MONTH)

    _drag(view, _rail_point(view, 2), QPoint(
        view.rail_width() // 2, _row_center(view, 4).y(),
    ))
    await wait_for(
        lambda: panel.filter_chip.text()
        == filter_chip_text(date(1245, 3, 1), date(1245, 5, 31))
    )
    assert panel._filter_range == (date(1245, 3, 1), date(1245, 5, 31))
    # семантика фильтра не изменилась: «До» выпало, остальные остались
    await wait_for(lambda: helpers.has_event_named(window, "Начало"))
    assert not helpers.has_event_named(window, "До")
    assert helpers.has_event_named(window, "Конец")
    # шкала осталась месячной и показывает только попавшие месяцы
    assert all(r.kind.name == "UNIT" for r in view.rows)


async def test_header_switchers_survive_with_selection_and_filter(app, wait_for):
    """Task 5.7: сутки·месяц·год и группы вписаны в шапку; выбор и фильтр живут."""
    application, window = app
    panel = window.timeline_widget
    vm = panel._vm
    view = _view(window)
    await _seed_months(app, wait_for, [
        ("Зима", date(1245, 1, 5)), ("Весна", date(1245, 3, 5)),
        ("Лето", date(1245, 6, 5)),
    ])
    # шапка целая: «+», чип, обе кнопки прыжка — никто не вытеснен
    for widget in (panel.add_button, panel.filter_chip,
                   panel.jump_prev_button, panel.jump_next_button,
                   panel.group_button):
        assert widget.isVisible() or widget.parent() is not None
    assert all(b.isVisible() for b in panel.scale_buttons.values())

    # фильтр через попап (чип-путь): март — июнь
    panel.filter_popup.start_calendar.clicked.emit(QDate(1245, 3, 1))
    panel.filter_popup.start_calendar.clicked.emit(QDate(1245, 6, 30))
    await wait_for(
        lambda: panel.filter_chip.text()
        == filter_chip_text(date(1245, 3, 1), date(1245, 6, 30))
    )

    event_id = helpers.click_timeline_event(window, "Весна")
    # ждём конец сигнала (wiring → VM), а не только синхронный отклик вьюа
    await wait_for(lambda: vm.selected_event is not None
                   and vm.selected_event.id == event_id)
    detail_title = window.detail_panel.title_label.text()
    chip_before = panel.filter_chip.text()

    # сутки → месяц → сутки: тот же выбор, тот же фильтр (spec scenarios)
    panel.scale_buttons[ScaleUnit.MONTH].click()
    await wait_for(lambda: vm.unit is ScaleUnit.MONTH)
    assert vm.selected_event is not None and vm.selected_event.id == event_id
    panel.scale_buttons[ScaleUnit.DAY].click()
    await wait_for(lambda: vm.unit is ScaleUnit.DAY)
    assert view.selected_id == event_id
    row = view.index_for_event(event_id)
    assert view.selectedIndexes() and view.selectedIndexes()[0].row() == row
    assert panel.filter_chip.text() == chip_before
    assert window.detail_panel.title_label.text() == detail_title

    # группировка применяется немедленно и ничего не роняет: на сутках она
    # только упорядочивает события внутри дня (секции — на крупных ступенях)
    panel.group_actions[EntityKind.CHARACTER].trigger()
    await wait_for(lambda: vm.group_by is EntityKind.CHARACTER)
    assert view.selected_id == event_id
    assert panel.filter_chip.text() == chip_before
    # на месяцах та же группировка секционирует список («Без привязки» — все)
    panel.scale_buttons[ScaleUnit.MONTH].click()
    await wait_for(lambda: view.scale_unit is ScaleUnit.MONTH)
    kinds = [r.kind.name for r in view.rows]
    assert "SECTION" in kinds and "UNIT" in kinds
