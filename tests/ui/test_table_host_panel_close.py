"""«Стол» panel lifecycle (NRI-0016 groups 1–3: TB1–TB7).

Close-while-running confirmation rides the existing ``stop_requested``
contour (fake host here, the real wiring in the last test); the address
requisites appear only for a running table; Enter in the panel never
starts anything; the seating rows are real QCheckBox widgets (3.1) and
«Выгнать» gates on a selected player (3.2); the small panel
captions/flags are pinned pointwise.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QMessageBox

from app.application.services.table_host_service import _new_pin
from app.infrastructure.table_host.http import DEFAULT_PORT
from app.presentation.views.table_host import panel as panel_module
from app.presentation.views.table_host.panel import TableHostPanel
from tests.ui.test_char_sheets_wiring import question_no, question_yes

_WEB_DIR = Path(panel_module.__file__).resolve().parent / "web"


class FakeHost:
    """TableHostService stand-in: state plus an action journal, no DB/HTTP."""

    def __init__(self, seated: tuple[int, ...] = ()) -> None:
        self.running = False
        self.port_value = DEFAULT_PORT
        self.pin_value = "530921"
        self.seated_value: set[int] = set(seated)
        self.players_list: list[tuple[int, str]] = []
        self.calls: list[tuple] = []
        self.subscribers: list = []

    # -- surface the panel uses ------------------------------------------
    def subscribe_occupancy(self, callback) -> None:
        self.subscribers.append(callback)

    @property
    def is_running(self) -> bool:
        return self.running

    @property
    def port(self) -> int:
        return self.port_value

    @property
    def pin(self) -> str | None:
        return self.pin_value

    @property
    def seated_ids(self) -> set[int]:
        return set(self.seated_value)

    def players(self) -> list[tuple[int, str]]:
        return list(self.players_list)

    def seat(self, instance_id: int) -> None:
        self.calls.append(("seat", instance_id))

    async def drop_seat(self, instance_id: int) -> None:
        self.calls.append(("drop_seat", instance_id))

    async def kick(self, instance_id: int) -> None:
        self.calls.append(("kick", instance_id))

    # -- test-side lifecycle (mirrors what the real stop notifies) --------
    def start_fake(self, port: int = DEFAULT_PORT) -> None:
        self.running = True
        self.port_value = port

    def stop_fake(self) -> None:
        self.running = False
        for callback in list(self.subscribers):
            callback()


@pytest.fixture
def fake_host() -> FakeHost:
    return FakeHost()


def _panel(qtbot, host: FakeHost, ipv4: tuple[str, ...] = ("10.0.0.8",)):
    panel = TableHostPanel(host, list_ipv4=lambda: list(ipv4))
    qtbot.addWidget(panel)
    panel.show()
    return panel


def _no_question(monkeypatch) -> list:
    asked: list = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(
            lambda *a, **k: asked.append(a) or QMessageBox.StandardButton.No
        ),
    )
    return asked


# ── 1.1 closeEvent (TB1) ─────────────────────────────────────────────────────

def test_close_while_running_asks_then_stops_and_closes(qtbot, fake_host, monkeypatch):
    fake_host.start_fake(7846)
    panel = _panel(qtbot, fake_host)
    calls = question_yes(monkeypatch)
    stops: list[int] = []
    panel.stop_requested.connect(lambda: stops.append(1))

    panel.close()

    assert calls == [["Стол", "Остановить стол?"]]
    assert stops == [1]
    # the panel waits for the stop signal — it went nowhere yet
    assert panel.isVisible()

    # the main contour answers the stop with the existing state sync
    fake_host.stop_fake()
    panel.sync_running()

    assert panel.isVisible() is False
    assert len(calls) == 1  # the closing pass asks nobody twice


def test_close_declined_keeps_table_and_panel(qtbot, fake_host, monkeypatch):
    fake_host.start_fake(7846)
    panel = _panel(qtbot, fake_host)
    calls = question_no(monkeypatch)
    stops: list[int] = []
    panel.stop_requested.connect(lambda: stops.append(1))

    panel.close()

    assert calls == [["Стол", "Остановить стол?"]]
    assert stops == []
    assert panel.isVisible()
    assert fake_host.running is True
    assert fake_host.calls == []  # nothing was touched
    # leave the fixture the way a user would: a running table stays, so the
    # qtbot cleanup close would otherwise sit in the confirmation modal
    fake_host.stop_fake()
    panel.sync_running()


def test_close_without_table_never_asks(qtbot, fake_host, monkeypatch):
    asked = _no_question(monkeypatch)
    panel = _panel(qtbot, fake_host)

    panel.close()

    assert asked == []
    assert panel.isVisible() is False


def test_force_close_skips_the_prompt(qtbot, fake_host, monkeypatch):
    # programmatic close (game switch / shutdown) never confirms
    fake_host.start_fake()
    asked = _no_question(monkeypatch)
    panel = _panel(qtbot, fake_host)

    panel.force_close()

    assert asked == []
    assert panel.isVisible() is False
    assert fake_host.running is True  # the host itself is left to main.py
    fake_host.stop_fake()


# ── 1.2 requisites only по факту (TB2), Enter (TB5) ─────────────────────────

def test_requisites_hidden_until_running_and_carry_actual_port(qtbot, fake_host):
    panel = _panel(qtbot, fake_host, ipv4=("192.168.1.5", "127.0.0.1"))
    assert panel.pin_label.isVisible() is False
    assert panel.urls_label.isVisible() is False
    assert panel.qr_label.isVisible() is False
    assert panel.urls_label.text() == ""
    assert panel.qr_url is None

    fake_host.start_fake(8123)  # spin still holds DEFAULT_PORT — host wins
    panel.sync_running()

    assert panel.pin_label.isVisible()
    assert panel.urls_label.isVisible()
    assert panel.qr_label.isVisible()
    assert f":{fake_host.port}/" in panel.urls_label.text()
    assert f":{DEFAULT_PORT}/" not in panel.urls_label.text()
    assert f":{fake_host.port}/" in (panel.qr_url or "")
    assert fake_host.pin_value in panel.pin_label.text()
    fake_host.stop_fake()


def test_port_edit_drops_stale_addresses(qtbot, fake_host):
    fake_host.start_fake(1111)
    panel = _panel(qtbot, fake_host)
    assert ":1111/" in panel.urls_label.text()

    fake_host.running = False  # table stopped without a sync in-between
    panel.port_spin.setValue(2222)

    assert panel.urls_label.text() == ""
    assert panel.qr_url is None
    # hidden again only once the state sync says so
    panel.sync_running()
    assert panel.qr_label.isVisible() is False


def test_enter_in_the_panel_starts_nothing(qtbot, fake_host):
    panel = _panel(qtbot, fake_host)
    starts: list[int] = []
    panel.start_requested.connect(lambda: starts.append(1))
    for button in (panel.start_button, panel.stop_button, panel.kick_button):
        assert button.autoDefault() is False
        assert button.isDefault() is False

    panel.port_spin.setFocus()
    QTest.keyClick(panel.port_spin, Qt.Key.Key_Return)

    assert starts == []


# ── 1.3 подписи, плейсхолдер, выделяемость, QR-хост (TB7) ───────────────────

def test_port_caption_and_selectable_pin(qtbot, fake_host):
    fake_host.start_fake()
    panel = _panel(qtbot, fake_host)
    assert panel.port_label.text() == "Порт:"
    assert panel.pin_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    fake_host.stop_fake()  # no running table left for the cleanup close


def test_players_placeholder_tracks_list_emptiness(qtbot, fake_host):
    fake_host.start_fake()
    panel = _panel(qtbot, fake_host)
    assert panel.player_list.count() == 0
    assert panel.player_placeholder.isVisible()

    fake_host.players_list = [(1, "Вася")]
    panel.refresh_players()
    assert panel.player_placeholder.isVisible() is False

    fake_host.players_list = []
    panel.refresh_players()
    assert panel.player_placeholder.isVisible()
    fake_host.stop_fake()


def test_qr_encodes_first_non_loopback_address(qtbot, fake_host):
    fake_host.start_fake(1234)
    panel = _panel(qtbot, fake_host, ipv4=("127.0.0.1", "10.0.0.9"))
    assert panel.qr_url == "http://10.0.0.9:1234/"
    assert "http://127.0.0.1:1234/" in panel.urls_label.text()
    fake_host.stop_fake()


def test_qr_falls_back_to_loopback_when_only_loopback(qtbot, fake_host):
    fake_host.start_fake(1234)
    panel = _panel(qtbot, fake_host, ipv4=("127.0.0.1",))
    assert panel.qr_url == "http://127.0.0.1:1234/"
    fake_host.stop_fake()


# ── 2.1 PIN шесть цифр, веб-константы синхронны (TB6) ────────────────────────

def test_web_constants_match_the_issued_pin_length():
    """The web client may never accept a PIN of another length than the
    service issues: both constants (index.html maxlength, app.js length
    check) are grepped against the actual issued PIN length."""
    issued = len(_new_pin(None))
    assert issued == 6  # TB6: the service contract itself
    html = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    js = (_WEB_DIR / "app.js").read_text(encoding="utf-8")
    pin_maxlength = re.search(r'id="pin"[^>]*maxlength="(\d+)"', html)
    js_length_check = re.search(r"pin\.length !== (\d+)", js)
    assert pin_maxlength is not None
    assert int(pin_maxlength.group(1)) == issued
    assert js_length_check is not None
    assert int(js_length_check.group(1)) == issued
    # the fake host used through this file must not lie about the length
    assert len(FakeHost().pin_value) == issued


# ── 3.1 посадки на настоящих QCheckBox (TB3-ремонт), 3.2 гейт «Выгнать» (TB4) ──

def _seat_box(panel: TableHostPanel, index: int) -> QCheckBox:
    row_widget = panel.seat_list.itemWidget(panel.seat_list.item(index))
    return row_widget.findChild(QCheckBox)


def test_seat_rows_carry_real_checkboxes_and_load_quietly(qtbot):
    # чекбокс-виджет в строке, имя — подпись рядом, у строк больше нет
    # ItemIsUserCheckable; загрузка чекнутой строки стреляет toggled под
    # _seats_loading-гардом — экземпляр не пересаживается (без рекурсии).
    host = FakeHost(seated=(11,))
    host.start_fake()
    panel = _panel(qtbot, host)
    panel.set_instances([(11, "Лист A"), (12, "Лист B")])

    assert host.calls == []
    assert isinstance(_seat_box(panel, 0), QCheckBox)
    assert _seat_box(panel, 0).isChecked()
    assert _seat_box(panel, 1).isChecked() is False
    row_widget = panel.seat_list.itemWidget(panel.seat_list.item(1))
    assert row_widget.findChild(QLabel).text() == "Лист B"
    # Живой ре-аудит 2026-09-25: текст на самом item рисуется делегатом ПОД
    # прозрачным row-widget — имя двоилось под чекбоксом. Item обязан быть
    # без текста, видимое имя несёт QLabel строки, а имя доступности —
    # AccessibleTextRole (делегат его не рисует).
    assert panel.seat_list.item(0).text() == ""
    assert panel.seat_list.item(1).text() == ""
    assert panel.seat_list.item(1).data(Qt.ItemDataRole.AccessibleTextRole) == "Лист B"
    assert panel.seat_list.item(0).data(Qt.ItemDataRole.CheckStateRole) is None
    assert panel.checked_seat_ids() == [11]
    host.stop_fake()


async def test_clicking_checkbox_and_row_label_drives_seating(qtbot):
    import asyncio

    host = FakeHost(seated=(11,))
    host.start_fake()
    panel = _panel(qtbot, host)
    panel.set_instances([(11, "Лист A"), (12, "Лист B")])

    # клик по строке (её подписи) — текущая строка, чекбокс не тронут
    panel.seat_list.setCurrentRow(0)
    label1 = panel.seat_list.itemWidget(panel.seat_list.item(1)).findChild(QLabel)
    QTest.mouseClick(label1, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert panel.seat_list.currentRow() == 1
    assert host.calls == []

    # клик по свободному чекбоксу сажает и оставляет строку текущей
    QTest.mouseClick(_seat_box(panel, 1), Qt.MouseButton.LeftButton)
    assert host.calls == [("seat", 12)]
    assert panel.seat_list.currentRow() == 1

    # клик по чекнутому снимает посадку: drop_seat уходит в событийный цикл
    QTest.mouseClick(_seat_box(panel, 0), Qt.MouseButton.LeftButton)
    for _ in range(20):
        if ("drop_seat", 11) in host.calls:
            break
        await asyncio.sleep(0)
    assert ("drop_seat", 11) in host.calls
    assert panel.checked_seat_ids() == [12]
    host.stop_fake()


def test_toggle_on_stopped_table_never_reaches_host(qtbot):
    host = FakeHost(seated=(11,))
    panel = _panel(qtbot, host)  # стол не поднят
    panel.set_instances([(11, "Лист A")])
    box = _seat_box(panel, 0)
    assert box.isChecked()  # нарисован по seated, загрузочный огонь съеден гардом

    QTest.mouseClick(box, Qt.MouseButton.LeftButton)
    assert host.calls == []
    assert panel.checked_seat_ids() == []
    QTest.mouseClick(box, Qt.MouseButton.LeftButton)
    assert host.calls == []
    assert panel.checked_seat_ids() == [11]


def test_kick_gate_needs_a_selected_player_on_running_table(qtbot, fake_host):
    panel = _panel(qtbot, fake_host)  # стол не поднята, список пуст
    assert panel.kick_button.isEnabled() is False

    fake_host.start_fake()
    panel.sync_running()
    assert panel.player_list.count() == 0
    assert panel.kick_button.isEnabled() is False  # running, но список пуст

    fake_host.players_list = [(5, "Вася"), (6, "Петя")]
    panel.refresh_players()
    assert panel.kick_button.isEnabled() is False  # running, но игрок не выбран

    panel.player_list.setCurrentRow(1)
    assert panel.kick_button.isEnabled() is True

    # сброс выделения оставляет current row; kick ходит по current row —
    # потому гейт именно на выделении, и кнопка снова гаснет
    panel.player_list.clearSelection()
    assert panel.player_list.currentRow() == 1
    assert panel.kick_button.isEnabled() is False
    fake_host.stop_fake()


async def test_kick_button_click_kicks_exactly_once(qtbot, fake_host):
    import asyncio

    fake_host.players_list = [(5, "Вася"), (6, "Петя")]
    fake_host.start_fake()
    panel = _panel(qtbot, fake_host)
    panel.player_list.setCurrentRow(1)
    assert panel.kick_button.isEnabled()
    kicked: list[int] = []
    panel.kick_requested.connect(kicked.append)

    QTest.mouseClick(panel.kick_button, Qt.MouseButton.LeftButton)
    for _ in range(20):
        if fake_host.calls:
            break
        await asyncio.sleep(0)

    assert [call for call in fake_host.calls if call[0] == "kick"] == [("kick", 6)]
    assert kicked == [6]
    # после пересборки списка выделения нет — кнопка снова выключена
    assert panel.kick_button.isEnabled() is False
    fake_host.stop_fake()


# ── 1.1 the same close through the real main.py wiring ───────────────────────

async def test_x_on_running_panel_stops_the_table_through_wiring(
    app, wait_for, monkeypatch
):
    application, window = app
    application._table_host.set_http(None)
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    panel = application._table_host_panel
    application._table_host.set_seating([1])
    await application._table_host.start(7899)
    panel.sync_running()
    calls = question_yes(monkeypatch)

    panel.close()

    assert calls == [["Стол", "Остановить стол?"]]
    await wait_for(lambda: application._table_host.is_running is False)
    await wait_for(lambda: panel.isVisible() is False)
