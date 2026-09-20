from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QIcon, QPixmap

from app.presentation.viewmodels.world_snapshot_view_model import (
    WorldSnapshotViewModel,
)


def _entity(entity_id, name, rating=1, characteristics=""):
    return SimpleNamespace(
        id=entity_id,
        name=name,
        rating=rating,
        image_ref=None,
        description=SimpleNamespace(characteristics=characteristics),
    )


def _event(
    event_id=1,
    name="Событие",
    *,
    locations=(),
    organizations=(),
    characters=(),
    items=(),
):
    return SimpleNamespace(
        id=event_id,
        name=name,
        start_date=date(1200, 1, 1),
        end_date=date(1200, 2, 1),
        locations=list(locations),
        organizations=list(organizations),
        characters=list(characters),
        items=list(items),
    )


def _rows(vm):
    return [
        {
            name.decode(): vm.rowModel.data(vm.rowModel.index(index, 0), role)
            for role, name in vm.rowModel.roleNames().items()
        }
        for index in range(vm.rowModel.rowCount())
    ]


def test_initial_clear_and_empty_populate_states(qapp):
    vm = WorldSnapshotViewModel()
    assert vm.emptyText == "Выберите дату и нажмите «Показать»"
    assert vm.statsText == ""
    assert vm.clearEnabled is False
    assert _rows(vm) == []

    vm.populate([], date(1200, 1, 1))
    assert vm.emptyText == "На эту дату нет активных событий"
    assert vm.clearEnabled is True

    vm.populate([], None)
    assert vm.emptyText == "Нет событий в игре"
    vm.clear()
    assert vm.emptyText == "Выберите дату и нажмите «Показать»"
    assert vm.clearEnabled is False


def test_populate_builds_render_ready_flat_rows_and_stats(qapp):
    location = _entity(3, "Замок", 5, "Высокая башня")
    character = _entity(4, "Герой", 15)
    vm = WorldSnapshotViewModel()
    vm.populate(
        [_event(locations=[location], characters=[character])],
        date(1200, 1, 15),
    )

    rows = _rows(vm)
    assert {row["rowKind"] for row in rows} == {"sectionHeader", "entityRow"}
    for row in rows:
        assert {
            "type", "id", "name", "ratingHex", "fontBold",
            "tooltipHtml", "icon",
        } <= row.keys()
    assert any(row["type"] == "character" and row["fontBold"] for row in rows)
    location_row = next(
        row for row in rows
        if row["rowKind"] == "entityRow" and row["type"] == "location"
    )
    assert "Высокая башня" in location_row["tooltipHtml"]
    assert "Дата: 15 Январь 1200" in vm.statsText
    assert "Событий: 1" in vm.statsText
    assert vm.emptyText == ""


def test_populate_prints_bc_event_dates_with_the_suffix(qapp):
    """Spec «Отображение эры» (add-era-aware-dates): the snapshot event row is
    another live display of the event date — BC bounds print the suffix, the
    open end stays ``∞`` regardless of era."""
    vm = WorldSnapshotViewModel()
    closed = _event(event_id=1)
    closed.start_date = date(44, 3, 5)
    closed.end_date = date(40, 1, 1)
    closed.start_bc = True
    closed.end_bc = True
    open_bc = _event(event_id=2)
    open_bc.start_date = date(300, 6, 1)
    open_bc.end_date = None
    open_bc.start_bc = True
    vm.populate([closed, open_bc], None)
    vm.toggleSection("events")

    event_rows = [
        row for row in _rows(vm)
        if row["rowKind"] == "entityRow" and row["type"] == "event"
    ]
    display = {row["id"]: row["displayText"] for row in event_rows}
    assert display[1] == "05 Март 44 г. до н.э. — 01 Январь 40 г. до н.э.  |  Событие"
    assert display[2] == "01 Июнь 300 г. до н.э. — ∞  |  Событие"


def test_sections_keep_expansion_across_populate(qapp):
    vm = WorldSnapshotViewModel()
    event = _event(locations=[_entity(1, "Лес")])
    vm.populate([event], None)
    assert not any(
        row["rowKind"] == "entityRow" and row["type"] == "event"
        for row in _rows(vm)
    )
    assert any(
        row["rowKind"] == "entityRow" and row["type"] == "location"
        for row in _rows(vm)
    )

    vm.toggleSection("locations")
    assert not any(
        row["rowKind"] == "entityRow" and row["type"] == "location"
        for row in _rows(vm)
    )
    vm.populate([event], date(1200, 1, 1))
    assert not any(
        row["rowKind"] == "entityRow" and row["type"] == "location"
        for row in _rows(vm)
    )

    vm.toggleSection("locations")
    assert any(
        row["rowKind"] == "entityRow" and row["type"] == "location"
        for row in _rows(vm)
    )


def test_ordering_icon_size_boldness_and_selection(qapp, monkeypatch):
    pixmap = QPixmap(24, 24)
    pixmap.fill()
    monkeypatch.setattr(
        "app.presentation.viewmodels.world_snapshot_view_model.load_entity_preview",
        lambda _entity, slot_size: pixmap if slot_size == 24 else QPixmap(),
    )
    vm = WorldSnapshotViewModel()
    selected = []
    vm.entitySelected.connect(lambda kind, entity_id: selected.append((kind, entity_id)))
    vm.populate(
        [
            _event(
                locations=[_entity(2, "Яма"), _entity(1, "Арка")],
                characters=[
                    _entity(5, "Низкий", 2),
                    _entity(6, "Высокий", 19),
                ],
            )
        ],
        None,
    )
    vm.toggleSection("events")
    rows = _rows(vm)
    location_names = [
        r["name"] for r in rows
        if r["rowKind"] == "entityRow" and r["type"] == "location"
    ]
    character_names = [
        r["name"] for r in rows
        if r["rowKind"] == "entityRow" and r["type"] == "character"
    ]
    assert location_names == ["Арка", "Яма"]
    assert character_names == ["Высокий", "Низкий"]

    character_row = next(
        r for r in rows
        if r["rowKind"] == "entityRow" and r["type"] == "character"
    )
    assert isinstance(character_row["icon"], QIcon)
    assert 24 in [size.width() for size in character_row["icon"].availableSizes()]
    assert character_row["fontBold"] is True

    character_index = next(
        i for i, row in enumerate(rows)
        if row["rowKind"] == "entityRow" and row["type"] == "character"
    )
    event_index = next(
        i for i, row in enumerate(rows)
        if row["rowKind"] == "entityRow" and row["type"] == "event"
    )
    header_index = next(i for i, row in enumerate(rows) if row["rowKind"] == "sectionHeader")
    vm.select(character_index)
    vm.select(event_index)
    vm.select(header_index)
    assert selected == [("character", character_row["id"])]


def test_all_mode_stats(qapp):
    vm = WorldSnapshotViewModel()
    vm.populate([_event(characters=[_entity(1, "Герой")])], None)
    assert vm.statsText.startswith("Показано: все события")
    assert "Персонажей: 1" in vm.statsText


def test_invalid_model_and_sync_inputs_are_ignored(qapp):
    vm = WorldSnapshotViewModel()
    model = vm.rowModel
    assert model.data(QModelIndex()) is None

    vm.populate([_event(locations=[_entity(1, "Лес")])], None)
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) is None
    # setDateIso is gone (piece C3a, design D6: QML never wrote the ISO slot
    # back — the reverse contract was fictional); the bridge itself still
    # ignores absent input.
    before_date = vm.dateIso
    vm.set_date(vm._date)
    vm.set_date(None)  # «нет даты» не сдвигает выбранный день
    assert vm.dateIso == before_date

    rows = _rows(vm)
    entity_index = next(
        index for index, row in enumerate(rows) if row["rowKind"] == "entityRow"
    )
    before_rows = rows
    vm.toggleSection("missing")
    vm.toggleSection(entity_index)
    vm.select(-1)
    vm.select(999)
    assert _rows(vm) == before_rows


def test_date_change_and_rating_color_refresh(qapp):
    runtime = SimpleNamespace(
        theme="dark",
        tokens={
            "color.rating.low": {"dark": "#101010", "light": "#202020"},
            "color.rating.high": {"dark": "#ff0000", "light": "#00ff00"},
        },
        add_listener=lambda callback: None,
    )
    vm = WorldSnapshotViewModel(runtime)
    # The deleted setDateIso slot is replaced by the bridge's own entry
    # (piece C3a): the same day arrives as a plain date, ISO stays ISO.
    vm.set_date(date(1200, 3, 4))
    assert vm.dateIso == "1200-03-04"
    vm.populate([_event(locations=[_entity(1, "Лес", 20)])], None)
    changed = []
    vm.rowModel.dataChanged.connect(lambda *args: changed.append(args))

    runtime.theme = "light"
    vm.rowModel.refresh_rating_colors(runtime)
    assert len(changed) == 1
    vm.rowModel.refresh_rating_colors(runtime)
    assert len(changed) == 1
