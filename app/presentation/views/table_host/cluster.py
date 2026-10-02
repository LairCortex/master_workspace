"""The live table cluster over the main window's search row (NRI-0024,
task 5.2, design Д3; spec character-sheet-host «Управление столом живо в
шапке главного окна»).

While the table is raised the master keeps control of it from the main
window's top-right corner — in the same band as the game-date chip, i.e.
above the right edge of the search row: the caption «Стол · N игроков»
(opens the desk sheet) and the «Остановить стол» button (stops the service
outright). The cluster lives through any sheet on purpose: the штатная
``WindowModal`` of a sheet blocks EVERY child widget of the main window, and
the only legal way to keep these two controls clickable over the scrim is a
window outside the modal layer. Hence the parentless
``Qt.Tool | FramelessWindowHint | WindowStaysOnTopHint`` + ``WA_ShowWithoutActivating``
— the same parentless-popup pattern the mention popup already ships (rule P3),
raised straight onto the desktop over the sheets.

Positioning is the window's shadow, not a layout row: the cluster re-reads
the search row's global rectangle on the anchor window's Move/Resize and on
its WindowStateChange (minimized → the row is off screen, the cluster hides;
restored → it comes back while the table is still up). Closing the anchor
window takes the cluster down with it — it never outlives the game it shadows.

The caption rides the service's occupancy pushes (join/leave/kick/drop all
notify; ``start`` alone never does, so the composition root calls
:meth:`TableCluster.sync_running` right after a successful start). The desk
click re-enters the connector's one ``open_sheet`` path with the live desk
panel (re-entry raises the live sheet, spec «Глянуть пульт из-под листа»).

Accessibility follows the island convention (AGENTS.md) with the widget-side
means: штатной controls only, role and press owned by the widgets themselves.
Both controls are text buttons — Qt derives their tree name from the caption
(«Стол · N игроков», «Остановить стол» — never re-annotated); the desk caption
adds only the description slot, the hidden meaning of its activation,
«Открывает пульт стола».
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from app.application.services.table_host_service import TableHostService
from app.presentation.theme.catalog import attach_theme

#: Fallback of the inset from the anchor row's right/top edges — the number
#: tokens.json itself carries for space.sm (the SheetFrame fallback pattern).
_EDGE_INSET_FALLBACK_PX = 8

#: The description-slot wording of the desk caption (the fixed-wording
#: convention of the islands; the QML DESCRIPTION_VOCABULARY guard does not
#: reach widget sources, the wording is pinned from the tree here instead).
DESK_DESCRIPTION = "Открывает пульт стола"


def cluster_caption(player_count: int) -> str:
    """The one caption of the desk label (the spec's «Стол · N игроков»)."""
    return f"Стол · {player_count} игроков"


class TableCluster(QWidget):
    """Parentless Tool band shadowing the main window while the table runs."""

    desk_requested = Signal()
    stop_requested = Signal()

    def __init__(
        self,
        host: TableHostService,
        search_row: QWidget,
        theme=None,
    ) -> None:
        # Parentless by design (Д3): a child of MainWindow would sit inside
        # the WindowModal layer and freeze under the first sheet.
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._host = host
        self._row = search_row
        self._theme = theme
        self._inset = self._token_px("space.sm", _EDGE_INSET_FALLBACK_PX)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(self._inset, 2, self._inset, 2)
        # The desk caption is a штатной text button wearing the flat face:
        # role Button, the Press action and the tree name all come from Qt's
        # own button semantics (the convention forbids re-annotating a stock
        # text control; the usage site only states the hidden meaning).
        self.desk_label = QPushButton(cluster_caption(0), self)
        self.desk_label.setObjectName("tableClusterDeskLabel")
        self.desk_label.setFlat(True)
        self.desk_label.setAccessibleDescription(DESK_DESCRIPTION)
        self.desk_label.clicked.connect(self.desk_requested.emit)
        self.stop_button = QPushButton("Остановить стол", self)
        self.stop_button.setObjectName("tableClusterStopButton")
        self.stop_button.clicked.connect(self.stop_requested.emit)
        layout.addWidget(self.desk_label)
        layout.addWidget(self.stop_button)

        if self._theme is not None:
            # The cluster is a chrome root of its own top-level window (the
            # QSS never reaches an unattached parentless widget on its own).
            attach_theme(self, self._theme)
            self._theme.apply()

        # join / leave / kick / drop / stop all push an occupancy notify; the
        # caption count and the «only while the table is up» rule both ride
        # this one slot (start never notifies — main.py syncs it there).
        host.subscribe_occupancy(self.sync_running)
        self._row.window().installEventFilter(self)
        self.sync_running()

    def _token_px(self, key: str, fallback: int) -> int:
        """A size token as integer px; off-skin (D7) the token's own number."""
        tokens = self._theme.tokens if self._theme is not None else None
        if tokens is None:
            return fallback
        return int(tokens[key][self._theme.theme].removesuffix("px"))

    # ── visibility + caption (the «показ только при поднятом столе» rule) ───

    def sync_running(self) -> None:
        """Repaint the count and show/hide from the service's state.

        A minimized anchor window hides the cluster too: its anchor row is
        off screen, a stays-on-top band floating over the desktop would be
        detached from the window it shadows (design Д3's desync risk).
        """
        window = self._row.window()
        if self._host.is_running and not (
            window.windowState() & Qt.WindowState.WindowMinimized
        ):
            self.desk_label.setText(cluster_caption(len(self._host.players())))
            self.show()
            self._reposition()
        else:
            self.hide()

    def _reposition(self) -> None:
        """Pin the cluster's right-top corner over the anchor row's right edge.

        Top-aligned with the row (the game-date chip's band, spec «в одном
        ряду с чипом игровой даты») and right-aligned to it, inset by the
        same space.sm margin on both sides.
        """
        top_right = self._row.mapToGlobal(QPoint(self._row.width(), 0))
        size = self.sizeHint()
        self.move(
            top_right.x() - size.width() - self._inset,
            top_right.y() + self._inset,
        )

    # ── following the anchor window (design Д3) ─────────────────────────────

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt API
        etype = event.type()
        if etype in (QEvent.Type.Move, QEvent.Type.Resize):
            if self.isVisible():
                self._reposition()
        elif etype == QEvent.Type.WindowStateChange:
            # Covers both directions: minimized → the row is off screen;
            # restored → the cluster returns while the table is still up.
            self.sync_running()
        elif etype == QEvent.Type.Close:
            # The cluster is the window's shadow and never outlives it (game
            # switch and exit both pass here through the anchor's closeEvent).
            self.close()
            self.deleteLater()
        return False
