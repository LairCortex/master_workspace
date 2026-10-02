"""World snapshot QML island behind the existing panel facade."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.island import IslandDialogMixin, QML_IMPORT_PATH
from app.presentation.qml.tooltip_shim import install_island_tooltips
from app.presentation.theme import get_default_theme
from app.presentation.viewmodels.world_snapshot_view_model import (
    WorldSnapshotViewModel,
)
from app.presentation.views.sheet_frame import SheetFrame
from app.presentation.views.theme_date_popup import ThemeDatePopup


ROOT_QML = str(Path(QML_IMPORT_PATH) / "WorldSnapshotRoot.qml")


def _colored_circle(color: QColor, size: int = 16) -> QIcon:
    """Compatibility helper retained for callers that build legend icons."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pixmap)


class WorldSnapshotWidget(IslandDialogMixin, QWidget):
    """Thin shared-engine island preserving the original wiring surface."""

    island_context_names = {"worldSnapshotVm": "vm"}

    entity_clicked = Signal(str, int)
    snapshot_requested = Signal(object)

    def __init__(
        self,
        parent: QWidget | None = None,
        theme=None,
        now_date_vm=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme if theme is not None else get_default_theme()
        # NRI-0021 task 6.2 (design Д5): the game's «now» VM joins the Python
        # VM only (island context stays minimal — worldSnapshotVm + palette,
        # spec qml-shell); the field starts at «now» and «Сброс» returns to it.
        self.vm = WorldSnapshotViewModel(
            self._theme, now_vm=now_date_vm, parent=self
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Panel-owned private context (IslandDialogMixin): neither the VM nor
        # the token bridge touches the shared engine root context.
        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        self.setup_island()
        layout.addWidget(self.quick)

        # P3 (NRI-0015): parent-less — this panel sits under the chrome-attached
        # central widget, whose generic QPushButton rule would accent-fill every
        # day cell through the stylesheet parent chain; popup sheet only.
        self.date_popup = ThemeDatePopup()
        self.date_popup.date_selected.connect(self.vm.set_date)
        self.vm.datePopupRequested.connect(self._open_date_popup)
        self.vm.snapshotRequested.connect(self.snapshot_requested.emit)
        self.vm.entitySelected.connect(self.entity_clicked.emit)

    def island_source(self) -> str:
        return ROOT_QML

    def _release_island(self) -> None:
        # DEFECT-1 (NRI-0016): the VM is parented into the island context,
        # so it leaves with the island while its wrapper lives here — the
        # theme subscription must not outlive the closed panel (spec
        # app-logging «Слушатели состояния не переживают окно»).
        self.vm.detach_theme_listener()
        super()._release_island()

    def load_island_scene(self, quick) -> None:
        # The bridge and the VM must be in the context BEFORE the scene
        # compiles (hand-written order preserved): both are raw context
        # pointers, and the VM is adopted under the context so the scene
        # (created before it) dies first at child destruction.
        self.vm.setParent(self._context)
        self._tooltip_bridge = install_island_tooltips(quick, self._context)
        super().load_island_scene(quick)

    def populate(
        self,
        events: Sequence[Any],
        for_date: Any,
        event_names: Mapping[int, str] | None = None,
    ) -> None:
        # ``for_date`` is the snapshot bridge payload: a (coordinate, era)
        # pair since piece C3a (a bare date or None stay legal) — the ViewModel
        # splits it. ``event_names`` (NRI-0023 task 8.3) is the wiring's
        # id → имя card the orphan stubs read the parent's name from.
        self.vm.populate(events, for_date, event_names)

    def _open_date_popup(
        self, x: float, y: float, width: float, height: float
    ) -> None:
        top_left = self.quick.mapToGlobal(QPoint(int(x), int(y)))
        anchor = QRect(
            top_left,
            QSize(max(int(width), 0), max(int(height), 0)),
        )
        # Since piece C3b (design D3) the popup grid paints the snapshot's
        # coordinate itself (intercalary chip included) — the picture-only
        # clamp of piece C3a died with the Gregorian widget, so the bridge
        # carries the coordinate pair as stored.
        self.date_popup.open_at(anchor, (self.vm._date, self.vm._date_bc))

    def _on_clear(self) -> None:
        self.vm.clear()

    # Island lifecycle (context, deferred closeEvent release) — IslandDialogMixin.


class WorldSnapshotWindow(SheetFrame):
    """The «Обзор мира» sheet: the panel's home (NRI-0022 task 2.1; the
    sheet format since NRI-0024 task 2.4, design Д1/Д6).

    spec world-snapshot «Обзор мира открывается листом из строки меню»: the
    content that used to live in a non-modal window of its own now rides the
    application's sheet contract — ``SheetFrame`` carries the header
    «Обзор мира + Закрыть» (one windowTitle-threaded caption, the frame's
    button the plain Esc cancel) and the stack scrim the connector dims
    through, and ``ApplicationWiring.open_sheet`` owns the show
    (WindowModal over the main window, the single ``finished`` release). The
    panel itself (island, VM, signals, the ListView scroll machinery) is
    untouched; the wrapper hosts it in the frame's content slot, releases
    the island on the way out, and never remembers a placement — a sheet
    always opens at its default (spec «Лист не помнит рамку»).
    """

    #: Sheet default (design Д6): 520×760 — the value at the default main
    #: window (1280×800, NRI-0018 Д5) under the growth rule below.
    DEFAULT_SIZE = QSize(520, 760)
    #: One shared usability floor, the value the retired splitter pane kept.
    MIN_SIZE = QSize(220, 300)
    #: The growth rule's breathing room (spec modal-sheets «Окно растёт —
    #: лист догоняет до предела»): the sheet's height tracks its parent
    #: window's minus this inset, floored at MIN_SIZE and capped at the
    #: default — the default IS the rule's value at the default 800 px
    #: window, so a sheet opened over a default-sized window never moves.
    HEIGHT_INSET = 40

    def __init__(
        self,
        parent: QWidget | None = None,
        theme=None,
        now_date_vm=None,
    ) -> None:
        # One windowTitle-threaded value: SheetFrame puts the same caption
        # into the header label and the title slot.
        super().__init__("Обзор мира", parent, theme)
        self.setMinimumSize(self.MIN_SIZE)
        self.resize(self.DEFAULT_SIZE)

        self.snapshot = WorldSnapshotWidget(
            theme=theme, now_date_vm=now_date_vm
        )
        self.add_content(self.snapshot)

        if parent is not None:
            # The growth half of the contract: the sheet follows its host
            # window's resizes while it is open (the filter object dies with
            # the sheet, so it can never outlive this wrapper).
            parent.installEventFilter(self)

    # ── рост с окном-родителем (spec modal-sheets «Листы не помнят
    # размещение»: fixed default, growth to the content's limit, scroll) ────

    def showEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().showEvent(event)
        self._fit_height_to_parent()

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802 — Qt API
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._fit_height_to_parent()
        return super().eventFilter(watched, event)

    def _fit_height_to_parent(self) -> None:
        """Track the host window's height: shrink with a smaller window,
        grow back to the default with a bigger one; never below the
        usability floor. Width is the sheet's own 520 default (the main
        window's 1024 floor never squeezes it)."""
        host = self.parentWidget()
        if host is None:  # a parent-less sheet (offscreen probes) keeps its size
            return
        height = min(
            self.DEFAULT_SIZE.height(),
            max(self.MIN_SIZE.height(), host.height() - self.HEIGHT_INSET),
        )
        if height != self.height():
            self.resize(self.width(), height)

    def done(self, result: int) -> None:  # noqa: N802 — Qt API name
        # Every way this dialog leaves the screen (the header's «Закрыть» or
        # Esc through reject, a programmatic close()) passes through done().
        # The growth filter leaves with the sheet — a closed layer has no
        # business tracking window resizes anymore. The panel is a child
        # widget: closing the sheet never reaches its closeEvent, so the
        # home releases its island here — one loop turn deferred, exactly
        # the contract IslandDialogMixin pins for an owned island (the
        # release must not run inside a QML handler), and idempotent on a
        # dead island.
        host = self.parentWidget()
        if host is not None:
            host.removeEventFilter(self)
        QTimer.singleShot(0, self.snapshot, self.snapshot.release_island)
        super().done(result)
