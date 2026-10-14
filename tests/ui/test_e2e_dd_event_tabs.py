"""E2E (dd-card-redesign task 5.1): the event card's two tabs through the module.

The master's route on the real window, the event half of the lineup the
redesign ships: attach the D&D module (settings enable + the composition's
two moves), seed one bestiary monster, create an event through the ladder,
and open its edit card — the strip grows the kernel's «Основное» head plus
the module's «Встреча» tail (spec dnd-encounters, design Д9). Pressing
«Встреча» seats the encounter frame; a composition row and a note staged
there go through the card's COMMON Save into ``dd_encounter`` (the hooks
themselves are pinned in test_e2e_module_tab_saves); reopening the card
re-reads the stored face on the same tab; a save refused over the empty name
while «Встреча» is active reveals «Основное» and marks the field (spec
«Ошибка указывает дорогу»); detaching the module retires the tab «без следа»
while the stored overlay survives (spec «Без модуля таба нет»).
"""
from __future__ import annotations

import json
from datetime import date

from PySide6.QtWidgets import QComboBox, QPlainTextEdit, QPushButton

from app.dd.application.dd_encounter_service import DdEncounterService
from app.dd.application.module_settings_service import ModuleSettingsService
from app.dd.application.monster_service import DdMonsterService
from app.dd.presentation.dd_encounter_frame import DndEncounterTabFrame
from app.dd.presentation.dd_encounter_source import (
    ENCOUNTER_TAB_KEY,
    ENCOUNTER_TAB_TITLE,
    DndEncounterSource,
)
from app.presentation.card_tab_groups import GROUP_OVERVIEW
from app.presentation.views.event_dialog import EventDialog

from tests.presentation.qml_helpers import click_item, find_item
from tests.ui import helpers
from tests.ui.conftest import query_db

MONSTER = "Гоблин"
NOTE = "Факелы у входа, ночь"


def _visible_event_dialog(window) -> EventDialog:
    return next(
        d for d in window.findChildren(EventDialog) if d.isVisible()
    )


def _tab_titles(dialog) -> list[str]:
    return [entry["title"] for entry in dialog.vm.groups or []]


def _tab_keys(dialog) -> list[str]:
    return [entry["key"] for entry in dialog.vm.groups or []]


async def _attach_module(application, source: DndEncounterSource) -> None:
    """The composition's enable posture without the confirmation box (the
    character e2e file's helper, restated: the tables, then attach + carrier)."""
    await application._wiring.run_locked(
        ModuleSettingsService(application._uow).enable()
    )
    source.set_attached(True)
    application._wiring.set_external_sources((source,))


async def test_event_two_tab_lineup_saves_encounter_and_retires_with_module(
    app, wait_for,
):
    application, window = app
    db_path = application._db_path
    source = DndEncounterSource(
        encounter_service=DdEncounterService(application._uow),
        monster_service=DdMonsterService(application._uow),
    )
    await _attach_module(application, source)
    try:
        monster = await application._wiring.run_locked(
            DdMonsterService(application._uow).save_monster(
                monster_id=None, name=MONSTER, rating=1, blocks={},
            )
        )
        name = "Бой у моста"
        await helpers.create_event_via_ui(
            window, wait_for, name,
            start_date=date(1200, 6, 1), end_date=date(1200, 6, 3),
        )
        event_id = helpers.double_click_timeline_event(window, name)
        await wait_for(
            lambda: any(d.isVisible() for d in window.findChildren(EventDialog))
        )
        dialog = _visible_event_dialog(window)

        # 1. The edit card grows the two-tab lineup: kernel head, module tail.
        await wait_for(lambda: _tab_titles(dialog) == [
            "Основное", ENCOUNTER_TAB_TITLE,
        ])
        assert _tab_keys(dialog) == [GROUP_OVERVIEW, ENCOUNTER_TAB_KEY]

        # 2. Pressing «Встреча» seats the frame; its read lands (the stored
        #    face is honestly empty for this fresh event, the bestiary is not).
        click_item(
            dialog.quick,
            find_item(dialog.quick, f"eventGroupTab_{ENCOUNTER_TAB_KEY}"),
        )
        assert dialog.vm.activeGroupKey == ENCOUNTER_TAB_KEY
        frame = next(iter(dialog.findChildren(DndEncounterTabFrame)))
        add = frame.findChild(QPushButton, "ddEncounterAdd")
        assert add is not None and add.isVisible()
        await wait_for(lambda: frame._loaded)

        # 3. Staged on the tab, written by the card's common Save: the row
        #    starts on the first bestiary monster, the note rides along.
        add.click()
        combo = frame.findChild(QComboBox, "ddEncounterMonster")
        assert combo is not None and combo.currentText() == MONSTER
        frame.findChild(QPlainTextEdit, "ddEncounterNote").setPlainText(NOTE)
        assert dialog.save_button.isEnabled()
        dialog.save_button.click()
        await wait_for(lambda: not dialog.isVisible())
        await helpers.wait_until_settled()

        stored = query_db(
            db_path,
            "SELECT composition, note FROM dd_encounter WHERE event_id = ?",
            (event_id,),
        )
        assert len(stored) == 1
        assert json.loads(stored[0][0]) == [
            {"monster_id": monster.id, "count": 1, "name": MONSTER}
        ]
        assert stored[0][1] == NOTE

        # 4. Reopened, the tab re-reads the stored face verbatim.
        helpers.double_click_timeline_event(window, name)
        await wait_for(
            lambda: any(
                d.isVisible() and d is not dialog
                for d in window.findChildren(EventDialog)
            )
        )
        card = _visible_event_dialog(window)
        await wait_for(lambda: _tab_titles(card) == [
            "Основное", ENCOUNTER_TAB_TITLE,
        ])
        click_item(
            card.quick,
            find_item(card.quick, f"eventGroupTab_{ENCOUNTER_TAB_KEY}"),
        )
        frame2 = next(iter(card.findChildren(DndEncounterTabFrame)))
        await wait_for(lambda: frame2._loaded)
        combo2 = frame2.findChild(QComboBox, "ddEncounterMonster")
        assert combo2 is not None and combo2.currentText() == MONSTER
        assert frame2.findChild(
            QPlainTextEdit, "ddEncounterNote"
        ).toPlainText() == NOTE

        # 5. A refusal over the kernel name while «Встреча» is active reveals
        #    the tab that hosts the field and marks it (the request reaches
        #    the VM the way the QML save button calls it).
        assert card.vm.activeGroupKey == ENCOUNTER_TAB_KEY
        card.name_input.setText("")
        card.vm.requestSave()
        assert card.vm.active_group_key() == GROUP_OVERVIEW
        assert card.vm.invalidatedField == "name"
        assert card.isVisible()  # refused, the card stays open for the fix
        card.reject()

        # 6. Detaching the module: the same event reopens on the single
        #    kernel screen; the stored overlay survives in its own table.
        source.set_attached(False)
        application._wiring.set_external_sources(())
        helpers.double_click_timeline_event(window, name)
        await wait_for(
            lambda: any(
                d.isVisible() and d is not dialog and d is not card
                for d in window.findChildren(EventDialog)
            )
        )
        off = _visible_event_dialog(window)
        assert _tab_titles(off) == ["Основное"]
        assert list(off.vm.moduleGroups or []) == []
        assert len(query_db(
            db_path, "SELECT event_id FROM dd_encounter WHERE event_id = ?",
            (event_id,),
        )) == 1
        off.reject()
    finally:
        source.set_attached(False)
        application._wiring.set_external_sources(())


def _live_pane(window):
    """The live area's pane dict or ``None`` (the entity-preview lifecycle
    helper restated: frames are built live-last, the trailing unpinned pane
    IS the live area)."""
    panes = window.entity_preview.vm.panes
    if panes and not panes[-1]["pinned"]:
        return panes[-1]
    return None


async def test_event_shows_the_encounter_mirror_in_the_preview_column(
    app, wait_for,
):
    """dd-card-redesign audit fix — spec entity-preview «Событие показывает
    встречу»: the event's live seat (the mention-anchor bus entry, the same
    ``entity_requested("event", id)`` an activated preview mention emits)
    loads the row through the event service, and the attached module's
    awaitable door answers the «Встреча» section — the composition «монстр ×
    количество» and the note — under the kernel fields. Before the fix this
    scenario was unreachable live (docs/qa/2026-10-13-live-preview-mirror.md
    Finding 1): the seat died on the missing EntityService."""
    application, window = app
    source = DndEncounterSource(
        encounter_service=DdEncounterService(application._uow),
        monster_service=DdMonsterService(application._uow),
    )
    await _attach_module(application, source)
    try:
        await application._wiring.run_locked(
            DdMonsterService(application._uow).save_monster(
                monster_id=None, name=MONSTER, rating=1, blocks={},
            )
        )
        name = "Засада у моста"
        await helpers.create_event_via_ui(
            window, wait_for, name,
            start_date=date(1200, 6, 1), end_date=date(1200, 6, 3),
        )
        event_id = helpers.double_click_timeline_event(window, name)
        await wait_for(
            lambda: any(d.isVisible() for d in window.findChildren(EventDialog))
        )
        dialog = _visible_event_dialog(window)
        click_item(
            dialog.quick,
            find_item(dialog.quick, f"eventGroupTab_{ENCOUNTER_TAB_KEY}"),
        )
        frame = next(iter(dialog.findChildren(DndEncounterTabFrame)))
        await wait_for(lambda: frame._loaded)
        frame.findChild(QPushButton, "ddEncounterAdd").click()
        frame.findChild(QPlainTextEdit, "ddEncounterNote").setPlainText(NOTE)
        dialog.save_button.click()
        await wait_for(lambda: not dialog.isVisible())
        await helpers.wait_until_settled()

        # The seat: the same bus entry an activated mention of this event
        # produces — the live card loads and mirrors the stored encounter.
        window.entity_preview.entity_requested.emit("event", event_id)
        await wait_for(
            lambda: (_live_pane(window) or {}).get("nameText") == name
        )
        pane = _live_pane(window)
        assert pane["title"] == "Карточка: Событие"
        assert pane["entityType"] == "event"
        assert pane["entityId"] == event_id
        # The event owns no rating column — the line stays absent (the
        # island hides an empty one), never a fabricated «1/20».
        assert pane["ratingText"] == ""
        sections = {s["title"]: s["lines"] for s in pane["moduleSections"]}
        assert sections["Встреча"] == [f"{MONSTER} × 1", f"Заметка: {NOTE}"]
        # Kernel texts stay under the absent rating/date lines: the event
        # row has a description pair, the composition rides empty here.
        assert pane["dateText"]

        # The event card save repaints the shown pair from the CURRENT state
        # (spec «Обновление показанной сущности … перекрашивать секции»):
        # the note edit staged on the tab lands in the pushed frame.
        helpers.double_click_timeline_event(window, name)
        await wait_for(
            lambda: any(
                d.isVisible() and d is not dialog
                for d in window.findChildren(EventDialog)
            )
        )
        card = _visible_event_dialog(window)
        click_item(
            card.quick,
            find_item(card.quick, f"eventGroupTab_{ENCOUNTER_TAB_KEY}"),
        )
        frame2 = next(iter(card.findChildren(DndEncounterTabFrame)))
        await wait_for(lambda: frame2._loaded)
        frame2.findChild(QPlainTextEdit, "ddEncounterNote").setPlainText(
            "Фонари у входа, ночь"
        )
        card.save_button.click()
        await wait_for(lambda: not card.isVisible())
        await wait_for(
            lambda: any(
                line.startswith("Заметка: Фонари")
                for s in (_live_pane(window) or {}).get("moduleSections", ())
                for line in s["lines"]
            )
        )
    finally:
        source.set_attached(False)
        application._wiring.set_external_sources(())
