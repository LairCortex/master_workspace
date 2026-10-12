"""The D&D module façade composed for games whose flag is enabled.

add-dnd-module-foundation task 1.1 established the seam; group 2 grew the
lifecycle: :meth:`DndModule.attach` installs the module's section on the
window (the «D&D» badge and menu group, task 2.4), :meth:`DndModule.detach`
takes it down again, and the section's «Выключить D&D-модуль…» entry runs
the confirm → :class:`ModuleSettingsService.disable` → section-down flow of
task 2.3. The composition point may also attach the module to a live
ordinary game without a restart (the enable path, task 2.2) — the very same
attach builds the section there, and the kernel re-hides its own «Включить
D&D-модуль…» entry around the call.

Everything the façade needs from the live game arrives through the protocol
— the kernel hands it the shown window and the connector; the flag writes go
through the settings service the composition injects. The confirmation box
follows the PR-010 posture of every live-app dialog: modeless ``show()`` on
the shared loop, never a nested event loop.

Since group 5 the façade also owns the datasets screen: the section's
«Датасеты D&D…» raises (or first builds) :class:`DndDatasetsSheet` on the
connector's sheet stack — one live sheet at a time (a repeated trigger
raises the living one instead of stacking twins), and a detach takes it
down through its own ``finished`` channel. The sheet stack arrives from the
composition together with the dataset library (connections + import services
+ the theme for the sheet chrome); without it the menu prints no datasets
entry.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.dd.application.character_import_service import CharacterImportService
    from app.dd.application.dataset_connections_service import (
        DatasetConnectionsService,
    )
    from app.dd.application.dataset_import_service import DatasetImportService
    from app.dd.application.dataset_library_service import DatasetLibraryService
    from app.dd.application.generation_deps import GenerationBundle
    from app.dd.application.grimoire_connections_service import (
        GrimoireConnectionsService,
    )
    from app.dd.application.grimoire_import_service import GrimoireImportService
    from app.dd.application.module_settings_service import ModuleSettingsService
    from app.dd.application.monster_service import DdMonsterService
    from app.dd.application.reference_visibility_service import (
        ReferenceVisibilityService,
    )
    from app.dd.domain.dataset import OfficialDatasetsResult
    from app.dd.infrastructure.grimoire_storage import GrimoireStorage
    from app.dd.presentation.bestiary_sheet import DndBestiarySheet
    from app.dd.presentation.datasets_sheet import DndDatasetsSheet
    from app.dd.presentation.grimoires_sheet import DndGrimoiresSheet
    from app.dd.presentation.monster_card_sheet import DndMonsterCardSheet
    from app.dd.presentation.reference_sheet import DndReferenceSheet
    from app.dd.presentation.section import DndWindowSection
    from app.presentation.modules.protocol import ExternalEntitySource
    from app.presentation.views.main_window import MainWindow
    from app.presentation.wiring import ApplicationWiring

#: Confirmation caption and body of the disable flow (spec «Выключение модуля
#: с сохранением данных»): the master must read that the data survives and
#: only disappears from view.
DD_DISABLE_CONFIRM_TITLE = "D&D-модуль"
DD_DISABLE_CONFIRM_BODY = (
    "Выключить D&D-модуль? Данные модуля останутся в игре и будут скрыты; "
    "повторное включение вернёт их без восстановления."
)

#: Caption of the official-datasets boxes (task 3.3): the download result is
#: a fact about the global library, not about this game's menu section.
DD_DATASETS_TITLE = "D&D-датасеты"
#: Caption of the character-import boxes (add-dnd-game-face task 9.4). The
#: result is a fact about the imported person, shown on the game window.
DD_CHARACTER_IMPORT_TITLE = "Импорт персонажа из файла LSS"
#: The bootstrap blew up on something no per-row message explains (the
#: service maps every fetch failure itself) — the user still reads a reason
#: instead of silence (coding principle 3: persistence/network errors never
#: go silent).
DD_DATASETS_UNEXPECTED_BODY = (
    "Не удалось проверить и загрузить официальные наборы SRD в хранилище. "
    "Подробности — в журнале приложения; повторить загрузку можно из экрана "
    "датасетов."
)


class DndModule:
    """The game-system module for D&D 5e games (Long Story Short formats).

    The façade satisfies the kernel protocol (:class:`GameSystemModule`):
    ``attach`` binds it to one game window/connector pair and installs the
    section, ``detach`` removes it and unbinds again, and ``enabled`` reports
    the bound state. It owns no session and never commits: the one write it
    performs (the flag off) goes through the injected
    :class:`ModuleSettingsService`, whose every operation is one unit-of-work
    transaction.
    """

    def __init__(
        self,
        settings_service: Optional["ModuleSettingsService"] = None,
        datasets_service: Optional["DatasetLibraryService"] = None,
        connections_service: Optional["DatasetConnectionsService"] = None,
        import_service: Optional["DatasetImportService"] = None,
        theme: object | None = None,
        reference_visibility: Optional["ReferenceVisibilityService"] = None,
        external_sources: "Sequence[ExternalEntitySource]" = (),
        character_import: Optional["CharacterImportService"] = None,
        monster_service: Optional["DdMonsterService"] = None,
        grimoire_storage: Optional["GrimoireStorage"] = None,
        grimoire_connections: Optional["GrimoireConnectionsService"] = None,
        grimoire_import: Optional["GrimoireImportService"] = None,
        generation: Optional["GenerationBundle"] = None,
    ) -> None:
        self._settings = settings_service
        # The global dataset library (task 3.3): attach schedules its
        # idempotent official-SRD bootstrap through this service; without
        # one (a module composed without the dataset stack) the façade keeps
        # its silence and no download is ever attempted.
        self._datasets = datasets_service
        # The datasets screen stack (group 5): the two per-game services and
        # the app theme the sheet chrome wears. All three (plus the library)
        # must be present for the «Датасеты D&D…» entry to be printed at all
        # — a partial composition shows no half-working screen.
        self._connections = connections_service
        self._importer = import_service
        self._theme = theme
        # The reference-search toggle holder (add-dnd-game-face task 3.3):
        # the sheet's checkbox and the reference source read and write THIS
        # one holder; a module composed without it prints no checkbox and
        # carries no sources (a partial composition shows no half-switch).
        self._reference_visibility = reference_visibility
        # The entity sources this module contributes (design Д1): declared
        # here, READ by the composition root, which alone calls
        # register_external (guard tests/test_dd_module_isolation.py rule 3).
        self._external_sources: tuple[ExternalEntitySource, ...] = tuple(
            external_sources
        )
        self._window: MainWindow | None = None
        self._wiring: ApplicationWiring | None = None
        self._section: DndWindowSection | None = None
        # The modeless confirmation box between show and finished (PR-010
        # live-ref posture: without it Qt's garbage takes the box away).
        self._confirm_box: QMessageBox | None = None
        # The in-flight disable task (spawned through the connector's lock);
        # the live ref keeps it out of the collector until it finishes.
        self._disable_task: object | None = None
        # The in-flight official-datasets bootstrap and its result box —
        # same live-ref posture (task 3.3).
        self._bootstrap_task: asyncio.Task | None = None
        self._datasets_box: QMessageBox | None = None
        # The live datasets sheet (task 5.2): raised, never twin-stacked;
        # released through its own ``finished`` or by detach.
        self._datasets_sheet: DndDatasetsSheet | None = None
        # The live reference sheet (add-dnd-game-face task 6.3): the same
        # single-instance discipline as the datasets screen.
        self._reference_sheet: "DndReferenceSheet | None" = None
        # The character-import flow (add-dnd-game-face task 9.4): the menu's
        # creation entry exists only when the composition handed in the
        # service; its in-flight task and result box ride live refs the same
        # posture as the datasets bootstrap's pair.
        self._character_import = character_import
        self._character_import_task: asyncio.Task | None = None
        self._character_import_box: QMessageBox | None = None
        # The bestiary stack (add-dnd-game-face task 10.1): the service is
        # the screen's whole requisite (its source rides the external tuple
        # and is found by its declaration, never by a second registry). The
        # live sheet and the open cards ride the single-instance discipline
        # of the other module screens — cards keyed by monster id, the
        # creation card under ``None``, re-keyed to its row on the first
        # save.
        self._monster_service = monster_service
        self._bestiary_sheet: DndBestiarySheet | None = None
        self._monster_cards: dict[int | None, DndMonsterCardSheet] = {}
        # The grimoire stack (add-dnd-game-face task 4.5): the storage is the
        # shelf, the connections service is the game's link list, the import
        # service is the parser's decision tree — the screen's whole trio,
        # each composed once by the root. The live sheet rides the same
        # single-instance discipline as the datasets and bestiary screens.
        self._grimoire_storage = grimoire_storage
        self._grimoire_connections = grimoire_connections
        self._grimoire_import = grimoire_import
        self._grimoires_sheet: DndGrimoiresSheet | None = None
        # The generation task sheets (add-dnd-lss-generation, группа 7):
        # the bundle is the composition's whole generation stack (AI-gate
        # doors, context builder, acceptance doors); without it no entry is
        # printed (the module's no-dead-action posture). The live sheets
        # ride the same single-instance discipline as every module screen,
        # keyed by kind — one dataset task, one spellbook task, one
        # character task (create or top-up).
        self._generation = generation
        self._generation_sheets: dict[str, object] = {}
        # In-flight dataset gate check and its explanation box (spec «Гейт
        # активации генерации»: персонаж требует ≥1 подключённый датасет).
        self._generation_gate_task: asyncio.Task | None = None
        self._generation_gate_box: QMessageBox | None = None

    @property
    def enabled(self) -> bool:
        """True between ``attach`` and the matching ``detach``."""
        return self._window is not None

    @property
    def external_sources(self) -> tuple[ExternalEntitySource, ...]:
        """The entity sources the module contributes (add-dnd-game-face Д1):
        the dataset-backed reference source (task 3.2) when the composition
        handed one in — declared here, registered ONLY by the composition
        root through the single ``register_external`` door (guard
        tests/test_dd_module_isolation.py rule 3; the module never registers
        anything itself). Without a composed source the façade answers the
        protocol with nothing and the kernel keeps its kernel-only registry
        byte-for-byte (the profile pin, task 2.2)."""
        return self._external_sources

    @property
    def reference_visibility(self) -> "ReferenceVisibilityService | None":
        """The toggle holder this module's source and sheet share (task 3.3).
        The public door the composition root reads on the open/enable paths
        to perform the one stored-state load before the first window shows
        (duck-typed by main — the kernel protocol stays silent about it)."""
        return self._reference_visibility

    async def ensure_tables(self) -> None:
        """The game-open bootstrap door (add-dnd-game-face task 8.1, design
        Д6): an existing D&D game gains the module's tables additively before
        its first window — existing rows untouched, present tables skipped.
        The composition root calls this on a module composed for an OPENED
        D&D game (the live enable needs no call: its flag write and the DDL
        share one transaction inside :meth:`ModuleSettingsService.enable`).
        A façade composed without a settings service has no unit to create
        on and keeps its silence, exactly like the datasets bootstrap
        without a library."""
        if self._settings is None:
            return
        await self._settings.ensure_schema()

    def _set_sources_attached(self, attached: bool) -> None:
        """Hand the attach/detach state to the contributed sources that ask
        for it (duck door ``set_attached``, the module's own protocol among
        its own classes). Why the façade owns it: the kernel carries the
        source LIST from composition to composition and only empties it when
        the game leaves; within a live session the enable/disable flows
        attach and detach THIS façade — so the module-lifetime visibility of
        its records (the character card's «D&D»/«Заклинания» tabs: spec
        entity-card-tabs «Таб модуля живёт с модулем», spec
        dnd-character-extension «выключение модуля SHALL гасить табы»)
        rides this propagation. A source whose visibility is its own affair
        (the reference toggle) carries no door and is left alone."""
        for source in self._external_sources:
            notify = getattr(source, "set_attached", None)
            if callable(notify):
                notify(attached)

    def _set_generation_doors(self) -> None:
        """Hand the AI top-up doors to the sources that ask for it (duck door
        ``set_generation``, the module's own protocol, one posture with
        ``set_attached``). Without a composed generation bundle the doors
        are ``None``/``None`` — the tab prints no dead button."""
        deps = self._generation.deps if self._generation is not None else None
        for source in self._external_sources:
            notify = getattr(source, "set_generation", None)
            if callable(notify):
                notify(self._open_character_top_up, deps)

    def attach(self, main_window: MainWindow, wiring: ApplicationWiring) -> None:
        """Bind to THIS game's window and connector and build the section.

        The composition calls this exactly once per opened game (startup and
        the live «Включить D&D-модуль…» path share it — tasks 1.1/2.2); a
        re-attach without a detach is a composition bug, not a supported
        flow, so the façade keeps the first binding's collaborators as live
        refs. Which way the kernel's «Включить D&D-модуль…» entry stands is
        the composition's bookkeeping, not the façade's: the startup offer is
        computed with the module already in mind, and the live enable flow
        hides the entry around this call.
        """
        from app.dd.presentation.section import DndWindowSection

        self._window = main_window
        self._wiring = wiring
        self._section = DndWindowSection(
            main_window,
            datasets_available=self._datasets_screen_ready(),
            reference_available=self._reference_screen_ready(),
            character_import_available=self._character_import is not None,
            bestiary_available=self._bestiary_screen_ready(),
            grimoires_available=self._grimoires_screen_ready(),
            character_generation_available=self._generation is not None,
        )
        self._section.disable_requested.connect(self._on_disable_requested)
        self._section.datasets_requested.connect(self._on_datasets_requested)
        self._section.reference_requested.connect(self._on_reference_requested)
        self._section.character_import_requested.connect(
            self._on_character_import_requested
        )
        self._section.bestiary_requested.connect(self._on_bestiary_requested)
        self._section.grimoires_requested.connect(self._on_grimoires_requested)
        self._section.character_generation_requested.connect(
            self._on_character_generation_requested
        )
        # The module-lifetime gate for the sources that ask for it (task 8.2:
        # the character card's tabs live with the module, spec entity-card-tabs
        # «Таб модуля живёт с модулем») — set BEFORE anything can populate a
        # card, so a freshly enabled module answers its tabs at once.
        self._set_sources_attached(True)
        # Вход ИИ-дозаполнения на D&D-табах (add-dnd-lss-generation task 7.3):
        # тот же утин порядок, что и attach-state — источник собирается до
        # façade, а лист умеет поднимать только façade на стеке коннектора.
        self._set_generation_doors()
        # Task 3.3 (spec «Автозагрузка SRD-наборов»): every attach of a module
        # composed with the dataset library asks the library for the official
        # sets. The ask is idempotent (both sets present — no request at all,
        # spec «Повторный запуск не качает»), runs as its own task OUTSIDE the
        # session lock (files and network, no session touched), and can never
        # hold up or fail the game opening — results and failures surface
        # through the modeless box below (spec «Офлайн не ломает игру»).
        self._start_datasets_bootstrap()

    def detach(self) -> None:
        """Release the section and the window/connector refs; no state stays.

        Called by the composition when the game closes and, from task 2.3 on,
        when the user switches the module off — the module's data survives
        either way (spec «Выключение модуля с сохранением данных»).
        """
        # The datasets sheet is the module's screen: leaving the game (or
        # switching the module off) takes it down through its own finished
        # channel — the connector peels the stack share and reopens the menu
        # gate exactly the way a master's close click would.
        if self._datasets_sheet is not None:
            sheet = self._datasets_sheet
            self._datasets_sheet = None
            sheet.close()
        if self._reference_sheet is not None:
            sheet = self._reference_sheet
            self._reference_sheet = None
            sheet.close()
        # The bestiary screens are the module's too (task 10.1): leaving the
        # game (or switching the module off) takes the list and every open
        # card down through their own finished channels.
        if self._bestiary_sheet is not None:
            sheet = self._bestiary_sheet
            self._bestiary_sheet = None
            sheet.close()
        for card in list(self._monster_cards.values()):
            card.close()
        self._monster_cards.clear()
        # The grimoire screen too (task 4.5): its own finished channel peels
        # the stack share, exactly like a master's close click.
        if self._grimoires_sheet is not None:
            sheet = self._grimoires_sheet
            self._grimoires_sheet = None
            sheet.close()
        # Задачи генерации — экраны модуля (add-dnd-lss-generation, группа 7):
        # уход игры снимает их force_close — тихая отмена in-flight без
        # подтверждения (подтверждение принадлежит клику мастера, а не
        # снятию окна), свои finished-каналы чистят стек коннектора.
        for sheet in list(self._generation_sheets.values()):
            sheet.force_close()
        self._generation_sheets.clear()
        if self._generation_gate_task is not None:
            self._generation_gate_task.cancel()
            self._generation_gate_task = None
        self._generation_gate_box = None
        if self._section is not None:
            self._section.remove()
            self._section = None
        # The tabs the sources contributed go dark with the module — before
        # the window/connector refs drop, so a card repopulated in the same
        # session (the disable flow ends with the window still open) already
        # sees the gate closed (task 8.2, spec dnd-character-extension:
        # «выключение модуля SHALL гасить табы»).
        self._set_sources_attached(False)
        # Двери ИИ-генерации гаснут вместе с модулем: табы пересоберутся без
        # кнопки (add-dnd-lss-generation task 7.3).
        for source in self._external_sources:
            notify = getattr(source, "set_generation", None)
            if callable(notify):
                notify(None, None)
        self._window = None
        self._wiring = None
        # A confirmation box was parented to the window; when the whole game
        # leaves the box dies with it — dropping the ref here is hygiene.
        self._confirm_box = None
        # A bootstrap still in flight belongs to a game that is leaving; the
        # download itself is global and re-runs (idempotently) at the next
        # attach, so cancelling the orphan is the tidy choice. Its done
        # callback sees the cancellation and keeps quiet.
        if self._bootstrap_task is not None:
            self._bootstrap_task.cancel()
            self._bootstrap_task = None
        self._datasets_box = None
        # Same leaving-game posture for the import half (task 9.4): an
        # in-flight import belongs to a game that is leaving — its result
        # box would parent to a dying window; the file itself is untouched
        # by the cancel, the master simply imports again in the new game.
        if self._character_import_task is not None:
            self._character_import_task.cancel()
            self._character_import_task = None
        self._character_import_box = None

    # ── datasets screen (task 5.2) ─────────────────────────────────────────────

    def _datasets_screen_ready(self) -> bool:
        """The screen needs the whole service stack: library (storage face +
        SRD re-run), connections (per-game links) and the import flow — one
        missing, no entry printed (the theme is chrome, not a requisite:
        off-skin the sheet keeps the token fallbacks)."""
        return (
            self._datasets is not None
            and self._connections is not None
            and self._importer is not None
        )

    def _on_datasets_requested(self) -> None:
        """The «Датасеты D&D…» entry. The live sheet is raised, never
        twin-stacked (the module's menu entries are not in the kernel's
        gated list — the gate was built before any attach, so single
        instance is this ref's job). The first request builds the sheet as
        a child of the game window and shows it on the connector's one
        sheet path (Qt.Sheet attach, stack, scrim, menu gate — contract in
        the sheet's own docstring); the connection state then loads through
        the connector's lock."""
        if self._window is None or self._wiring is None:
            return
        if not self._datasets_screen_ready():  # belt-and-braces (no action)
            return
        if self._datasets_sheet is not None:
            self._datasets_sheet.raise_()
            self._datasets_sheet.activateWindow()
            return
        from app.dd.presentation.datasets_sheet import DndDatasetsSheet

        assert self._datasets is not None and self._connections is not None
        assert self._importer is not None  # same readiness, for the checker
        sheet = DndDatasetsSheet(
            library=self._datasets,
            connections=self._connections,
            importer=self._importer,
            run_locked=self._wiring.run_locked,
            parent=self._window,
            theme=self._theme,
            reference_visibility=self._reference_visibility,
            generation_open=(
                self._open_dataset_task_sheet
                if self._generation is not None
                else None
            ),
            generation_deps=(
                self._generation.deps if self._generation is not None else None
            ),
        )
        self._datasets_sheet = sheet
        # Default-arg capture: the release must forget THIS sheet even if a
        # newer one takes its place meanwhile (the CR5 _lift_* pattern).
        sheet.finished.connect(
            lambda _result, _sheet=sheet: self._datasets_sheet_finished(_sheet)
        )
        self._wiring.open_sheet(sheet)
        sheet.request_refresh()

    def _datasets_sheet_finished(self, sheet: DndDatasetsSheet) -> None:
        """Drop the live ref only while THIS sheet is still the resident."""
        if self._datasets_sheet is sheet:
            self._datasets_sheet = None

    # ── reference screen (add-dnd-game-face task 6.3) ────────────────────────

    def _reference_screen_ready(self) -> bool:
        """The browsing sheet browses the module's sources — with none
        composed there is nothing to list, so the menu prints no entry (the
        datasets screen's no-dead-action posture, one floor lower: the
        sheet reads only the protocol doors, no per-service stack needed)."""
        return bool(self._external_sources)

    def _on_reference_requested(self) -> None:
        """The «Справочник…» entry: the live sheet is raised, never
        twin-stacked (same single-instance rule as the datasets screen —
        these entries sit outside the kernel's gated list). The first
        request builds the sheet on the connector's one sheet path; the
        record lists then load through the connector's lock. A row click
        seats the card through the connector's public external door; the
        empty state's way out opens the datasets sheet — but only when
        that screen is actually composed (no dead button over a module
        without the datasets stack)."""
        if self._window is None or self._wiring is None:
            return
        if not self._reference_screen_ready():  # belt-and-braces (no action)
            return
        if self._reference_sheet is not None:
            self._reference_sheet.raise_()
            self._reference_sheet.activateWindow()
            return
        from app.dd.presentation.reference_sheet import DndReferenceSheet

        wiring = self._wiring
        sheet = DndReferenceSheet(
            sources=self._external_sources,
            run_locked=wiring.run_locked,
            # The connector's public door of task 6.3 (spec «клик по строке
            # открывает карточку в правой колонке»): read-only live seat,
            # serialized like every other connector flow.
            show_card=lambda key, source_id: wiring.run_locked(
                wiring.show_external_card(key, source_id)
            ),
            open_datasets=(
                self._on_datasets_requested
                if self._datasets_screen_ready()
                else None
            ),
            parent=self._window,
            theme=self._theme,
        )
        self._reference_sheet = sheet
        # Default-arg capture (the CR5 pattern): the release forgets THIS
        # sheet even if a newer one takes its place meanwhile.
        sheet.finished.connect(
            lambda _result, _sheet=sheet: self._reference_sheet_finished(_sheet)
        )
        self._wiring.open_sheet(sheet)
        sheet.request_refresh()

    def _reference_sheet_finished(self, sheet: "DndReferenceSheet") -> None:
        """Drop the live ref only while THIS sheet is still the resident."""
        if self._reference_sheet is sheet:
            self._reference_sheet = None

    # ── bestiary (add-dnd-game-face task 10.1) ───────────────────────────────

    def _bestiary_screen_ready(self) -> bool:
        """The bestiary browses and edits through the composed service (the
        same no-dead-action posture as every other module screen: without it
        the menu prints no entry)."""
        return self._monster_service is not None

    def _monster_source(self) -> "ExternalEntitySource | None":
        """The source declaring the monster type, found in the contributed
        tuple by its declaration — no second registry, no composition extra:
        the same object the composition already handed to the kernel's
        surfaces. None only in a composition without the bestiary source
        (the card then saves without reconciling a cache that does not
        exist)."""
        from app.dd.presentation.monster_source import MONSTER_TYPE

        for source in self._external_sources:
            descriptors = getattr(source, "type_descriptors", ())
            if any(
                descriptor.key == MONSTER_TYPE.key for descriptor in descriptors
            ):
                return source
        return None

    def _on_bestiary_requested(self) -> None:
        """The «Бестиарий…» entry: the live sheet is raised, never
        twin-stacked (the module's entries sit outside the kernel's gated
        list — single instance is this ref's job). The first request builds
        the sheet on the connector's one sheet path; the list then loads
        through the connector's lock."""
        if self._window is None or self._wiring is None:
            return
        if not self._bestiary_screen_ready():  # belt-and-braces (no action)
            return
        if self._bestiary_sheet is not None:
            self._bestiary_sheet.raise_()
            self._bestiary_sheet.activateWindow()
            return
        from app.dd.presentation.bestiary_sheet import DndBestiarySheet

        assert self._monster_service is not None  # same gate, for the checker
        sheet = DndBestiarySheet(
            service=self._monster_service,
            run_locked=self._wiring.run_locked,
            open_card=self._open_monster_card,
            parent=self._window,
            theme=self._theme,
        )
        self._bestiary_sheet = sheet
        # Default-arg capture (the CR5 pattern): the release forgets THIS
        # sheet even if a newer one takes its place meanwhile.
        sheet.finished.connect(
            lambda _result, _sheet=sheet: self._bestiary_sheet_finished(_sheet)
        )
        self._wiring.open_sheet(sheet)
        sheet.request_refresh()

    def _bestiary_sheet_finished(self, sheet: "DndBestiarySheet") -> None:
        """Drop the live ref only while THIS sheet is still the resident."""
        if self._bestiary_sheet is sheet:
            self._bestiary_sheet = None

    # ── grimoires (add-dnd-game-face task 4.5) ────────────────────────────────

    def _grimoires_screen_ready(self) -> bool:
        """The grimoire screen needs its whole composed trio (shelf, links,
        importer) — a partial composition prints no dead entry (the posture
        of every other module screen)."""
        return (
            self._grimoire_storage is not None
            and self._grimoire_connections is not None
            and self._grimoire_import is not None
        )

    def _on_grimoires_requested(self) -> None:
        """The «Гримуары…» entry: the live sheet is raised, never
        twin-stacked; the first request builds it on the connector's one
        sheet path and loads the connection frame through the lock."""
        if self._window is None or self._wiring is None:
            return
        if not self._grimoires_screen_ready():  # belt-and-braces (no action)
            return
        if self._grimoires_sheet is not None:
            self._grimoires_sheet.raise_()
            self._grimoires_sheet.activateWindow()
            return
        from app.dd.presentation.grimoires_sheet import DndGrimoiresSheet

        assert self._grimoire_storage is not None  # same gate, for the checker
        assert self._grimoire_connections is not None
        assert self._grimoire_import is not None
        sheet = DndGrimoiresSheet(
            storage=self._grimoire_storage,
            connections=self._grimoire_connections,
            importer=self._grimoire_import,
            run_locked=self._wiring.run_locked,
            parent=self._window,
            theme=self._theme,
            generation_open=(
                self._open_spellbook_task_sheet
                if self._generation is not None
                else None
            ),
            generation_deps=(
                self._generation.deps if self._generation is not None else None
            ),
        )
        self._grimoires_sheet = sheet
        # Default-arg capture (the CR5 pattern): the release forgets THIS
        # sheet even if a newer one takes its place meanwhile.
        sheet.finished.connect(
            lambda _result, _sheet=sheet: self._grimoires_sheet_finished(_sheet)
        )
        self._wiring.open_sheet(sheet)
        sheet.request_refresh()

    def _grimoires_sheet_finished(self, sheet: "DndGrimoiresSheet") -> None:
        """Drop the live ref only while THIS sheet is still the resident."""
        if self._grimoires_sheet is sheet:
            self._grimoires_sheet = None

    # ── generation task sheets (add-dnd-lss-generation, группа 7) ────────────

    #: Пояснение гейта «≥1 подключённый датасет» (spec «Гейт активации
    #: генерации», scenario «Персонаж без подключённых датасетов»).
    GENERATION_NO_DATASET_BODY = (
        "Для генерации персонажа нужен хотя бы один подключённый к игре "
        "датасет: включите набор в листе «Датасеты D&D…» и повторите."
    )
    #: Заголовок boxes гейта генерации — имя меню модуля.
    GENERATION_BOX_TITLE = "D&D"

    def _live_generation_sheet(self, kind: str):
        sheet = self._generation_sheets.get(kind)
        if sheet is not None:
            sheet.raise_()
            sheet.activateWindow()
            return sheet
        return None

    def _install_generation_sheet(self, kind: str, sheet) -> None:
        """Посадить лист-задачу на стек коннектора под единственный
        экземпляр своего рода (тот же порядок ref'а, что у всех экранов)."""
        self._generation_sheets[kind] = sheet
        # Default-arg capture (CR5): finished-канал забывает ИМЕННО этот лист.
        sheet.finished.connect(
            lambda _result, _kind=kind, _sheet=sheet: (
                self._generation_sheet_finished(_kind, _sheet)
            )
        )
        self._wiring.open_sheet(sheet)

    def _generation_sheet_finished(self, kind: str, sheet) -> None:
        if self._generation_sheets.get(kind) is sheet:
            self._generation_sheets.pop(kind, None)

    def _open_dataset_task_sheet(self) -> None:
        """Вход листа-задачи датасетов (кнопка «Сгенерировать ИИ» в листе
        «Датасеты D&D…»): живой лист поднимается, близнец не штабелируется."""
        if self._window is None or self._wiring is None:
            return
        if self._generation is None or not self._datasets_screen_ready():
            return
        if self._live_generation_sheet("dataset") is not None:
            return
        from app.dd.presentation.generation.dataset_task_sheet import (
            DndDatasetTaskSheet,
        )

        sheet = DndDatasetTaskSheet(
            deps=self._generation.deps,
            inputs=self._generation.inputs,
            acceptance=self._generation.dataset_acceptance,
            run_locked=self._wiring.run_locked,
            parent=self._window,
            theme=self._theme,
        )
        self._install_generation_sheet("dataset", sheet)

    def _open_spellbook_task_sheet(self) -> None:
        """Вход листа заклинаний (кнопка «Сгенерировать ИИ» в листе
        «Гримуары…»): тот же порядок единственного экземпляра."""
        if self._window is None or self._wiring is None:
            return
        if self._generation is None or not self._grimoires_screen_ready():
            return
        if self._live_generation_sheet("spellbook") is not None:
            return
        from app.dd.presentation.generation.spellbook_task_sheet import (
            DndSpellbookTaskSheet,
        )

        sheet = DndSpellbookTaskSheet(
            deps=self._generation.deps,
            inputs=self._generation.inputs,
            acceptance=self._generation.spellbook_acceptance,
            run_locked=self._wiring.run_locked,
            parent=self._window,
            theme=self._theme,
        )
        self._install_generation_sheet("spellbook", sheet)

    def _on_character_generation_requested(self) -> None:
        """Пункт меню «Сгенерировать персонажа…» (task 7.3): общий AI-гейт
        перечитывается при каждом срабатывании (неактивная часть — на кнопке
        таба, меню объясняет боксом), затем гейт «≥1 подключённый датасет» —
        с русским пояснением и без открытия листа (spec «Гейт активации
        генерации»)."""
        if self._window is None or self._wiring is None:
            return
        if self._generation is None:  # belt-and-braces (no action printed)
            return
        if not self._generation.deps.available():
            self._show_generation_notice(self._generation.deps.hint())
            return
        if self._live_generation_sheet("character") is not None:
            return
        self._check_dataset_gate(lambda: self._show_character_sheet(None, None))

    def _open_character_top_up(self, character_id: int, document: str) -> None:
        """Утина дверь таба «Дозаполнить ИИ» (task 7.3): карточка отдала
        собранный документ — тот же лист в режиме дозаполнения, за
        исключением гейтов."""
        if self._window is None or self._wiring is None:
            return
        if self._generation is None:
            return
        if not self._generation.deps.available():
            self._show_generation_notice(self._generation.deps.hint())
            return
        if self._live_generation_sheet("character") is not None:
            return
        self._check_dataset_gate(
            lambda: self._show_character_sheet(character_id, document)
        )

    def _check_dataset_gate(self, then) -> None:
        """Гейт датасета читает список подключённых (read, под локом — поза
        остальных загрузок) и либо зовёт ``then``, либо объясняет отказ."""
        if self._connections is None or self._generation_gate_task is not None:
            if self._connections is None:
                self._show_generation_notice(self.GENERATION_NO_DATASET_BODY)
            return
        self._generation_gate_task = self._wiring.run_locked(
            self._connections.connections()
        )
        self._generation_gate_task.add_done_callback(
            lambda task, _then=then: self._on_gate_checked(task, _then)
        )

    def _on_gate_checked(self, task: asyncio.Task, then) -> None:
        self._generation_gate_task = None
        if self._window is None or self._wiring is None:
            return  # модуль снялся, пока читался список
        if task.cancelled():
            return
        if task.exception() is not None:
            logging.getLogger("app.dd.module").error(
                "D&D generation gate check failed: %s", task.exception()
            )
            self._show_generation_notice(
                "Не удалось проверить подключённые датасеты. Подробности — в "
                "журнале приложения; повторите позже."
            )
            return
        if not task.result():
            self._show_generation_notice(self.GENERATION_NO_DATASET_BODY)
            return
        then()

    def _show_character_sheet(
        self, character_id: int | None, current_document: str | None
    ) -> None:
        if self._window is None or self._wiring is None:
            return
        assert self._generation is not None  # callers gate on the bundle
        if self._live_generation_sheet("character") is not None:
            return
        from app.dd.presentation.generation.character_task_sheet import (
            DndCharacterTaskSheet,
        )

        sheet = DndCharacterTaskSheet(
            deps=self._generation.deps,
            inputs=self._generation.inputs,
            character_import=self._generation.character_import,
            run_locked=self._wiring.run_locked,
            character_id=character_id,
            current_document=current_document,
            parent=self._window,
            theme=self._theme,
        )
        self._install_generation_sheet("character", sheet)

    def _show_generation_notice(self, body: str) -> None:
        """Modeless-пояснение гейта с живой ссылкой (PR-010 поза модуля)."""
        box = QMessageBox(self._window)
        box.setWindowTitle(self.GENERATION_BOX_TITLE)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(body)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._generation_gate_box = box
        box.finished.connect(self._generation_notice_finished)
        box.show()

    def _generation_notice_finished(self, _result: int) -> None:
        self._generation_gate_box = None

    def _open_monster_card(self, monster_id: int | None) -> None:
        """Raise (or first build) the card of one monster — the creation
        card lives under the ``None`` key. One card per monster: a second
        row click on the same monster lifts the living sheet instead of
        stacking an unsaved twin (the module's single-instance rule); the
        card writes through the connector's lock and reconciles the showcase
        source right after a save."""
        if self._window is None or self._wiring is None:
            return
        if not self._bestiary_screen_ready():  # belt-and-braces (no opener)
            return
        existing = self._monster_cards.get(monster_id)
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        from app.dd.presentation.monster_card_sheet import DndMonsterCardSheet

        assert self._monster_service is not None  # same gate, for the checker
        card = DndMonsterCardSheet(
            monster_id=monster_id,
            service=self._monster_service,
            run_locked=self._wiring.run_locked,
            on_saved=self._monster_card_saved,
            source=self._monster_source(),
            parent=self._window,
            theme=self._theme,
        )
        self._monster_cards[monster_id] = card
        card.finished.connect(
            lambda _result, _card=card: self._monster_card_finished(_card)
        )
        self._wiring.open_sheet(card)

    def _monster_card_finished(self, card: "DndMonsterCardSheet") -> None:
        """Drop the live ref of a closed card, under whichever key the card
        ended on (a creation card re-keyed itself on its first save)."""
        for key, resident in list(self._monster_cards.items()):
            if resident is card:
                del self._monster_cards[key]
                break

    def _monster_card_saved(self, card: "DndMonsterCardSheet") -> None:
        """A save answered: the creation card moves from the ``None`` key to
        its row (opening it from the bestiary now raises THIS card, not a
        second one), and an open bestiary list repaints through the sheet's
        own single-in-flight loader."""
        key, resident = None, None
        for candidate_key, candidate in self._monster_cards.items():
            if candidate is card:
                key, resident = candidate_key, candidate
                break
        if resident is not None and key != card.monster_id:
            del self._monster_cards[key]
            self._monster_cards[card.monster_id] = resident
        if self._bestiary_sheet is not None:
            self._bestiary_sheet.request_refresh()

    # ── character import (add-dnd-game-face task 9.4) ────────────────────────

    def _on_character_import_requested(self) -> None:
        """The «Импорт персонажа из файла LSS…» entry — the spec's creation
        half (dnd-character-import «Точки входа явные»): a fresh character
        has no id and no module tab, so this menu is its entry; the
        overwrite half lives on the open card's «D&D» tab. The target of a
        creation is the new row itself — there is nothing to match against
        (spec «сопоставления по имени нет»). The file is read here and the
        flow runs under the connector's session lock; every answer (success
        with its warnings, refusal with the report) gets a modeless box."""
        from app.dd.presentation.character_tab_frames import CHARACTER_FILE_FILTER

        if self._character_import is None:  # belt-and-braces (no entry exists)
            return
        if self._window is None or self._wiring is None:
            return
        path, _selected = QFileDialog.getOpenFileName(
            self._window,
            DD_CHARACTER_IMPORT_TITLE,
            "",
            CHARACTER_FILE_FILTER,
            # L1 (NRI-0014): always the Russian Qt panel, never the native one.
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return  # the отвод is a no-op — the service was never approached
        try:
            content = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self._show_character_import_box(
                QMessageBox.Icon.Warning,
                f"Не удалось прочитать файл «{path}»: {exc}",
            )
            return
        assert self._wiring is not None  # same gate, for the checker
        self._character_import_task = self._wiring.run_locked(
            self._character_import.import_character(content)
        )
        self._character_import_task.add_done_callback(self._on_character_import_done)

    def _on_character_import_done(self, task: asyncio.Task) -> None:
        """The creation answered (the datasets bootstrap's callback posture:
        a detach that came first takes the report with the window)."""
        if self._character_import_task is task:
            self._character_import_task = None
        if task.cancelled():
            return
        if self._window is None:
            return
        from app.dd.application.character_import_service import CharacterImportStatus
        from app.dd.presentation.datasets_sheet import report_lines

        try:
            outcome = task.result()
        except Exception as exc:  # noqa: BLE001 — the user must see the reason
            logging.getLogger("app.dd.module").error(
                "D&D: импорт персонажа из файла LSS не завершился: %s", exc, exc_info=True
            )
            self._show_character_import_box(
                QMessageBox.Icon.Warning,
                "Импорт персонажа не завершился. Подробности — в журнале "
                "приложения; повторите выбор файла.",
            )
            return
        if outcome.status is CharacterImportStatus.BLOCKED:
            lines = (
                "\n".join(report_lines(outcome.report))
                if outcome.report is not None
                else ""
            )
            body = (
                f"Импорт отклонён — отчёт проверки:\n{lines}"
                if lines
                else outcome.message
            )
            self._show_character_import_box(QMessageBox.Icon.Warning, body)
            return
        if outcome.status is CharacterImportStatus.NEEDS_CONFIRMATION:
            # Unreachable for a creation (no target to confirm) — the honest
            # answer is printed, never swallowed.
            self._show_character_import_box(
                QMessageBox.Icon.Warning, outcome.message
            )
            return
        body = outcome.message
        warnings = outcome.report.warnings if outcome.report is not None else ()
        if warnings:
            body += "\nПредупреждения:\n" + "\n".join(
                f"{issue.path} — {issue.message}" for issue in warnings
            )
        self._show_character_import_box(QMessageBox.Icon.Information, body)

    def _show_character_import_box(self, icon: QMessageBox.Icon, body: str) -> None:
        """Modeless result box on the live window (the datasets box's PR-010
        posture: show(), live ref until finished, never a nested loop)."""
        box = QMessageBox(self._window)
        box.setIcon(icon)
        box.setWindowTitle(DD_CHARACTER_IMPORT_TITLE)
        box.setText(body)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._character_import_box = box
        box.finished.connect(self._character_import_box_finished)
        box.show()

    def _character_import_box_finished(self, _result: int) -> None:
        """Drop the live ref of the closed import box."""
        self._character_import_box = None

    # ── official-datasets bootstrap (task 3.3) ───────────────────────────────

    def _start_datasets_bootstrap(self) -> None:
        """Schedule the idempotent SRD bootstrap on the running loop.

        Without the dataset service there is nothing to ask; without a
        running loop (a bare offscreen attach outside the qasync contour) the
        schedule is skipped — the next real game open asks again through the
        same attach, so skipping never loses the bootstrap."""
        if self._datasets is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logging.getLogger("app.dd.module").debug(
                "D&D datasets bootstrap skipped: no running event loop"
            )
            return
        self._bootstrap_task = loop.create_task(
            self._datasets.download_official_datasets()
        )
        self._bootstrap_task.add_done_callback(self._on_datasets_bootstrapped)

    def _on_datasets_bootstrapped(self, task: asyncio.Task) -> None:
        """The bootstrap answered: silence while the routine state (all sets
        already present — a box for «already there» on every game open would
        be noise), the Russian summary when something downloaded or failed
        (spec: «Успех и каждая ошибка выводятся пользователю по-русски»); a
        detach that came first takes the report with the window."""
        # Clear the ref only while THIS task is still the registered one: a
        # cancel from a detach can report after the next attach already put a
        # fresh task in its place, and the newcomer's ref must survive.
        if self._bootstrap_task is task:
            self._bootstrap_task = None
        if task.cancelled():
            return
        if self._window is None:
            return
        try:
            result: OfficialDatasetsResult = task.result()
        except Exception as exc:  # noqa: BLE001 — the user must see the reason
            logging.getLogger("app.dd.module").error(
                "D&D datasets bootstrap crashed: %s", exc, exc_info=True
            )
            self._show_datasets_box(QMessageBox.Icon.Warning, DD_DATASETS_UNEXPECTED_BODY)
            return
        if result.all_present:
            return
        icon = (
            QMessageBox.Icon.Information
            if result.ok
            else QMessageBox.Icon.Warning
        )
        self._show_datasets_box(icon, result.summary)

    def _show_datasets_box(self, icon: QMessageBox.Icon, body: str) -> None:
        """Modeless result box on the live window — the PR-010 posture again
        (show(), live ref until finished, never a nested event loop); a
        closed box drops its ref the way the disable box does. Reached only
        from the done callback, which has already seen a live window — the
        callback is synchronous, so no detach can slip between that check
        and this box.

        fix-dnd-followups (Д1, live repro «evidence/» + notes.md): a
        QMessageBox is ApplicationModal BY DEFAULT, and on the live cocoa
        display such a window holds the keyboard — with the offline summary
        open, Esc never reached the focused sheet until the master clicked
        «OK». The spec («Уведомление результата SHALL быть необязывающим»)
        demands the opposite, so the box explicitly wears Qt's NonModal (the
        PR-012 posture of every window in this app)."""
        box = QMessageBox(self._window)
        box.setWindowModality(Qt.WindowModality.NonModal)
        box.setIcon(icon)
        box.setWindowTitle(DD_DATASETS_TITLE)
        box.setText(body)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._datasets_box = box
        box.finished.connect(self._datasets_box_finished)
        box.show()

    def _datasets_box_finished(self, _result: int) -> None:
        """Drop the live ref of the closed datasets box."""
        self._datasets_box = None

    # ── disable flow (task 2.3) ─────────────────────────────────────────────

    def _on_disable_requested(self) -> None:
        """The «Выключить D&D-модуль…» entry: ask first, never act on the
        trigger itself (spec: «с подтверждением»). Modeless Yes/No on the
        shared loop — an answer arrives through ``finished``, the window
        stays workable meanwhile; the отвод is a no-op."""
        if self._window is None:
            return
        box = QMessageBox(self._window)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(DD_DISABLE_CONFIRM_TITLE)
        box.setText(DD_DISABLE_CONFIRM_BODY)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        self._confirm_box = box
        box.finished.connect(self._on_disable_answered)
        box.show()

    def _on_disable_answered(self, result: int) -> None:
        """Yes spawns the disable under the connector's session lock; any
        other answer (No, Esc, the close) is the spec's бездействие."""
        self._confirm_box = None
        if result != QMessageBox.StandardButton.Yes:
            return
        if self._wiring is None or self._settings is None:
            return
        self._disable_task = self._wiring.run_locked(self._disable_async())

    async def _disable_async(self) -> None:
        """Flag off, then the section down — data untouched (task 2.3).

        The order is the flow's contract: the write finishes first (one
        transaction in the service), so a failed write leaves the module and
        its section standing exactly as they were; only after the flag is
        committed does the UI come down. The kernel's «Включить D&D-модуль…»
        entry becomes reachable again — the game is ordinary now, and the
        re-enable must be reachable in the same session (spec scenario
        «Выключили и снова включили»).
        """
        if self._settings is None or self._window is None:
            return
        window = self._window
        # detach() drops the connector ref — the reload door needs it after.
        wiring = self._wiring
        await self._settings.disable()
        self.detach()
        window.set_enable_dd_module_visible(True)
        # add-dnd-game-face (task 11.2, spec event-timeline «при выключенном
        # модуле … пометки быть НЕ SHALL»): the sources went dark inside
        # detach(), but the ladder already PAINTS its encounter rings — one
        # reload through the connector's public door re-asks the marks
        # (all dark now) and repaints the rows. This flow already holds the
        # connector's session lock (run_locked above) and the reload opens no
        # second one; the game-close detach needs nothing — the ladder leaves
        # with the window.
        if wiring is not None:
            await wiring.reload_timeline()
