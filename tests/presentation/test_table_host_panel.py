"""Tests for the master table-host panel (tasks 5.1 / 5.2)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
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


def test_urls_include_ipv4_and_loopback_and_qr(qtbot):
    host = TableHostService(MagicMock(), MagicMock())
    panel = TableHostPanel(host, list_ipv4=lambda: ["192.168.1.5", "127.0.0.1"])
    qtbot.addWidget(panel)
    text = panel.urls_label.text()
    assert f"http://192.168.1.5:{DEFAULT_PORT}/" in text
    assert f"http://127.0.0.1:{DEFAULT_PORT}/" in text
    pix = panel.qr_label.pixmap()
    assert pix is not None and not pix.isNull()


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
    panel.seat_list.item(1).setCheckState(Qt.CheckState.Checked)
    assert b.id in host.seated_ids
    panel.seat_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    for _ in range(20):
        if a.id not in host.seated_ids:
            break
        await asyncio.sleep(0)
    assert a.id not in host.seated_ids
    assert host.occupancy == {}
    panel.seat_list.item(1).setData(Qt.ItemDataRole.UserRole, None)
    panel.seat_list.item(1).setCheckState(Qt.CheckState.Unchecked)
