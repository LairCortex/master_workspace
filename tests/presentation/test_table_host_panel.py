"""Tests for the master table-host panel (tasks 5.1 / 5.2)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QCheckBox
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import CharacterSheetService
from app.application.services.table_host_service import TableHostService
from app.domain.enums.field_type import FieldType
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.infrastructure.table_host.http import DEFAULT_PORT
from app.presentation.views.main_window import MainWindow
from app.presentation.views.table_host.panel import TableHostPanel


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _seat_box(panel: TableHostPanel, index: int) -> QCheckBox:
    """NRI-0016 (TB3-ремонт) + PR-022-ремонт: the seating state lives on the
    row's QCheckBox — a plain child widget of the desk, by row order."""
    return panel.seat_boxes()[index]


def test_seat_rows_use_the_style_facing_tick_checkbox(qtbot):
    # The seating rows are the STYLE-FACING TableHostSeatCheck: the named rule
    # in compile_qss and the painted tick in its paintEvent hang on this class.
    # The stock contract the PR-022 pins rely on survives the subclass: it IS
    # a QCheckBox (isinstance), so every old type check keeps passing.
    from PySide6.QtWidgets import QCheckBox as StockQCheckBox

    from app.presentation.views.table_host.panel import TableHostSeatCheck

    host = TableHostService(MagicMock(), MagicMock())
    panel = TableHostPanel(host, list_ipv4=lambda: ["10.0.0.2"])
    qtbot.addWidget(panel)
    panel.set_instances([(1, "Лист A"), (2, "Лист B")])
    box = _seat_box(panel, 0)
    assert isinstance(box, TableHostSeatCheck)
    assert isinstance(box, StockQCheckBox)
    assert type(box) is TableHostSeatCheck


def test_menu_table_exists(qtbot):
    w = MainWindow(
        timeline_vm=MagicMock(),
        detail_vm=MagicMock(),
        search_vm=MagicMock(),
    )
    qtbot.addWidget(w)
    assert w.table_host_action.text() == "Стол…"
    with qtbot.waitSignal(w.table_host_requested, timeout=1000):
        w.table_host_action.trigger()


def test_port_editable_before_start(qtbot):
    host = TableHostService(MagicMock(), MagicMock())
    panel = TableHostPanel(host, list_ipv4=lambda: ["10.0.0.2"])
    qtbot.addWidget(panel)
    assert panel.port_spin.value() == DEFAULT_PORT
    assert panel.port_spin.isEnabled()
    panel.port_spin.setValue(8000)
    assert panel.port_spin.value() == 8000


async def test_urls_include_ipv4_and_loopback_and_qr(qtbot):
    # NRI-0016 (TB2): the requisites are shown only for a running table, so
    # the address contract is checked after start instead of before it.
    host = TableHostService(MagicMock(), MagicMock())
    host.set_seating([1])
    await host.start()
    panel = TableHostPanel(host, list_ipv4=lambda: ["192.168.1.5", "127.0.0.1"])
    qtbot.addWidget(panel)
    text = panel.urls_label.text()
    assert f"http://192.168.1.5:{DEFAULT_PORT}/" in text
    assert f"http://127.0.0.1:{DEFAULT_PORT}/" in text
    pix = panel.qr_label.pixmap()
    assert pix is not None and not pix.isNull()
    await host.stop()  # NRI-0016: the cleanup close must not meet a running table


async def test_player_list_and_kick(qtbot, async_session: AsyncSession):
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    host = TableHostService(inst_svc, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    template.add_field(FieldType.TEXT, (10.0, 10.0))
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист 1", row.id)
    host.seat(inst.id)
    await host.start()
    await host.join(host.pin, "Вася", inst.id)

    panel = TableHostPanel(host, list_ipv4=lambda: ["10.0.0.2"])
    qtbot.addWidget(panel)
    panel.refresh_players()
    assert panel.player_list.count() == 1
    assert "Вася" in panel.player_list.item(0).text()
    panel.player_list.setCurrentRow(0)
    await panel.kick_selected()
    panel.refresh_players()
    assert panel.player_list.count() == 0
    assert host.occupancy == {}
    await panel.kick_selected()
    panel._on_player_click()
    await host.stop()  # NRI-0016: cleanup close must not meet a running table


async def test_player_click_emits_selected(qtbot, async_session: AsyncSession):
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    host = TableHostService(inst_svc, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    template.add_field(FieldType.TEXT, (10.0, 10.0))
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист 1", row.id)
    host.seat(inst.id)
    await host.start()
    await host.join(host.pin, "Вася", inst.id)
    panel = TableHostPanel(host, list_ipv4=lambda: ["10.0.0.2"])
    qtbot.addWidget(panel)
    panel.refresh_players()
    seen: list[int] = []
    panel.player_selected.connect(seen.append)
    panel.player_list.setCurrentRow(0)
    assert seen == [inst.id]
    item = panel.player_list.item(0)
    item.setData(Qt.ItemDataRole.UserRole, None)
    panel.player_list.clearSelection()
    panel.player_list.setCurrentRow(0)
    await panel.kick_selected()
    await host.stop()  # NRI-0016: cleanup close must not meet a running table


def _click_player_row(panel: TableHostPanel, index: int) -> None:
    """One real mouse click (press + release) on a player row — the route
    only the mouse has (setCurrentRow never fires itemClicked). The buttons
    are spelled out explicitly: the suite's recipe against the stale
    process-global button state the offscreen platform leaves behind."""
    item = panel.player_list.item(index)
    viewport = panel.player_list.viewport()
    pos = panel.player_list.visualItemRect(item).center()
    global_pos = viewport.mapToGlobal(pos)
    for kind, buttons in (
        (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
    ):
        QApplication.sendEvent(viewport, QMouseEvent(
            kind, QPointF(pos), global_pos,
            Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier,
        ))
        QApplication.processEvents()


async def test_player_row_first_click_emits_once_and_reclick_repeats(
    qtbot, async_session: AsyncSession
):
    """NRI-0024 (task 5.3, spec «Повторный клик поднимает живое окно»): the
    mouse contract on the players list. A click that moves the selection is
    ONE emission (the click channel recognises the press-side row change and
    stays silent); a repeat click on the already-current row changes no
    selection, so the press-side channel must repeat the emission — this is
    what lets the connector re-enter open_fill and raise the live Fill
    window instead of leaving the second click inert."""
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    host = TableHostService(inst_svc, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    template.add_field(FieldType.TEXT, (10.0, 10.0))
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист 1", row.id)
    host.seat(inst.id)
    await host.start()
    await host.join(host.pin, "Вася", inst.id)
    panel = TableHostPanel(host, list_ipv4=lambda: ["10.0.0.2"])
    qtbot.addWidget(panel)
    panel.refresh_players()
    panel.show()
    QApplication.processEvents()  # lay the rows out — clicks aim at their rects
    seen: list[int] = []
    panel.player_selected.connect(seen.append)
    _click_player_row(panel, 0)
    assert seen == [inst.id], "a row-changing click must emit exactly once"
    _click_player_row(panel, 0)
    assert seen == [inst.id, inst.id], (
        "a repeat click on the current row must re-emit for the re-raise"
    )
    # A rebuild (occupancy push) drops the rows AND the stale snapshot: the
    # next click selects a fresh row through the selection channel, once.
    panel.refresh_players()
    _click_player_row(panel, 0)
    assert seen == [inst.id, inst.id, inst.id]
    await host.stop()  # NRI-0016: cleanup close must not meet a running table


def test_kick_disabled_and_pin_hidden_when_stopped(qtbot):
    host = TableHostService(MagicMock(), MagicMock())
    host._pin = "1234"
    host._running = False
    panel = TableHostPanel(host, list_ipv4=lambda: ["10.0.0.2"])
    qtbot.addWidget(panel)
    panel.sync_running()
    assert panel.kick_button.isEnabled() is False
    assert "—" in panel.pin_label.text()


async def test_checkbox_seats_and_unseats_while_running(qtbot, async_session: AsyncSession):
    import asyncio

    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    host = TableHostService(inst_svc, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    template.add_field(FieldType.TEXT, (10.0, 10.0))
    await sheet_svc.update_pages(row.id, template)
    a = await inst_svc.create("Лист A", row.id)
    b = await inst_svc.create("Лист B", row.id)
    host.seat(a.id)
    await host.start()
    await host.join(host.pin, "Вася", a.id)
    panel = TableHostPanel(host, list_ipv4=lambda: ["10.0.0.2"])
    qtbot.addWidget(panel)
    panel.set_instances([(a.id, "Лист A"), (b.id, "Лист B")])
    assert b.id not in host.seated_ids
    # NRI-0016 (TB3-ремонт): seating flips through the row's real QCheckBox.
    assert _seat_box(panel, 0).isChecked()  # a was seated before the panel
    _seat_box(panel, 1).setChecked(True)
    assert b.id in host.seated_ids
    _seat_box(panel, 0).setChecked(False)
    for _ in range(20):
        if a.id not in host.seated_ids:
            break
        await asyncio.sleep(0)
    assert a.id not in host.seated_ids
    assert host.occupancy == {}
    assert panel.checked_seat_ids() == [b.id]
    await host.stop()  # NRI-0016: cleanup close must not meet a running table
