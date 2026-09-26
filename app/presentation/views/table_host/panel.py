"""Master «Стол» panel: URLs, QR, PIN, players (design D4)."""
from __future__ import annotations

import asyncio
import io
from collections.abc import Callable, Sequence
from functools import partial

import segno
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from app.presentation.theme.catalog import attach_theme, set_role
from app.application.services.table_host_service import (
    EmptySeatingError,
    PortBusyError,
    TableHostService,
)
from app.infrastructure.table_host.http import DEFAULT_PORT
from app.infrastructure.table_host.lan import local_ipv4_addresses


def qr_pixmap(url: str, scale: int = 4) -> QPixmap:
    buf = io.BytesIO()
    segno.make(url).save(buf, kind="png", scale=scale)
    pix = QPixmap()
    pix.loadFromData(buf.getvalue())
    return pix


def host_urls(port: int, ipv4: Sequence[str]) -> list[str]:
    non_loop = [ip for ip in ipv4 if not ip.startswith("127.")]
    urls = [f"http://{ip}:{port}/" for ip in non_loop]
    urls.append(f"http://127.0.0.1:{port}/")
    return urls


class TableHostPanel(QDialog):
    """Non-modal table-host controls."""

    start_requested = Signal()
    stop_requested = Signal()
    player_selected = Signal(int)
    kick_requested = Signal(int)

    def __init__(
        self,
        host: TableHostService,
        parent: QWidget | None = None,
        list_ipv4: Callable[[], list[str]] | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._theme = theme
        self._list_ipv4 = list_ipv4 or local_ipv4_addresses
        # NRI-0016 (TB1): close-while-running flow. ``_stopping`` — the user
        # confirmed «Остановить стол?» and the panel waits for the stop signal
        # to finish closing; ``_force_closing`` — programmatic close (game
        # switch / shutdown), which never asks.
        self._stopping = False
        self._force_closing = False
        # The URL the shown QR encodes (test/observer surface, TB2/TB7).
        self.qr_url: str | None = None
        self.setWindowTitle("Стол")
        self.resize(440, 560)

        self.port_label = QLabel("Порт:", self)
        self.port_spin = QSpinBox(self)
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(DEFAULT_PORT)
        self.pin_label = QLabel("PIN: —", self)
        self.pin_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.urls_label = QLabel(self)
        self.urls_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.urls_label.setWordWrap(True)
        self.qr_label = QLabel(self)
        self.qr_label.setMinimumSize(160, 160)
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.firewall_label = QLabel(
            "Разрешите порт в брандмауэре, если игроки не подключаются.",
            self,
        )
        self.firewall_label.setWordWrap(True)
        self.seat_list = QListWidget(self)
        set_role(self.seat_list, "list")
        self.player_list = QListWidget(self)
        set_role(self.player_list, "list")
        self.start_button = QPushButton("Открыть стол", self)
        self.stop_button = QPushButton("Остановить", self)
        self.kick_button = QPushButton("Выгнать", self)
        # TB5 (NRI-0016): no QDialog button may swallow Enter from the port
        # field — pressing Return in the panel must never start or stop anything.
        for button in (self.start_button, self.stop_button, self.kick_button):
            button.setDefault(False)
            button.setAutoDefault(False)

        outer = QVBoxLayout(self)
        # The chrome reaches the dialog edges so no OS-palette band frames it.
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.chrome = QWidget()
        self.chrome.setObjectName("tableHostChrome")  # identifier, not style
        outer.addWidget(self.chrome)
        layout = QVBoxLayout(self.chrome)
        port_row = QHBoxLayout()
        port_row.addWidget(self.port_label)
        port_row.addWidget(self.port_spin)
        layout.addLayout(port_row)
        layout.addWidget(self.pin_label)
        layout.addWidget(self.urls_label)
        layout.addWidget(self.qr_label)
        layout.addWidget(self.firewall_label)
        layout.addWidget(QLabel("Посадка", self))
        layout.addWidget(self.seat_list, 1)
        layout.addWidget(QLabel("Игроки", self))
        # TB7 (NRI-0016): an empty players list carries a hint instead of an
        # unexplained blank — the label stacks over the list, never stealing
        # its mouse events, and only shows while the list is empty.
        self.players_box = QWidget(self)
        players_stack = QStackedLayout(self.players_box)
        players_stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.player_placeholder = QLabel("Пока никто не вошёл.", self.players_box)
        self.player_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.player_placeholder.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        players_stack.addWidget(self.player_list)
        players_stack.addWidget(self.player_placeholder)
        self.player_placeholder.setVisible(False)
        layout.addWidget(self.players_box, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.kick_button)
        layout.addLayout(buttons)

        self.start_button.clicked.connect(self.start_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.kick_button.clicked.connect(lambda: asyncio.ensure_future(self.kick_selected()))
        self.player_list.itemSelectionChanged.connect(self._on_player_click)
        # TB4 (NRI-0016): the «Выгнать» gate follows the selection here and
        # the running state through sync_running/refresh_players below.
        self.player_list.itemSelectionChanged.connect(self._sync_kick_gate)
        # TB2 (NRI-0016): editing the port before start drops whatever address
        # was shown, so stale requisites of an unstarted table never linger.
        self.port_spin.valueChanged.connect(self._on_port_changed)
        host.subscribe_occupancy(self.refresh_players)
        self._seats_loading = False
        self.sync_running()
        self._apply_theme()

    def _apply_theme(self) -> None:
        """One attach point: the chrome container carries the whole sheet (D1)."""
        if self._theme is not None:
            attach_theme(self.chrome, self._theme)
            self._theme.apply()

    def selected_port(self) -> int:
        return int(self.port_spin.value())

    def set_instances(self, rows: Sequence[tuple[int, str]]) -> None:
        # TB3-ремонт (NRI-0016): a real QCheckBox in a row widget replaces the
        # ItemIsUserCheckable hint — an accessibility tool can press an actual
        # checkbox, not an item decoration. The name stays a plain QLabel, so
        # a click on it keeps reaching the viewport and selecting the row.
        self._seats_loading = True
        self.seat_list.clear()
        seated = self._host.seated_ids
        for instance_id, name in rows:
            # Live re-audit (2026-09-25): a text-bearing item paints its own
            # text *behind* the transparent row widget — the name showed up
            # doubled under the checkbox row. The row keeps the name for
            # accessibility through AccessibleTextRole (QAccessibleTableCell
            # reads it before DisplayRole; the delegate never paints it).
            item = QListWidgetItem("", self.seat_list)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, name)
            item.setData(Qt.ItemDataRole.UserRole, instance_id)
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(6, 2, 6, 2)
            check = QCheckBox(row_widget)
            # Connected before the initial setChecked below: a loading fire
            # lands on the _seats_loading guard, so a pre-checked row can
            # never re-seat the instance it is drawn for (no recursion).
            check.toggled.connect(partial(self._on_seat_toggled, instance_id))
            check.pressed.connect(partial(self._on_seat_row_pressed, item))
            row_layout.addWidget(check)
            row_layout.addWidget(QLabel(name, row_widget))
            row_layout.addStretch(1)
            self.seat_list.setItemWidget(item, row_widget)
            item.setSizeHint(row_widget.sizeHint())
            check.setChecked(instance_id in seated)
        self._seats_loading = False

    def checked_seat_ids(self) -> list[int]:
        ids: list[int] = []
        for i in range(self.seat_list.count()):
            item = self.seat_list.item(i)
            check = self.seat_list.itemWidget(item).findChild(QCheckBox)
            if check.isChecked():
                ids.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return ids

    def refresh_urls(self) -> None:
        # TB2 (NRI-0016): the address requisites exist only for a running
        # table — before start (and after stop) they are wiped, so the shown
        # addresses always carry the actual host port.
        if not self._host.is_running:
            self.qr_url = None
            self.urls_label.clear()
            self.qr_label.clear()
            return
        urls = host_urls(self._host.port, self._list_ipv4())
        self.qr_url = urls[0]
        self.urls_label.setText("\n".join(urls))
        self.qr_label.setPixmap(qr_pixmap(urls[0]))

    def _on_port_changed(self, _value: int) -> None:
        self.refresh_urls()

    def _set_requisites_visible(self, visible: bool) -> None:
        for widget in (self.pin_label, self.urls_label, self.qr_label):
            widget.setVisible(visible)

    def refresh_players(self) -> None:
        self.player_list.clear()
        for instance_id, name in self._host.players():
            item = QListWidgetItem(name, self.player_list)
            item.setData(Qt.ItemDataRole.UserRole, instance_id)
        self.player_placeholder.setVisible(self.player_list.count() == 0)
        # Rebuilding the rows drops the current row, so the kick gate is
        # re-evaluated here too (TB4: no selection, no enabled button).
        self._sync_kick_gate()

    def sync_running(self) -> None:
        running = self._host.is_running
        self.port_spin.setEnabled(not running)
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        pin = self._host.pin if running else None
        self.pin_label.setText("PIN: " + (pin if pin else "—"))
        self._set_requisites_visible(running)
        self.refresh_urls()
        self.refresh_players()
        if self._stopping and not running:
            # TB1: the confirmed stop finished (this sync is the stop signal),
            # so the pending close proceeds without asking a second time.
            self._stopping = False
            self.close()

    def _on_player_click(self) -> None:
        item = self.player_list.currentItem()
        if item is None:
            return
        instance_id = item.data(Qt.ItemDataRole.UserRole)
        if instance_id is not None:
            self.player_selected.emit(int(instance_id))

    def _on_seat_toggled(self, instance_id: int, checked: bool) -> None:
        # The old itemChanged contract, guard included: reloading the list or
        # toggling while the table is stopped must not reach the host.
        if self._seats_loading or not self._host.is_running:
            return
        if checked:
            self._host.seat(instance_id)
        else:
            asyncio.ensure_future(self._host.drop_seat(instance_id))

    def _on_seat_row_pressed(
        self, item: QListWidgetItem, _pressed: bool = False
    ) -> None:
        # The checkbox swallows the press that used to land on the viewport;
        # a press on the row still makes it the current row, mouse-wise as
        # before (the label and the free row area propagate on their own).
        self.seat_list.setCurrentItem(item)

    def _sync_kick_gate(self) -> None:
        # TB4 (NRI-0016): «Выгнать» is actionable only for a running table
        # with a selected player — an inactive button beats a silent click.
        # A selection (not a bare currentRow) is the gate: deselecting keeps
        # the current row, and kick_selected follows the current row, so an
        # enabled button without a visible selection would kick a ghost.
        self.kick_button.setEnabled(
            self._host.is_running and bool(self.player_list.selectedItems())
        )

    async def kick_selected(self) -> None:
        item = self.player_list.currentItem()
        if item is None:
            return
        instance_id = item.data(Qt.ItemDataRole.UserRole)
        if instance_id is None:
            return
        await self._host.kick(int(instance_id))
        self.kick_requested.emit(int(instance_id))
        self.refresh_players()

    def show_start_error(self, exc: Exception) -> None:
        if isinstance(exc, (EmptySeatingError, PortBusyError)):
            QMessageBox.warning(self, "Стол", str(exc))
        else:
            QMessageBox.critical(self, "Стол", str(exc))

    def force_close(self) -> None:
        """Close without the running-table prompt (shutdown / game switch)."""
        self._force_closing = True
        try:
            self.close()
        finally:
            self._force_closing = False

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API
        # TB1 (NRI-0016): an X on a running table stops it first, through the
        # existing stop_requested contour (the panel never touches the
        # service); the deferred close lands in sync_running when the stop
        # signal arrives. Declining leaves both the table and the panel alone.
        if self._stopping or self._force_closing or not self._host.is_running:
            super().closeEvent(event)
            return
        answer = QMessageBox.question(
            self,
            "Стол",
            "Остановить стол?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,  # default «Нет» (spec)
        )
        if answer != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        event.ignore()
        self._stopping = True
        self.stop_requested.emit()
