"""Main-window signal wiring — thin glue between UI signals and services.

Moved 1:1 from ``Application._wire_signals`` (the "glue layer"): Qt signals
+ ``asyncio.ensure_future`` mechanism preserved, handlers only unpack dialog
data, call the services, and refresh the panels.
"""
from __future__ import annotations

import asyncio

from PySide6.QtWidgets import QMessageBox

from app.application.services.event_service import EventService
from app.application.services.xlsx_import_service import XlsxImportService
from app.presentation.views.entity_card_dialog import EntityCardDialog, _RELATED_CONFIG
from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.xlsx_import_dialog import XlsxImportDialog


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
        self._xlsx_import = XlsxImportService(
            event_service=event_service,
            character_service=app._entity_services["character"],
            location_service=app._entity_services["location"],
            organization_service=app._entity_services["organization"],
            item_service=app._entity_services["item"],
        )

    def connect(self) -> None:
        """Connect all signals (called once from Application.start)."""
        window = self._window
        timeline_vm = self._timeline_vm
        detail_vm = self._detail_vm
        search_vm = self._search_vm
        event_service = self._event_service
        event_dialog_vm = self._event_dialog_vm

        # Timeline selection -> detail panel
        async def on_event_selected(index):
            timeline_vm.select_event(index)
            event = timeline_vm.selected_event
            if event:
                await detail_vm.load_details(event.id)
                window.detail_panel.show_event(detail_vm.event)
            else:
                window.detail_panel.clear()

        window.timeline_widget.event_selected.connect(
            lambda idx: asyncio.ensure_future(on_event_selected(idx))
        )

        # Date range filter
        def on_filter_changed(start, end):
            timeline_vm.filter_by_dates(start, end)
            window.timeline_widget.update_events(timeline_vm.events)

        window.timeline_widget.filter_changed.connect(on_filter_changed)

        # ── XLSX import actions ─────────────────────────────────────────────
        async def _run_import(entity_type: str):
            dlg = XlsxImportDialog(entity_type, window)
            dlg.open()

            async def _do_import(path: str):
                try:
                    result = await self._xlsx_import.import_file(
                        entity_type, path, progress_callback=dlg.set_progress
                    )
                    await timeline_vm.load_events()
                    window.timeline_widget.update_events(timeline_vm.events)
                    msg = f"Создано записей: {result.created}"
                    if result.errors:
                        msg += "\n\nНекоторые строки пропущены:\n- " + "\n- ".join(result.errors[:10])
                    QMessageBox.information(window, "Импорт завершён", msg)
                except Exception as exc:  # noqa: BLE001
                    QMessageBox.critical(window, "Ошибка импорта", str(exc))
                finally:
                    dlg.close()

            dlg.import_requested.connect(lambda p: asyncio.ensure_future(_do_import(p)))

        window.import_events_action.triggered.connect(
            lambda: asyncio.ensure_future(_run_import("event"))
        )
        window.import_characters_action.triggered.connect(
            lambda: asyncio.ensure_future(_run_import("character"))
        )
        window.import_locations_action.triggered.connect(
            lambda: asyncio.ensure_future(_run_import("location"))
        )
        window.import_organizations_action.triggered.connect(
            lambda: asyncio.ensure_future(_run_import("organization"))
        )
        window.import_items_action.triggered.connect(
            lambda: asyncio.ensure_future(_run_import("item"))
        )

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

        # Add event button
        def on_add_event():
            dialog = EventDialog(event_dialog_vm, parent=window)
            asyncio.ensure_future(_load_available_into_dialog(dialog))
            self._app._wire_mentions_for_dialog(dialog, on_entity_click)
            self._app._wire_ai_buttons(dialog)

            async def on_saved(data):
                relations = {
                    "organizations": data.pop("organizations", []),
                    "characters": data.pop("characters", []),
                    "items": data.pop("items", []),
                    "locations": data.pop("locations", []),
                }
                await event_service.create_event_with_relations(
                    name=data.pop("name"),
                    start_date=data.pop("start_date"),
                    end_date=data.pop("end_date"),
                    characteristics=data.pop("characteristics", ""),
                    backstory=data.pop("backstory", ""),
                    relations=relations,
                )
                await timeline_vm.load_events()
                window.timeline_widget.update_events(timeline_vm.events)

            dialog.saved.connect(lambda data: asyncio.ensure_future(on_saved(data)))
            dialog.create_related_requested.connect(
                lambda a, t: asyncio.ensure_future(
                    _open_related_create_dialog(dialog, a, t)
                )
            )
            dialog.open()

        window.timeline_widget.add_event_requested.connect(on_add_event)

        # Create standalone entities from timeline "+" context menu
        async def on_add_entity(entity_type: str):
            try:
                entity_service = self._app._get_entity_service(entity_type)
                if not entity_service:
                    return

                dialog = EntityCardDialog(None, entity_type=entity_type, parent=window)
                self._app._wire_mentions_for_dialog(dialog, on_entity_click)
                self._app._wire_ai_buttons(dialog)

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
                    except Exception:
                        await self._app._session.rollback()

                dialog.saved.connect(lambda d: asyncio.ensure_future(on_entity_saved(d)))
                dialog.open()
            except Exception:
                await self._app._session.rollback()

        window.timeline_widget.add_entity_requested.connect(
            lambda t: asyncio.ensure_future(on_add_entity(t))
        )

        # Edit event (double-click on timeline)
        async def on_edit_event(event_id):
            try:
                event = await event_service.get_event(event_id)
                if not event:
                    return
                dialog = EventDialog(event_dialog_vm, parent=window)
                await _load_available_into_dialog(dialog)
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
                    await event_service.update_event_with_relations(
                        eid,
                        name=data.pop("name"),
                        start_date=data.pop("start_date"),
                        end_date=data.pop("end_date"),
                        characteristics=data.pop("characteristics", ""),
                        backstory=data.pop("backstory", ""),
                        relations=relations,
                    )
                    await timeline_vm.load_events()
                    window.timeline_widget.update_events(timeline_vm.events)

                    # Refresh detail panel
                    await detail_vm.load_details(eid)
                    window.detail_panel.show_event(detail_vm.event)

                dialog.saved.connect(lambda d: asyncio.ensure_future(on_event_updated(d)))
                dialog.create_related_requested.connect(
                    lambda a, t: asyncio.ensure_future(
                        _open_related_create_dialog(dialog, a, t)
                    )
                )
                dialog.open()
            except Exception:
                await self._app._session.rollback()

        window.timeline_widget.event_double_clicked.connect(
            lambda eid: asyncio.ensure_future(on_edit_event(eid))
        )

        # Search
        async def on_search(query):
            await search_vm.search(query)

        window.search_bar.search_requested.connect(
            lambda q: asyncio.ensure_future(on_search(q))
        )

        # Search result click -> open entity card (or select event in timeline)
        async def on_search_result(entity_type, entity_id):
            if entity_type == "event":
                # Select in timeline and show details
                for i, ev in enumerate(timeline_vm.events):
                    if ev.id == entity_id:
                        window.timeline_widget.list_widget.setCurrentRow(i)
                        break
            else:
                await on_entity_click(entity_type, entity_id)

        window.search_bar.result_selected.connect(
            lambda t, i: asyncio.ensure_future(on_search_result(t, i))
        )

        # Entity card double-click
        async def on_entity_click(entity_type, entity_id):
            try:
                entity_service = self._app._get_entity_service(entity_type)
                if not entity_service:
                    return
                entity = await entity_service.get_entity(entity_id)
                if not entity:
                    return

                dialog = EntityCardDialog(None, entity_type=entity_type, parent=window)
                dialog.populate(entity)
                self._app._wire_mentions_for_dialog(dialog, on_entity_click)
                self._app._wire_ai_buttons(dialog)

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
                    await entity_service.update_entity_with_relations(
                        entity_id, field_data, chars_text, backstory_text, related_changes,
                    )

                    # Refresh detail panel if an event is selected
                    if detail_vm.event:
                        await detail_vm.load_details(detail_vm.event.id)
                        window.detail_panel.show_event(detail_vm.event)

                dialog.saved.connect(lambda d: asyncio.ensure_future(on_entity_saved(d)))

                dialog.create_related_requested.connect(
                    lambda a, t: asyncio.ensure_future(
                        _open_related_create_dialog(dialog, a, t)
                    )
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
            )
            self._app._wire_mentions_for_dialog(sub_dialog, on_entity_click)
            self._app._wire_ai_buttons(sub_dialog)

            # Fill the popup's own related sections so «Привязать существующего» works inside.
            for cfg in _RELATED_CONFIG.get(entity_type, []):
                rel_svc = self._app._get_entity_service(cfg["entity_type"])
                if rel_svc:
                    available = await rel_svc.get_all()
                    sub_dialog.set_available_entities(cfg["attr"], list(available))

            async def on_sub_saved(sub_data):
                related_changes = sub_data.pop("related_changes", {})
                sub_svc = self._app._get_entity_service(entity_type)
                if not sub_svc:
                    return
                chars_text = sub_data.pop("characteristics", "")
                backstory_text = sub_data.pop("backstory", "")
                new_entity = await sub_svc.create_entity(
                    characteristics=chars_text,
                    backstory=backstory_text,
                    **sub_data,
                )
                await self._app._session.flush()
                for attr, change in related_changes.items():
                    # Pre-load the collection (link-only sync must not lazy-load).
                    await self._app._session.refresh(new_entity, attribute_names=[attr])
                    await sub_svc.sync_related(
                        new_entity, attr, set(change.get("current_ids", []))
                    )
                parent_dialog.add_related_entity(attr_name, new_entity)

            sub_dialog.saved.connect(lambda d: asyncio.ensure_future(on_sub_saved(d)))
            sub_dialog.open()

        window.detail_panel.entity_clicked.connect(
            lambda t, i: asyncio.ensure_future(on_entity_click(t, i))
        )

        # World snapshot — date query
        async def on_snapshot_requested(target_date):
            if target_date is None:
                events = await event_service.get_all_events()
            else:
                events = await event_service.get_events_at_date(target_date)
            window.world_snapshot.populate(events, target_date)

        window.world_snapshot.snapshot_requested.connect(
            lambda d: asyncio.ensure_future(on_snapshot_requested(d))
        )

        # World snapshot — entity double-click (reuse on_entity_click)
        window.world_snapshot.entity_clicked.connect(
            lambda t, i: asyncio.ensure_future(on_entity_click(t, i))
        )
