"""The live table cluster docked into the main window (was NRI-0024 task 5.2,
design Д3's parentless Tool band; the owner ruling 2026-10-05 re-docked it —
the character-sheet-host spec «Управление столом живо в шапке главного окна»
is retouched by the next change).

While the table is raised the master keeps control of it from the same place
as before — at the right end of the search row's band, above the columns —
but no longer from a floating window: the cluster is a CHILD panel of the
main window, occupying its own layout row between the search bar and the
splitter (``MainWindow.attach_table_cluster``). The deliberate trade of the
re-dock, accepted by the owner: under an open sheet the panel stays VISIBLE
but unclickable — the sheet's block covers the whole window content layer,
and this panel is part of that layer now.

Placement is the window's layout, not a positioning shadow: the controls
hug the row's right end through the layout's leading stretch, the height is
fixed (vertical policy ``Fixed`` — a window resize never stretches the band,
the splitter absorbs the surplus), and a stopped table reserves no strip at
all: the panel manages its own visibility, and a hidden widget takes neither
height nor spacing in a box layout.

The caption rides the service's occupancy pushes (join/leave/kick/drop all
notify; ``start`` alone never does, so the composition root calls
:meth:`TableCluster.sync_running` right after a successful start). The desk
click re-enters the connector's one ``open_sheet`` path with the live desk
panel (re-entry raises the live sheet) whenever no sheet covers the window;
the stop button rides the very locked stop the desk button uses.

Theming: as a child of the ``#themeChrome`` central container the panel is
skinned by the window's own QSS — the compiler addresses chrome buttons as
``QWidget[uiRole="chrome"] QPushButton`` (a descendant selector reaching
this subtree), so the cluster is no longer a chrome root and never calls
``attach_theme``. Only the token insets still read the runtime directly.

Accessibility follows the island convention (AGENTS.md) with the widget-side
means: штатной controls only, role and press owned by the widgets themselves.
Both controls are text buttons — Qt derives their tree name from the caption
(«Стол · N игроков», «Остановить стол» — never re-annotated); the desk caption
adds only the description slot, the hidden meaning of its activation,
«Открывает пульт стола».
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from app.application.services.table_host_service import TableHostService

#: Fallback of the inset from the band's right edge — the number
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
    """Child panel of the main window, visible only while the table runs."""

    desk_requested = Signal()
    stop_requested = Signal()

    def __init__(
        self,
        host: TableHostService,
        parent: QWidget,
        theme=None,
    ) -> None:
        # A plain child — the floating Tool posture of design Д3 is retired:
        # the desk controls live inside the window's content layer now and
        # ride its sheet-stack block like every other child.
        super().__init__(parent)
        self._host = host
        self._theme = theme
        inset = self._token_px("space.sm", _EDGE_INSET_FALLBACK_PX)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(inset, 2, inset, 2)
        # The leading stretch keeps the row's full width with the controls at
        # its right end and natural width: the panel sits where the floating
        # band used to shadow — above the right edge of the search row.
        layout.addStretch(1)
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

        # Fixed height: sizeHint is the only acceptable height, so neither a
        # window resize nor a layout surplus ever stretches the band.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        # join / leave / kick / drop / stop all push an occupancy notify; the
        # caption count and the «only while the table is up» rule both ride
        # this one slot (start never notifies — main.py syncs it there).
        host.subscribe_occupancy(self.sync_running)
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

        The panel is the row's only visibility source: hidden, it reserves
        neither height nor spacing, so the stopped table leaves no empty
        strip between the search bar and the columns.
        """
        if self._host.is_running:
            self.desk_label.setText(cluster_caption(len(self._host.players())))
            self.show()
        else:
            self.hide()
