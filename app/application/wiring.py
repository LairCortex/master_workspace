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

from app.application.services.event_service import EventService, _TYPE_UNSET
from app.application.services.xlsx_import_service import XlsxImportService
from app.infrastructure.db.models import DescriptionModel
from app.presentation.views.entity_card_dialog import EntityCardDialog, _RELATED_CONFIG
from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.event_types_dialog import EventTypesDialog
from app.presentation.views.xlsx_import_dialog import XlsxImportDialog, save_template_as


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
    ) -> None:
        self._app = app
        self._window = window
        self._timeline_vm = timeline_vm
        self._detail_vm = detail_vm
        self._search_vm = search_vm
        self._event_dialog_vm = event_dialog_vm
        self._event_service = event_service
        self._on_edit_event = None
        # Serializes every task spawned below (via ``_spawn``) against the
        # single shared AsyncSession: SQLAlchemy's AsyncSession does not
        # support concurrent operations on one connection — two overlapping
        # tasks racing on it can leave an awaited Future unresolved forever
        # (an asyncio hang, not a clean "concurrent operations" error), which
        # is what timed out the E2E suite before this lock covered every
        # session-touching task uniformly. Acquired exactly once per task in
        # ``_run_locked``; nested helper coroutines reached via plain
        # ``await`` (not through ``_spawn``) must never acquire it themselves.
        self._session_lock = asyncio.Lock()
        # parent_dialog → [(entity_type, entity_id, description_id)] for
        # entities created in its popups: flushed but not committed, so they
        # are explicitly deleted if the parent dialog is rejected.
        self._popup_created: dict[Any, list[tuple[str, int, int]]] = {}
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

    def connect(self) -> None:
        """Connect all signals (called once from Application.start)."""
        window = self._window
        timeline_vm = self._timeline_vm
        detail_vm = self._detail_vm
        search_vm = self._search_vm
        event_service = self._event_service
        event_dialog_vm = self._event_dialog_vm

        # Timeline selection -> detail panel (W3: the signal carries event ids)
        async def on_event_selected(event_id):
            timeline_vm.select_event_by_id(event_id)
            event = timeline_vm.selected_event
            if event:
                await detail_vm.load_details(event.id)
                window.detail_panel.show_event(detail_vm.event)
            else:
                window.detail_panel.clear()

        window.timeline_widget.event_selected.connect(
            lambda event_id: self._spawn(on_event_selected(event_id))
        )

        # «Выбор даты» window (task 7.1): the panel's single window_changed
        # channel writes the ViewModel's navigation window (None bounds =
        # «Все дни»), the tape re-models over the overlap-visible sample.
        def on_window_changed(start, end):
            timeline_vm.window = (start, end)
            window.timeline_widget.update_events(timeline_vm.events)

        window.timeline_widget.window_changed.connect(on_window_changed)

        # A selection the ViewModel had to prune (the event fell out of the
        # visible set, e.g. after a window move) must leave the detail panel
        # too: the scale drops the id while re-modelling the new set, the
        # panel has no other reason to notice.
        def on_selected_event_changed():
            if timeline_vm.selected_event is None:
                window.detail_panel.clear()
                window.timeline_widget.set_selected(None)

        timeline_vm.selected_event_changed.connect(on_selected_event_changed)

        # ── XLSX import (rework 4.3): one menu entry, one flow ─────────────
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
                    plan = await self._xlsx_import.analyze_file(
                        path, session=self._app._session
                    )
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
                        plan, self._app._session, progress_callback=dlg.set_progress,
                    )
                except Exception as exc:  # noqa: BLE001
                    # apply_plan уже откатил транзакцию (design D6) —
                    # причину принимает диалог (в т.ч. уже закрытый: publish_*
                    # проверяют живость C++-стороны перед показом).
                    dlg.publish_import_failure(str(exc))
                    return
                await timeline_vm.load_events()
                window.timeline_widget.update_events(timeline_vm.events)
                dlg.publish_report(report)

            dlg.analyze_requested.connect(lambda path: self._spawn(_analyze(path)))
            dlg.confirm_import.connect(lambda: self._spawn(_confirm()))
            # «Скачать шаблон» (task 5.2): pure file flow — save--as dialog +
            # byte copy of the bundled resource, no session involved.
            dlg.download_template.connect(lambda: save_template_as(dlg))
            dlg.finished.connect(lambda _: dlg.deleteLater())
            dlg.open()

        window.import_xlsx_action.triggered.connect(_run_import)

        # ── Helper: load available entities and set them on dialog sections ──
        async def _load_available_into_dialog(dialog):
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

        async def _load_types_into_dialog(dialog):
            """Fill the event dialog's type selector with the game's set (W4)."""
            dialog.set_event_types(list(await event_service.get_event_types()))

        async def _reload_timeline():
            """Re-read events and re-render the scale (selection/window kept)."""
            await timeline_vm.load_events()
            window.timeline_widget.update_events(timeline_vm.events)

        # ── Event types (W4 6.1/6.2): dialog entry in the panel's «+» menu ──
        def on_event_types():
            dialog = EventTypesDialog(
                event_service, run=self._spawn, parent=window,
                theme=self._app._theme,
            )

            dialog.types_changed.connect(lambda: self._spawn(_reload_timeline()))
            dialog.open()

        window.timeline_widget.event_types_requested.connect(on_event_types)

        # Add event button
        def on_add_event():
            dialog = EventDialog(event_dialog_vm, parent=window, theme=self._app._theme)
            self._spawn(_load_available_into_dialog(dialog))
            self._spawn(_load_types_into_dialog(dialog))
            self._app._wire_mentions_for_dialog(dialog, on_entity_click)
            self._app._wire_ai_buttons(dialog)

            async def on_saved(data):
                relations = {
                    "organizations": data.pop("organizations", []),
                    "characters": data.pop("characters", []),
                    "items": data.pop("items", []),
                    "locations": data.pop("locations", []),
                }
                try:
                    await event_service.create_event_with_relations(
                        name=data.pop("name"),
                        start_date=data.pop("start_date"),
                        end_date=data.pop("end_date"),
                        characteristics=data.pop("characteristics", ""),
                        backstory=data.pop("backstory", ""),
                        relations=relations,
                        event_type_id=data.pop("event_type_id", None),
                    )
                except Exception as exc:  # noqa: BLE001 — причину показывает модалка
                    # Транзакцию уже откатил сервис; ленту перегружаем до модалки
                    # (тот же приём, что в других save-handler'ах), чтобы под
                    # блокирующий QMessageBox осталось консистентное состояние.
                    await _reload_timeline()
                    QMessageBox.critical(
                        window, "Ошибка", f"Не удалось сохранить событие: {exc}",
                    )
                    dialog.finish_saving(False)
                    return
                await timeline_vm.load_events()
                window.timeline_widget.update_events(timeline_vm.events)
                dialog.finish_saving(True)

            dialog.saved.connect(lambda data: self._spawn(on_saved(data)))
            dialog.create_related_requested.connect(
                lambda a, t: self._spawn(_open_related_create_dialog(dialog, a, t))
            )
            dialog.accepted.connect(lambda: self._popup_created.pop(dialog, None))
            dialog.rejected.connect(
                lambda: self._spawn(self._cleanup_popup_entities(dialog))
            )
            dialog.open()

        window.timeline_widget.add_event_requested.connect(on_add_event)

        # Create standalone entities from timeline "+" context menu
        async def on_add_entity(entity_type: str):
            try:
                entity_service = self._app._get_entity_service(entity_type)
                if not entity_service:
                    return

                dialog = EntityCardDialog(
                    None, entity_type=entity_type, parent=window,
                    theme=self._app._theme,
                )
                self._app._wire_mentions_for_dialog(dialog, on_entity_click)
                self._app._wire_ai_buttons(dialog)
                self._wire_image_picked(dialog)

                async def on_entity_saved(data):
                    try:
                        data.pop("related_changes", None)
                        chars_text = data.pop("characteristics", "")
                        backstory_text = data.pop("backstory", "")
                        await entity_service.create_entity(
                            characteristics=chars_text,
                            backstory=backstory_text,
                            **data,
                        )
                        await self._app._session.commit()
                    except Exception as exc:  # noqa: BLE001 — причину показывает модалка
                        # Путь СОХРАНЕНИЯ данных (сущность ещё не создана):
                        # откат здесь — владелец этого транзакционного блока, +
                        # то же уведомление, что и в остальных save-handler'ах
                        # (save-error-reporting). Частичный refresh не нужен:
                        # объект не создан, лента сущностей на шкале не показывается.
                        await self._app._session.rollback()
                        QMessageBox.critical(
                            window, "Ошибка", f"Не удалось создать сущность: {exc}",
                        )
                        dialog.finish_saving(False)
                        return
                    dialog.finish_saving(True)

                dialog.saved.connect(lambda d: self._spawn(on_entity_saved(d)))
                dialog.open()
            except Exception as exc:
                # Путь «ДИАЛОГ НЕ ОТКРЫЛСЯ» (конструктор/поповер), а не сбой
                # сохранения данных: только откат + лог, БЕЗ модалки — чтобы
                # провал открытия не плодил двойные сообщения. Ср. on_entity_saved
                # выше — там путь сохранения, он сообщает пользователю.
                await self._app._session.rollback()
                logging.getLogger("app.wiring").warning(
                    "Не удалось открыть диалог создания сущности: %s", exc,
                )

        window.timeline_widget.add_entity_requested.connect(
            lambda t: self._spawn(on_add_entity(t))
        )

        # Edit event (double-click on timeline)
        async def on_edit_event(event_id):
            try:
                event = await event_service.get_event(event_id)
                if not event:
                    return
                dialog = EventDialog(event_dialog_vm, parent=window, theme=self._app._theme)
                await _load_available_into_dialog(dialog)
                # Types before populate: the selector gets the game's set, then
                # populate() preselects this event's current type (W4 6.3).
                dialog.set_event_types(list(await event_service.get_event_types()))
                dialog.populate(event)
                self._app._wire_mentions_for_dialog(dialog, on_entity_click)
                self._app._wire_ai_buttons(dialog)

                async def on_event_updated(data):
                    eid = data.pop("event_id", None)
                    relations = {
                        "organizations": data.pop("organizations", []),
                        "characters": data.pop("characters", []),
                        "items": data.pop("items", []),
                        "locations": data.pop("locations", []),
                    }
                    try:
                        await event_service.update_event_with_relations(
                            eid,
                            name=data.pop("name"),
                            start_date=data.pop("start_date"),
                            end_date=data.pop("end_date"),
                            characteristics=data.pop("characteristics", ""),
                            backstory=data.pop("backstory", ""),
                            relations=relations,
                            event_type_id=data.pop("event_type_id", _TYPE_UNSET),
                        )
                    except Exception as exc:  # noqa: BLE001 — причину показывает модалка
                        # Откат уже выполнен сервисом. Перезагружаем ленту до
                        # модалки (тот же приём, что в других save-handler'ах);
                        # детальную панель НЕ обновляем — «обновлённой» версии нет,
                        # показываем прежнее.
                        await _reload_timeline()
                        QMessageBox.critical(
                            window, "Ошибка", f"Не удалось сохранить событие: {exc}",
                        )
                        dialog.finish_saving(False)
                        return
                    await timeline_vm.load_events()
                    window.timeline_widget.update_events(timeline_vm.events)

                    # Refresh detail panel
                    await detail_vm.load_details(eid)
                    window.detail_panel.show_event(detail_vm.event)
                    dialog.finish_saving(True)

                dialog.saved.connect(lambda d: self._spawn(on_event_updated(d)))
                dialog.create_related_requested.connect(
                    lambda a, t: self._spawn(_open_related_create_dialog(dialog, a, t))
                )
                dialog.accepted.connect(lambda: self._popup_created.pop(dialog, None))
                dialog.rejected.connect(
                    lambda: self._spawn(self._cleanup_popup_entities(dialog))
                )
                dialog.open()
            except Exception:
                await self._app._session.rollback()

        self._on_edit_event = on_edit_event

        window.timeline_widget.event_double_clicked.connect(
            lambda eid: self._spawn(on_edit_event(eid))
        )

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
                    await on_event_selected(entity_id)
                    scale = window.timeline_widget
                    # The window reset may have re-modelled the list to
                    # «Все дни»: the list repaints from the ViewModel before
                    # the highlight — the same sample push every other
                    # mutation path performs, otherwise the re-modelled row
                    # would exist in the VM but not on the panel.
                    scale.update_events(timeline_vm.events)
                    scale.set_selected(entity_id)
                    scale.scroll_to_event(entity_id)
            else:
                # Plain await, not a new spawn: on_search_result's own task
                # already holds the session lock (see _spawn at the connect
                # site below), and on_entity_click never acquires it itself.
                await on_entity_click(entity_type, entity_id)

        window.search_bar.result_selected.connect(
            lambda t, i: self._spawn(on_search_result(t, i))
        )

        async def _wire_open_character_sheet(dialog, entity_type, entity_id):
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
        async def on_entity_click(entity_type, entity_id):
            try:
                entity_service = self._app._get_entity_service(entity_type)
                if not entity_service:
                    return
                entity = await entity_service.get_entity(entity_id)
                if not entity:
                    return

                dialog = EntityCardDialog(
                    None, entity_type=entity_type, parent=window,
                    theme=self._app._theme,
                )
                dialog.populate(entity)
                self._app._wire_mentions_for_dialog(dialog, on_entity_click)
                self._app._wire_ai_buttons(dialog)
                self._wire_image_picked(dialog)

                # Load available related entities for linking
                related_configs = _RELATED_CONFIG.get(entity_type, [])
                for cfg in related_configs:
                    rel_svc = self._app._get_entity_service(cfg["entity_type"])
                    if rel_svc:
                        available = await rel_svc.get_all()
                        dialog.set_available_entities(cfg["attr"], list(available))

                # Handle save (update entity fields + sync relationships)
                async def on_entity_saved(data):
                    related_changes = data.pop("related_changes", {})
                    chars_text = data.pop("characteristics", "")
                    backstory_text = data.pop("backstory", "")
                    field_data = {k: v for k, v in data.items() if k not in ("characteristics", "backstory")}
                    try:
                        await entity_service.update_entity_with_relations(
                            entity_id, field_data, chars_text, backstory_text, related_changes,
                        )
                    except Exception as exc:  # noqa: BLE001 — причину показывает модалка
                        # Откат уже выполнен сервисом; перегружаем ленту до
                        # модалки (тот же приём, что в других save-handler'ах),
                        # деталь не обновляем — обновлённой версии нет.
                        await _reload_timeline()
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

                dialog.saved.connect(lambda d: self._spawn(on_entity_saved(d)))

                dialog.create_related_requested.connect(
                    lambda a, t: self._spawn(_open_related_create_dialog(dialog, a, t))
                )
                await _wire_open_character_sheet(dialog, entity_type, entity_id)
                dialog.accepted.connect(lambda: self._popup_created.pop(dialog, None))
                dialog.rejected.connect(
                    lambda: self._spawn(self._cleanup_popup_entities(dialog))
                )

                dialog.open()
            except Exception:
                await self._app._session.rollback()

        # ── Shared helper: popup for creating a related entity ─────────────
        # One card window opened from the parent dialog (event or entity card).
        # On save the entity is created + flushed (no commit) and attached to
        # the parent's section; commit happens with the parent dialog's save.
        # Nested «Создать нового» is intentionally not wired (depth = 1).
        async def _open_related_create_dialog(parent_dialog, attr_name: str, entity_type: str):
            sub_dialog = EntityCardDialog(
                None, entity_type=entity_type, parent=parent_dialog,
                theme=self._app._theme,
            )
            self._app._wire_mentions_for_dialog(sub_dialog, on_entity_click)
            self._app._wire_ai_buttons(sub_dialog)
            self._wire_image_picked(sub_dialog)

            # Fill the popup's own related sections so «Привязать существующего»
            # works inside. Plain awaits: this runs inside the task already
            # spawned (locked) at the connect site that scheduled us.
            for cfg in _RELATED_CONFIG.get(entity_type, []):
                rel_svc = self._app._get_entity_service(cfg["entity_type"])
                if rel_svc:
                    available = await rel_svc.get_all()
                    sub_dialog.set_available_entities(cfg["attr"], list(available))

            async def on_sub_saved(sub_data):
                related_changes = sub_data.pop("related_changes", {})
                sub_svc = self._app._get_entity_service(entity_type)
                if not sub_svc:
                    sub_dialog.finish_saving(False)
                    return
                chars_text = sub_data.pop("characteristics", "")
                backstory_text = sub_data.pop("backstory", "")
                try:
                    new_entity = await sub_svc.create_entity(
                        characteristics=chars_text,
                        backstory=backstory_text,
                        **sub_data,
                    )
                    await self._app._session.flush()
                    for attr, change in related_changes.items():
                        current_ids = change.get("current_ids", [])
                        if not current_ids:
                            continue
                        # Pre-load the collection (link-only sync must not lazy-load).
                        await self._app._session.refresh(new_entity, attribute_names=[attr])
                        await sub_svc.sync_related(new_entity, attr, set(current_ids))
                except Exception as exc:  # noqa: BLE001
                    # Roll back the partial state (description row, failed
                    # entity) so the shared session is left usable, and notify.
                    await self._app._session.rollback()
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

            sub_dialog.saved.connect(lambda d: self._spawn(on_sub_saved(d)))
            sub_dialog.open()

        window.detail_panel.entity_clicked.connect(
            lambda t, i: self._spawn(on_entity_click(t, i))
        )

        # World snapshot — date query
        async def on_snapshot_requested(target_date):
            if target_date is None:
                events = await event_service.get_all_events()
            else:
                events = await event_service.get_events_at_date(target_date)
            window.world_snapshot.populate(events, target_date)

        window.world_snapshot.snapshot_requested.connect(
            lambda d: self._spawn(on_snapshot_requested(d))
        )

        # World snapshot — entity double-click (reuse on_entity_click)
        window.world_snapshot.entity_clicked.connect(
            lambda t, i: self._spawn(on_entity_click(t, i))
        )

    async def _cleanup_popup_entities(self, parent_dialog) -> None:
        """Delete popup-created rows when the parent dialog is rejected.

        Popup saves only flush (no commit): without this cleanup the flushed
        rows (entities, their descriptions, M2M links) sit pending in the
        shared session and ride any later commit, persisting entities the
        user cancelled.
        """
        pending = self._popup_created.pop(parent_dialog, [])
        if not pending:
            return
        for entity_type, entity_id, description_id in pending:
            service = self._app._get_entity_service(entity_type)
            entity = await service.get_entity(entity_id)
            if entity is not None:
                await self._app._session.delete(entity)
            description = await self._app._session.get(DescriptionModel, description_id)
            if description is not None:
                await self._app._session.delete(description)
        await self._app._session.flush()
