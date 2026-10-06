"""Master «Стол» desk sheet: URLs, QR, PIN, players (design D4).

NRI-0024 (task 5.1, design Д5): the desk lives on the application's sheet
contract — a ``SheetFrame`` named «Стол» shown through the connector's one
``open_sheet`` path. The table session belongs to the service, never to the
container: closing the sheet HIDES the desk only — it stops nothing and asks
nothing (the old «Остановить стол?» closeEvent is abolished, spec
character-sheet-host «Крест при работающем столе»); the explicit
«Остановить стол» button in this desk is the only stop inside the sheet, and
a game switch or exit stops the table unconditionally (main.py). A re-entry
«Стол…» therefore raises the desk over the live service with the current
requisites.
"""
from __future__ import annotations

import asyncio
import io
from collections.abc import Callable, Sequence
from functools import partial

import segno
from PySide6.QtCore import QEvent, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedLayout,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from app.presentation.theme import get_default_theme
from app.presentation.theme.catalog import set_role
from app.presentation.theme.compiler import token_rgb
from app.application.services.table_host_service import (
    EmptySeatingError,
    PortBusyError,
    TableHostService,
)
from app.infrastructure.table_host.http import DEFAULT_PORT
from app.infrastructure.table_host.lan import local_ipv4_addresses
from app.presentation.utils.clipboard_utils import copy_pixmap, copy_text
from app.presentation.views.lucide_icons import (
    ACCENT_INK_TOKEN_KEY,
    lucide_icon,
)
from app.presentation.views.sheet_frame import SheetFrame


def qr_pixmap(url: str, scale: int = 4) -> QPixmap:
    buf = io.BytesIO()
    segno.make(url).save(buf, kind="png", scale=scale)
    pix = QPixmap()
    pix.loadFromData(buf.getvalue())
    return pix


#: Address prefixes of virtual adapters the host enumeration keeps reporting
#: although they are almost always dead for LAN guests (macOS's vmnet shared
#: network lives in 192.168.64.0/24, user request 2026-10-05).  Such an
#: address is neither shown nor encoded into the QR.  The filter lives HERE,
#: not in lan.py: the panel's tests substitute the whole ``list_ipv4``, so
#: the desk's offer is the surface that must never carry a virtual address.
VIRTUAL_SUBNET_PREFIXES: tuple[str, ...] = ("192.168.64.",)


def host_urls(port: int, ipv4: Sequence[str]) -> list[str]:
    non_loop = [
        ip
        for ip in ipv4
        if not ip.startswith("127.")
        and not ip.startswith(VIRTUAL_SUBNET_PREFIXES)
    ]
    urls = [f"http://{ip}:{port}/" for ip in non_loop]
    urls.append(f"http://127.0.0.1:{port}/")
    return urls


#: The ink of the seat tick: the same caption ink the accent fill is read
#: against (``color.accent.fg``, the ink the QSS checked-indicator pairs with
#: the accent background).
SEAT_TICK_TOKEN_KEY = "color.accent.fg"

#: The checkmark legs of the skinned state, one ``(x, y, length, angle)`` per
#: leg in the indicator's fractions — the geometry of the QML library's tick
#: (``ThemeCheckBox.qml`` ``tickLegs``): a short leg running down-right into
#: the elbow and a long leg leaving it up-right, both hanging off their top-
#: left corner.  The QML measures them against the 16 px box, so every number
#: scales with the actual indicator width.
_SEAT_TICK_LEGS: tuple[tuple[float, float, float, float], ...] = (
    (0.18, 0.48, 0.24, 45.0),
    (0.34, 0.52, 0.44, -45.0),
)
_SEAT_TICK_LEG_PX = 2.0  # leg thickness at the 16 px box (geometry, no token)
_SEAT_TICK_BOX_PX = 16.0  # the width the QML fractions were measured against


class TableHostSeatCheck(QCheckBox):
    """A seating row's flag with a visible checkmark (STYLE-FACING, see
    :class:`GameCalendarEraCheck` for the naming contract's precedent).

    Qt QSS draws no tick without bitmap assets, so the compiled sheet gives
    the checked state only the solid accent fill (NRI-0018 Д8) — the desk's
    seating rows therefore ask for MORE than QSS can paint: the user must see
    a tick, not a filled square.  The tick is the widget's own QPainter
    content in :meth:`paintEvent` — two legs of ``color.accent.fg`` over the
    accent fill, the very geometry the QML ``ThemeCheckBox`` draws its
    ``tickLegs`` with; the ink travels the canonical token route (precedent
    ``lucide_icons._ink_for``: the runtime's tokens through ``token_rgb``,
    degrading to the named black the same way, never an invented color).

    The named class is the styling handle for the sheet rule that keeps the
    indicator's frame/fill from tokens (``compile_qss``); the accessibility
    face is stock ``QCheckBox`` untouched (CheckBox role, Press/Toggle, Tab +
    Space — the PR-022 contract).  Off-skin (D7) nothing is drawn on top of
    ``super()`` and the native OS indicator — native tick included — stands
    (ui-widget-catalog «Off-skin не ломается»).
    """

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().paintEvent(event)
        if not self.isChecked():
            return
        runtime = get_default_theme()
        if runtime.tokens is None:
            # Off-skin: super() just painted the native indicator with its
            # native tick — a token-colored leg painted over it would be the
            # invented color D7 forbids.
            return
        rgb = token_rgb(runtime.tokens, runtime.theme, SEAT_TICK_TOKEN_KEY)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        # Qt 6.10's PySide bindings do not expose QStyle::CC_CheckBox /
        # SC_CheckBoxIndicator (the enums ship truncated), so the indicator's
        # box is reconstructed the way the sheet draws it: PM_IndicatorWidth/
        # Height answer the QSS rule's full indicator geometry (16 px + the
        # 1 px border), and ``subcontrol-position: left center`` lands it at
        # the contents rect's left edge, vertically centred.
        style = self.style()
        width = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, option, self)
        height = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight, option, self)
        area = self.contentsRect()
        indicator = QRect(
            area.left(),
            area.top() + (area.height() - height) // 2,
            width,
            height,
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            QColor(*rgb) if rgb is not None else QColor(Qt.GlobalColor.black)
        )
        leg_height = _SEAT_TICK_LEG_PX * indicator.width() / _SEAT_TICK_BOX_PX
        for x_ratio, y_ratio, length_ratio, angle in _SEAT_TICK_LEGS:
            painter.save()
            painter.translate(
                indicator.x() + indicator.width() * x_ratio,
                indicator.y() + indicator.height() * y_ratio,
            )
            painter.rotate(angle)
            painter.drawRect(
                QRectF(0.0, 0.0, indicator.width() * length_ratio, leg_height)
            )
            painter.restore()
        painter.end()


class TableHostPanel(SheetFrame):
    """The table-host desk — a sheet whose close hides it only (Д5)."""

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
        # The frame owns the sheet chrome: header «Стол», the Esc-equal
        # «Закрыть», the stack scrim, the catalog skin (Д1). The desk adds no
        # close behaviour of its own — the prompt of NRI-0016 (TB1) is
        # abolished (NRI-0024 spec «Крест при работающем столе»).
        super().__init__("Стол", parent, theme)
        self._host = host
        self._list_ipv4 = list_ipv4 or local_ipv4_addresses
        # The URL the shown QR encodes (test/observer surface, TB2/TB7).
        self.qr_url: str | None = None
        # NRI-0024 (design Д6): the desk sheet opens at the old panel's size;
        # like every sheet it keeps no placement of its own.
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
        # PR-022 (live raw-дерево 2026-10-04): the seating is a scrollable
        # stack of PLAIN row widgets, not a QListWidget of cell widgets.
        # An item view's accessibility enumeration publishes only its virtual
        # cells (QAccessibleTable), so the row's setItemWidget checkbox never
        # reached the live cocoa tree (AXList→AXRow→AXStaticText, 0 AXCheckBox,
        # action-less AXRow) and sat outside the tab chain — while the
        # offscreen pin, querying the box by POINTER, stayed green on a face
        # AppKit never saw. Plain-widget rows put the real QCheckBox into the
        # panel's own child hierarchy: it projects as a named AXCheckBox,
        # answers Press/Toggle (Qt 6.10 cocoa turns an AXPress on a CheckBox
        # into Toggle — the widget bridge handles both), and Tab/Space reach
        # it. The frame keeps the catalog's list face (the QSS rule reads the
        # uiRole property, not the class).
        self.seat_scroll = QScrollArea(self)
        set_role(self.seat_scroll, "list")
        self.seat_scroll.setWidgetResizable(True)
        self.seat_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # The viewport must not paint its palette Base over the list's themed
        # surface — the surface belongs to the scroll area's own QSS rule.
        self.seat_scroll.viewport().setAutoFillBackground(False)
        self.seat_rows = QWidget()
        self._seat_rows_layout = QVBoxLayout(self.seat_rows)
        self._seat_rows_layout.setContentsMargins(0, 0, 0, 0)
        # The tail stretch keeps rows at their sizeHint when the list is
        # taller than the seating.
        self._seat_rows_layout.addStretch(1)
        self.seat_scroll.setWidget(self.seat_rows)
        # (instance_id, checkbox) per drawn row, in row order — the one seat
        # bookkeeping both checked_seat_ids and the tree-addressing use.
        self._seat_rows: list[tuple[int, QCheckBox]] = []
        self.player_list = QListWidget(self)
        set_role(self.player_list, "list")
        # The compiled sheet paints the ordinary chrome face on every button;
        # only «Открыть стол» opts into the primary face, so its glyph wears
        # the accent.fg caption ink (F2) while the plain buttons' glyphs keep
        # the default fg.primary ink of their captions.
        self.start_button = QPushButton("Открыть стол", self)
        set_role(self.start_button, "primary")
        self.start_button.setIcon(
            lucide_icon("play", ink_token=ACCENT_INK_TOKEN_KEY)
        )
        self.stop_button = QPushButton("Остановить стол", self)
        self.stop_button.setIcon(lucide_icon("circle-stop"))
        self.kick_button = QPushButton("Выгнать", self)
        self.kick_button.setIcon(lucide_icon("user-minus"))
        # User request 2026-10-05: the shown requisites must be TAKEN, not
        # only read — the address goes to the clipboard as text, the QR as an
        # image, both through the app's one clipboard roof (AGENTS principle
        # 2, clipboard_utils).
        self.copy_address_button = QPushButton("Копировать адрес", self)
        self.copy_address_button.setIcon(lucide_icon("copy"))
        self.copy_qr_button = QPushButton("Копировать QR", self)
        self.copy_qr_button.setIcon(lucide_icon("copy"))
        # TB5 (NRI-0016): no QDialog button may swallow Enter from the port
        # field — pressing Return in the panel must never start or stop anything.
        for button in (
            self.start_button,
            self.stop_button,
            self.kick_button,
            self.copy_address_button,
            self.copy_qr_button,
        ):
            button.setDefault(False)
            button.setAutoDefault(False)

        # The desk body is the sheet's content slot: the frame's own layout
        # is zero-margined (header above, content below), the body keeps the
        # insets the retired chrome container carried.
        body = QWidget(self)
        layout = QVBoxLayout(body)
        port_row = QHBoxLayout()
        port_row.addWidget(self.port_label)
        port_row.addWidget(self.port_spin)
        layout.addLayout(port_row)
        layout.addWidget(self.pin_label)
        layout.addWidget(self.urls_label)
        layout.addWidget(self.qr_label)
        # The two copy actions live right with the requisites they read and
        # are gated with them (a copy of a stopped table's stale address is
        # never one click away).
        copy_row = QHBoxLayout()
        copy_row.addWidget(self.copy_address_button)
        copy_row.addWidget(self.copy_qr_button)
        layout.addLayout(copy_row)
        layout.addWidget(self.firewall_label)
        layout.addWidget(QLabel("Посадка", self))
        layout.addWidget(self.seat_scroll, 1)
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
        self.add_content(body, 1)

        self.start_button.clicked.connect(self.start_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.kick_button.clicked.connect(lambda: asyncio.ensure_future(self.kick_selected()))
        self.copy_address_button.clicked.connect(self._on_copy_address)
        self.copy_qr_button.clicked.connect(self._on_copy_qr)
        self.player_list.itemSelectionChanged.connect(self._on_player_click)
        # NRI-0024 (task 5.3, spec character-sheet-host «Повторный клик
        # поднимает живое окно»): a click on the row that is ALREADY current
        # changes no selection, so the selection channel stays silent and the
        # repeat never reaches open_fill. itemClicked is the mouse-only signal
        # that ALWAYS fires; the viewport press filter runs before the list
        # view processes the press (Qt changes the selection first, so the
        # itemPressed/selChanged ordering is unusable), which makes it the one
        # seat that still sees the row current from BEFORE this press. A click
        # whose row already was the pre-press current row is the repeat the
        # spec names — it re-emits so the connector re-opens the SAME instance
        # and the connector's reopen contour raises the live Fill window.
        self.player_list.itemClicked.connect(self._on_player_reclick)
        # TB4 (NRI-0016): the «Выгнать» gate follows the selection here and
        # the running state through sync_running/refresh_players below.
        self.player_list.itemSelectionChanged.connect(self._sync_kick_gate)
        # The pre-press snapshot for the repeat-click recognition above.
        self.player_list.viewport().installEventFilter(self)
        # TB2 (NRI-0016): editing the port before start drops whatever address
        # was shown, so stale requisites of an unstarted table never linger.
        self.port_spin.valueChanged.connect(self._on_port_changed)
        # An occupancy push is also the desk's stop notification: the real
        # service stop clears the room and pushes HERE, so the handler must
        # re-read the running state along with the players — requisites and
        # the copy buttons riding with them come down even when no explicit
        # sync_running follows (the cluster subscribes its sync_running the
        # same way).
        host.subscribe_occupancy(self._on_occupancy)
        self._seats_loading = False
        # NRI-0024 (task 5.3): the row current at the last player-list press —
        # the click-side snapshot that recognises the repeat click.
        self._player_row_before_press: QListWidgetItem | None = None
        self.sync_running()

    def selected_port(self) -> int:
        return int(self.port_spin.value())

    def set_instances(self, rows: Sequence[tuple[int, str]]) -> None:
        # TB3-ремонт (NRI-0016) + PR-022-ремонт: every seating row is a plain
        # child QWidget carrying the row's real QCheckBox — not an item-view
        # cell widget. The checkbox's OWN QAccessible interface (CheckBox role,
        # Press AND Toggle, Space on focus) is what the live tree addresses, so
        # the box must live in the panel's widget hierarchy; the name of the
        # instance is its accessible name right here at the point of
        # application, so the tree can tell WHICH seat a press drives. The
        # visible caption stays the row's own QLabel; a click on it toggles
        # nothing — it is the label, not the control.
        self._seats_loading = True
        for _instance_id, box in self._seat_rows:
            row = box.parentWidget()
            row.setParent(None)
            row.deleteLater()
        self._seat_rows = []
        seated = self._host.seated_ids
        for instance_id, name in rows:
            row = QWidget(self.seat_rows)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 2, 6, 2)
            check = TableHostSeatCheck(row)
            check.setAccessibleName(name)
            # Connected before the initial setChecked below: a loading fire
            # lands on the _seats_loading guard, so a pre-checked row can
            # never re-seat the instance it is drawn for (no recursion).
            check.toggled.connect(partial(self._on_seat_toggled, instance_id))
            row_layout.addWidget(check)
            row_layout.addWidget(QLabel(name, row))
            row_layout.addStretch(1)
            # Insert above the tail stretch — rows keep their top-to-bottom order.
            self._seat_rows_layout.insertWidget(
                self._seat_rows_layout.count() - 1, row
            )
            # Unlike the item view's setIndexWidget (which showed its cell
            # widget itself), a child born after the window is shown stays
            # hidden until asked: the desk is usually refreshed while open
            # (seating pushes repaint the rows), so the row shows here.
            row.show()
            self._seat_rows.append((instance_id, check))
            check.setChecked(instance_id in seated)
        self._seats_loading = False
        # PR-022's keyboard half: Tab must reach the seats in row order
        # between the port spin and the players list — the chain built by
        # creation order would park dynamically born rows at its tail.
        prev: QWidget = self.port_spin
        for _instance_id, check in self._seat_rows:
            QWidget.setTabOrder(prev, check)
            prev = check
        QWidget.setTabOrder(prev, self.player_list)

    def seat_boxes(self) -> list[QCheckBox]:
        """The rows' checkboxes in row order (the tree-addressable face)."""
        return [check for _instance_id, check in self._seat_rows]

    def checked_seat_ids(self) -> list[int]:
        return [
            instance_id
            for instance_id, check in self._seat_rows
            if check.isChecked()
        ]

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
        # urls[0] is the live host: lan.py leads the enumeration with the
        # active (default-route) address and the virtual prefixes are already
        # filtered here; only a loopback-only host leaves the fallback (2026-10-05).
        self.qr_url = urls[0]
        self.urls_label.setText("\n".join(urls))
        self.qr_label.setPixmap(qr_pixmap(urls[0]))

    def _on_port_changed(self, _value: int) -> None:
        self.refresh_urls()

    def _set_requisites_visible(self, visible: bool) -> None:
        for widget in (
            self.pin_label,
            self.urls_label,
            self.qr_label,
            self.copy_address_button,
            self.copy_qr_button,
        ):
            widget.setVisible(visible)

    def _on_copy_address(self) -> None:
        # The desk's own notify channel (show_start_error's QMessageBox) —
        # an unready requisite is announced, never copied as empty garbage.
        if not copy_text(self.qr_url):
            QMessageBox.warning(self, "Стол", "Адрес ещё не готов — копировать нечего.")

    def _on_copy_qr(self) -> None:
        if not copy_pixmap(self.qr_label.pixmap()):
            QMessageBox.warning(self, "Стол", "QR-код ещё не готов — копировать нечего.")

    def _on_occupancy(self) -> None:
        # The one subscriber of the service: players AND the running gate ride
        # every push, so a stopped table never leaves live requisites — nor a
        # live copy button — standing in a closed desk.
        self.refresh_players()
        self.sync_running()

    def refresh_players(self) -> None:
        self.player_list.clear()
        # The rows are being replaced; a pre-press snapshot of a dead row
        # must never meet the next click (NRI-0024 task 5.3).
        self._player_row_before_press = None
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

    def _on_player_click(self) -> None:
        item = self.player_list.currentItem()
        if item is None:
            return
        instance_id = item.data(Qt.ItemDataRole.UserRole)
        if instance_id is not None:
            self.player_selected.emit(int(instance_id))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt API
        # NRI-0024 (task 5.3): the player viewport sees this press BEFORE the
        # view moves the selection (and before itemPressed), so it is the only
        # seat that records the row the click is about to land on top of. The
        # filter watches, never consumes — every other mouse route is Qt's.
        if (
            obj is self.player_list.viewport()
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            self._player_row_before_press = self.player_list.currentItem()
        return super().eventFilter(obj, event)

    def _on_player_reclick(self, item: QListWidgetItem) -> None:
        # The repeat itself (spec «Повторный клик поднимает живое окно»): the
        # click hit the row that was already current at press, so the
        # selection channel stayed silent and this is the single emission.
        # It rides the same connector route as any click — open_fill sees the
        # same instance and raises the live Fill window, no second one. A
        # click that DID move the selection was already emitted by the
        # selection slot; the snapshot tells it apart from the repeat.
        if item is self._player_row_before_press:
            self._player_row_before_press = None
            self._on_player_click()

    def _on_seat_toggled(self, instance_id: int, checked: bool) -> None:
        # The old itemChanged contract, guard included: reloading the list or
        # toggling while the table is stopped must not reach the host.
        if self._seats_loading or not self._host.is_running:
            return
        if checked:
            self._host.seat(instance_id)
        else:
            asyncio.ensure_future(self._host.drop_seat(instance_id))

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
