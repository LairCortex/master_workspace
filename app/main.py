"""Application entry point — DI, qasync, startup."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from app.infrastructure.db.database import create_engine, create_session_factory
from app.infrastructure.db.game_manager import export_game, get_db_url
from app.infrastructure.db.models import Base, GameSettingsModel
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.repositories.rating_repository import RatingRepository
from app.infrastructure.db.models import DescriptionModel

from app.application.services.event_service import EventService
from app.application.services.search_service import SearchService
from app.application.services.entity_service import EntityService
from app.application.services.xlsx_import_service import XlsxImportService
from app.application.services.llm_service import LlmService

from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.viewmodels.detail_viewmodel import DetailViewModel
from app.presentation.viewmodels.search_viewmodel import SearchViewModel
from app.presentation.viewmodels.event_dialog_viewmodel import EventDialogViewModel
from app.presentation.viewmodels.llm_viewmodel import (
    FIELD_PROMPTS_KEY, WORLD_PROMPT_KEY, LlmViewModel,
)

from app.presentation.utils.date_utils import (
    SETTINGS_KEY, get_custom_months, months_from_json, months_to_json, set_custom_months,
)
from app.infrastructure.http import AppHttpClient
from app.infrastructure.llm.config import LlmConfig, LlmConfigManager
from app.infrastructure.llm.remote_provider import RemoteLlmProvider
from app.presentation.views.main_window import MainWindow
from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.game_launcher_dialog import GameLauncherDialog
from app.presentation.views.month_settings_dialog import MonthSettingsDialog
from app.presentation.views.llm_setup_dialog import LlmSetupDialog

# Map attr names to entity_type strings for relationship syncing
_ATTR_TO_ENTITY_TYPE = {
    "characters": "character",
    "items": "item",
    "organizations": "organization",
    "locations": "location",
}


async def _migrate_nullable_end_dates(conn):
    """Make end_date columns nullable in existing databases (SQLite table rebuild)."""
    import re
    tables = ["events", "organizations", "characters", "items", "locations", "ratings"]
    for table in tables:
        try:
            rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
        except Exception:
            continue
        for row in rows:
            # row: (cid, name, type, notnull, dflt_value, pk)
            if row[1] == "end_date" and row[3] == 1:  # notnull == 1 → needs fix
                sql_result = (await conn.exec_driver_sql(
                    f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'"
                )).scalar()
                if not sql_result:
                    break
                new_sql = re.sub(
                    r'(end_date\s+\w+)\s+NOT\s+NULL',
                    r'\1',
                    sql_result,
                    flags=re.IGNORECASE,
                )
                tmp = f"__{table}_tmp"
                new_sql = new_sql.replace(f'"{table}"', f'"{tmp}"', 1).replace(f" {table} ", f" {tmp} ", 1).replace(f" {table}(", f" {tmp}(", 1)
                if tmp not in new_sql:
                    new_sql = new_sql.replace(table, tmp, 1)
                col_names = ", ".join(r[1] for r in rows)
                await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
                await conn.exec_driver_sql(new_sql)
                await conn.exec_driver_sql(
                    f"INSERT INTO {tmp} ({col_names}) SELECT {col_names} FROM {table}"
                )
                await conn.exec_driver_sql(f"DROP TABLE {table}")
                await conn.exec_driver_sql(f"ALTER TABLE {tmp} RENAME TO {table}")
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                break


async def init_db(engine):
    """Create tables if they don't exist, and migrate missing columns."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Migrate missing columns for existing databases
    _MIGRATIONS = [
        ("organizations", "rating", "INTEGER DEFAULT 1"),
        ("characters", "rating", "INTEGER DEFAULT 1"),
        ("items", "rating", "INTEGER DEFAULT 1"),
        ("locations", "rating", "INTEGER DEFAULT 1"),
        ("organizations", "image", "TEXT"),
        ("organizations", "music_url", "TEXT"),
        ("characters", "music_url", "TEXT"),
        ("items", "music_url", "TEXT"),
        ("locations", "music_url", "TEXT"),
    ]
    async with engine.begin() as conn:
        for table, column, col_type in _MIGRATIONS:
            try:
                await conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                )
            except Exception:
                pass  # column already exists

    # Migrate end_date NOT NULL → nullable
    async with engine.begin() as conn:
        await _migrate_nullable_end_dates(conn)


class Application:
    """Wires up DI and manages the application lifecycle."""

    def __init__(self, qapp: QApplication) -> None:
        self._qapp = qapp
        self.engine = None
        self.session_factory = None
        self._session = None
        self._window: MainWindow | None = None
        self._db_path: str | None = None

        self._config_manager = LlmConfigManager()
        self._http: AppHttpClient | None = None
        self._llm_service: LlmService | None = None
        self._llm_vm: LlmViewModel | None = None

    async def start(self, db_path: str) -> MainWindow:
        """Initialize DB, create all layers, show main window."""
        self._db_path = db_path
        db_url = get_db_url(db_path)
        self.engine = create_engine(db_url)
        self.session_factory = create_session_factory(self.engine)
        await init_db(self.engine)
        self._session = self.session_factory()

        game_name = Path(db_path).stem

        # Load custom month names
        await self._load_month_settings()

        # Repositories
        desc_repo = BaseRepository(self._session, DescriptionModel)
        event_repo = EventRepository(self._session)
        org_repo = OrganizationRepository(self._session)
        char_repo = CharacterRepository(self._session)
        item_repo = ItemRepository(self._session)
        loc_repo = LocationRepository(self._session)
        rating_repo = RatingRepository(self._session)

        # Services
        event_service = EventService(event_repo=event_repo, description_repo=desc_repo)
        search_service = SearchService(
            event=event_repo,
            organization=org_repo,
            character=char_repo,
            item=item_repo,
            location=loc_repo,
        )

        # ViewModels
        timeline_vm = TimelineViewModel(event_service)
        detail_vm = DetailViewModel(event_service)
        search_vm = SearchViewModel(search_service)
        event_dialog_vm = EventDialogViewModel(event_service)

        # LLM: shared http client + provider from the global connection config
        self._http = AppHttpClient()
        self._llm_service = LlmService(RemoteLlmProvider(LlmConfig(), self._http))
        self._llm_vm = LlmViewModel(self._llm_service, self._config_manager, self._http)

        # Load LLM settings
        await self._load_llm_settings()

        # Main window
        window = MainWindow(
            timeline_vm=timeline_vm,
            detail_vm=detail_vm,
            search_vm=search_vm,
            llm_vm=self._llm_vm,
            game_name=game_name,
        )

        self._search_service = search_service

        # Wire signals
        self._wire_signals(window, timeline_vm, detail_vm, search_vm, event_dialog_vm, event_service)

        # Switch game menu
        window.switch_game_requested.connect(lambda: asyncio.ensure_future(self._on_switch_game()))

        # Export game menu
        window.export_requested.connect(self._on_export_game)

        # Month settings menu
        window.month_settings_requested.connect(
            lambda: asyncio.ensure_future(self._on_month_settings(window, timeline_vm))
        )

        # LLM setup menu
        window.llm_setup_requested.connect(
            lambda: self._on_llm_setup(window)
        )

        # Initial load
        await timeline_vm.load_events()
        window.timeline_widget.update_events(timeline_vm.events)

        # Replace old window if switching
        if self._window is not None:
            self._window.close()
        self._window = window
        window.show()
        return window

    def _on_export_game(self) -> None:
        """Export current game as .nri archive."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        if not self._db_path:
            return
        game_name = Path(self._db_path).stem
        dest, _ = QFileDialog.getSaveFileName(
            self._window,
            "Экспорт игры",
            f"{game_name}.nri",
            "NRI архив (*.nri);;Все файлы (*)",
        )
        if not dest:
            return
        try:
            export_game(self._db_path, dest)
            QMessageBox.information(
                self._window, "Экспорт", f"Игра «{game_name}» успешно экспортирована.",
            )
        except Exception as e:
            QMessageBox.critical(self._window, "Ошибка экспорта", str(e))

    async def _on_switch_game(self) -> None:
        """Show launcher, switch to selected game."""
        dialog = GameLauncherDialog(parent=self._window)

        async def _do_switch(path: str):
            await self.shutdown()
            await self.start(path)

        dialog.game_selected.connect(lambda p: asyncio.ensure_future(_do_switch(p)))
        dialog.open()

    def _wire_signals(self, window, timeline_vm, detail_vm, search_vm, event_dialog_vm, event_service):
        """Connect signals between components."""

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
        desc_repo = BaseRepository(self._session, DescriptionModel)
        org_svc = EntityService(repo=OrganizationRepository(self._session), description_repo=desc_repo)
        char_svc = EntityService(repo=CharacterRepository(self._session), description_repo=desc_repo)
        item_svc = EntityService(repo=ItemRepository(self._session), description_repo=desc_repo)
        loc_svc = EntityService(repo=LocationRepository(self._session), description_repo=desc_repo)
        xlsx_import = XlsxImportService(
            event_service=event_service,
            character_service=char_svc,
            location_service=loc_svc,
            organization_service=org_svc,
            item_service=item_svc,
        )

        async def _run_import(entity_type: str):
            from PySide6.QtWidgets import QMessageBox
            from app.presentation.views.xlsx_import_dialog import XlsxImportDialog

            dlg = XlsxImportDialog(entity_type, window)
            dlg.open()

            async def _do_import(path: str):
                try:
                    result = await xlsx_import.import_file(
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

        # ── Helper: load available entities and set them on dialog tabs ──
        async def _load_available_into_dialog(dialog):
            """Load all entities from DB and set them as available for linking."""
            desc_repo = BaseRepository(self._session, DescriptionModel)
            org_svc = EntityService(repo=OrganizationRepository(self._session), description_repo=desc_repo)
            char_svc = EntityService(repo=CharacterRepository(self._session), description_repo=desc_repo)
            item_svc = EntityService(repo=ItemRepository(self._session), description_repo=desc_repo)
            loc_svc = EntityService(repo=LocationRepository(self._session), description_repo=desc_repo)
            dialog.org_tab.set_available_entities(list(await org_svc.get_all()))
            dialog.char_tab.set_available_entities(list(await char_svc.get_all()))
            dialog.item_tab.set_available_entities(list(await item_svc.get_all()))
            dialog.loc_tab.set_available_entities(list(await loc_svc.get_all()))

        # ── Helper: process entity items (existing → link, new → create) ──
        async def _process_entity_items(items, repo_cls, event_collection):
            desc_repo = BaseRepository(self._session, DescriptionModel)
            existing_ids = {obj.id for obj in event_collection}
            new_ids = set()

            for ent in items:
                eid = ent.get("_existing_id")
                if eid:
                    new_ids.add(eid)
                    if eid not in existing_ids:
                        svc = EntityService(repo=repo_cls(self._session), description_repo=desc_repo)
                        obj = await svc.get_entity(eid)
                        if obj:
                            event_collection.append(obj)
                else:
                    svc = EntityService(repo=repo_cls(self._session), description_repo=desc_repo)
                    obj = await svc.create_entity(**ent)
                    event_collection.append(obj)
                    new_ids.add(obj.id)

            # Remove unlinked entities (were in event before but not in new list)
            to_remove = [obj for obj in event_collection if obj.id not in new_ids]
            for obj in to_remove:
                event_collection.remove(obj)

        # Add event button
        def on_add_event():
            dialog = EventDialog(event_dialog_vm, parent=window)
            asyncio.ensure_future(_load_available_into_dialog(dialog))
            self._wire_mentions_for_dialog(dialog, on_entity_click)
            self._wire_ai_buttons(dialog)

            async def on_saved(data):
                try:
                    org_items = data.pop("organizations", [])
                    char_items = data.pop("characters", [])
                    item_items = data.pop("items", [])
                    loc_items = data.pop("locations", [])

                    event = await event_service.create_event(**data)
                    await self._session.refresh(event, attribute_names=["organizations", "characters", "items", "locations"])

                    await _process_entity_items(org_items, OrganizationRepository, event.organizations)
                    await _process_entity_items(char_items, CharacterRepository, event.characters)
                    await _process_entity_items(item_items, ItemRepository, event.items)
                    await _process_entity_items(loc_items, LocationRepository, event.locations)

                    await self._session.commit()
                    await timeline_vm.load_events()
                    window.timeline_widget.update_events(timeline_vm.events)
                except Exception:
                    await self._session.rollback()

            dialog.saved.connect(lambda data: asyncio.ensure_future(on_saved(data)))
            dialog.open()

        window.timeline_widget.add_event_requested.connect(on_add_event)

        # Create standalone entities from timeline "+" context menu
        async def on_add_entity(entity_type: str):
            try:
                entity_service = self._get_entity_service(entity_type)
                if not entity_service:
                    return

                dialog = EntityCardDialog(None, entity_type=entity_type, parent=window)
                self._wire_mentions_for_dialog(dialog, on_entity_click)
                self._wire_ai_buttons(dialog)

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
                        await self._session.commit()
                    except Exception:
                        await self._session.rollback()

                dialog.saved.connect(lambda d: asyncio.ensure_future(on_entity_saved(d)))
                dialog.open()
            except Exception:
                await self._session.rollback()

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
                self._wire_mentions_for_dialog(dialog, on_entity_click)
                self._wire_ai_buttons(dialog)

                async def on_event_updated(data):
                    try:
                        eid = data.pop("event_id", None)
                        chars_text = data.pop("characteristics", "")
                        backstory_text = data.pop("backstory", "")
                        org_items = data.pop("organizations", [])
                        char_items = data.pop("characters", [])
                        item_items = data.pop("items", [])
                        loc_items = data.pop("locations", [])

                        await event_service.update_event(
                            event_id,
                            name=data["name"],
                            start_date=data["start_date"],
                            end_date=data["end_date"],
                        )

                        # Update description
                        updated_event = await event_service.get_event(event_id)
                        if updated_event and updated_event.description:
                            updated_event.description.characteristics = chars_text
                            updated_event.description.backstory = backstory_text

                        # Sync M2M relationships
                        await self._session.refresh(updated_event, attribute_names=["organizations", "characters", "items", "locations"])
                        await _process_entity_items(org_items, OrganizationRepository, updated_event.organizations)
                        await _process_entity_items(char_items, CharacterRepository, updated_event.characters)
                        await _process_entity_items(item_items, ItemRepository, updated_event.items)
                        await _process_entity_items(loc_items, LocationRepository, updated_event.locations)

                        await self._session.commit()
                        await timeline_vm.load_events()
                        window.timeline_widget.update_events(timeline_vm.events)

                        # Refresh detail panel
                        await detail_vm.load_details(event_id)
                        window.detail_panel.show_event(detail_vm.event)
                    except Exception:
                        await self._session.rollback()

                dialog.saved.connect(lambda d: asyncio.ensure_future(on_event_updated(d)))
                dialog.open()
            except Exception:
                await self._session.rollback()

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
                entity_service = self._get_entity_service(entity_type)
                if not entity_service:
                    return
                entity = await entity_service.get_entity(entity_id)
                if not entity:
                    return

                dialog = EntityCardDialog(None, entity_type=entity_type, parent=window)
                dialog.populate(entity)
                self._wire_mentions_for_dialog(dialog, on_entity_click)
                self._wire_ai_buttons(dialog)

                # Load available related entities for linking
                from app.presentation.views.entity_card_dialog import _RELATED_CONFIG
                related_configs = _RELATED_CONFIG.get(entity_type, [])
                for cfg in related_configs:
                    rel_svc = self._get_entity_service(cfg["entity_type"])
                    if rel_svc:
                        available = await rel_svc.get_all()
                        dialog.set_available_entities(cfg["attr"], list(available))

                # Handle save (update entity fields + sync relationships)
                async def on_entity_saved(data):
                    try:
                        related_changes = data.pop("related_changes", {})
                        chars_text = data.pop("characteristics", "")
                        backstory_text = data.pop("backstory", "")

                        # Update basic entity fields
                        field_data = {k: v for k, v in data.items() if k not in ("characteristics", "backstory")}
                        await entity_service.update_entity(entity_id, **field_data)

                        # Update description
                        refreshed = await entity_service.get_entity(entity_id)
                        if refreshed and refreshed.description:
                            refreshed.description.characteristics = chars_text
                            refreshed.description.backstory = backstory_text

                        # Sync M2M relationships
                        for attr_name, change_data in related_changes.items():
                            desired_ids = set(change_data.get("current_ids", []))
                            rel_type = _ATTR_TO_ENTITY_TYPE.get(attr_name)
                            if not rel_type:
                                continue
                            rel_svc = self._get_entity_service(rel_type)
                            if not rel_svc:
                                continue

                            ent = await entity_service.get_entity(entity_id)
                            await self._session.refresh(ent, attribute_names=[attr_name])
                            current_collection = getattr(ent, attr_name)
                            current_ids = {e.id for e in current_collection}

                            # Add missing
                            for aid in desired_ids - current_ids:
                                rel_entity = await rel_svc.get_entity(aid)
                                if rel_entity:
                                    current_collection.append(rel_entity)

                            # Remove extras
                            to_remove = [e for e in current_collection if e.id in (current_ids - desired_ids)]
                            for e in to_remove:
                                current_collection.remove(e)

                        await self._session.commit()

                        # Refresh detail panel if an event is selected
                        if detail_vm.event:
                            await detail_vm.load_details(detail_vm.event.id)
                            window.detail_panel.show_event(detail_vm.event)
                    except Exception:
                        await self._session.rollback()

                dialog.saved.connect(lambda d: asyncio.ensure_future(on_entity_saved(d)))

                # Handle create new related entity
                async def on_create_related(attr_name, related_entity_type):
                    sub_dialog = EntityCardDialog(None, entity_type=related_entity_type, parent=dialog)
                    self._wire_mentions_for_dialog(sub_dialog, on_entity_click)
                    self._wire_ai_buttons(sub_dialog)

                    async def on_sub_saved(sub_data):
                        sub_data.pop("related_changes", None)
                        sub_svc = self._get_entity_service(related_entity_type)
                        if not sub_svc:
                            return
                        chars_text = sub_data.pop("characteristics", "")
                        backstory_text = sub_data.pop("backstory", "")
                        new_entity = await sub_svc.create_entity(
                            characteristics=chars_text,
                            backstory=backstory_text,
                            **sub_data,
                        )
                        await self._session.flush()
                        dialog.add_related_entity(attr_name, new_entity)

                    sub_dialog.saved.connect(lambda d: asyncio.ensure_future(on_sub_saved(d)))
                    sub_dialog.open()

                dialog.create_related_requested.connect(
                    lambda a, t: asyncio.ensure_future(on_create_related(a, t))
                )

                dialog.open()
            except Exception:
                await self._session.rollback()

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

    def _wire_mentions_for_dialog(self, dialog, on_entity_click_fn):
        """Connect mention search and click signals for a dialog's MentionTextEdits."""
        for edit in dialog.get_mention_edits():
            async def _do_search(query, _edit=edit):
                try:
                    results = await self._search_service.search_names(query)
                    _edit.show_mention_results(results)
                except Exception:
                    pass

            edit.mention_search_requested.connect(
                lambda q, _fn=_do_search: asyncio.ensure_future(_fn(q))
            )

        dialog.mention_clicked.connect(
            lambda t, i: asyncio.ensure_future(on_entity_click_fn(t, i))
        )

    def _get_entity_service(self, entity_type: str) -> EntityService | None:
        desc_repo = BaseRepository(self._session, DescriptionModel)
        repo_map = {
            "organization": OrganizationRepository(self._session),
            "character": CharacterRepository(self._session),
            "item": ItemRepository(self._session),
            "location": LocationRepository(self._session),
        }
        repo = repo_map.get(entity_type)
        if repo:
            return EntityService(repo=repo, description_repo=desc_repo)
        return None

    async def _load_month_settings(self) -> None:
        """Load custom month names from game_settings table."""
        from sqlalchemy import select
        try:
            result = await self._session.execute(
                select(GameSettingsModel).where(GameSettingsModel.key == SETTINGS_KEY)
            )
            row = result.scalars().first()
            if row:
                months = months_from_json(row.value)
                set_custom_months(months)
            else:
                set_custom_months(None)
        except Exception:
            set_custom_months(None)

    async def _save_month_settings(self, months: dict) -> None:
        """Save custom month names to game_settings table."""
        from sqlalchemy import select
        result = await self._session.execute(
            select(GameSettingsModel).where(GameSettingsModel.key == SETTINGS_KEY)
        )
        row = result.scalars().first()
        value = months_to_json(months)
        if row:
            row.value = value
        else:
            self._session.add(GameSettingsModel(key=SETTINGS_KEY, value=value))
        await self._session.commit()

    async def _on_month_settings(self, window, timeline_vm) -> None:
        """Show month settings dialog and apply changes."""
        dialog = MonthSettingsDialog(get_custom_months(), parent=window)

        async def _on_saved(months):
            set_custom_months(months)
            await self._save_month_settings(months)
            # Refresh all views with new month names
            await timeline_vm.load_events()
            window.timeline_widget.update_events(timeline_vm.events)

        dialog.saved.connect(lambda m: asyncio.ensure_future(_on_saved(m)))
        dialog.open()

    def _wire_ai_buttons(self, dialog) -> None:
        """Connect AI buttons in a dialog to the LLM ViewModel."""
        if not hasattr(dialog, "get_ai_buttons"):
            return
        llm_vm = self._llm_vm
        for btn in dialog.get_ai_buttons():
            btn.update_llm_state(llm_vm.status, llm_vm.has_world_prompt)
            llm_vm.model_status_changed.connect(
                lambda _s, _b=btn: _b.update_llm_state(llm_vm.status, llm_vm.has_world_prompt)
            )

            def _on_generate(et, fn, fl, ct, _btn=btn):
                field_id = f"{et}.{fn}"
                log = logging.getLogger("llm.wire")
                log.info("AI button clicked: %s, label=%s, text=%r", field_id, fl, ct[:50] if ct else "")
                _btn.set_generating(True)

                async def _do():
                    try:
                        await llm_vm.request_generation(field_id, et, fn, fl, ct)
                    except Exception as exc:
                        log.error("Generation failed: %s — %s", field_id, exc)
                        _btn.set_generating(False)

                asyncio.ensure_future(_do())

            btn.generate_requested.connect(_on_generate)

            def _on_finished(fid, text, _btn=btn, _et=btn.entity_type, _fn=btn.field_name):
                expected_id = f"{_et}.{_fn}"
                if fid == expected_id:
                    _btn.set_result_text(text)

            def _on_error(fid, _err, _btn=btn, _et=btn.entity_type, _fn=btn.field_name):
                expected_id = f"{_et}.{_fn}"
                if fid == expected_id:
                    _btn.set_generating(False)

            llm_vm.generation_finished.connect(_on_finished)
            llm_vm.generation_error.connect(_on_error)

    def _on_llm_setup(self, window) -> None:
        llm_vm = self._llm_vm
        dialog = LlmSetupDialog(
            config=llm_vm.config,
            world_prompt=llm_vm.world_prompt,
            field_prompts=llm_vm.field_prompts,
            http=self._http,
            parent=window,
        )

        async def _on_saved(config, world_prompt, field_prompts):
            self._config_manager.save(config)
            llm_vm.world_prompt = world_prompt
            llm_vm.field_prompts = field_prompts
            llm_vm.apply_config(config)
            await self._save_llm_settings()

        dialog.saved.connect(lambda c, wp, fp: asyncio.ensure_future(_on_saved(c, wp, fp)))
        dialog.open()

    async def _load_llm_settings(self) -> None:
        from sqlalchemy import select
        try:
            result = await self._session.execute(
                select(GameSettingsModel).where(GameSettingsModel.key == WORLD_PROMPT_KEY)
            )
            row = result.scalars().first()
            if row:
                self._llm_vm.world_prompt_from_json(row.value)

            result2 = await self._session.execute(
                select(GameSettingsModel).where(GameSettingsModel.key == FIELD_PROMPTS_KEY)
            )
            row2 = result2.scalars().first()
            if row2:
                self._llm_vm.field_prompts_from_json(row2.value)
        except Exception:
            pass

    async def _save_llm_settings(self) -> None:
        from sqlalchemy import select
        for key, value in [
            (WORLD_PROMPT_KEY, self._llm_vm.world_prompt_to_json()),
            (FIELD_PROMPTS_KEY, self._llm_vm.field_prompts_to_json()),
        ]:
            result = await self._session.execute(
                select(GameSettingsModel).where(GameSettingsModel.key == key)
            )
            row = result.scalars().first()
            if row:
                row.value = value
            else:
                self._session.add(GameSettingsModel(key=key, value=value))
        await self._session.commit()

    async def shutdown(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
        if self.engine:
            await self.engine.dispose()
            self.engine = None
        if self._llm_service is not None:
            await self._llm_service.provider.close()
            self._llm_service = None
            self._llm_vm = None
        if self._http is not None and not self._http.is_closed:
            await self._http.close()
        self._http = None


def main():
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    application = Application(app)

    # Show launcher
    launcher = GameLauncherDialog()
    result = launcher.exec()
    if not launcher.selected_path:
        sys.exit(0)

    db_path = launcher.selected_path

    with loop:
        loop.run_until_complete(application.start(db_path))
        loop.run_forever()


if __name__ == "__main__":
    main()
