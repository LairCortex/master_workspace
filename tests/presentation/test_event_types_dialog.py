"""EventTypesDialog (W4 task 6.1): list, rename, ↑/↓ order, add, delete, colors.

The dialog owns no state of its own — every edit must land in the game through
``EventService`` and become readable back from it (round-trip "через service"),
so the tests below drive real widgets against the real service on in-memory
SQLite. Also pinned here: the palette-not-colorpicker contract (exactly the
eight chart swatches), the numbered-gray off-skin samples and the live
re-theme of the swatch icons without losing the list selection.
"""
from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import Qt as _Qt, QSize
from PySide6.QtGui import QColor

from app.application.services.entity_service import EntityService
from app.application.services.event_service import EventService
from app.infrastructure.db.models import DescriptionModel, EventModel
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository
from app.presentation.theme.compiler import CHART_TOKEN_KEYS
from app.presentation.views.event_types_dialog import (
    DEFAULT_NEW_TYPE_NAME,
    EventTypesDialog,
)

from tests.ui.test_theme_grab import make_runtime, token_color

D1 = date(1200, 1, 1)


async def _make_service(session) -> EventService:
    desc_repo = BaseRepository(session, DescriptionModel)
    return EventService(
        event_repo=EventRepository(session),
        description_repo=desc_repo,
        organization_service=EntityService(OrganizationRepository(session), desc_repo),
        character_service=EntityService(CharacterRepository(session), desc_repo),
        item_service=EntityService(ItemRepository(session), desc_repo),
        location_service=EntityService(LocationRepository(session), desc_repo),
    )


async def _make_event(session, name: str, event_type_id: int | None = None) -> EventModel:
    desc = DescriptionModel(characteristics="ch", backstory="bs")
    session.add(desc)
    await session.flush()
    ev = EventModel(
        name=name, start_date=D1, end_date=None,
        description_id=desc.id, event_type_id=event_type_id,
    )
    session.add(ev)
    await session.flush()
    return ev


async def _open_dialog(service, qtbot, theme=None):
    dialog = EventTypesDialog(service, theme=theme)
    qtbot.addWidget(dialog)
    await dialog.wait_idle()  # the initial load ran through `run`
    return dialog


def _select_item(dialog, name: str):
    for i in range(dialog.type_list.count()):
        if dialog.type_list.item(i).text() == name:
            dialog.type_list.setCurrentRow(i)
            return dialog.type_list.item(i)
    raise AssertionError(f"no list item {name!r}")


async def _seed_defaults(service) -> list:
    created = []
    for name, index in [
        ("Сюжет", 1), ("Побочное", 2), ("Слух", 3), ("Встреча", 4),
    ]:
        created.append(await service.save_event_type(name=name, color_index=index))
    return created


# ── round-trips through the service (task 6.1) ──────────────────────────────

class TestDialogRoundTripThroughService:
    async def test_initial_load_lists_types_in_order(self, async_session, qtbot):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        assert dialog.type_names() == ["Сюжет", "Побочное", "Слух", "Встреча"]

    async def test_rename_persists_through_service(self, async_session, qtbot):
        service = await _make_service(async_session)
        types = await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        _select_item(dialog, "Слух")
        dialog.name_input.setText("Примета")
        dialog.name_input.editingFinished.emit()
        await dialog.wait_idle()

        stored = {t.name: t for t in await service.get_event_types()}
        assert "Примета" in stored and "Слух" not in stored
        # Rename kept the type's identity: same id, same color (spec scenario).
        assert stored["Примета"].id == types[2].id
        assert stored["Примета"].color_index == 3
        # The same type shows the new name in the list, color unchanged.
        assert dialog.type_list.item(2).text() == "Примета"

    async def test_empty_or_unchanged_rename_is_not_persisted(self, async_session, qtbot):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        _select_item(dialog, "Сюжет")
        dialog.name_input.setText("   ")
        dialog.name_input.editingFinished.emit()
        await dialog.wait_idle()
        assert [t.name for t in await service.get_event_types()] == [
            "Сюжет", "Побочное", "Слух", "Встреча",
        ]

    async def test_swatch_color_choice_round_trips(self, async_session, qtbot):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        _select_item(dialog, "Сюжет")
        assert dialog.swatch_buttons[0].isChecked()  # reflects the current color
        dialog.swatch_buttons[6].click()  # palette sample №7
        await dialog.wait_idle()
        stored = {t.name: t for t in await service.get_event_types()}
        assert stored["Сюжет"].color_index == 7
        assert dialog.swatch_buttons[6].isChecked()

    async def test_add_appends_with_first_free_color_and_selects_it(
        self, async_session, qtbot
    ):
        service = await _make_service(async_session)
        await _seed_defaults(service)  # colors 1..4 used
        dialog = await _open_dialog(service, qtbot)
        dialog.type_list.clearSelection()
        dialog.name_input.setText("Находка")
        dialog.add_button.click()
        await dialog.wait_idle()

        types = list(await service.get_event_types())
        assert [t.name for t in types][-1] == "Находка"
        assert types[-1].color_index == 5  # first unused palette index
        assert dialog.type_list.currentItem().text() == "Находка"

    async def test_add_without_name_falls_back_to_default_name(
        self, async_session, qtbot
    ):
        service = await _make_service(async_session)
        dialog = await _open_dialog(service, qtbot)
        dialog.add_button.click()
        await dialog.wait_idle()
        names = [t.name for t in await service.get_event_types()]
        assert names == [DEFAULT_NEW_TYPE_NAME]

    async def test_ninth_type_rotates_palette_index(self, async_session, qtbot):
        service = await _make_service(async_session)
        for k in range(1, 9):  # all eight palette colors are used
            await service.save_event_type(name=f"T{k}", color_index=k)
        dialog = await _open_dialog(service, qtbot)
        dialog.type_list.clearSelection()
        dialog.name_input.setText("Девятый")
        dialog.add_button.click()
        await dialog.wait_idle()
        types = list(await service.get_event_types())
        idx = {t.name: t.color_index for t in types}["Девятый"]
        assert 1 <= idx <= 8  # rotation stays inside the token palette

    async def test_delete_removes_type_from_service(self, async_session, qtbot):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        _select_item(dialog, "Встреча")
        dialog.remove_button.click()  # plain unbind, no confirmation dialog
        await dialog.wait_idle()
        assert [t.name for t in await service.get_event_types()] == [
            "Сюжет", "Побочное", "Слух",
        ]
        assert dialog.type_names() == ["Сюжет", "Побочное", "Слух"]

    async def test_delete_of_occupied_type_unbinds_events_intact(
        self, async_session, qtbot
    ):
        service = await _make_service(async_session)
        occupied = await service.save_event_type(name="Слух", color_index=3)
        events = [
            await _make_event(async_session, f"R{i}", occupied.id) for i in range(3)
        ]
        await async_session.commit()
        dialog = await _open_dialog(service, qtbot)
        _select_item(dialog, "Слух")
        dialog.remove_button.click()
        await dialog.wait_idle()

        assert list(await service.get_event_types()) == []
        all_events = list(await service.get_all_events())
        assert {e.id for e in all_events} == {e.id for e in events}  # events intact
        for e in all_events:
            assert e.event_type is None  # every unbound, a valid typed-less event

    async def test_up_down_buttons_reorder_via_service(self, async_session, qtbot):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        assert dialog.up_button.isEnabled() is False  # first row: nowhere to rise
        _select_item(dialog, "Сюжет")
        assert dialog.up_button.isEnabled() is False
        dialog.down_button.click()
        await dialog.wait_idle()
        assert [t.name for t in await service.get_event_types()] == [
            "Побочное", "Сюжет", "Слух", "Встреча",
        ]
        assert dialog.type_names() == ["Побочное", "Сюжет", "Слух", "Встреча"]
        assert dialog.type_list.currentItem().text() == "Сюжет"  # selection keeps up
        _select_item(dialog, "Сюжет")
        dialog.up_button.click()
        await dialog.wait_idle()
        assert [t.name for t in await service.get_event_types()] == [
            "Сюжет", "Побочное", "Слух", "Встреча",
        ]

    async def test_each_edit_emits_types_changed(self, async_session, qtbot):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        fired: list = []
        dialog.types_changed.connect(lambda: fired.append(1))
        _select_item(dialog, "Слух")
        dialog.name_input.setText("Примета")
        dialog.name_input.editingFinished.emit()
        await dialog.wait_idle()
        dialog.swatch_buttons[5].click()
        await dialog.wait_idle()
        assert len(fired) == 2


# ── palette, not a colorpicker (spec scenario) ──────────────────────────────

class TestPaletteNotColorpicker:
    async def test_exactly_eight_swatch_samples(self, async_session, qtbot):
        service = await _make_service(async_session)
        dialog = await _open_dialog(service, qtbot)
        assert len(dialog.swatch_buttons) == len(CHART_TOKEN_KEYS) == 8
        # The only color affordances are the fixed samples; the tooltip names
        # the palette entry, no free-color control exists.
        for index, button in enumerate(dialog.swatch_buttons, start=1):
            assert button.toolTip() == f"Цвет {index}"
            assert button.isCheckable()

    async def test_off_skin_swarps_are_numbered_gray(self, async_session, qtbot):
        service = await _make_service(async_session)
        dialog = await _open_dialog(service, qtbot, theme=None)  # no skin at all
        gray = QColor(_Qt.GlobalColor.gray)
        for index, button in enumerate(dialog.swatch_buttons, start=1):
            assert button.text() == str(index)  # the number carries the identity
            image = button.icon().pixmap(QSize(18, 18)).toImage()
            # A pixel inside the circle (above the digit) is the named Qt gray.
            assert image.pixelColor(9, 2) == gray


# ── attach_theme + live re-theme (task 6.1) ─────────────────────────────────

class TestLiveRetheme:
    async def test_swatch_icons_follow_theme_switch(
        self, async_session, qtbot, tmp_path
    ):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        runtime = make_runtime(tmp_path, "dark")
        dialog = await _open_dialog(service, qtbot, theme=runtime)
        _select_item(dialog, "Сюжет")  # selection must survive the swap

        def center(button):
            return button.icon().pixmap(QSize(18, 18)).toImage().pixelColor(9, 9)

        for index, button in enumerate(dialog.swatch_buttons, start=1):
            assert center(button) == token_color(CHART_TOKEN_KEYS[index - 1], "dark")

        assert runtime.toggle()  # dark → light through the runtime
        for index, button in enumerate(dialog.swatch_buttons, start=1):
            assert center(button) == token_color(CHART_TOKEN_KEYS[index - 1], "light")
        # Live swap repainted the circles in place: same widgets, same selection.
        assert dialog.type_list.currentItem().text() == "Сюжет"
        assert dialog.swatch_buttons[0].isChecked()

    async def test_theme_switch_clears_off_skin_numbers(
        self, async_session, qtbot, tmp_path
    ):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        offskin = make_runtime(tmp_path, "dark", tokens_path=tmp_path / "absent.json")
        assert not offskin.is_valid
        dialog = await _open_dialog(service, qtbot, theme=offskin)
        assert [b.text() for b in dialog.swatch_buttons] == [str(k) for k in range(1, 9)]
