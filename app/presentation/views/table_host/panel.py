"""Master «Стол» panel: URLs, QR, PIN, players (design D4)."""
from __future__ import annotations

import asyncio
import io
from collections.abc import Callable, Sequence

import segno
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
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
        self.setWindowTitle("Стол")
        self.resize(420, 560)

        self.port_spin = QSpinBox(self)
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(DEFAULT_PORT)
        self.pin_label = QLabel("PIN: —", self)
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
        self.player_list = QListWidget(self)
        set_role(self.seat_list, "list")
        set_role(self.player_list, "list")
        self.start_button = QPushButton("Открыть стол", self)
        self.stop_button = QPushButton("Остановить", self)
        self.kick_button = QPushButton("Выгнать", self)

        outer = QVBoxLayout(self)
        # The chrome reaches the dialog edges so no OS-palette band frames it.
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.chrome = QWidget()
        self.chrome.setObjectName("tableHostChrome")  # identifier, not style
        outer.addWidget(self.chrome)
        layout = QVBoxLayout(self.chrome)
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Порт", self))
        port_row.addWidget(self.port_spin)
        layout.addLayout(port_row)
        layout.addWidget(self.pin_label)
        layout.addWidget(self.urls_label)
        layout.addWidget(self.qr_label)
        layout.addWidget(self.firewall_label)
        layout.addWidget(QLabel("Посадка", self))
        layout.addWidget(self.seat_list, 1)
        layout.addWidget(QLabel("Игроки", self))
        layout.addWidget(self.player_list, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.kick_button)
        layout.addLayout(buttons)

        self.start_button.clicked.connect(self.start_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.kick_button.clicked.connect(lambda: asyncio.ensure_future(self.kick_selected()))
        self.player_list.itemSelectionChanged.connect(self._on_player_click)
        self.seat_list.itemChanged.connect(self._on_seat_item_changed)
        host.subscribe_occupancy(self.refresh_players)
        self._seats_loading = False
        self.refresh_urls()
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
        self._seats_loading = True
        self.seat_list.clear()
        seated = self._host.seated_ids
        for instance_id, name in rows:
            item = QListWidgetItem(name, self.seat_list)
            item.setData(Qt.ItemDataRole.UserRole, instance_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if instance_id in seated else Qt.CheckState.Unchecked
            )
        self._seats_loading = False

    def checked_seat_ids(self) -> list[int]:
        ids: list[int] = []
        for i in range(self.seat_list.count()):
            item = self.seat_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                ids.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return ids

    def refresh_urls(self) -> None:
        port = self._host.port if self._host.is_running else self.selected_port()
        urls = host_urls(port, self._list_ipv4())
        self.urls_label.setText("\n".join(urls))
        self.qr_label.setPixmap(qr_pixmap(urls[0]))

    def refresh_players(self) -> None:
        self.player_list.clear()
        for instance_id, name in self._host.players():
            item = QListWidgetItem(name, self.player_list)
            item.setData(Qt.ItemDataRole.UserRole, instance_id)

    def sync_running(self) -> None:
        running = self._host.is_running
        self.port_spin.setEnabled(not running)
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.kick_button.setEnabled(running)
        pin = self._host.pin if running else None
        self.pin_label.setText("PIN: " + (pin if pin else "—"))
        self.refresh_urls()
        self.refresh_players()

    def _on_player_click(self) -> None:
        item = self.player_list.currentItem()
        if item is None:
            return
        instance_id = item.data(Qt.ItemDataRole.UserRole)
        if instance_id is not None:
            self.player_selected.emit(int(instance_id))

    def _on_seat_item_changed(self, item: QListWidgetItem) -> None:
        if self._seats_loading or not self._host.is_running:
            return
        instance_id = item.data(Qt.ItemDataRole.UserRole)
        if instance_id is None:
            return
        iid = int(instance_id)
        if item.checkState() == Qt.CheckState.Checked:
            self._host.seat(iid)
        else:
            asyncio.ensure_future(self._host.drop_seat(iid))

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
