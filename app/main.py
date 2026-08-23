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
from app.infrastructure.db.migrations import init_db
from app.infrastructure.db.game_manager import export_game, get_db_url
from app.infrastructure.db.models import GameSettingsModel
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.db.models import DescriptionModel

from app.application.services.event_service import EventService
from app.application.services.search_service import SearchService
from app.application.services.entity_service import EntityService
from app.application.services.llm_service import LlmService
from app.application.wiring import ApplicationWiring

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
from app.presentation.views.game_launcher_dialog import GameLauncherDialog
from app.presentation.views.month_settings_dialog import MonthSettingsDialog
from app.presentation.views.llm_setup_dialog import LlmSetupDialog

class Application:
    """Wires up DI and manages the application lifecycle."""

    def __init__(self, qapp: QApplication, http: AppHttpClient | None = None) -> None:
        """Wires up DI and manages the application lifecycle.

        ``http`` is the optional application-wide HTTP client (injected by
        tests with an emulated transport). When omitted the application
        creates and closes its own default client per start/shutdown cycle.
        """
        self._qapp = qapp
        self.engine = None
        self.session_factory = None
        self._session = None
        self._window: MainWindow | None = None
        self._db_path: str | None = None

        self._config_manager = LlmConfigManager()
        self._http_injected: AppHttpClient | None = http
        self._http: AppHttpClient | None = None
        self._llm_service: LlmService | None = None
        self._llm_vm: LlmViewModel | None = None
        # Entity service catalog — built once per game in start()
        self._entity_services: dict[str, EntityService] = {}
        self._wiring: ApplicationWiring | None = None

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

        # Services
        self._entity_services = self._build_entity_services()
        event_service = EventService(
            event_repo=event_repo,
            description_repo=desc_repo,
            organization_service=self._entity_services["organization"],
            character_service=self._entity_services["character"],
            item_service=self._entity_services["item"],
            location_service=self._entity_services["location"],
        )
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

        # LLM: shared http client (injected in tests) + provider from the global connection config
        self._http = self._http_injected if self._http_injected is not None else AppHttpClient()
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
        self._wiring = ApplicationWiring(
            self, window, timeline_vm, detail_vm, search_vm, event_dialog_vm, event_service,
        )
        self._wiring.connect()

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

    def _wire_mentions_for_dialog(self, dialog, on_entity_click_fn):
        """Connect mention search and click signals for a dialog's MentionTextEdits."""
        for edit in dialog.get_mention_edits():
            async def _do_search(query, _edit=edit):
                try:
                    results = await self._search_service.search_names(query)
                    _edit.show_mention_results(results)
                except Exception as exc:
                    logging.getLogger("app.main").error(
                        "Mention search failed for %r: %s", query, exc, exc_info=True
                    )

            edit.mention_search_requested.connect(
                lambda q, _fn=_do_search: asyncio.ensure_future(_fn(q))
            )

        dialog.mention_clicked.connect(
            lambda t, i: asyncio.ensure_future(on_entity_click_fn(t, i))
        )

    def _get_entity_service(self, entity_type: str) -> EntityService | None:
        """Thin wrapper over the per-game service catalog."""
        return self._entity_services.get(entity_type)

    def _build_entity_services(self) -> dict[str, EntityService]:
        """Build the per-game catalog once (replaces per-call construction)."""
        desc_repo = BaseRepository(self._session, DescriptionModel)
        repo_map = {
            "organization": OrganizationRepository(self._session),
            "character": CharacterRepository(self._session),
            "item": ItemRepository(self._session),
            "location": LocationRepository(self._session),
        }
        services = {
            t: EntityService(repo=r, description_repo=desc_repo)
            for t, r in repo_map.items()
        }
        for type_name, svc in services.items():
            svc.set_related_services(
                {t: s for t, s in services.items() if t != type_name},
            )
        return services

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
        except Exception as exc:
            logging.getLogger("app.main").warning(
                "Failed to load month settings: %s", exc
            )
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
            ok = True
            try:
                self._config_manager.save(config)
                llm_vm.world_prompt = world_prompt
                llm_vm.field_prompts = field_prompts
                llm_vm.apply_config(config)
                if self._session is not None:
                    await self._save_llm_settings()
                else:
                    # App is shutting down: global config file is saved,
                    # per-game prompts are dropped — nothing to surface.
                    logging.getLogger("llm.setup").info(
                        "LLM session closed before per-game prompts saved"
                    )
            except Exception as exc:
                logging.getLogger("llm.setup").error("Failed to save LLM settings: %s", exc)
                ok = False
            dialog.finish_saving(ok)

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
        except Exception as exc:
            logging.getLogger("app.main").warning(
                "Failed to load LLM settings: %s", exc
            )

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
            # An injected client is owned by the caller — the app must not close it.
            if self._http is not self._http_injected:
                await self._http.close()
        self._http = None


def main():
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    application = Application(app)

    # Show launcher
    launcher = GameLauncherDialog()
    launcher.exec()
    if not launcher.selected_path:
        sys.exit(0)

    db_path = launcher.selected_path

    with loop:
        loop.run_until_complete(application.start(db_path))
        loop.run_forever()


if __name__ == "__main__":
    main()
