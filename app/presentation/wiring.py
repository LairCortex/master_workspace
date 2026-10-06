"""Main-window signal wiring — thin glue between UI signals and services.

Moved 1:1 from ``Application._wire_signals`` (the "glue layer"): Qt signals
+ ``asyncio.ensure_future`` mechanism preserved, handlers only unpack dialog
data, call the services, and refresh the panels.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox

from app.application.services.current_date_service import CurrentDateService
from app.application.services.event_service import EventService
from app.application.services.preview_pins_service import PreviewPinsService
from app.application.services.xlsx_import_service import XlsxImportService
from app.domain import entity_registry
from app.domain.date_era import era_key
from app.infrastructure.db.uow import GameSessionUoW
from app.presentation.bundle_resources import bundle_resource_path
from app.presentation.dialog_results import (
    EntityCreateResult,
    EntityEditResult,
    EventDialogResult,
    EventEditResult,
)
from app.presentation.utils.date_utils import split_date_era
from app.presentation.viewmodels.detail_viewmodel import DetailViewModel
from app.presentation.viewmodels.entity_preview_view_model import MAX_PINNED_CARDS
from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.viewmodels.world_snapshot_view_model import (
    SUPPORTED_ENTITY_TYPES,
)
from app.presentation.views.doc_viewer_dialog import DocViewerDialog
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.event_types_dialog import EventTypesDialog
from app.presentation.views.theme_date_popup import ThemeDatePopup
from app.presentation.views.theme_hour_popup import ThemeHourPopup
from app.presentation.views.world_snapshot_widget import WorldSnapshotWindow
from app.presentation.views.xlsx_import_dialog import XlsxImportDialog, save_template_as

# NRI-0014 task 4.3 (CR5), the sheet-stack dim: every sheet opened over a
# parent sheet adds this share to the parent's color.scrim overlay alpha —
# «лист под ним явно темнее», a deeper layer darkens by one share more than
# the layer above it. The cap keeps even a deeply covered sheet readable (the
# dim is a depth cue, never a black wall). This is the one owner of the depth
# arithmetic (design D3): the palette only carries the dim COLOR (qml_palette),
# the islands only paint the alpha they are handed, and no second place
# counts sheets.
SHEET_SCRIM_ALPHA_PER_SHEET = 0.25
SHEET_SCRIM_ALPHA_MAX = 0.75

class ApplicationWiring(QObject):
    """Connects main-window signals to services/viewmodels.

    ``app`` is the owning Application (session + service catalog + dialog
    mention/AI helpers); everything else is the window's component set.
    """

    #: NRI-0024 (task 1.1, design Д2): this connector opens every sheet of
    #: the application, so it owns the open-sheet stack and announces it —
    #: True the moment the first sheet covers the main window, False when the
    #: last one leaves. The main window turns this into the menu gate (its
    #: sheet-opening entries live only while the stack is empty), which is
    #: why no sheet needs a "single instance" window bookkeeping anymore.
    sheet_stack_changed = Signal(bool)

    def __init__(
        self,
        app,
        window,
        timeline_vm,
        detail_vm,
        search_vm,
        event_dialog_vm,
        event_service: EventService,
        uow: GameSessionUoW,
        current_date_service: CurrentDateService | None = None,
        now_date_vm=None,
        preview_pins_service: PreviewPinsService | None = None,
    ) -> None:
        super().__init__()
        self._app = app
        self._window = window
        self._timeline_vm = timeline_vm
        self._detail_vm = detail_vm
        self._search_vm = search_vm
        self._event_dialog_vm = event_dialog_vm
        self._event_service = event_service
        # NRI-0021 (task 2.3, design Д2): the game's «now» holder loaded by
        # the composition root at game open; the connector is its presentation
        # carrier — the date widget's view model and the derived surfaces
        # read/edit it through this wiring (defaulted: the widget wiring
        # joins in group 3, unit-built connectors need nothing of it).
        self._current_date_service = current_date_service
        # NRI-0021 (task 3.3): the widget VM built by the composition root
        # from the loaded value; its popup lives on this connector (one grid
        # per game, parent-less like every date popup here), created when the
        # widget area is connected.
        self._now_date_vm = now_date_vm
        self._now_date_popup: ThemeDatePopup | None = None
        # NRI-0025 (task 1.2, design Д3): the thin settings face for the
        # column's pin list; defaulted like the «now» pair above because the
        # unit-built connectors of the sheet tests need nothing of it — with
        # no service the pin model still works, only its persistence is off.
        self._preview_pins_service = preview_pins_service
        # Task 12.6 (A1 host half, design Д14.1): the hour list's bridge window
        # — the search island clips the component pop-up to its own fixed
        # height, so the «now» selector opens this top level instead (the same
        # parent-less posture as the date grid above).
        self._now_hour_popup: ThemeHourPopup | None = None
        self._on_edit_event = None
        # Wave 5 (design D4, task 5.11): the single transaction finish point
        # over the game's one shared session, REQUIRED at construction — the
        # composition root injects the SAME unit the entity/event/char-sheet
        # services use, so no caller can build a connector around a second
        # finish point, and the raw session never enters this package. The
        # unit owns the serialization lock (``uow.lock``) that ``_spawn``
        # below acquires — one lock, one owner.
        # Serializing every spawned task against the session is required:
        # SQLAlchemy's session type does not support concurrent operations on
        # one connection — two overlapping tasks racing on it can leave an
        # awaited Future unresolved forever (an asyncio hang, not a clean
        # "concurrent operations" error), which is what timed out the E2E
        # suite before this lock covered every session-touching task
        # uniformly. Acquired exactly once per task in ``_run_locked``;
        # nested helper coroutines reached via plain ``await`` (not through
        # ``_spawn``) must never acquire it themselves.
        self._uow = uow
        self._session_lock = self._uow.lock
        # parent_dialog → [(entity_type, entity_id, description_id)] for
        # entities created in its popups: persisted by the popup's own unit
        # of work (task 5.8), so they are explicitly deleted (and that delete
        # persisted) when the parent dialog is rejected.
        self._popup_created: dict[Any, list[tuple[str, int, int]]] = {}
        # Sheet stack (nri-0014 task 4.3, CR5): parent sheet → how many sheets
        # are currently open under it (see _dim_sheet_stack). The connector is
        # its only reader/writer; entries die with the last sheet that made
        # them, and a game switch rebuilds the connector anyway.
        self._sheet_scrim_units: dict[Any, int] = {}
        # NRI-0024 (task 1.1, design Д2): the open sheets in opening order —
        # the stack this connector owns (open_sheet is its one show path) and
        # announces through sheet_stack_changed: True while the list holds at
        # least one sheet, False the moment it empties. Entries leave through
        # the sheet's own ``finished`` (every close route passes it).
        self._open_sheets: list = []
        # NRI-0024 (task 1.3, sheet since task 2.4): the live «Обзор мира»
        # sheet — registry retired, this connector is its only owner because
        # the flow is session-bound (its date query and row activation run on
        # THIS game's wiring).
        self._snapshot_sheet: WorldSnapshotWindow | None = None
        # NRI-0022 (tasks 5.1/5.2, design D2) → NRI-0025 (task 5.1, design
        # Д1/Д4): the preview column is slot-owned — pinned pairs in pin
        # order (the single limit transition, MAX_PINNED_CARDS, is enforced
        # HERE, the number itself stays owned by the VM) plus the live pair
        # under them. A game switch rebuilds the connector (shutdown →
        # start), so the fresh column simply restores from storage (task
        # 5.2). The rows cache holds the loaded entity behind every shown
        # pair (pins ∪ live): frames are assembled from it so a pinned card
        # is never re-loaded behind the user's back — only pin, restore,
        # delete and the pair's own card save touch these entries.
        self._preview_pins: list[tuple[str, int]] = []
        self._preview_live: tuple[str, int] | None = None
        self._preview_rows: dict[tuple[str, int], Any] = {}
        # Unified five-sheet import (rework 4.3): writes through the session/
        # ORM in apply_plan, only the image ingest pipeline is a dependency.
        self._xlsx_import = XlsxImportService(image_store=app._image_store)

    def _spawn(self, coro: Coroutine) -> asyncio.Task:
        """Schedule ``coro`` as a task serialized against the shared session.

        Every handler in this file that is triggered by a Qt signal must be
        scheduled through here instead of a bare ``asyncio.ensure_future`` —
        see ``_session_lock`` above. Nested coroutines called via plain
        ``await`` from within an already-spawned task run under the same
        lock for free and must not call this again for themselves.
        """
        return asyncio.ensure_future(self._run_locked(coro))

    def run_locked(self, coro: Coroutine) -> asyncio.Task:
        """Public ``_spawn`` for widgets living outside this wiring.

        The character-sheet dialogs start their flows with a bare
        ``asyncio.ensure_future`` (their UI is not ours); their
        session-touching steps must still go through the session lock, so the
        application passes this callable to them as ``run_locked``.
        """
        return self._spawn(coro)

    async def _run_locked(self, coro: Coroutine) -> Any:
        async with self._session_lock:
            return await coro

    # ── public surface for the composition root (task 6.4, finding B2) ──────
    # The application drives a couple of connector-owned flows (reload after a
    # calendar change, mention click-throughs); it goes through these accessors
    # instead of poking connector privates.

    @property
    def window(self):
        """The main window this connector serves."""
        return self._window

    @property
    def timeline_vm(self) -> TimelineViewModel:
        """The timeline feed view model."""
        return self._timeline_vm

    @property
    def detail_vm(self) -> DetailViewModel:
        """The detail panel view model."""
        return self._detail_vm

    @property
    def event_service(self) -> EventService:
        """The event service behind the timeline/detail/dialog flows."""
        return self._event_service

    @property
    def current_date_service(self) -> CurrentDateService | None:
        """The game's «now» holder handed in by the composition root (Д2)."""
        return self._current_date_service

    @property
    def now_date_vm(self):
        """The «now» widget VM — the subscription carrier the derived
        surfaces of groups 4–6 attach to (design Д2)."""
        return self._now_date_vm

    async def open_event_editor(self, event_id: int) -> None:
        """Run the connector's open-edit-event handler for ``event_id``.

        Public entry to the flow the mention click-through needs; the handler
        itself is the closure installed by :meth:`connect` (with dialogs,
        snapshot and images wired around it).
        """
        await self._on_edit_event(event_id)

    def _wire_image_picked(self, dialog: EntityCardDialog) -> None:
        """Ingest a freshly picked file through ``ImageStore`` (design D4/6.1).

        The dialog only reads bytes and shows a local preview; persisting
        through the single ingest pipeline (dedup, sha256, file writes) is
        this glue's job. A failure here (corrupt/undecodable content that
        slipped past the dialog's own check) warns instead of failing
        silently — the field just stays unset.
        """
        async def on_image_picked(data: bytes) -> None:
            image_store = self._app._image_store
            if image_store is None:
                return
            try:
                image_id = await image_store.store(data)
            except ValueError:
                QMessageBox.warning(
                    self._window, "Изображение", "Файл повреждён или не является изображением.",
                )
                return
            dialog.set_stored_image_id(image_id)

        dialog.image_picked.connect(lambda data: self._spawn(on_image_picked(data)))

    # ── Timeline bridge (wave B3, findings B3/C6) ───────────────────────────
    # The connector's single point of contact with the window's timeline
    # scale. Reading ``window.timeline_widget`` lives ONLY here; the two
    # re-model operations (push the visible sample, move the highlight) go
    # through the helpers below, so the wiring reads as intent, not as panel
    # traversal (the law-of-Demeter chains of the old connect() end here).

    @property
    def _timeline(self):
        """The timeline scale widget — the one access point."""
        return self._window.timeline_widget

    def _timeline_update_events(self) -> None:
        """Push the ViewModel's current visible sample onto the scale."""
        self._timeline.update_events(self._timeline_vm.events)

    def _timeline_set_selected(self, event_id: int | None) -> None:
        """Move (or clear with None) the scale's highlight to ``event_id``."""
        self._timeline.set_selected(event_id)

    def connect(self) -> None:
        """Connect all signals (called once from Application.start).

        Thin dispatcher (wave B3): every wiring area lives in its private
        ``_connect_*`` section below, called in exactly the linear order the
        connections took inside the old single-body method.
        """
        self._connect_timeline()
        self._connect_xlsx_import()
        self._connect_event_types()
        self._connect_docs()
        self._connect_event_dialogs()
        self._connect_entity_cards()
        self._connect_preview()
        self._connect_image_viewer()
        self._connect_search()
        self._connect_snapshot()
        self._connect_now_date()
        self._connect_sheet_gate()

    def _connect_docs(self) -> None:
        """«Документация»/«Changelog» (NRI-0024 task 2.2): the documents are
        sheets now (spec document-viewer «Документ открывается листом»).

        The two entries stay on the window's «О приложении» menu — and stay
        in its sheet-opening gate list — but the flow moved here, next to the
        one sheet show path: every entry builds a FRESH ``DocViewerDialog``
        (a SheetFrame wearing the document's name in its header) and shows it
        through :meth:`open_sheet`, so the stack rises with the document (the
        gate then closes every other sheet entry, which is also what makes a
        second copy of one document unreachable — Д2, no window bookkeeping
        left). The docs directory resolves at open time through the shared
        bundle resolver (dev tree vs the datas layouts the spec bundle ships).
        """
        window = self._window

        def open_doc(title: str, file_name: str) -> None:
            dialog = DocViewerDialog(
                title,
                bundle_resource_path("docs") / file_name,
                parent=window,
                theme=self._app._theme,
            )
            self.open_sheet(dialog)

        window.readme_action.triggered.connect(
            lambda: open_doc("Документация", "README.md")
        )
        window.changelog_action.triggered.connect(
            lambda: open_doc("Changelog", "CHANGELOG.md")
        )

    def _connect_sheet_gate(self) -> None:
        """Sheet-stack menu gate (NRI-0024 task 1.2, design Д2): the main
        window turns this connector's announcements into the enabled state of
        its sheet-opening entries — while any sheet covers the main layer the
        entries that would open another sheet are disabled; the exception
        entries (char-sheet windows) and the system paths stay alive. The
        window owns the entry list (its menu), this connector owns the stack.
        """
        self.sheet_stack_changed.connect(self._window.on_sheet_stack_changed)

    # ── connect() sections (wave B3) ────────────────────────────────────────
    # One private section per wiring area. The section order above is the
    # original per-line connect order; within a section the order is kept too.
    # Closures shared by several areas are the promoted private handlers in
    # the next block — every area references the same objects.

    def _connect_timeline(self) -> None:
        """Timeline widget <-> view models / detail panel signals."""
        window = self._window
        timeline_vm = self._timeline_vm

        # Timeline selection -> detail panel (W3: the signal carries event ids)
        self._timeline.event_selected.connect(
            lambda event_id: self._spawn(self._on_event_selected(event_id))
        )

        # «Выбор даты» window (task 7.1): the panel's single window_changed
        # channel writes the ViewModel's navigation window (None bounds =
        # «Все дни»; from add-era-aware-dates 4.2 a bound may be a bare date
        # or a (date, era) pair), the tape re-models over the overlap-visible
        # sample.
        def on_window_changed(start, end):
            timeline_vm.window = (start, end)
            self._timeline_update_events()

        self._timeline.window_changed.connect(on_window_changed)

        # A selection the ViewModel had to prune (the event fell out of the
        # visible set, e.g. after a window move) must leave the detail panel
        # too: the scale drops the id while re-modelling the new set, the
        # panel has no other reason to notice.
        def on_selected_event_changed():
            if timeline_vm.selected_event is None:
                window.detail_panel.clear()
                self._timeline_set_selected(None)

        timeline_vm.selected_event_changed.connect(on_selected_event_changed)

    def _connect_xlsx_import(self) -> None:
        """XLSX import (rework 4.3): one menu entry, one flow."""
        window = self._window
        timeline_vm = self._timeline_vm

        # analyze → (problems in the dialog) → confirm → apply, every step a
        # _spawn task so all of them serialize on the same _session_lock as
        # every other session-touching task. The analyzed plan is carried on
        # the dialog itself (design D2: the plan shown IS the plan applied —
        # no second read, no window for the file to change in between).
        # The result — report or failure reason — goes into the dialog panel,
        # no QMessageBox report anymore.
        def _run_import():
            dlg = XlsxImportDialog(window, theme=self._app._theme)

            async def _analyze(path: str):
                try:
                    plan = await self._xlsx_import.analyze_file(path, self._uow)
                except Exception as exc:  # noqa: BLE001
                    # Сбой чтения вне штатных фатальных ошибок плана —
                    # причину показывает список проблем диалога.
                    dlg.publish_analysis_failure(str(exc))
                    return
                dlg.publish_analysis(plan)

            async def _confirm():
                plan = dlg.plan
                if plan is None or plan.has_fatal:
                    return
                try:
                    report = await self._xlsx_import.apply_plan(
                        plan, self._uow, progress_callback=dlg.set_progress,
                    )
                except Exception as exc:  # noqa: BLE001
                    # apply_plan's unit already rolled the transaction back
                    # (design D6) —
                    # причину принимает диалог (в т.ч. уже закрытый: publish_*
                    # проверяют живость C++-стороны перед показом).
                    dlg.publish_import_failure(str(exc))
                    return
                await timeline_vm.load_events()
                self._timeline_update_events()
                dlg.publish_report(report)

            dlg.analyze_requested.connect(lambda path: self._spawn(_analyze(path)))
            dlg.confirm_import.connect(lambda: self._spawn(_confirm()))
            # «Скачать шаблон» (C5): save--as dialog + the workbook generated
            # under the active game calendar at save time, no session involved.
            dlg.download_template.connect(lambda: save_template_as(dlg))
            dlg.finished.connect(lambda _: dlg.deleteLater())
            self.open_sheet(dlg)

        window.import_xlsx_action.triggered.connect(_run_import)

    def _connect_event_types(self) -> None:
        """Event types (W4 6.1/6.2): dialog entry in the panel's «+» menu."""
        window = self._window
        event_service = self._event_service

        def on_event_types():
            dialog = EventTypesDialog(
                event_service, run=self._spawn, parent=window,
                theme=self._app._theme,
            )

            dialog.types_changed.connect(lambda: self._spawn(self._reload_timeline()))
            self.open_sheet(dialog)

        self._timeline.event_types_requested.connect(on_event_types)

    def _connect_event_dialogs(self) -> None:
        """The timeline's event dialog flows: add, related create, edit."""
        window = self._window
        detail_vm = self._detail_vm
        event_service = self._event_service
        event_dialog_vm = self._event_dialog_vm

        # ── Event save (task 5.10, design D5): ONE apply path for both ──────
        # dialog flows. The dialogs emit frozen contracts (dialog_results), so
        # the old near-duplicate dict.pop blocks are gone; the service finishes
        # the write through the shared unit of work (task 5.9).
        async def _apply_event_result(result: EventDialogResult) -> bool:
            relations = result.as_relations_payload()
            try:
                if isinstance(result, EventEditResult):
                    await event_service.update_event_with_relations(
                        result.event_id,
                        name=result.name,
                        start_date=result.start_date,
                        end_date=result.end_date,
                        start_bc=result.start_bc,
                        end_bc=result.end_bc,
                        characteristics=result.characteristics,
                        backstory=result.backstory,
                        relations=relations,
                        event_type_id=result.event_type_id,
                        # NRI-0023 task 7.1: the card's combo is authoritative
                        # on edit — an id перецепляет, None поднимает в
                        # основные (populate loads the stored link, so saving
                        # an untouched card re-writes what was there).
                        # Task 7.2: the «Час»/«Минута» pair, None = без времени.
                        parent_id=result.parent_id,
                        start_time=result.start_time,
                    )
                else:
                    await event_service.create_event_with_relations(
                        name=result.name,
                        start_date=result.start_date,
                        end_date=result.end_date,
                        start_bc=result.start_bc,
                        end_bc=result.end_bc,
                        characteristics=result.characteristics,
                        backstory=result.backstory,
                        relations=relations,
                        event_type_id=result.event_type_id,
                        # NRI-0023 task 6.1: the sub-event link the dialog
                        # carries (the «Создать подсобытие» prefill); a plain
                        # create reads None and the service guard stands.
                        # Task 7.2: the wall-clock start from the card's lists.
                        parent_id=result.parent_id,
                        start_time=result.start_time,
                    )
            except Exception as exc:  # noqa: BLE001 — the modal names the reason
                # The service's unit of work already undid the partial write
                # (no undo here — the finish is the unit's). Reload the
                # timeline BEFORE the blocking modal so the state under it is
                # consistent (the same move as every other save handler).
                await self._reload_timeline()
                QMessageBox.critical(
                    window, "Ошибка", f"Не удалось сохранить событие: {exc}",
                )
                return False
            return True

        # Add event button (and its NRI-0023 task 6.1 sibling, «Создать
        # подсобытие»): ONE create-dialog factory. Without a parent it is the
        # plain create card; with one (the row's context menu) the same card
        # opens prefilled with the parent and the parent's start date.
        def _open_create_dialog(prefill_parent: Any = None):
            # NRI-0021 task 4.4: the dialog's read-only «С начала» line reads
            # and follows the game's «now» through the widget VM.
            dialog = EventDialog(
                event_dialog_vm, parent=window, theme=self._app._theme,
                now_vm=self._now_date_vm,
            )
            if prefill_parent is not None:
                dialog.prefill_parent(prefill_parent)
            self._spawn(self._load_available_into_dialog(dialog))
            self._spawn(self._load_types_into_dialog(dialog))
            # NRI-0023 task 7.1: the «Родительское событие» pool (the prefilled
            # parent is one of its main events, spec «Родитель и дата подставлены»).
            self._spawn(self._load_parents_into_dialog(dialog))
            self._app._wire_mentions_for_dialog(dialog, self._on_entity_click)
            self._app._wire_ai_buttons(dialog)
            # NRI-0024 task 2.5: the dialog's child sheets (the «Выберите …»
            # picker) ride this connector's stack over the dialog itself.
            dialog.sheet_requested.connect(self.open_sheet)

            async def on_saved(result: EventDialogResult) -> None:
                if not await _apply_event_result(result):
                    dialog.finish_saving(False)
                    return
                await self._reload_timeline()
                dialog.finish_saving(True)

            dialog.saved.connect(lambda result: self._spawn(on_saved(result)))
            dialog.create_related_requested.connect(
                lambda a, t: self._spawn(self._open_related_create_dialog(dialog, a, t))
            )
            dialog.accepted.connect(lambda: self._popup_created.pop(dialog, None))
            dialog.rejected.connect(
                lambda: self._spawn(self._cleanup_popup_entities(dialog))
            )
            self.open_sheet(dialog)

        def on_add_event():
            _open_create_dialog()

        self._timeline.add_event_requested.connect(on_add_event)

        # Create subevent (NRI-0023 task 6.1, spec «Создание подсобытия правым
        # кликом»): the row's context menu arrives as the ViewModel's signal,
        # the parent's start date is re-read for the prefill, and the shared
        # create factory opens the card (design Д7). A parent that is gone or
        # unreadable is a silent no-op — the scale quoted a stale row (the
        # same open-failure posture the edit flow keeps, no modal for a read).
        async def on_subevent_create(parent_id: int) -> None:
            try:
                parent = await event_service.get_event(parent_id)
            except Exception as exc:  # noqa: BLE001 — logged, no dialog
                logging.getLogger("app.wiring").warning(
                    "Не удалось загрузить родителя для подсобытия %s: %s",
                    parent_id, exc,
                )
                return
            if parent is None:
                return
            _open_create_dialog(parent)

        self._timeline_vm.subevent_create_requested.connect(
            lambda parent_id: self._spawn(on_subevent_create(parent_id))
        )

        # Create standalone entities from timeline "+" context menu
        async def on_add_entity(entity_type: str):
            try:
                entity_service = self._app._get_entity_service(entity_type)
                if not entity_service:
                    return

                async def on_entity_saved(result: EntityCreateResult) -> None:
                    try:
                        # The unit of work is the finish (design D4): it persists on
                        # clean exit, reverts + re-raises on any failure.
                        async with self._uow.transaction():
                            await entity_service.create_entity(
                                characteristics=result.characteristics,
                                backstory=result.backstory,
                                **result.fields,
                            )
                    except Exception as exc:  # noqa: BLE001 — the modal names the reason
                        # The data SAVE path of an entity not yet stored: the
                        # unit already rolled the partial rows back; a partial
                        # reload is pointless (no object, the scale shows no
                        # entity rows) — only the report stays (save-error-reporting).
                        QMessageBox.critical(
                            window, "Ошибка", f"Не удалось создать сущность: {exc}",
                        )
                        dialog.finish_saving(False)
                        return
                    dialog.finish_saving(True)

                dialog = await self._open_entity_card(
                    entity_type, parent=window, on_saved=on_entity_saved,
                    load_available=False,
                )
                self.open_sheet(dialog)
            except Exception as exc:
                # The "DIALOG DID NOT OPEN" path (constructor/popover), not a
                # data-save failure: log only, NO modal — an open failure must
                # not spawn double reports. The save path above is the one
                # reporting to the user.
                logging.getLogger("app.wiring").warning(
                    "Не удалось открыть диалог создания сущности: %s", exc,
                )

        self._timeline.add_entity_requested.connect(
            lambda t: self._spawn(on_add_entity(t))
        )

        # Edit event (double-click on timeline)
        async def on_edit_event(event_id):
            try:
                event = await event_service.get_event(event_id)
                if not event:
                    return
                # NRI-0021 task 4.4: the edit dialog's «С начала» line reads
                # and follows the game's «now» through the widget VM too.
                dialog = EventDialog(
                    event_dialog_vm, parent=window, theme=self._app._theme,
                    now_vm=self._now_date_vm,
                )
                await self._load_available_into_dialog(dialog)
                # Types before populate: the selector gets the game's set, then
                # populate() preselects this event's current type (W4 6.3).
                # Flat options (PR-032), same as the create dialog's loader.
                dialog.set_event_types(
                    await event_service.get_event_type_options()
                )
                dialog.populate(event)
                # NRI-0023 task 7.1: the parent pool loads AFTER populate — the
                # exclusion of the edited event reads the id populate() loaded.
                await self._load_parents_into_dialog(dialog)
                self._app._wire_mentions_for_dialog(dialog, self._on_entity_click)
                self._app._wire_ai_buttons(dialog)
                # NRI-0024 task 2.5: same child-sheet channel as the create
                # dialog — the picker stacks over this edit dialog.
                dialog.sheet_requested.connect(self.open_sheet)

                async def on_event_updated(result: EventDialogResult) -> None:
                    if not await _apply_event_result(result):
                        # The unit of work already rolled back; the timeline was
                        # reloaded for the modal. The detail panel stays on the
                        # previous state — an "updated" version does not exist.
                        dialog.finish_saving(False)
                        return
                    await self._reload_timeline()
                    # Refresh detail panel
                    await detail_vm.load_details(result.event_id)
                    window.detail_panel.show_event(detail_vm.event)
                    dialog.finish_saving(True)

                dialog.saved.connect(lambda result: self._spawn(on_event_updated(result)))
                dialog.create_related_requested.connect(
                    lambda a, t: self._spawn(self._open_related_create_dialog(dialog, a, t))
                )
                dialog.accepted.connect(lambda: self._popup_created.pop(dialog, None))
                dialog.rejected.connect(
                    lambda: self._spawn(self._cleanup_popup_entities(dialog))
                )
                self.open_sheet(dialog)
            except Exception as exc:
                # Open-failure path (reads only happened): the unit of work
                # owns every finish, so this is a plain log, no undo here.
                logging.getLogger("app.wiring").warning(
                    "Не удалось открыть диалог события: %s", exc,
                )

        self._on_edit_event = on_edit_event

        self._timeline.event_double_clicked.connect(
            lambda eid: self._spawn(on_edit_event(eid))
        )

    def _connect_entity_cards(self) -> None:
        """Entity-card flows: double-click on an entity row in the detail panel.

        The card factory, the related-create popup and the character-sheet
        glue are closure handlers shared by several wiring areas — they are
        promoted private handlers below; this section keeps the plain connect.
        """
        window = self._window

        window.detail_panel.entity_clicked.connect(
            lambda t, i: self._spawn(self._on_entity_click(t, i))
        )

    def _connect_preview(self) -> None:
        """Entity preview (NRI-0022 tasks 5.1/5.2, design D2/D4; slots and
        the pin channel since NRI-0025 tasks 5.1–5.3, design Д1/Д3/Д4): the
        one selection bus between the middle column and the read-only right
        column plus the pin channel. The preview never loads anything itself
        — every direction rides here as (type, id) pairs, the entity service
        answers with the row (its relations come from ``get_entity``), and
        only then does the connector push the full slot frame. The timeline
        is deliberately absent from this section: selecting or deselecting an
        event on the scale leaves every card in place (spec preview-pins
        «Смена события колонку не трогает»)."""
        # Single-click / Press selection in the middle column (task 3.1's
        # relay): the panel already painted the row wash, the connector
        # shows the freshly loaded entity in the live area.
        self._window.detail_panel.entity_selected.connect(
            lambda t, i: self._spawn(self._show_in_preview(t, i))
        )
        # Relation-row / mention-link activation inside ANY pane: the same
        # bus in the opposite direction, plus the middle-column sync attempt
        # (task 5.3: the source pane never matters — the target always goes
        # to the live area, pinned cards stay as they were).
        self._window.entity_preview.entity_requested.connect(
            lambda t, i: self._spawn(self._on_preview_entity_requested(t, i))
        )
        # The pin channel (NRI-0025 design Д3): the pair plus the card's
        # current pinned state; the connector owns the transition limit and
        # the storage, then answers with the next frame.
        self._window.entity_preview.pin_toggle_requested.connect(
            lambda t, i, p: self._spawn(self._on_preview_pin_toggled(t, i, p))
        )

    async def restore_preview_pins(self) -> None:
        """Read the saved pins at game open (NRI-0025 task 5.2, design Д3;
        the composition root calls this right after the connector connected,
        while no user signal can race it). A pair that no longer resolves —
        unknown type, deleted row — is silently dropped from the RESTORED
        list and storage is NOT rewritten (the next pin/unpin persists the
        clean list; no background repair writes)."""
        if self._preview_pins_service is None:
            return
        for entity_type, entity_id in await self._preview_pins_service.get_pins():
            entity_service = self._app._get_entity_service(entity_type)
            if entity_service is None:
                continue
            entity = await entity_service.get_entity(entity_id)
            if entity is None:
                continue
            self._preview_pins.append((entity_type, entity_id))
            self._preview_rows[(entity_type, entity_id)] = entity
        self._push_preview_frame()

    def _push_preview_frame(self) -> None:
        """The facade's single write channel (design Д1): the full frame
        derived from the slot state — pinned pairs in pin order with their
        cached rows, the live pair last. Every caller has just established
        the cache entries this reads."""
        pins = [(t, self._preview_rows[(t, i)]) for t, i in self._preview_pins]
        live = (
            None
            if self._preview_live is None
            else (self._preview_live[0], self._preview_rows[self._preview_live])
        )
        self._window.entity_preview.show_slots(pins, live)

    async def _save_preview_pins(self) -> None:
        """Persist the current pin list (design Д3: one save per pin/unpin);
        a connector built without the storage face just keeps the model."""
        if self._preview_pins_service is None:
            return
        await self._preview_pins_service.save_pins(self._preview_pins)

    async def _on_preview_pin_toggled(
        self, entity_type: str, entity_id: int, pinned: bool
    ) -> None:
        """The pin channel's rule set (NRI-0025 task 5.1, design Д3/Д4).
        Pinning seats the LIVE pair (a press on any other pair is stale and
        silently rejected), adds it at the end of the order, clears the live
        area — the card visually stays put because the very next frame shows
        it as a pin above the now-empty live slot — and refuses the fourth
        pin in the model exactly as the island refuses it on screen. A pin
        already in the list is never seated a second time (storage would
        hold one dead slot the UI cannot even reach). Unpinning removes the
        pair from the list only — the live area is never touched (spec
        «Открепление убирает карточку» / «Открепление не съедает живую
        копию»). Both accepted moves persist and push one fresh frame."""
        pair = (entity_type, entity_id)
        if pinned:
            if pair not in self._preview_pins:
                return
            self._preview_pins.remove(pair)
            if self._preview_live != pair:
                self._preview_rows.pop(pair, None)
        else:
            if pair != self._preview_live:
                return
            if pair in self._preview_pins or len(self._preview_pins) >= MAX_PINNED_CARDS:
                return
            self._preview_pins.append(pair)
            self._preview_live = None
        await self._save_preview_pins()
        self._push_preview_frame()

    async def _show_in_preview(self, entity_type: str, entity_id: int) -> bool:
        """Show one entity in the column's LIVE area (NRI-0025 design Д4:
        the old single-card «shown» channel became the live pointer). Load
        through its entity service, seat the pair as live, push the frame.
        True when the live area shows that pair afterwards. The pair already
        live reloads NOTHING and pushes no frame (spec «Повторный выбор
        ничего не делает», which also swallows the ``entitySelected`` echo
        of :meth:`DetailPanel.select_entity` below). Matching a PIN is
        deliberately not checked — re-selecting a pinned entity is the
        user's conscious duplicate (spec «Дубль закреплённой сущности»).
        A dead type key or a vanished row keeps the live pair in place: the
        broken-mention posture of task 4.5 survives into the wiring."""
        if self._preview_live == (entity_type, entity_id):
            return True
        entity_service = self._app._get_entity_service(entity_type)
        if not entity_service:
            return False
        entity = await entity_service.get_entity(entity_id)
        if entity is None:
            return False
        previous = self._preview_live
        self._preview_live = (entity_type, entity_id)
        self._preview_rows[(entity_type, entity_id)] = entity
        # The replaced live row leaves the cache unless a pinned copy still
        # paints that pair (the shared duplicate row).
        if previous is not None and previous not in self._preview_pins:
            self._preview_rows.pop(previous, None)
        self._push_preview_frame()
        return True

    async def _on_preview_entity_requested(self, entity_type: str, entity_id: int) -> None:
        if not await self._show_in_preview(entity_type, entity_id):
            return
        # Middle-column sync (design D4): switch to the row's tab and wash it;
        # a pair outside the current lists stays a preview-only navigation
        # (the facade's no-op) and the scale is never touched from here.
        self._window.detail_panel.select_entity(entity_type, entity_id)

    def _connect_image_viewer(self) -> None:
        """Picture click → viewer SHEET (NRI-0024 task 2.5, design Д6/Д7, spec
        image-display «Просмотр оригинала полного размера»): the two columns'
        facades build their viewer — they hold the entity's pixels — and hand
        it to the connector's one show path. The sheet is attached natively
        over the main layer (Qt.Sheet, NonModal at Qt level — PR-012), the
        original above the sheet's size stays reachable by
        scroll, and both closes (header «Закрыть», Esc) land back on the
        column that opened it — on the non-blocking ``open_sheet`` show, so
        the qasync loop never
        nests (spec «Прикладные диалоги не входят во вложенный цикл
        событий»). The card's viewer travels the same channel, connected on
        the card factory below.
        """
        self._window.detail_panel.sheet_requested.connect(self.open_sheet)
        self._window.entity_preview.sheet_requested.connect(self.open_sheet)

    def _connect_search(self) -> None:
        """Search bar: the query dispatch and the result-open flows."""
        window = self._window
        timeline_vm = self._timeline_vm
        search_vm = self._search_vm

        # Search
        async def on_search(query):
            # NRI-0023 task 8.2 (design Д9, spec global-search «Подсобытие
            # названо через родителя»): the row prefix names a sub-event's
            # parent even when the parent itself never matched the query, so
            # the VM gets the game-wide id → имя card — one pass over the
            # ladder's loaded sample (the same gate the result-open path
            # already uses); an id the card cannot name adds no prefix.
            await search_vm.search(
                query,
                {event.id: event.name for event in timeline_vm.all_events},
            )

        window.search_bar.search_requested.connect(
            lambda q: self._spawn(on_search(q))
        )

        # Search result gestures (NRI-0022 task 6.2; spec rewritten by
        # NRI-0025 task 6.1, design Д7 — «Клик по результату: событие ведёт
        # к цели, сущность — только в предпросмотр»): the two channels the
        # island separates — single click routes, double click edits.
        async def on_search_result(entity_type, entity_id):
            if entity_type == "event":
                # Select by id and show details (plain await: the task of
                # this handler already holds the session lock), then scroll
                # the scale so the highlighted row is visible (W3b panel API).
                # The gate checks the WHOLE sample, not the windowed slice:
                # a result the current window excludes must still reach
                # ``select_event_by_id``, which resets the window to «Все
                # дни» before the selection lands (spec «Внешний выбор вне
                # окна сбрасывает окно»). An id the timeline never held
                # stays a plain miss — the list untouched.
                if any(ev.id == entity_id for ev in timeline_vm.all_events):
                    await self._on_event_selected(entity_id)
                    # The window reset may have re-modelled the list to
                    # «Все дни»: the list repaints from the ViewModel before
                    # the highlight — the same sample push every other
                    # mutation path performs, otherwise the re-modelled row
                    # would exist in the VM but not on the panel.
                    self._timeline_update_events()
                    self._timeline_set_selected(entity_id)
                    self._timeline.scroll_to_event(entity_id)
            else:
                # A single click on an entity result shows it in the live
                # preview area and NOTHING else (NRI-0025 task 6.1, design
                # Д7 — the full path of the retired requirement is abolished:
                # no event selection, no window reset, no tab switch, no row
                # wash; the scale and the detail panel stay exactly as they
                # were, pinned cards stay as they were). The live pointer's
                # own rules apply unchanged: a re-click on the pair already
                # live reloads nothing (the task 5.1 bus semantics).
                await self._show_in_preview(entity_type, entity_id)

        window.search_bar.result_selected.connect(
            lambda t, i: self._spawn(on_search_result(t, i))
        )

        async def on_search_result_activated(entity_type, entity_id):
            # Double click — the edit gesture (spec «Сущность открывается
            # карточкой» / «Событие открывается редактором двойным кликом»):
            # the entity's editable card, or the event editor for an event.
            # Plain awaits: this handler's own task already holds the session
            # lock, and neither shared handler acquires it itself.
            if entity_type == "event":
                await self._on_edit_event(entity_id)
            else:
                await self._on_entity_click(entity_type, entity_id)

        window.search_bar.result_activated.connect(
            lambda t, i: self._spawn(on_search_result_activated(t, i))
        )

    def _connect_snapshot(self) -> None:
        """World-snapshot SHEET (NRI-0022; sheet format since NRI-0024 task
        2.4, design Д1/Д6): the menu entry, the date query and the entity
        activation.

        Every entry opens a fresh sheet through the connector's one show path
        (:meth:`open_sheet`): attached natively over the main window (Qt.Sheet,
        NonModal at Qt level — PR-012), the header
        «Обзор мира», a stack the opening entry is gated in (spec «Повторный
        вызов недостижим» — the abolished registry's single instance falls out
        of the gate), and NO placement memory — a sheet reopens at its default
        520×760, whatever a previous run left in ui.json (spec «Лист не помнит
        рамку»). QML content and the panel VM are untouched by the container
        move — the wiring surface (``snapshot_requested``, ``entity_clicked``)
        is the same object as before. Row activation threads the sheet in as
        the card's parent, so the entity card lands OVER the snapshot and the
        scrim cascade dims it one share (spec «Активация строки открывает
        карточку поверх листа»); the card closing peels the share back and the
        sheet stays open and live.
        """
        window = self._window

        def open_snapshot_sheet() -> None:
            snapshot_sheet = WorldSnapshotWindow(
                parent=window,
                theme=self._app._theme,
                now_date_vm=self._now_date_vm,
            )
            snapshot_sheet.snapshot.snapshot_requested.connect(
                lambda target, _w=snapshot_sheet: self._spawn(
                    self._on_snapshot_requested(_w.snapshot, target)
                )
            )
            # The sheet is the card's Qt parent: the parent chain IS the
            # stack (open_sheet dims every ancestor with the scrim duck).
            snapshot_sheet.snapshot.entity_clicked.connect(
                lambda t, i, _w=snapshot_sheet: self._spawn(
                    self._on_entity_click(t, i, parent=_w)
                )
            )
            self.open_sheet(snapshot_sheet)
            # This connector is the sheet's owner (the registry is gone): the
            # live one is kept for the game-shutdown teardown, and every close
            # route passes finished — the stale-guard keeps a late lift from
            # forgetting a newer sheet an entry opened meanwhile.
            self._snapshot_sheet = snapshot_sheet
            snapshot_sheet.finished.connect(
                lambda _result, _w=snapshot_sheet: self._forget_snapshot_sheet(_w)
            )

        window.world_snapshot_requested.connect(open_snapshot_sheet)

    def _forget_snapshot_sheet(self, snapshot_sheet: WorldSnapshotWindow) -> None:
        """Release the tracked «Обзор мира» slot for the sheet that closed."""
        if self._snapshot_sheet is snapshot_sheet:
            self._snapshot_sheet = None

    @property
    def snapshot_sheet(self) -> WorldSnapshotWindow | None:
        """The live «Обзор мира» sheet (None when never opened or closed)."""
        return self._snapshot_sheet

    def close_snapshot_sheet(self) -> None:
        """Take the session-bound «Обзор мира» sheet down with the game
        (Application.shutdown; NRI-0024 task 2.4 renamed it with the class)."""
        if self._snapshot_sheet is not None:
            self._snapshot_sheet.close()
            self._snapshot_sheet = None

    async def _on_snapshot_requested(self, snapshot, target) -> None:
        """Answer one date query for the open snapshot panel.

        The bridge carries a (date, era) pair (task 3.4); the query itself is
        key-based, so era_key translates it here exactly once (a bare legacy
        date reads as «н.э.»). The panel arrives as an argument because every
        opening builds a fresh sheet (a fresh panel per open), not a permanent
        child of the main window.
        """
        if target is None:
            events = await self._event_service.get_all_events()
        else:
            target_date, target_bc = split_date_era(target)
            events = await self._event_service.get_events_at_date(
                era_key(target_date, bool(target_bc))
            )
        # NRI-0023 task 8.3 (design Д9, spec world-snapshot «Осиротевшее в
        # срезе подсобытие получает заглушку»): the tree names an orphan's
        # parent from the id → имя card — one pass over the ladder's loaded
        # sample (the whole game's events), the same source the search prefix
        # reads. In «все события» mode no parent can be out of the slice, so
        # the card simply never gets asked.
        #
        # PR-019 (spec world-snapshot «Секции снимка» + entity-addition
        # «Успешное создание»): the four entity sections are the game's
        # census, read on every query — an entity the master has just saved
        # belongs to the world whether or not any event mentions it, so the
        # panel must not learn about it through the event slice alone.
        world_entities = {
            type_key: list(
                await self._app._entity_services[type_key].get_all()
            )
            for type_key in SUPPORTED_ENTITY_TYPES
        }
        snapshot.populate(
            events,
            target,
            {event.id: event.name for event in self._timeline_vm.all_events},
            world_entities,
        )

    def _connect_now_date(self) -> None:
        """Game-«now» widget (NRI-0021 task 3.3): popup, write, broadcast.

        The chip lives in the search island; its VM carries only the sync
        request. This section is the whole async half of the flow (spec
        qml-shell «Sync-вход достаточен»): VM signal → the widgets bridge
        (parent-less top-level, never inside the island rectangle — spec
        «Выбор даты идёт через widgets-мост») prefilled with the served
        value → the service's single UoW transaction → the applied-value
        slot, whose ``nowChanged`` repaints the caption and every derived
        surface without a restart.
        """
        vm = self._now_date_vm
        service = self._current_date_service
        if vm is None or service is None:
            # A connector built without the game's «now» pair (unit-built
            # connectors, bare windows) simply has no widget area.
            return
        self._now_date_popup = ThemeDatePopup()
        self._now_date_popup.date_selected.connect(
            lambda pair: self._spawn(self._apply_now_date(pair))
        )
        vm.datePopupRequested.connect(self._open_now_date_popup)
        # NRI-0023 task 9.1: the neighbor hour list runs the same finish —
        # one service transaction, then the applied-value mirror.
        vm.hourChangeRequested.connect(
            lambda hour: self._spawn(self._apply_now_hour(hour))
        )
        # Task 12.6 (A1 host half, re-audit 2026-09-29): the hour list needs
        # the same bridge route as the grid — the island's fixed-height host
        # cuts the component pop-up, so the combo asks, this connector opens
        # the list window, and a pick re-enters the VM's own request channel
        # (requestHour maps the index and bounds-checks it; the existing
        # hourChangeRequested half finishes the transaction unchanged).
        self._now_hour_popup = ThemeHourPopup()
        self._now_hour_popup.hour_selected.connect(vm.requestHour)
        vm.hourPopupRequested.connect(self._open_now_hour_popup)

    def _open_now_date_popup(
        self, x: float, y: float, width: float, height: float
    ) -> None:
        # The VM carries the island-local chip rectangle; the facade maps
        # it to global (scene→widget is the island's knowledge, not ours).
        value = self._current_date_service.value
        self._now_date_popup.open_at(
            self._window.search_bar.now_date_anchor(x, y, width, height),
            (value.coord, value.is_bc) if value is not None else None,
        )

    def _open_now_hour_popup(
        self, x: float, y: float, width: float, height: float
    ) -> None:
        # Same rectangle contract as the grid above: the VM carries the
        # combo's island-local rectangle, the facade maps it to global. The
        # rows are the VM's live hour options — re-read here on every open,
        # so a calendar switch that narrowed the day is reflected without
        # any island rebuild (design Д4: the bounds are the calendar's).
        self._now_hour_popup.open_at(
            self._window.search_bar.now_date_anchor(x, y, width, height),
            list(self._now_date_vm.hourOptions),
            self._now_date_vm.selectedHourIndex,
        )

    async def _apply_now_date(self, selected) -> None:
        """Finish one widget edit: service write, then mirror it into the VM.

        The popup bridge answers with a ``(coord, is_bc)`` pair (the grid's
        own era flag); the served hour rides along untouched (NRI-0023 task
        9.1 — the date half and the hour half edit one and the same value).
        The service moves its value and counter only on a committed
        transaction, so ``applyNow`` runs only on success; the failure half
        of the AGENTS rule («any persistence error reaches the user») is the
        modal, like every other save path here.
        """
        coord, is_bc = selected
        value = self._current_date_service.value
        hour = value.hour if value is not None else None
        try:
            await self._current_date_service.set_now(coord, is_bc, hour)
        except Exception as exc:  # noqa: BLE001 — the modal names the reason
            QMessageBox.critical(
                self._window, "Ошибка", f"Не удалось изменить игровую дату: {exc}",
            )
            return
        self._now_date_vm.applyNow(coord, is_bc, hour)

    async def _apply_now_hour(self, hour) -> None:
        """Finish one hour-list edit (NRI-0023 task 9.1, spec «Час меняет
        только подпись»): the day half of the served value stays put, only
        the optional hour moves; same one-transaction finish and applied-
        value mirror as the date half, same modal on failure."""
        value = self._current_date_service.value
        coord, is_bc = value.coord, value.is_bc
        try:
            await self._current_date_service.set_now(coord, is_bc, hour)
        except Exception as exc:  # noqa: BLE001 — the modal names the reason
            QMessageBox.critical(
                self._window, "Ошибка", f"Не удалось изменить игровую дату: {exc}",
            )
            return
        self._now_date_vm.applyNow(coord, is_bc, hour)

    # ── Shared handlers (the closures the old connect() shared between its
    # areas, promoted to private methods in wave B3) ─────────────────────────
    # Bodies moved unchanged; they all read the same connector state through
    # ``self``, so every wiring area references the same objects.

    async def _on_event_selected(self, event_id) -> None:
        """Select the event by id and show it in the detail panel."""
        window = self._window
        timeline_vm = self._timeline_vm
        detail_vm = self._detail_vm
        timeline_vm.select_event_by_id(event_id)
        event = timeline_vm.selected_event
        if event:
            await detail_vm.load_details(event.id)
            window.detail_panel.show_event(detail_vm.event)
        else:
            window.detail_panel.clear()

    async def _reload_timeline(self) -> None:
        """Re-read events and re-render the scale (selection/window kept)."""
        await self._timeline_vm.load_events()
        self._timeline_update_events()

    # ── Helper: load available entities and set them on dialog sections ──
    async def _load_available_into_dialog(self, dialog) -> None:
        """Load all entities from DB and set them as available for linking.

        PR-032: the census arrives as flat EntityOptions — the section rows
        and picker candidates outlive failed-save rollbacks on the QML side,
        so raw ORM rows must not be handed over here."""
        dialog.set_available_entities(
            "organizations",
            await self._app._entity_services["organization"].get_options(),
        )
        dialog.set_available_entities(
            "characters",
            await self._app._entity_services["character"].get_options(),
        )
        dialog.set_available_entities(
            "items",
            await self._app._entity_services["item"].get_options(),
        )
        dialog.set_available_entities(
            "locations",
            await self._app._entity_services["location"].get_options(),
        )

    async def _load_types_into_dialog(self, dialog) -> None:
        """Fill the event dialog's type selector with the game's set (W4).
        Flat options (PR-032) — the «Тип» binding survives a failed save."""
        dialog.set_event_types(await self._event_service.get_event_type_options())

    async def _load_parents_into_dialog(self, dialog) -> None:
        """Fill the event dialog's «Родительское событие» pool (NRI-0023
        task 7.1): the whole event list is handed over as flat options
        (PR-032) — the ViewModel keeps main events only out of it (spec
        «Чужих детей в списке нет») and the facade excludes the edited event
        through its loaded id."""
        dialog.set_parent_options(await self._event_service.get_parent_options())

    # ── Shared entity-card factory (task 5.10, design D5) ──────────────
    # One place for the card's opening ceremony: creation, populate, the
    # mention/AI/image wiring, the linkable-sections load and the save pump.
    # Callers only add their own save handler and the window-local extras
    # (the popup-cleanup pair for a parent dialog).
    async def _open_entity_card(
        self,
        entity_type: str,
        *,
        parent,
        on_saved,
        entity: Any = None,
        load_available: bool = True,
        popup_cleanup: bool = False,
        related_create_enabled: bool = True,
    ):
        dialog = EntityCardDialog(
            None, entity_type=entity_type, parent=parent,
            theme=self._app._theme,
            # NRI-0021 task 4.3: every card of the factory (create, edit,
            # related popup) reads and follows the game's «now» through the
            # widget VM for its read-only age line.
            now_vm=self._now_date_vm,
            related_create_enabled=related_create_enabled,
        )
        if entity is not None:
            dialog.populate(entity)
        self._app._wire_mentions_for_dialog(dialog, self._on_entity_click)
        self._app._wire_ai_buttons(dialog)
        self._wire_image_picked(dialog)
        # NRI-0024 task 2.5: every card of this factory (create, edit, related
        # popup) shows its child sheets — the viewer and the «Выберите …»
        # picker — through the connector's stack, over the card itself.
        dialog.sheet_requested.connect(self.open_sheet)
        if load_available:
            # Load available related entities for linking (registry, wave 3).
            # Plain awaits: every caller runs inside its own locked task.
            for cfg in entity_registry.related_refs_for_key(entity_type):
                rel_svc = self._app._get_entity_service(cfg.entity_type.value)
                if rel_svc:
                    # Flat options (PR-032): the card's sections live across
                    # failed saves just like the event dialog's.
                    available = await rel_svc.get_options()
                    dialog.set_available_entities(cfg.attr, available)
        dialog.saved.connect(lambda result: self._spawn(on_saved(result)))
        if popup_cleanup:
            dialog.accepted.connect(lambda: self._popup_created.pop(dialog, None))
            dialog.rejected.connect(
                lambda: self._spawn(self._cleanup_popup_entities(dialog))
            )
        return dialog

    async def _wire_open_character_sheet(self, dialog, entity_type, entity_id):
        if entity_type != "character":
            return
        svc = self._app._instance_service
        if svc is None:
            return

        async def _refresh_button():
            inst = await svc.get_by_character_id(entity_id)
            dialog.set_character_sheet_available(inst is not None)

        async def _open_bound_sheet():
            inst = await svc.get_by_character_id(entity_id)
            if inst is None:
                dialog.set_character_sheet_available(False)
                return
            self._app._on_instance_open(inst.id)

        dialog.open_character_sheet_requested.connect(
            lambda: self._spawn(_open_bound_sheet())
        )
        await _refresh_button()

    # Entity card double-click. ``parent`` is the sheet the activation came
    # from when that is not the main layer (nri-0024 task 2.4: a row of the
    # «Обзор мира» sheet opens its card OVER the sheet — the parent chain is
    # the stack the scrim cascade walks); every other route (detail panel,
    # search, mentions) keeps the default main-window parent.
    async def _on_entity_click(self, entity_type, entity_id, parent=None):
        window = self._window
        detail_vm = self._detail_vm
        card_parent = window if parent is None else parent
        try:
            entity_service = self._app._get_entity_service(entity_type)
            if not entity_service:
                return
            entity = await entity_service.get_entity(entity_id)
            if not entity:
                return

            # Handle save (update entity fields + sync relationships)
            async def on_entity_saved(result: EntityEditResult) -> None:
                try:
                    await entity_service.update_entity_with_relations(
                        entity_id, result.fields, result.characteristics,
                        result.backstory, result.related_changes,
                    )
                except Exception as exc:  # noqa: BLE001 — the modal names the reason
                    # The service's unit of work already undid the partial
                    # write; reload the timeline before the blocking modal
                    # (the same move as every other save handler); the
                    # detail stays previous — no "updated" version exists.
                    await self._reload_timeline()
                    QMessageBox.critical(
                        window, "Ошибка", f"Не удалось сохранить сущность: {exc}",
                    )
                    dialog.finish_saving(False)
                    return

                # Refresh detail panel if an event is selected
                if detail_vm.event:
                    await detail_vm.load_details(detail_vm.event.id)
                    window.detail_panel.show_event(detail_vm.event)
                # NRI-0022 (task 5.2) retargeted by NRI-0025 (task 5.2, spec
                # «Сохранение карточки перекрашивает все копии»): a save of
                # a pair shown anywhere in the column — a pin, the live card
                # or both copies of a duplicate — repaints EVERY copy from a
                # fresh read of the just-saved row; a save of any other
                # entity never reaches the right column (its pair simply
                # differs from both slot faces).
                pair = (entity_type, entity_id)
                if pair in self._preview_pins or pair == self._preview_live:
                    refreshed = await entity_service.get_entity(entity_id)
                    if refreshed is not None:
                        self._preview_rows[pair] = refreshed
                        self._push_preview_frame()
                dialog.finish_saving(True)

            dialog = await self._open_entity_card(
                entity_type, parent=card_parent, entity=entity,
                on_saved=on_entity_saved, popup_cleanup=True,
            )
            dialog.create_related_requested.connect(
                lambda a, t: self._spawn(self._open_related_create_dialog(dialog, a, t))
            )
            await self._wire_open_character_sheet(dialog, entity_type, entity_id)
            self.open_sheet(dialog)
        except Exception as exc:
            # Open-failure path (reads only happened): the unit of work
            # owns every transaction finish — plain log, no undo here.
            logging.getLogger("app.wiring").warning(
                "Не удалось открыть карточку сущности: %s", exc,
            )

    # ── Sheet show-contract (nri-0024 task 1.1, design Д1/Д2) ──────────────
    # This connector opens every sheet of the application, so one method is
    # the show path for all of them — QML-island dialogs and the widget-side
    # SheetFrame alike. A sheet entering here joins the stack (announced to
    # the window as the menu gate — Д2: with the opening entries gated, no
    # sheet needs a "single instance" window bookkeeping anymore), dims the
    # sheets it was opened over, and releases through the single ``finished``
    # channel every close route (Esc/«Отмена»/header ✕/accept/window close)
    # passes through. The sheet itself answers only the scrim duck
    # (``set_sheet_scrim_alpha``): the connector never asks what class it is.

    def open_sheet(self, sheet) -> None:
        """Show ``sheet`` (attached sheet over its parent) under the stack.

        NRI-0024 (task 5.1, design Д5) adds the reopen contour: a sheet whose
        content outlives its close (the table desk — the session rides the
        service, not the dialog) returns here for a second showing. Such a
        sheet joins the stack again but keeps the ONE release channel hooked
        at its first opening: a second lambda on ``finished`` would fire the
        release twice on the next close and the second ``remove`` would raise.
        The hook marker rides the dialog's own dynamic property, so it dies
        with the sheet and can never alias another sheet.

        PR-012 (the show half, this method's last lines): the sheet rides the
        ``Qt.Sheet`` window type with NO Qt-side modality — never ``open()``,
        never WindowModal. On cocoa ``Qt.Sheet`` is what keeps the window a
        native attached sheet (the platform plugin calls ``beginSheet`` on
        exactly this flag, independent of modality), so AppKit document
        modality still blocks the main window's layer, while the native menu
        bar answers the app's own enabled states: Qt's cocoa validation
        (``QNSViewMenuHelper.validateMenuItem:``) disables EVERY foreign
        window's menu items while a Qt-modal window is active, which is what
        used to kill the window-class exceptions under a live sheet. Off the
        native sheet the main layer is held by ``MainWindow``'s own input
        gate (the same ``sheet_stack_changed`` signal), so the block is the
        contract on every platform, not an accident of the attached window.
        """
        if sheet in self._open_sheets:
            # Already up: raise the live sheet, never stack it twice.
            sheet.raise_()
            sheet.activateWindow()
            return
        if not self._open_sheets:
            self.sheet_stack_changed.emit(True)
        self._open_sheets.append(sheet)
        self._dim_sheet_stack(sheet)
        # Default-arg capture: the release must see THIS sheet even after the
        # slot's own name is rebound (the CR5 _lift_* binding pattern).
        if not sheet.property("nriSheetReleaseHooked"):
            sheet.setProperty("nriSheetReleaseHooked", True)
            sheet.finished.connect(
                lambda _result, _sheet=sheet: self._release_sheet(_sheet)
            )
        # The type swap goes through the whole WindowType_Mask, not
        # ``setWindowFlag``: QWidget::windowType() reports the widget's
        # extra-set type (the default Window bit here), so setWindowFlag
        # would only OR the Sheet bit over the Dialog one — and the cocoa
        # plugin compares the decoded type against Qt::Sheet exactly.
        sheet.setWindowFlags(
            (sheet.windowFlags() & ~Qt.WindowType.WindowType_Mask)
            | Qt.WindowType.Sheet
        )
        sheet.setWindowModality(Qt.WindowModality.NonModal)
        sheet.show()

    def _release_sheet(self, sheet) -> None:
        """Undo :meth:`open_sheet` for the one sheet that just closed.

        PR-034 (the native attached-stack invariant, live 2026-10-05): a
        native attached sheet carries its children down with it — closing a
        LOWER sheet detaches the whole cascade, and the detached children
        never emit ``finished``. The stack's own knowledge of "attached
        over" is the Qt parent chain (design D3, the same chain the scrim
        walks), so every entry standing above ``sheet`` and chained to it
        is already dead on screen: each one is run through this very
        channel, topmost first (the direction :meth:`close_all_sheets`
        tears the stack down in), by its own plain ``close()`` — that
        emits the ``finished`` the cascade withheld, the emission re-enters
        here, and each nested release peels its scrim back. The departing
        sheet stays in ``_open_sheets`` until that cascade has passed, so
        the nested releases see a non-empty stack and the gate's single
        ``False`` for the emptied stack rides exactly this call.

        An entry above that is NOT chained to this sheet is a sibling sheet
        of the same window — cocoa detaches it with neither sheet, so it
        stays (TC-SHET-005/006: a lower sheet under any close stays whole;
        nothing lives above the top sheet, so ordinary closings never see
        this cascade at all).
        """
        if sheet not in self._open_sheets:
            # A late ``finished`` of an already-released sheet (a detached
            # child closing one turn after the cascade released it): the
            # channel already ran — a second ``remove`` would raise.
            return
        index = self._open_sheets.index(sheet)
        for over in reversed(self._open_sheets[index + 1:]):
            if self._attached_under(over, sheet):
                over.close()  # the sheet's own finished re-enters this method
        self._open_sheets.remove(sheet)
        self._lift_sheet_stack(sheet)
        if not self._open_sheets:
            self.sheet_stack_changed.emit(False)

    @staticmethod
    def _attached_under(sheet, host_sheet) -> bool:
        """True when ``sheet``'s Qt parent chain passes through ``host_sheet``.

        A child sheet is built with its parent sheet as Qt parent, which is
        what makes cocoa attach it to that sheet — so the parent's cascade
        detach takes exactly these sheets down with it.
        """
        parent = sheet.parent()
        while parent is not None:
            if parent is host_sheet:
                return True
            parent = parent.parent()
        return False

    def close_all_sheets(self) -> None:
        """Take the whole sheet stack down at once (NRI-0024 task 4.2, the
        game-switch confirmation): the switch tears its own sheet — and any
        sheet stacked over it — off the main layer before the game closes.

        Children first (reverse opening order) is the honest teardown
        direction, and the release itself stays the sheets' own: every
        :meth:`QDialog.close` passes ``finished``, so each sheet leaves
        through the single :meth:`_release_sheet` channel — the scrim walks
        back, the stack empties, and the menu gate reopens exactly the way
        an ordinary closing click does.

        PR-034 compatibility: children-first means nothing is ever left
        stacked above the sheet being closed, so the release-side cascade
        of :meth:`_release_sheet` never fires from this loop — the two
        teardown routes meet at the same single channel without recursion
        or a double release (the late-finished guard covers any stray).
        """
        for sheet in reversed(list(self._open_sheets)):
            sheet.close()

    # ── Stack depth (nri-0014 task 4.3, CR5): the one owner of the dim ──────
    # The connector is the only place that sees when a child sheet goes over
    # a parent sheet and which sheets are under it. The sheets receive the
    # finished alpha, never a layer count (design D3): the islands paint it
    # with their sheetScrim layer, the SheetFrame with its own scrim widget.

    def _dim_sheet_stack(self, child_sheet) -> None:
        """Add one scrim share to every sheet ``child_sheet`` was opened over.

        The stack is the dialogs' Qt parent chain: a sheet opened over a sheet
        has that parent sheet as ``parent()`` (the related-create popup and
        any future sheet-over-sheet flow pass it), so the walk dims every
        ancestor one share deeper than the sheet under it — the reading rule
        «нижний лист затемнён сильнее верхнего» falls out of the arithmetic.
        NRI-0024 (task 1.1) generalized the walk from the two island classes
        to the scrim duck, so widget sheets cascade exactly like islands.
        """
        host = child_sheet.parent()
        while hasattr(host, "set_sheet_scrim_alpha"):
            units = self._sheet_scrim_units.get(host, 0) + 1
            self._sheet_scrim_units[host] = units
            host.set_sheet_scrim_alpha(
                min(units * SHEET_SCRIM_ALPHA_PER_SHEET, SHEET_SCRIM_ALPHA_MAX)
            )
            host = host.parent()

    def _lift_sheet_stack(self, child_sheet) -> None:
        """Undo :meth:`_dim_sheet_stack` for the one sheet that just closed.

        Every way a QDialog leaves the screen (reject via Esc/«Отмена»/header
        ✕, accept after a save, the window-manager close through done) emits
        ``finished`` — the single release channel hooked by :meth:`open_sheet`,
        so a scrim can never outlive the sheet that caused it.
        """
        host = child_sheet.parent()
        while hasattr(host, "set_sheet_scrim_alpha"):
            units = self._sheet_scrim_units.get(host, 1) - 1
            if units > 0:
                self._sheet_scrim_units[host] = units
            else:
                self._sheet_scrim_units.pop(host, None)
            host.set_sheet_scrim_alpha(
                min(units * SHEET_SCRIM_ALPHA_PER_SHEET, SHEET_SCRIM_ALPHA_MAX)
                if units > 0
                else 0.0
            )
            host = host.parent()

    # ── Shared helper: popup for creating a related entity ─────────────
    # One card window opened from the parent dialog (event or entity card)
    # through _open_entity_card (task 5.10). On save the entity and its own
    # links are written as one unit of work (task 5.8): the row never
    # rides a later unrelated finish, and rejecting the parent deletes it
    # through the cleanup's own transaction (tasks 5.4/5.6, audit Q14
    # scenario 1 stays closed). The nested «Создать нового» stays unwired
    # (depth = 1) and — design claim 2026-10-06, a shown button must work —
    # this card is built with related_create_enabled=False, so its sections
    # HIDE the entry instead of showing one that silently does nothing;
    # «Привязать существующего» and «Отвязать» work and stay visible.
    async def _open_related_create_dialog(self, parent_dialog, attr_name: str, entity_type: str):
        async def on_sub_saved(result: EntityCreateResult) -> None:
            sub_svc = self._app._get_entity_service(entity_type)
            if not sub_svc:
                sub_dialog.finish_saving(False)
                return
            try:
                async with self._uow.transaction():
                    new_entity = await sub_svc.create_entity(
                        characteristics=result.characteristics,
                        backstory=result.backstory,
                        **result.fields,
                    )
                    # The one related_changes sync loop (C3), link-only.
                    # Inside the same transaction: the entity and its
                    # links are one atomic write (task 5.8).
                    await sub_svc.apply_related_changes(
                        new_entity, result.related_changes,
                    )
            except Exception as exc:  # noqa: BLE001
                # The unit of work rolled the partial state (description
                # row, failed entity) back so the shared session is left
                # usable; the user gets the reason.
                QMessageBox.critical(
                    self._window, "Ошибка создания сущности", str(exc)
                )
                sub_dialog.finish_saving(False)
                return
            parent_dialog.add_related_entity(attr_name, new_entity)
            self._popup_created.setdefault(parent_dialog, []).append(
                (entity_type, new_entity.id, new_entity.description_id)
            )
            sub_dialog.finish_saving(True)

        sub_dialog = await self._open_entity_card(
            entity_type, parent=parent_dialog, on_saved=on_sub_saved,
            related_create_enabled=False,
        )
        # NRI-0014 task 4.3 (CR5) + NRI-0024 task 1.1: the show contract does
        # what the manual dim/finished pair did before it was generalized —
        # the child sheet darkens the sheets under it for exactly as long as
        # it is open, and it rides the stack the same way its parent does.
        self.open_sheet(sub_dialog)

    async def _cleanup_popup_entities(self, parent_dialog) -> None:
        """Delete popup-created rows when the parent dialog is rejected.

        Popup saves persist through the unit of work (task 5.8) — rows a user
        cancelled must therefore be deleted explicitly and that delete
        persisted (tasks 5.4/5.6, audit Q14 scenario 1): the cleanup runs as
        its own transaction, so the removal lands at once instead of hanging
        pending to ride a later save or burn in an unrelated revert.
        The deletion itself is the entity service's (task 5.11) — this glue
        opened the transaction and owns the pending list, nothing more.
        """
        pending = self._popup_created.pop(parent_dialog, [])
        if not pending:
            return
        async with self._uow.transaction():
            for entity_type, entity_id, description_id in pending:
                service = self._app._get_entity_service(entity_type)
                await service.delete_entity_and_description(entity_id, description_id)
        # NRI-0022 (task 5.2) rewritten by NRI-0025 (task 5.2, design Д4):
        # this is still the connector's entity-delete channel, now retargeted
        # onto the slots — deleting a PINNED entity lifts its pin in the
        # column and in storage (spec «Удаление снимает закрепление»),
        # deleting the LIVE one clears the live area only (spec preview-pins
        # «Удаление показанной в живой области сущности очистит живую
        # область»). A delete touching neither face leaves the column alone;
        # None-safe: a pair never equals the empty live pointer.
        deleted = {(entity_type, entity_id) for entity_type, entity_id, _d in pending}
        changed = False
        if any(pair in deleted for pair in self._preview_pins):
            self._preview_pins = [
                pair for pair in self._preview_pins if pair not in deleted
            ]
            changed = True
            await self._save_preview_pins()
        if self._preview_live in deleted:
            self._preview_live = None
            changed = True
        if changed:
            self._preview_rows = {
                pair: row
                for pair, row in self._preview_rows.items()
                if pair not in deleted
            }
            self._push_preview_frame()
