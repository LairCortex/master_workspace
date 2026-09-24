"""Main-window signal wiring — thin glue between UI signals and services.

Moved 1:1 from ``Application._wire_signals`` (the "glue layer"): Qt signals
+ ``asyncio.ensure_future`` mechanism preserved, handlers only unpack dialog
data, call the services, and refresh the panels.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine

from PySide6.QtWidgets import QMessageBox

from app.application.services.event_service import EventService
from app.application.services.xlsx_import_service import XlsxImportService
from app.domain import entity_registry
from app.domain.date_era import era_key
from app.infrastructure.db.uow import GameSessionUoW
from app.presentation.dialog_results import (
    EntityCreateResult,
    EntityEditResult,
    EventDialogResult,
    EventEditResult,
)
from app.presentation.utils.date_utils import split_date_era
from app.presentation.viewmodels.detail_viewmodel import DetailViewModel
from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.event_types_dialog import EventTypesDialog
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


class ApplicationWiring:
    """Connects main-window signals to services/viewmodels.

    ``app`` is the owning Application (session + service catalog + dialog
    mention/AI helpers); everything else is the window's component set.
    """

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
    ) -> None:
        self._app = app
        self._window = window
        self._timeline_vm = timeline_vm
        self._detail_vm = detail_vm
        self._search_vm = search_vm
        self._event_dialog_vm = event_dialog_vm
        self._event_service = event_service
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
        self._connect_event_dialogs()
        self._connect_entity_cards()
        self._connect_search()
        self._connect_snapshot()

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
            dlg.open()

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
            dialog.open()

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

        # Add event button
        def on_add_event():
            dialog = EventDialog(event_dialog_vm, parent=window, theme=self._app._theme)
            self._spawn(self._load_available_into_dialog(dialog))
            self._spawn(self._load_types_into_dialog(dialog))
            self._app._wire_mentions_for_dialog(dialog, self._on_entity_click)
            self._app._wire_ai_buttons(dialog)

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
            dialog.open()

        self._timeline.add_event_requested.connect(on_add_event)

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
                dialog.open()
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
                dialog = EventDialog(event_dialog_vm, parent=window, theme=self._app._theme)
                await self._load_available_into_dialog(dialog)
                # Types before populate: the selector gets the game's set, then
                # populate() preselects this event's current type (W4 6.3).
                dialog.set_event_types(list(await event_service.get_event_types()))
                dialog.populate(event)
                self._app._wire_mentions_for_dialog(dialog, self._on_entity_click)
                self._app._wire_ai_buttons(dialog)

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
                dialog.open()
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

    def _connect_search(self) -> None:
        """Search bar: the query dispatch and the result-open flows."""
        window = self._window
        timeline_vm = self._timeline_vm
        search_vm = self._search_vm

        # Search
        async def on_search(query):
            await search_vm.search(query)

        window.search_bar.search_requested.connect(
            lambda q: self._spawn(on_search(q))
        )

        # Search result click -> open entity card (or select event in timeline)
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
                # Plain await, not a new spawn: on_search_result's own task
                # already holds the session lock (see _spawn at the connect
                # site below), and on_entity_click never acquires it itself.
                await self._on_entity_click(entity_type, entity_id)

        window.search_bar.result_selected.connect(
            lambda t, i: self._spawn(on_search_result(t, i))
        )

    def _connect_snapshot(self) -> None:
        """World-snapshot panel: the date query and the entity double-click."""
        window = self._window
        event_service = self._event_service

        # World snapshot — date query. The bridge carries a (date, era) pair
        # (task 3.4); the query itself is key-based, so era_key translates it
        # here exactly once (a bare legacy date reads as «н.э.»).
        async def on_snapshot_requested(target):
            if target is None:
                events = await event_service.get_all_events()
            else:
                target_date, target_bc = split_date_era(target)
                events = await event_service.get_events_at_date(
                    era_key(target_date, bool(target_bc))
                )
            window.world_snapshot.populate(events, target)

        window.world_snapshot.snapshot_requested.connect(
            lambda d: self._spawn(on_snapshot_requested(d))
        )

        # World snapshot — entity double-click (reuse _on_entity_click)
        window.world_snapshot.entity_clicked.connect(
            lambda t, i: self._spawn(self._on_entity_click(t, i))
        )

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
        """Load all entities from DB and set them as available for linking."""
        dialog.set_available_entities(
            "organizations",
            list(await self._app._entity_services["organization"].get_all()),
        )
        dialog.set_available_entities(
            "characters",
            list(await self._app._entity_services["character"].get_all()),
        )
        dialog.set_available_entities(
            "items",
            list(await self._app._entity_services["item"].get_all()),
        )
        dialog.set_available_entities(
            "locations",
            list(await self._app._entity_services["location"].get_all()),
        )

    async def _load_types_into_dialog(self, dialog) -> None:
        """Fill the event dialog's type selector with the game's set (W4)."""
        dialog.set_event_types(list(await self._event_service.get_event_types()))

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
    ):
        dialog = EntityCardDialog(
            None, entity_type=entity_type, parent=parent,
            theme=self._app._theme,
        )
        if entity is not None:
            dialog.populate(entity)
        self._app._wire_mentions_for_dialog(dialog, self._on_entity_click)
        self._app._wire_ai_buttons(dialog)
        self._wire_image_picked(dialog)
        if load_available:
            # Load available related entities for linking (registry, wave 3).
            # Plain awaits: every caller runs inside its own locked task.
            for cfg in entity_registry.related_refs_for_key(entity_type):
                rel_svc = self._app._get_entity_service(cfg.entity_type.value)
                if rel_svc:
                    available = await rel_svc.get_all()
                    dialog.set_available_entities(cfg.attr, list(available))
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

    # Entity card double-click
    async def _on_entity_click(self, entity_type, entity_id):
        window = self._window
        detail_vm = self._detail_vm
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
                dialog.finish_saving(True)

            dialog = await self._open_entity_card(
                entity_type, parent=window, entity=entity,
                on_saved=on_entity_saved, popup_cleanup=True,
            )
            dialog.create_related_requested.connect(
                lambda a, t: self._spawn(self._open_related_create_dialog(dialog, a, t))
            )
            await self._wire_open_character_sheet(dialog, entity_type, entity_id)
            dialog.open()
        except Exception as exc:
            # Open-failure path (reads only happened): the unit of work
            # owns every transaction finish — plain log, no undo here.
            logging.getLogger("app.wiring").warning(
                "Не удалось открыть карточку сущности: %s", exc,
            )

    # ── Sheet stack (nri-0014 task 4.3, CR5): the one owner of stack depth ──
    # This connector opens every dialog of the sheet flows, so it is the only
    # place that sees when a child sheet goes over a parent sheet and which
    # sheets are under it. The islands receive the finished alpha, never a
    # layer count (design D3): the dim is painted by their sheetScrim layer.

    def _dim_sheet_stack(self, child_sheet) -> None:
        """Add one scrim share to every sheet ``child_sheet`` was opened over.

        The stack is the dialogs' Qt parent chain: a sheet opened over a sheet
        has that parent sheet as ``parent()`` (the related-create popup and
        any future sheet-over-sheet flow pass it), so the walk dims every
        ancestor one share deeper than the sheet under it — the reading rule
        «нижний лист затемнён сильнее верхнего» falls out of the arithmetic.
        """
        host = child_sheet.parent()
        while isinstance(host, (EventDialog, EntityCardDialog)):
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
        ``finished`` — the single release channel hooked at the opening site
        below, so a scrim can never outlive the sheet that caused it.
        """
        host = child_sheet.parent()
        while isinstance(host, (EventDialog, EntityCardDialog)):
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
    # scenario 1 stays closed). Nested «Создать нового» is intentionally
    # not wired (depth = 1).
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
        )
        # NRI-0014 task 4.3 (CR5): the child sheet darkens the sheets under it
        # for exactly as long as it is open — finished is the one channel every
        # close route (reject/accept/window close) passes through.
        self._dim_sheet_stack(sub_dialog)
        sub_dialog.finished.connect(
            lambda _r, _c=sub_dialog: self._lift_sheet_stack(_c)
        )
        sub_dialog.open()

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
