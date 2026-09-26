"""Sync view model of the game's «now» widget (NRI-0021 task 3.1, design Д2).

The one presentation carrier of the game date «now»: the composition root
builds it from the loaded :class:`~app.application.services.current_date_service.CurrentDateService`
value, hands it to the search island as the ``nowDateVm`` context property and
to :class:`~app.presentation.wiring.ApplicationWiring` as the popup/write
counterpart.  The widget row itself is a library ``ThemeDateField`` inside the
search island — this VM is the only new binding surface (design Д4; the
spec qml-shell wording «только подпись „сейчас“, сигнал выбора даты и приём
выбранного значения»).

Contract (frozen for the derived surfaces of groups 4–6):

* ``caption`` — the visible chip text «Сейчас: <дата активного календаря с
  эрой>» (era suffix «г. до н.э.», intercalary day by its rule name — exactly
  what ``format_game_date`` prints);
* ``datePopupRequested(x, y, width, height)`` — the chip asked for the
  single-date grid, anchored at this island-local rectangle; QML enters
  through the sync ``requestDatePopup`` slot, the wiring answers the signal
  with the widgets bridge (no ``QML-Popup``, spec qml-shell);
* ``applyNow(coord, is_bc)`` — the applied-value slot: the wiring calls it
  only after the service transaction committed (design Д2 keeps the service
  as the value owner; the VM mirrors it for display and fan-out);
* ``nowChanged`` — the single broadcast channel every derived surface
  (summary, card, event dialog, timeline, snapshot) subscribes to;
* ``coord`` / ``is_bc`` — plain Python reads of the served value for those
  subscribers (duration math needs the coordinate, not the text).

No async here: the write path is the wiring's (session lock, one UoW
transaction); this QObject only formats, requests and mirrors (spec qml-shell
«Sync-вход достаточен»).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal, Slot

from app.domain.game_calendar import GameCoord
from app.presentation.utils.date_utils import format_game_date, worst_case_date_caption

#: The widget's visible prefix (spec «Виджет „Сейчас: <дата>“ в главном окне»).
NOW_CAPTION_PREFIX = "Сейчас: "


class NowDateViewModel(QObject):
    """The «now» chip state: caption, popup request, applied-value mirror."""

    captionChanged = Signal()
    #: The one edit broadcast every derived surface subscribes to (design Д2).
    nowChanged = Signal()
    #: Island-local rectangle of the chip; the wiring maps it to global and
    #: opens the game-calendar grid there (pattern of WorldSnapshotViewModel).
    datePopupRequested = Signal(float, float, float, float)

    def __init__(
        self,
        coord: GameCoord,
        is_bc: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._coord = coord
        self._is_bc = bool(is_bc)

    # ── Python-side reads (the derived surfaces compute durations from the
    # coordinate, not from the caption text) ────────────────────────────────

    @property
    def coord(self) -> GameCoord:
        """The served «now» coordinate of the active calendar."""
        return self._coord

    @property
    def is_bc(self) -> bool:
        """The served era flag (``True`` — «до н.э.»)."""
        return self._is_bc

    # ── QML-facing surface ──────────────────────────────────────────────────

    def _caption(self) -> str:
        return NOW_CAPTION_PREFIX + format_game_date(self._coord, is_bc=self._is_bc)

    caption = Property(str, _caption, notify=captionChanged)

    #: Width floor for the chip (design F1 convention): the widest caption
    #: the active calendar can print under this very prefix — the VM, not
    #: QML, assembles it so the prefix can never be elided away (the same
    #: formatter ``caption`` runs on).
    worstCaseDisplay = Property(
        str, lambda self: NOW_CAPTION_PREFIX + worst_case_date_caption(),
        notify=captionChanged,
    )

    @Slot(float, float, float, float)
    def requestDatePopup(  # noqa: N802
        self, x: float, y: float, width: float, height: float
    ) -> None:
        self.datePopupRequested.emit(x, y, width, height)

    @Slot(object, bool)
    def applyNow(self, coord: GameCoord, is_bc: bool) -> None:  # noqa: N802
        """Mirror an applied edit: called by the wiring AFTER the service
        transaction committed, never before (a failed write must leave the
        caption at its previous value).  An identical value is silent."""
        is_bc = bool(is_bc)
        if coord == self._coord and is_bc == self._is_bc:
            return
        self._coord = coord
        self._is_bc = is_bc
        self.captionChanged.emit()
        self.nowChanged.emit()
