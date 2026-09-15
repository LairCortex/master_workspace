from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QModelIndex, Qt

from app.presentation.viewmodels.detail_panel_view_model import (
    DetailPanelViewModel,
    DetailRowsModel,
)


def _entity(entity_id=1, name="Гильдия", rating=12, **extra):
    entity = SimpleNamespace(
        id=entity_id,
        name=name,
        rating=rating,
        description=SimpleNamespace(
            characteristics="Скрытная",
            backstory="Основана давно",
        ),
        personality=None,
        tasks="Найти артефакт",
        characters=[],
        organizations=[],
        items=[],
        locations=[],
        image_ref=None,
    )
    for key, value in extra.items():
        setattr(entity, key, value)
    return entity


def _event(**extra):
    event = SimpleNamespace(
        id=7,
        name="Битва",
        start_date=date(1200, 1, 2),
        end_date=None,
        organizations=[_entity()],
        characters=[],
        items=[],
        locations=[],
    )
    for key, value in extra.items():
        setattr(event, key, value)
    return event


def _row(model: DetailRowsModel, index=0):
    return {
        bytes(name).decode(): model.data(model.index(index, 0), role)
        for role, name in model.roleNames().items()
    }


def test_show_event_publishes_header_tabs_and_python_derived_rows(monkeypatch):
    monkeypatch.setattr(
        "app.presentation.viewmodels.detail_panel_view_model.resolve_preview_path",
        lambda entity: "/tmp/entity preview.webp",
    )
    vm = DetailPanelViewModel()
    vm.show_event(_event())

    assert vm.title == "Битва"
    assert vm.dateText == "02 Январь 1200 — ∞"
    assert vm.tabTitles == ["Организации", "Персонажи", "Предметы", "Локации"]
    assert [model.rowCount() for model in vm.models] == [1, 0, 0, 0]

    row = _row(vm.organizations)
    assert row["name"] == "Гильдия"
    assert "<b>Рейтинг:</b> 12/20" in row["summary"]
    assert "<b>Хар-ки:</b> Скрытная" in row["summary"]
    assert row["entityType"] == "organization"
    assert row["entityId"] == 1
    assert row["imageSource"].startswith("file:")
    assert "entity preview.webp" in row["imageSource"]


def test_clear_resets_header_and_all_four_models():
    vm = DetailPanelViewModel()
    vm.show_event(_event(characters=[_entity(2, "Герой")]))
    vm.clear()

    assert vm.title == ""
    assert vm.dateText == ""
    assert [model.rowCount() for model in vm.models] == [0, 0, 0, 0]


def test_row_activation_and_image_request_keep_entity_identity(qtbot):
    entity = _entity(19)
    vm = DetailPanelViewModel()
    vm.show_event(_event(organizations=[entity]))

    with qtbot.waitSignal(vm.entityActivated) as selected:
        vm.activate("organization", 19)
    assert selected.args == ["organization", 19]

    with qtbot.waitSignal(vm.imageRequested) as requested:
        vm.requestImage("organization", 19)
    assert requested.args == [entity]


def test_retheme_recomputes_rating_tint_incrementally(monkeypatch):
    colors = iter(["#11223350", "#445566dc"])
    monkeypatch.setattr(
        "app.presentation.viewmodels.detail_panel_view_model.rating_to_color",
        lambda rating, runtime: next(colors),
    )
    runtime = SimpleNamespace(add_listener=lambda callback: setattr(runtime, "listener", callback))
    vm = DetailPanelViewModel(runtime)
    vm.show_event(_event())
    before = _row(vm.organizations)["ratingTint"]

    changed = []
    vm.organizations.dataChanged.connect(lambda *args: changed.append(args))
    runtime.listener()

    assert before == "#11223350"
    assert _row(vm.organizations)["ratingTint"] == "#445566dc"
    assert changed
    assert changed[0][2] == [DetailRowsModel.RatingTintRole]
    assert vm.organizations.data(QModelIndex(), Qt.ItemDataRole.DisplayRole) is None
    assert (
        vm.organizations.data(
            vm.organizations.index(0, 0), Qt.ItemDataRole.DisplayRole
        )
        is None
    )


def test_unknown_entity_requests_are_ignored():
    vm = DetailPanelViewModel()
    vm.show_event(_event())
    activated = []
    images = []
    vm.entityActivated.connect(lambda *args: activated.append(args))
    vm.imageRequested.connect(lambda *args: images.append(args))

    vm.activate("character", 999)
    vm.requestImage("character", 999)

    assert activated == []
    assert images == []


def test_show_event_prints_bc_dates_with_the_suffix():
    """Spec «Отображение эры» (add-era-aware-dates): the detail panel is one of
    the places the event's date shows — every BC bound prints with the
    «N г. до н.э.» suffix, an open end stays era-free ``∞``."""
    vm = DetailPanelViewModel()
    vm.show_event(_event(
        start_date=date(44, 3, 5), end_date=date(40, 1, 1),
        start_bc=True, end_bc=True,
    ))

    assert vm.dateText == "05 Март 44 г. до н.э. — 01 Январь 40 г. до н.э."


def test_show_event_bc_start_open_end_keeps_unbounded_mark_era_free():
    """Spec «Пометка открытого конца не зависит от эры»."""
    vm = DetailPanelViewModel()
    vm.show_event(_event(start_date=date(300, 6, 1), end_date=None, start_bc=True))

    assert vm.dateText == "01 Июнь 300 г. до н.э. — ∞"
