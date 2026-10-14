"""E2E (dd-card-redesign tasks 4.3/5.5): the character card through the module.

The master's route, end to end on the real window: attach the D&D module to
a living game (the settings service's enable + the composition's two moves),
create a character through the timeline «+» menu, and watch the kernel
answer the module's door — «Характеристики»/«Предыстория» hidden (the field
itself still stores, the hiding is a render fact), the module blocks arrive
after the controller's load, a block write (the level) commits through the
connector's lock into ``dd_character_ext``, and detaching the module lets
the kernel texts back into the same card.

The second scenario is the four-tab pass of tasks 4.3/5.5 (spec
dnd-character-extension «Вкладки модуля на карточке персонажа»): the stored
card grows «Основное» + «Способности» + «Личность» + «Заклинания», each tab
seats its frame when pressed, a «Личность» text and a slot-grid cell commit
through the same lock into the module's columns, the kernel Save of the same
card keeps both writes, and detaching the module retires the tabs «без следа»
(spec «выключение модуля SHALL гасить табы»).
"""
from __future__ import annotations

import json

from PySide6.QtWidgets import QComboBox, QLineEdit

from app.dd.application.dataset_index_service import IndexSnapshot
from app.dd.application.dnd_character_extension_service import (
    DndCharacterExtensionService,
)
from app.dd.application.module_settings_service import ModuleSettingsService
from app.dd.domain.character_mechanics import ALIGNMENTS
from app.dd.presentation.character_tab_source import (
    DndCharacterTabSource,
    FEATS_TAB_KEY,
    PERSONALITY_TAB_KEY,
    SPELLS_TAB_KEY,
)
from app.presentation.card_tab_groups import GROUP_OVERVIEW
from app.presentation.views.entity_card_dialog import EntityCardDialog

from tests.presentation.qml_helpers import click_item, find_item
from tests.ui import helpers
from tests.ui.conftest import query_db

_KERNEL_HIDDEN = ["characteristics", "backstory"]


class _EmptyIndex:
    """No datasets connected: the combos carry only «— не выбрано», which is
    the honest offline posture and keeps the scenario about the channel."""

    async def snapshot(self) -> IndexSnapshot:
        return IndexSnapshot(ids=(), titles={}, sections={}, slugs={})


async def _attach_module(application, source: DndCharacterTabSource) -> None:
    """The composition's enable posture without the confirmation box: the
    service's enable transaction creates the module tables, then the same
    two moves main.py makes when a module joins (attach + wiring carrier)."""
    await application._wiring.run_locked(
        ModuleSettingsService(application._uow).enable()
    )
    source.set_attached(True)
    application._wiring.set_external_sources((source,))


def _visible_card(window, *, exclude=None) -> EntityCardDialog | None:
    for dialog in window.findChildren(EntityCardDialog):
        if dialog.isVisible() and dialog is not exclude:
            return dialog
    return None


async def test_module_hides_texts_paints_blocks_and_writes_the_level(
    app, wait_for, menu_qmenu,
):
    application, window = app
    db_path = application._db_path
    name, kernel_text = "Грог Трясучка", "Трясётся от собственного храпа"
    source = DndCharacterTabSource(
        character_service=DndCharacterExtensionService(application._uow),
        dataset_index=_EmptyIndex(),
    )
    await _attach_module(application, source)
    try:
        # 1. Creation: the new-card door already answers «hide these kernel
        #    texts», yet the hidden field still stores what the master typed.
        dialog = await helpers.create_entity_via_context_menu(
            window, wait_for, menu_qmenu, "character", name,
            characteristics=kernel_text,
        )
        assert list(dialog.vm.hiddenFields) == _KERNEL_HIDDEN
        await wait_for(lambda: len(query_db(
            db_path, "SELECT id FROM characters WHERE name = ?", (name,)
        )) == 1)
        entity_id = query_db(
            db_path, "SELECT id FROM characters WHERE name = ?", (name,)
        )[0][0]
        assert kernel_text in query_db(
            db_path,
            "SELECT d.characteristics FROM characters c "
            "JOIN descriptions d ON d.id = c.description_id WHERE c.id = ?",
            (entity_id,),
        )[0][0]
        await helpers.wait_until_settled()

        # 2. The stored card: the same hidden answer plus, one pump later,
        #    the module's blocks arriving at their anchor (the controller's
        #    first republish through the host — the door itself is sync).
        window.detail_panel.entity_clicked.emit("character", entity_id)
        await wait_for(
            lambda: _visible_card(window, exclude=dialog) is not None
        )
        card = _visible_card(window, exclude=dialog)
        assert list(card.vm.hiddenFields) == _KERNEL_HIDDEN

        def blocks() -> list[dict]:
            return list(card.vm.moduleBlocks or [])

        await wait_for(lambda: any(b["id"] == "level" for b in blocks()))
        painted = {b["id"]: b for b in blocks()}
        assert painted["level"]["anchor"] == "after_short_fields"
        assert painted["abilities"]["kind"] == "table"
        assert painted["link_race"]["anchor"] == "after_short_fields"
        # No file doors composed (no import/export stack in this game) →
        # the no-dead-action posture prints no button row at all.
        assert "lss_doors" not in painted

        # 3. A module write is a real save: the level commits through the
        #    connector's lock and lands in the module's own table.
        card.vm.writeModuleBlock("level", "value", "5")
        await wait_for(lambda: query_db(
            db_path,
            "SELECT level FROM dd_character_ext WHERE character_id = ?",
            (entity_id,),
        ) == [(5,)])
        # The repaint follows the same locked read the write ended with.
        await wait_for(lambda: next(
            b for b in blocks() if b["id"] == "level"
        )["value"] == "5")
        await helpers.wait_until_settled()

        # 4. Detaching the module (the game switch's posture): the same
        #    card opens with the kernel texts back and no module blocks.
        card.reject()
        await wait_for(lambda: _visible_card(window) is None)
        source.set_attached(False)
        application._wiring.set_external_sources(())
        window.detail_panel.entity_clicked.emit("character", entity_id)
        await wait_for(lambda: _visible_card(window, exclude=dialog) is not None)
        reopened = _visible_card(window, exclude=dialog)
        assert list(reopened.vm.hiddenFields) == []
        # The channel re-collects for the new card: with no source attached
        # there is nothing to paint and nothing to hide (spec «при выключении
        # модуля скрытые поля SHALL снова появиться»).
        assert not list(reopened.vm.moduleBlocks or [])
        reopened.reject()
    finally:
        source.set_attached(False)
        application._wiring.set_external_sources(())


def _tab_titles(card) -> list[str]:
    return [entry["title"] for entry in card.vm.groups or []]


def _tab_keys(card) -> list[str]:
    return [entry["key"] for entry in card.vm.groups or []]


async def test_four_tab_lineup_writes_through_tabs_and_retires_with_module(
    app, wait_for, menu_qmenu,
):
    """Tasks 4.3/5.5: create → four tabs → live writes on «Личность» and
    «Заклинания» → kernel Save keeps them → detach retires the lineup."""
    application, window = app
    db_path = application._db_path
    name = "Морра Кракен"
    source = DndCharacterTabSource(
        character_service=DndCharacterExtensionService(application._uow),
        dataset_index=_EmptyIndex(),
    )
    await _attach_module(application, source)
    try:
        dialog = await helpers.create_entity_via_context_menu(
            window, wait_for, menu_qmenu, "character", name,
        )
        await wait_for(lambda: len(query_db(
            db_path, "SELECT id FROM characters WHERE name = ?", (name,)
        )) == 1)
        entity_id = query_db(
            db_path, "SELECT id FROM characters WHERE name = ?", (name,)
        )[0][0]
        await helpers.wait_until_settled()

        # 1. The stored card grows the spec's lineup: kernel head, module tail.
        window.detail_panel.entity_clicked.emit("character", entity_id)
        await wait_for(
            lambda: _visible_card(window, exclude=dialog) is not None
        )
        card = _visible_card(window, exclude=dialog)
        await wait_for(lambda: _tab_titles(card) == [
            "Основное", "Способности", "Личность", "Заклинания",
        ])
        assert _tab_keys(card) == [
            GROUP_OVERVIEW, FEATS_TAB_KEY, PERSONALITY_TAB_KEY, SPELLS_TAB_KEY,
        ]

        # 2. «Способности» seats its frame — no datasets connected, the
        #    candidate wall answers honestly, nothing is invented (the frame
        #    half of the scenario is pinned in tests/dd; here: the seat).
        click_item(card.quick, find_item(card.quick, f"entityGroupTab_{FEATS_TAB_KEY}"))
        assert card.vm.activeGroupKey == FEATS_TAB_KEY

        def feats_seated() -> bool:
            frame = card.findChild(QLineEdit, "ddFeatsFilter")
            return frame is not None and frame.isVisible()

        await wait_for(feats_seated)
        await helpers.wait_until_settled()

        # 3. «Личность»: a short text and the alignment combo write through
        #    the connector's lock into the module's own columns.
        click_item(
            card.quick, find_item(card.quick, f"entityGroupTab_{PERSONALITY_TAB_KEY}")
        )
        height = card.findChild(QLineEdit, "ddPersonalityShort_height")
        background = card.findChild(QComboBox, "ddPersonalityBackground")
        alignment = card.findChild(QComboBox, "ddPersonalityAlignment")
        assert height is not None and background is not None
        # The fill built the background combo — the load has landed, the
        # frame now accepts writes (an untouched-load frame refuses them).
        await wait_for(lambda: background.count() > 0)

        height.setText("170 см")
        height.editingFinished.emit()
        stored_alignment = ALIGNMENTS[1]
        alignment.setCurrentIndex(ALIGNMENTS.index(stored_alignment) + 1)

        def ext_row():
            return query_db(
                db_path,
                "SELECT text_blocks, alignment FROM dd_character_ext "
                "WHERE character_id = ?",
                (entity_id,),
            )

        await wait_for(
            lambda: ext_row()
            and json.loads(ext_row()[0][0] or "{}").get("Рост") == "170 см"
            and ext_row()[0][1] == stored_alignment
        )

        # 4. «Заклинания»: one slot-grid cell commits the whole map.
        click_item(
            card.quick, find_item(card.quick, f"entityGroupTab_{SPELLS_TAB_KEY}")
        )
        slot3 = card.findChild(QLineEdit, "ddSpellsSlot_3")
        assert slot3 is not None
        await helpers.wait_until_settled()  # the tab's own read has landed
        slot3.setText("4")
        slot3.editingFinished.emit()
        await wait_for(lambda: query_db(
            db_path,
            "SELECT slots_json FROM dd_character_ext WHERE character_id = ?",
            (entity_id,),
        ) == [(json.dumps({"3": 4}),)])

        # 5. The kernel Save of the same card survives next to the module
        #    writes: a renamed character keeps its «Личность» and its cells.
        card.name_input.setText(name + "-младшая")
        assert card.save_button.isEnabled()
        card.save_button.click()
        await wait_for(lambda: not card.isVisible())
        assert query_db(
            db_path, "SELECT name FROM characters WHERE id = ?", (entity_id,)
        ) == [(name + "-младшая",)]
        assert json.loads(ext_row()[0][0]).get("Рост") == "170 см"
        assert ext_row()[0][1] == stored_alignment
        assert query_db(
            db_path,
            "SELECT slots_json FROM dd_character_ext WHERE character_id = ?",
            (entity_id,),
        ) == [(json.dumps({"3": 4}),)]

        # 6. Detaching the module: the same character reopens on the single
        #    kernel screen — the lineup is gone «без следа», the data stays.
        source.set_attached(False)
        application._wiring.set_external_sources(())
        window.detail_panel.entity_clicked.emit("character", entity_id)
        await wait_for(lambda: _visible_card(window, exclude=dialog) is not None)
        reopened = _visible_card(window, exclude=dialog)
        assert _tab_titles(reopened) == ["Основное"]
        assert list(reopened.vm.moduleGroups or []) == []
        reopened.reject()
    finally:
        source.set_attached(False)
        application._wiring.set_external_sources(())


async def test_fresh_card_stands_four_tabs_and_creation_stands_the_extension(
    app, wait_for, menu_qmenu,
):
    """Checkpoint-2 audit (spec dnd-character-extension «Новая карточка с
    пустыми разделами»): the tab lineup does not wait for the row — a fresh
    card opens on all four tabs with their sections honestly empty, and the
    first Save creates the extension alongside the kernel character, without
    a single module write from the user."""
    application, window = app
    db_path = application._db_path
    name = "Свежак Персонажей"
    source = DndCharacterTabSource(
        character_service=DndCharacterExtensionService(application._uow),
        dataset_index=_EmptyIndex(),
    )
    await _attach_module(application, source)
    try:
        # The same '+' channel as every creation, but the card is inspected
        # BEFORE the save click — the lineup is a construction fact now.
        helpers.pick_menu_action(menu_qmenu, "Новый персонаж")
        from PySide6.QtCore import Qt

        from tests.ui import timeline_probe

        timeline_probe.click_object(
            window, "addButton", button=Qt.MouseButton.RightButton
        )
        await wait_for(
            lambda: any(
                d.isVisible() for d in window.findChildren(EntityCardDialog)
            )
        )
        dialog = next(
            d for d in window.findChildren(EntityCardDialog) if d.isVisible()
        )
        # 1. Four tabs stand on a card that edits nothing yet.
        assert _tab_keys(dialog) == [
            GROUP_OVERVIEW, FEATS_TAB_KEY, PERSONALITY_TAB_KEY, SPELLS_TAB_KEY,
        ]
        # 2. The sections are honestly empty: the «Способности» frame opened
        #    on the unsaved id, read no character rows and prints its hint.
        from PySide6.QtWidgets import QLabel

        await wait_for(
            lambda: dialog.findChild(QLabel, "ddFeatsEmpty") is not None
        )
        # 3. The first save creates the character AND its extension — the
        #    connector's creation door, not a deferred first write.
        dialog.name_input.setText(name)
        dialog.save_button.click()
        await wait_for(
            lambda: len(query_db(
                db_path, "SELECT id FROM characters WHERE name = ?", (name,)
            )) == 1
        )
        entity_id = query_db(
            db_path, "SELECT id FROM characters WHERE name = ?", (name,)
        )[0][0]
        await wait_for(lambda: query_db(
            db_path,
            "SELECT character_id FROM dd_character_ext WHERE character_id = ?",
            (entity_id,),
        ) == [(entity_id,)])
        # 4. The stored card reopens with the same lineup and the extension's
        #    empty face — the fresh state and the stored one are the same
        #    honest emptiness, now keyed by a real id.
        await wait_for(lambda: not dialog.isVisible())
        window.detail_panel.entity_clicked.emit("character", entity_id)
        await wait_for(lambda: _visible_card(window, exclude=dialog) is not None)
        card = _visible_card(window, exclude=dialog)
        await wait_for(lambda: _tab_keys(card) == [
            GROUP_OVERVIEW, FEATS_TAB_KEY, PERSONALITY_TAB_KEY, SPELLS_TAB_KEY,
        ])
        card.reject()
        await helpers.wait_until_settled()
    finally:
        source.set_attached(False)
        application._wiring.set_external_sources(())
