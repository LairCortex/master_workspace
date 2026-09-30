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
  what ``format_game_date`` prints) plus the NRI-0023 optional hour tail
  «, HH:00» (spec current-date: minutes are always «:00», an unset hour
  keeps the caption bit-identical to the pre-0023 text);
* the hour half of NRI-0023 task 9.1 — ``hour`` (Python read),
  ``hourOptions``/``selectedHourIndex`` (the neighbor combo's list and
  selection, bounds from ``current_calendar().day_hours``) and
  ``requestHour(index)`` → ``hourChangeRequested``: the VM only asks, the
  wiring's service transaction decides, and the day-only mirrors
  (``coord``/``is_bc``, the one ``nowChanged`` broadcast) NEVER move for an
  hour edit — «час — только подпись» (spec «Час меняет только подпись»);
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

from app.domain.game_calendar import GameCoord, current_calendar
from app.presentation.utils.date_utils import format_game_date, worst_case_date_caption

#: The widget's visible prefix (spec «Виджет „Сейчас: <дата>“ в главном окне»).
NOW_CAPTION_PREFIX = "Сейчас: "

#: Head of the hour list — the empty «час не выставлен» option (spec: the
#: list offers «—» plus ``0 … часовВСуток−1`` of the active calendar).
NOW_HOUR_EMPTY_OPTION = "—"

#: Visible label the hour selector prints before its value (NRI-0023 group 12,
#: design Д14.2, spec current-date «Назначение селектора понятно без выбора»:
#: «Час:» is readable before the very first pick; the LIST rows stay bare
#: numbers — only the closed control's display text carries the label).
NOW_HOUR_SELECTOR_PREFIX = "Час: "


def format_now_hour(hour: int) -> str:
    """The caption tail one «now» hour contributes — «, HH:00», two-digit
    hour with leading zero, minutes always «:00» (spec current-date: the
    widget carries hours only)."""
    return f", {hour:02d}:00"


class NowDateViewModel(QObject):
    """The «now» chip state: caption (date + optional hour), popup request,
    hour-list request, applied-value mirror."""

    captionChanged = Signal()
    #: The one edit broadcast every derived surface subscribes to (design Д2)
    #: — fired only when the DAY (coordinate or era) moved; an hour-only edit
    #: repaints the caption alone and never reaches it (NRI-0023 task 9.1,
    #: spec «Час меняет только подпись»).
    nowChanged = Signal()
    #: Island-local rectangle of the chip; the wiring maps it to global and
    #: opens the game-calendar grid there (pattern of WorldSnapshotViewModel).
    datePopupRequested = Signal(float, float, float, float)
    #: The hour combo asked for its list at this island-local rectangle
    #: (task 12.6, A1 host half of design Д14.1): the search island fixes its
    #: widget to the island's implicit height, so the component's own QML
    #: popup could never show the full list there — the wiring answers with
    #: the widgets-bridge list window, the very route the date chip already
    #: takes (spec qml-shell «Выбор … идёт через widgets-мост»).
    hourPopupRequested = Signal(float, float, float, float)
    #: The neighbor hour combo picked a new hour (``None`` — «—», час снят);
    #: the wiring runs the service transaction and mirrors the result back
    #: through ``applyNow`` (design Д2 keeps the service as the value owner).
    hourChangeRequested = Signal(object)

    def __init__(
        self,
        coord: GameCoord,
        is_bc: bool = False,
        hour: int | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._coord = coord
        self._is_bc = bool(is_bc)
        self._hour = hour

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

    @property
    def hour(self) -> int | None:
        """The served optional hour; ``None`` means «час не выставлен»."""
        return self._hour

    # ── QML-facing surface ──────────────────────────────────────────────────

    def _caption(self) -> str:
        text = NOW_CAPTION_PREFIX + format_game_date(self._coord, is_bc=self._is_bc)
        return text if self._hour is None else text + format_now_hour(self._hour)

    caption = Property(str, _caption, notify=captionChanged)

    #: Width floor for the chip (design F1 convention): the widest caption
    #: the active calendar can print under this very prefix — the VM, not
    #: QML, assembles it so the prefix can never be elided away (the same
    #: formatter ``caption`` runs on). With an hour set the floor carries the
    #: widest hour tail the active day hosts (NRI-0023 task 9.1); without
    #: one it is exactly the pre-0023 floor (spec: «при пустом — выглядеть
    #: ровно как прежде»).
    worstCaseDisplay = Property(
        str,
        lambda self: NOW_CAPTION_PREFIX
        + worst_case_date_caption()
        + (
            ""
            if self._hour is None
            else format_now_hour(current_calendar().day_hours - 1)
        ),
        notify=captionChanged,
    )

    # ── Час «сейчас» (NRI-0023 task 9.1, spec «Виджет „Сейчас: <дата>“») ───
    # The neighbor combo's list and selection; the bounds live in the active
    # calendar (design Д4 — no consumer hardcodes 24). «—» heads the list and
    # the index of hour H is H + 1 (the EventDialog combo pattern of task
    # 7.2), so the hour list survives a day narrowing via the service's own
    # read sanitisation (design Д5).

    hourOptions = Property(
        "QVariant",
        lambda self: [NOW_HOUR_EMPTY_OPTION]
        + [str(hour) for hour in range(current_calendar().day_hours)],
        notify=captionChanged,
    )
    selectedHourIndex = Property(
        int,
        lambda self: 0 if self._hour is None else self._hour + 1,
        notify=captionChanged,
    )
    # Д14.2 (H1): the closed selector explains itself — the display text is
    # «Час: —» / «Час: 14», while the pop-up rows stay the bare numbers of
    # ``hourOptions`` (spec qml-components rows never read «Час: N»).
    hourDisplay = Property(
        str,
        lambda self: NOW_HOUR_SELECTOR_PREFIX
        + (NOW_HOUR_EMPTY_OPTION if self._hour is None else str(self._hour)),
        notify=captionChanged,
    )
    # Д14.3 (H2/A5): the fixed-width hint of the selector (ThemeDateField's
    # worstCaseText convention, VM side of the pair): the widest label the
    # ACTIVE calendar can print («Час: 23» for 24-hour days) — the control
    # keeps this width across «—»/1/23 switches and stops nudging the row.
    worstCaseHourOption = Property(
        str,
        lambda self: NOW_HOUR_SELECTOR_PREFIX
        + str(current_calendar().day_hours - 1),
        notify=captionChanged,
    )

    @Slot(float, float, float, float)
    def requestDatePopup(  # noqa: N802
        self, x: float, y: float, width: float, height: float
    ) -> None:
        self.datePopupRequested.emit(x, y, width, height)

    @Slot(float, float, float, float)
    def requestHourPopup(  # noqa: N802
        self, x: float, y: float, width: float, height: float
    ) -> None:
        """The combo's ask for the hour list, island-local rectangle in, the
        same shape as ``requestDatePopup`` — the VM only forwards, the wiring
        opens the bridge window outside the clipping host."""
        self.hourPopupRequested.emit(x, y, width, height)

    @Slot(int)
    def requestHour(self, index: int) -> None:  # noqa: N802
        """The combo's activation channel: maps the list index onto the hour
        («—» → ``None``), bounds-checked against the ACTIVE calendar — an
        index the current day cannot host is ignored — and asks the wiring
        for the write; the VM never writes itself (design Д2)."""
        if not 0 <= index <= current_calendar().day_hours:
            return
        self.hourChangeRequested.emit(None if index == 0 else index - 1)

    @Slot(object, bool, int)
    def applyNow(  # noqa: N802
        self, coord: GameCoord, is_bc: bool, hour: int | None = None
    ) -> None:
        """Mirror an applied edit: called by the wiring AFTER the service
        transaction committed, never before (a failed write must leave the
        caption at its previous value).  An identical value is silent.  Only
        the day half (coordinate/era) additionally moves the ``nowChanged``
        broadcast — the hour repaints the caption alone (spec «Час меняет
        только подпись»), so no derived surface even re-reads on it."""
        is_bc = bool(is_bc)
        if coord == self._coord and is_bc == self._is_bc and hour == self._hour:
            return
        day_changed = coord != self._coord or is_bc != self._is_bc
        self._coord = coord
        self._is_bc = is_bc
        self._hour = hour
        self.captionChanged.emit()
        if day_changed:
            self.nowChanged.emit()
