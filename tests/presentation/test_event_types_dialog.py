"""EventTypesDialog — QML island in the kept QDialog facade (R3 pack 2, §4).

Two halves, the same split the other islands use:

* the ``objectName`` contract of ``EventTypesRoot.qml`` (task 4.1) — loaded
  into a bare ``QQuickWidget`` with only ``eventTypesVm`` + ``islandPalette``
  in context, driven by real synthetic clicks, so «QML лишь эмитит запросы»
  is verified against the VM and nothing else;
* the facade round-trips (tasks 4.3/4.5) — the real ``EventService`` on
  in-memory SQLite, addressed through the island: every edit must land in the
  game immediately (no Save, no confirmation on close) and become readable
  back from the service, with the public API (ctor, ``types_changed``,
  ``wait_idle``, ``reload``, ``type_names``) untouched by the port.

The palette-not-colorpicker contract lives here too: exactly the eight
``ThemeSwatch`` samples of ``color.chart.1…8`` (built by a ``Repeater`` from
``eventTypesVm.paletteSize``) and no free-color affordance. Swatch pixels and
their off-skin degradation are the library's acceptance
(``test_theme_password_swatch.py``); this suite pins the island's wiring and
the one live-retheme scenario (selection + order survive the swap).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtGui import QAccessible, QColor
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QDialog

from app.application.services.entity_service import EntityService
from app.application.services.event_service import EventService
from app.infrastructure.db.models import DescriptionModel, EventModel
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.event_type_repository import EventTypeRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository
from app.presentation import qml as qml_shell
from app.presentation.theme.compiler import CHART_TOKEN_KEYS
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.viewmodels.event_types_view_model import EventTypesViewModel
from app.presentation.views.event_types_dialog import (
    DEFAULT_NEW_TYPE_NAME,
    NO_TYPE_TEXT,
    EventTypesDialog,
    _token_color,
    type_dot_icon,
)

from tests.presentation.qml_helpers import (
    click_item,
    find_item,
    find_items,
    island_row_texts,
    island_rows,
    track,
    walk_items,
)
from tests.ui.test_theme_grab import make_runtime, token_color

D1 = date(1200, 1, 1)

ROOT_QML = Path(qml_shell.__file__).resolve().parent / "EventTypesRoot.qml"

#: The island's control contract — renames must fail this suite, not silently
#: unbind the facade (the very names the facade and the e2e address).
OBJECT_NAMES = (
    "eventTypesRoot",
    "typeHint",
    "typeList",
    "typeNameField",
    "typeAddButton",
    "typeRemoveButton",
    "typeUpButton",
    "typeDownButton",
    "typeCloseButton",
)

DEFAULT_NAMES = ["Сюжет", "Побочное", "Слух", "Встреча"]


# ── service / dialog fixtures ───────────────────────────────────────────────

async def _make_service(session) -> EventService:
    desc_repo = BaseRepository(session, DescriptionModel)
    return EventService(
        event_repo=EventRepository(session),
        description_repo=desc_repo,
        organization_service=EntityService(OrganizationRepository(session), desc_repo),
        character_service=EntityService(CharacterRepository(session), desc_repo),
        item_service=EntityService(ItemRepository(session), desc_repo),
        location_service=EntityService(LocationRepository(session), desc_repo),
        event_type_repo=EventTypeRepository(session),
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


async def _seed_defaults(service) -> list:
    created = []
    for name, index in [
        ("Сюжет", 1), ("Побочное", 2), ("Слух", 3), ("Встреча", 4),
    ]:
        created.append(await service.save_event_type(name=name, color_index=index))
    return created


async def _open_dialog(service, qtbot, theme=None):
    dialog = EventTypesDialog(service, theme=theme)
    qtbot.addWidget(dialog)
    await dialog.wait_idle()  # the initial load ran through `run`
    return dialog


# ── island addressing helpers (the production input route) ──────────────────

def _row_texts(dialog) -> list[str]:
    return island_row_texts(dialog.quick, "typeRow", "typeRowText")


def _click(dialog, object_name: str) -> None:
    click_item(dialog.quick, find_item(dialog.quick, object_name))


def _enabled(dialog, object_name: str) -> bool:
    return find_item(dialog.quick, object_name).property("enabled")


def _select(dialog, name: str) -> None:
    """Tap the island row whose label is ``name`` (the delegate's own click)."""
    for row in island_rows(dialog.quick, "typeRow"):
        labels = [i for i in walk_items(row) if i.objectName() == "typeRowText"]
        if labels and labels[0].property("text") == name:
            click_item(dialog.quick, row)
            return
    raise AssertionError(f"no island row {name!r} in {_row_texts(dialog)}")


def _type_name(dialog, text: str) -> None:
    """Type into the island name field, then finish the edit (rename route)."""
    find_item(dialog.quick, "typeNameField").setProperty("text", text)


def _finish_name_edit(dialog) -> None:
    find_item(dialog.quick, "typeNameField").editingFinished.emit()


def _name_text(dialog) -> str:
    return find_item(dialog.quick, "typeNameField").property("text")


# ── task 4.1: the island's objectName contract, VM requests only ────────────

@pytest.fixture
def island_palette(tmp_path):
    return QmlPalette(make_runtime(tmp_path, "dark"))


def _load_island(qtbot, vm, palette) -> QQuickWidget:
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    widget = QQuickWidget()
    qtbot.addWidget(widget)
    widget.engine().addImportPath(qml_shell.QML_IMPORT_PATH)
    vm.setParent(widget)
    palette.setParent(widget)
    # Island-scoped context: the VM + the palette bridge, nothing else — no
    # service, no http client, no `_run` (spec «Контекст типов изолирован»).
    widget.rootContext().setContextProperty("eventTypesVm", vm)
    widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(ROOT_QML)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    # The same size the facade opens its window at (`fit_dialog_to_island`):
    # a hardcoded box of the port's choosing hid whatever the fonts need and
    # the suite would click on clipped controls instead of the real ones. The
    # grab is what makes the layouts settle at the new size (the project's
    # convention for delegate materialization rides the same render pass).
    widget.resize(int(widget.rootObject().implicitWidth()),
                  int(widget.rootObject().implicitHeight()))
    widget.grab()
    return widget


def _island_vm() -> EventTypesViewModel:
    vm = EventTypesViewModel()
    vm.set_rows([
        SimpleNamespace(id=11, name="Сюжет", color_index=1, sort_order=0),
        SimpleNamespace(id=12, name="Побочное", color_index=2, sort_order=1),
    ])
    return vm


class TestIslandContract:
    def test_every_interactive_control_carries_its_object_name(
        self, qtbot, island_palette
    ):
        widget = _load_island(qtbot, _island_vm(), island_palette)
        names = {widget.rootObject().objectName()} | {
            item.objectName() for item in walk_items(widget.rootObject())
        }
        for expected in OBJECT_NAMES:
            assert expected in names, expected
        # Write-through: no Save button and no confirm affordance exists.
        assert "saveButton" not in names
        assert "confirmButton" not in names

    def test_map_names_surface_through_the_accessibility_interface(
        self, qtbot, island_palette
    ):
        """nri-0012 task 3.5: the rename field, the arrows and the palette
        swatches are addressable by name through the interface; text buttons
        keep the stock face (empty name slot offscreen, caption in ``text``)."""
        widget = _load_island(qtbot, _island_vm(), island_palette)

        def iface(object_name: str):
            found = QAccessible.queryAccessibleInterface(
                find_item(widget, object_name))
            assert found is not None, object_name
            return found

        name_field = iface("typeNameField")
        assert name_field.role() == QAccessible.Role.EditableText
        assert name_field.text(QAccessible.Name) == "Название типа события"

        up = iface("typeUpButton")
        assert up.role() == QAccessible.Role.Button
        assert up.text(QAccessible.Name) == "Поднять тип"
        down = iface("typeDownButton")
        assert down.role() == QAccessible.Role.Button
        assert down.text(QAccessible.Name) == "Опустить тип"

        # The swatch keeps the group-1 component default: «Цвет палитры №N»
        # (the map spells it, so no island override — index follows colorIndex).
        swatch2 = iface("typeColorSwatch2")
        assert swatch2.role() == QAccessible.Role.RadioButton
        assert swatch2.text(QAccessible.Name) == "Цвет палитры №2"

        add_item = find_item(widget, "typeAddButton")
        add = QAccessible.queryAccessibleInterface(add_item)
        assert add.role() == QAccessible.Role.Button
        assert add.text(QAccessible.Name) == ""
        assert add_item.property("text") == "Добавить"

    def test_exactly_eight_chart_swatches_and_no_free_color_control(
        self, qtbot, island_palette
    ):
        widget = _load_island(qtbot, _island_vm(), island_palette)
        swatches = [
            item for item in walk_items(widget.rootObject())
            if item.objectName().startswith("typeColorSwatch")
        ]
        assert len(swatches) == len(CHART_TOKEN_KEYS) == 8
        for index in range(1, 9):
            swatch = find_item(widget, f"typeColorSwatch{index}")
            assert swatch.property("colorIndex") == index
        # The only color affordance is the closed palette.
        assert find_items(widget, "colorPicker") == []
        assert find_items(widget, "colorDialogButton") == []

    def test_rows_are_listed_and_a_tap_selects_through_the_vm(
        self, qtbot, island_palette
    ):
        vm = _island_vm()
        widget = _load_island(qtbot, vm, island_palette)
        assert island_row_texts(widget, "typeRow", "typeRowText") == [
            "Сюжет", "Побочное",
        ]
        click_item(widget, island_rows(widget, "typeRow")[1])
        assert vm.selectedId == 12

    def test_action_row_stays_inside_the_island_at_its_own_size(
        self, qtbot, island_palette
    ):
        """↑/↓ must not fall off the right edge (the wide-font regression).

        Implicit button widths come from the system font, so a port-time width
        number is not a guarantee: whatever overflowed the frame was clipped and
        stopped receiving clicks (Qt 6.11 does not deliver clicks to a clipped
        control at all). The island therefore grows with its content, and this
        checks the row against the island's own width, not a fixed number.
        """
        widget = _load_island(qtbot, _island_vm(), island_palette)
        root = widget.rootObject()

        for name in ("typeAddButton", "typeRemoveButton", "typeUpButton",
                     "typeDownButton"):
            button = find_item(widget, name)
            origin = button.mapToScene(QPointF(0, 0))
            assert button.width() > 0, name
            assert origin.x() + button.width() <= root.width() + 1, name

    def test_clicks_emit_view_model_requests_only(self, qtbot, island_palette):
        vm = _island_vm()
        widget = _load_island(qtbot, vm, island_palette)
        added = track(vm.addRequested)
        removed = track(vm.removeRequested)
        moved = track(vm.moveRequested)
        recolored = track(vm.recolorRequested)
        closed = track(vm.closeRequested)

        click_item(widget, island_rows(widget, "typeRow")[0])
        click_item(widget, find_item(widget, "typeColorSwatch6"))
        click_item(widget, find_item(widget, "typeAddButton"))
        click_item(widget, find_item(widget, "typeDownButton"))
        click_item(widget, find_item(widget, "typeRemoveButton"))
        click_item(widget, find_item(widget, "typeCloseButton"))

        assert recolored == [(11, 6)]
        assert added == [("Сюжет",)]  # the name field mirrors the selection
        assert moved == [(11, 1)]
        assert removed == [(11,)]
        assert closed == [()]

    def test_swatches_and_actions_are_dead_without_a_selection(
        self, qtbot, island_palette
    ):
        vm = _island_vm()
        widget = _load_island(qtbot, vm, island_palette)
        recolored = track(vm.recolorRequested)
        click_item(widget, find_item(widget, "typeColorSwatch3"))
        assert recolored == []
        assert find_item(widget, "typeRemoveButton").property("enabled") is False
        assert find_item(widget, "typeUpButton").property("enabled") is False
        assert find_item(widget, "typeDownButton").property("enabled") is False
        assert find_item(widget, "typeAddButton").property("enabled") is True


# ── tasks 4.3/4.5: round-trips through the service, addressed on the island ──

class TestDialogRoundTripThroughService:
    async def test_initial_load_lists_types_in_order(self, async_session, qtbot):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        assert dialog.type_names() == DEFAULT_NAMES
        assert _row_texts(dialog) == DEFAULT_NAMES

    async def test_rename_persists_through_service(self, async_session, qtbot):
        service = await _make_service(async_session)
        types = await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        _select(dialog, "Слух")
        _type_name(dialog, "Примета")
        _finish_name_edit(dialog)
        await dialog.wait_idle()

        stored = {t.name: t for t in await service.get_event_types()}
        assert "Примета" in stored and "Слух" not in stored
        # Rename kept the type's identity: same id, same color (spec scenario).
        assert stored["Примета"].id == types[2].id
        assert stored["Примета"].color_index == 3
        # The same row shows the new name, the selection stayed on it.
        assert _row_texts(dialog)[2] == "Примета"
        assert dialog.vm.selectedId == types[2].id

    async def test_empty_or_unchanged_rename_is_not_persisted(
        self, async_session, qtbot
    ):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        _select(dialog, "Сюжет")
        _type_name(dialog, "   ")
        _finish_name_edit(dialog)
        _type_name(dialog, "Сюжет")
        _finish_name_edit(dialog)
        await dialog.wait_idle()
        assert [t.name for t in await service.get_event_types()] == DEFAULT_NAMES

    async def test_swatch_color_choice_round_trips(self, async_session, qtbot):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        _select(dialog, "Сюжет")
        assert dialog.vm.selectedColorIndex == 1  # reflects the current color
        _click(dialog, "typeColorSwatch7")  # palette sample №7
        await dialog.wait_idle()
        stored = {t.name: t for t in await service.get_event_types()}
        assert stored["Сюжет"].color_index == 7
        assert dialog.vm.selectedColorIndex == 7

    async def test_add_appends_with_first_free_color_and_selects_it(
        self, async_session, qtbot
    ):
        service = await _make_service(async_session)
        await _seed_defaults(service)  # colors 1..4 used
        dialog = await _open_dialog(service, qtbot)
        _type_name(dialog, "Находка")
        _click(dialog, "typeAddButton")
        await dialog.wait_idle()

        types = list(await service.get_event_types())
        assert [t.name for t in types][-1] == "Находка"
        assert types[-1].color_index == 5  # first unused palette index
        assert dialog.vm.selectedId == types[-1].id
        assert _name_text(dialog) == "Находка"

    async def test_add_without_name_falls_back_to_default_name(
        self, async_session, qtbot
    ):
        service = await _make_service(async_session)
        dialog = await _open_dialog(service, qtbot)
        _click(dialog, "typeAddButton")
        await dialog.wait_idle()
        names = [t.name for t in await service.get_event_types()]
        assert names == [DEFAULT_NEW_TYPE_NAME]

    async def test_ninth_type_rotates_palette_index(self, async_session, qtbot):
        service = await _make_service(async_session)
        for k in range(1, 9):  # all eight palette colors are used
            await service.save_event_type(name=f"T{k}", color_index=k)
        dialog = await _open_dialog(service, qtbot)
        _type_name(dialog, "Девятый")
        _click(dialog, "typeAddButton")
        await dialog.wait_idle()
        types = list(await service.get_event_types())
        idx = {t.name: t.color_index for t in types}["Девятый"]
        assert 1 <= idx <= 8  # rotation stays inside the token palette

    async def test_delete_removes_type_from_service(self, async_session, qtbot):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        _select(dialog, "Встреча")
        _click(dialog, "typeRemoveButton")  # plain unbind, no confirmation
        await dialog.wait_idle()
        assert [t.name for t in await service.get_event_types()] == [
            "Сюжет", "Побочное", "Слух",
        ]
        assert dialog.type_names() == ["Сюжет", "Побочное", "Слух"]
        assert dialog.vm.selectedId is None  # the removed row took the selection

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
        _select(dialog, "Слух")
        _click(dialog, "typeRemoveButton")
        await dialog.wait_idle()

        assert list(await service.get_event_types()) == []
        all_events = list(await service.get_all_events())
        assert {e.id for e in all_events} == {e.id for e in events}  # intact
        for e in all_events:
            assert e.event_type is None  # every unbound, a valid typed-less event

    async def test_up_down_buttons_reorder_via_service(self, async_session, qtbot):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        assert _enabled(dialog, "typeUpButton") is False  # nothing selected
        _select(dialog, "Сюжет")
        assert _enabled(dialog, "typeUpButton") is False  # first row
        _click(dialog, "typeDownButton")
        await dialog.wait_idle()
        assert [t.name for t in await service.get_event_types()] == [
            "Побочное", "Сюжет", "Слух", "Встреча",
        ]
        assert _row_texts(dialog) == ["Побочное", "Сюжет", "Слух", "Встреча"]
        assert _name_text(dialog) == "Сюжет"  # selection kept up with the row
        assert _enabled(dialog, "typeUpButton") is True
        _click(dialog, "typeUpButton")
        await dialog.wait_idle()
        assert [t.name for t in await service.get_event_types()] == DEFAULT_NAMES
        # The last row has nothing below it — the ↓ affordance is off there.
        _select(dialog, "Встреча")
        assert _enabled(dialog, "typeDownButton") is False
        assert _enabled(dialog, "typeUpButton") is True

    async def test_each_edit_emits_types_changed(self, async_session, qtbot):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        fired = track(dialog.types_changed)
        _select(dialog, "Слух")
        _type_name(dialog, "Примета")
        _finish_name_edit(dialog)
        await dialog.wait_idle()
        _click(dialog, "typeColorSwatch6")
        await dialog.wait_idle()
        assert len(fired) == 2

    async def test_public_reload_picks_up_a_change_made_outside(
        self, async_session, qtbot
    ):
        """``reload()`` is the public refresh seam: a type created behind the
        dialog's back shows up on the next reload."""
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        await service.save_event_type(name="Внешний", color_index=5)
        assert "Внешний" not in dialog.type_names()

        await dialog.reload()

        assert dialog.type_names() == DEFAULT_NAMES + ["Внешний"]
        assert _row_texts(dialog) == DEFAULT_NAMES + ["Внешний"]


# ── write-through: no Save, no confirmation on close (spec scenarios) ───────

class TestWriteThroughClose:
    async def test_close_accepts_without_confirmation_and_keeps_the_edits(
        self, async_session, qtbot
    ):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        _select(dialog, "Слух")
        _type_name(dialog, "Примета")
        _finish_name_edit(dialog)
        await dialog.wait_idle()

        _click(dialog, "typeCloseButton")
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert not dialog.isVisible()
        # Nothing rolled back: the applied rename is still the game's state.
        assert "Примета" in [t.name for t in await service.get_event_types()]

    async def test_esc_rejects_without_confirmation(self, async_session, qtbot):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        dialog.reject()
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert [t.name for t in await service.get_event_types()] == DEFAULT_NAMES


# ── write guards (line-coverage gate of the facade) ─────────────────────────

class TestWriteGuards:
    async def test_no_selection_silences_every_write(self, async_session, qtbot):
        """Nothing selected: no rename, recolor, delete or move starts a task."""
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        emitted = track(dialog.types_changed)

        _type_name(dialog, "Ничья")
        _finish_name_edit(dialog)
        _click(dialog, "typeColorSwatch2")
        _click(dialog, "typeRemoveButton")
        _click(dialog, "typeUpButton")
        _click(dialog, "typeDownButton")
        await dialog.wait_idle()

        assert dialog._task is None
        assert emitted == []
        assert dialog.type_names() == DEFAULT_NAMES

    async def test_move_past_the_ladder_edges_is_a_no_op(self, async_session, qtbot):
        """The first row has nothing above it, the last nothing below."""
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)

        _select(dialog, "Сюжет")
        dialog.vm.moveRequested.emit(dialog.vm.selectedId, -1)
        await dialog.wait_idle()
        assert dialog._task is None

        _select(dialog, "Встреча")
        dialog.vm.moveRequested.emit(dialog.vm.selectedId, 1)
        await dialog.wait_idle()
        assert dialog._task is None
        assert dialog.type_names() == DEFAULT_NAMES

    async def test_requests_for_a_vanished_type_are_dropped(
        self, async_session, qtbot
    ):
        """A stale id (the row was deleted behind the island) writes nothing."""
        service = await _make_service(async_session)
        await _seed_defaults(service)
        dialog = await _open_dialog(service, qtbot)
        gone = 999

        dialog.vm.renameRequested.emit(gone, "Никак")
        dialog.vm.recolorRequested.emit(gone, 5)
        dialog.vm.removeRequested.emit(gone)
        dialog.vm.moveRequested.emit(gone, 1)
        await dialog.wait_idle()

        assert dialog._task is None
        assert [t.name for t in await service.get_event_types()] == DEFAULT_NAMES

    async def test_done_releases_the_island(self, async_session, qtbot):
        service = await _make_service(async_session)
        dialog = await _open_dialog(service, qtbot)
        dialog.done(0)
        qtbot.waitUntil(lambda: dialog.quick.source().isEmpty(), timeout=2000)


# ── the one live-retheme scenario of this island (task 5.1) ─────────────────

class TestLiveRetheme:
    async def test_theme_swap_keeps_selection_and_order(
        self, async_session, qtbot, tmp_path
    ):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        runtime = make_runtime(tmp_path, "dark")
        dialog = await _open_dialog(service, qtbot, theme=runtime)
        _select(dialog, "Слух")
        selected = dialog.vm.selectedId

        def swatch_color(index: int) -> QColor:
            return find_item(dialog.quick, f"typeColorSwatch{index}").property(
                "chartColor"
            )

        for index, key in enumerate(CHART_TOKEN_KEYS, start=1):
            assert swatch_color(index) == token_color(key, "dark")

        assert runtime.toggle()  # dark → light through the runtime

        for index, key in enumerate(CHART_TOKEN_KEYS, start=1):
            assert swatch_color(index) == token_color(key, "light")
        # Same island, same selection, same order (no rebuild, no reload).
        assert dialog.vm.selectedId == selected
        assert _name_text(dialog) == "Слух"
        assert _row_texts(dialog) == DEFAULT_NAMES

    async def test_off_skin_island_loads_without_a_palette(
        self, async_session, qtbot, tmp_path
    ):
        service = await _make_service(async_session)
        await _seed_defaults(service)
        offskin = make_runtime(tmp_path, "dark", tokens_path=tmp_path / "absent.json")
        assert not offskin.is_valid
        dialog = await _open_dialog(service, qtbot, theme=offskin)
        assert _row_texts(dialog) == DEFAULT_NAMES
        # The library swatch degrades to its numbered off-skin sample.
        assert find_item(dialog.quick, "typeColorSwatch1").property("skinned") is False


# ── helpers other screens import from this module (kept 1:1) ───────────────

def test_type_palette_helpers_stay_exported_for_the_event_dialog():
    """``event_dialog.py`` (still widgets) imports these two names."""
    assert NO_TYPE_TEXT == "Без типа"
    assert not type_dot_icon(None, 3).isNull()
    assert _token_color(None, 0) is None
    assert _token_color(None, -1) is None
    assert _token_color(None, len(CHART_TOKEN_KEYS) + 1) is None


async def test_theme_none_takes_the_process_default_palette(async_session, qtbot):
    """The island always needs a palette bridge: ``theme=None`` takes the
    process default (the pack-1 facade rule), never a bare context."""
    service = await _make_service(async_session)
    dialog = await _open_dialog(service, qtbot)
    assert dialog._palette.tokens["color.bg.surface"]
    assert find_item(dialog.quick, "typeColorSwatch1").property("skinned") is True
