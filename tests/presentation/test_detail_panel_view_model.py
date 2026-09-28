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


def test_event_selection_flag_tracks_show_event_and_clear():
    # NRI-0015 (M4): the empty-panel hint binds this flag; show_event raises
    # it, clear lowers it again.
    vm = DetailPanelViewModel()
    assert vm.eventSelected is False
    vm.show_event(_event())
    assert vm.eventSelected is True
    vm.clear()
    assert vm.eventSelected is False


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


# ── change nri-0022-entity-preview, task 3.1/3.2: the single row selection ──


def _selection_flags(model) -> list[bool]:
    return [
        bool(model.data(model.index(i, 0), DetailRowsModel.SelectedRole))
        for i in range(model.rowCount())
    ]


def test_select_washes_only_the_chosen_row_and_announces_the_preview(qtbot):
    # Task 3.1: the single click moves the panel's ONE selection — the chosen
    # row takes the `selected` role, the sibling loses it (mutual removal) —
    # and the new entitySelected carries the preview target the wiring rides.
    vm = DetailPanelViewModel()
    vm.show_event(_event(organizations=[_entity(1, "Гильдия"), _entity(2, "Купцы")]))
    selected = []
    vm.entitySelected.connect(lambda *args: selected.append(args))

    vm.select("organization", 2)

    assert _selection_flags(vm.organizations) == [False, True]
    assert selected == [("organization", 2)]
    assert vm.last_selected == ("organization", 2)


def test_selection_is_the_panels_one_across_tabs(qtbot):
    # Task 3.1: choosing a row removes the wash from any previously selected
    # row, the other tabs included (spec «в том числе на другой вкладке»).
    vm = DetailPanelViewModel()
    vm.show_event(
        _event(organizations=[_entity()], characters=[_entity(9, "Герой")])
    )

    vm.select("organization", 1)
    vm.select("character", 9)

    assert _selection_flags(vm.organizations) == [False]
    assert _selection_flags(vm.characters) == [True]
    assert vm.last_selected == ("character", 9)


def test_select_ignores_a_pair_outside_the_shown_lists():
    # The same ignore posture as activate: a stale/wrong pair emits nothing
    # and moves neither the wash nor the remembered selection.
    vm = DetailPanelViewModel()
    vm.show_event(_event())
    selected = []
    vm.entitySelected.connect(lambda *args: selected.append(args))

    vm.select("character", 999)

    assert selected == []
    assert vm.last_selected is None


def test_tab_switch_hides_the_wash_and_keeps_the_remembered_selection(qtbot):
    # Task 3.2 (design D3): the wash is screen state — hideRowHighlight
    # answers every row False with a targeted SelectedRole dataChanged — while
    # the remembered selection (and the preview behind the one signal) waits
    # for the next select; re-selecting the same row re-lights it.
    vm = DetailPanelViewModel()
    vm.show_event(_event())
    vm.select("organization", 1)

    changed = []
    vm.organizations.dataChanged.connect(lambda *args: changed.append(args))
    vm.hideRowHighlight()

    assert _selection_flags(vm.organizations) == [False]
    assert changed[0][2] == [DetailRowsModel.SelectedRole]
    assert vm.last_selected == ("organization", 1)

    vm.select("organization", 1)
    assert _selection_flags(vm.organizations) == [True]


def test_selecting_the_already_washed_row_is_stable():
    # A second single click on the same row re-answers every row False->False
    # except its own already-True one — no dataChanged churn on the siblings,
    # the preview signal still fires (the user asked to look again).
    vm = DetailPanelViewModel()
    vm.show_event(_event(organizations=[_entity(1, "Гильдия"), _entity(2, "Купцы")]))
    vm.select("organization", 2)
    changed = []
    vm.organizations.dataChanged.connect(lambda *args: changed.append(args))
    selected = []
    vm.entitySelected.connect(lambda *args: selected.append(args))

    vm.select("organization", 2)

    assert _selection_flags(vm.organizations) == [False, True]
    assert changed == []
    assert selected == [("organization", 2)]


def test_a_new_event_rebuilds_rows_without_a_wash():
    # Re-rendering the lists (show_event) paints fresh rows; the remembered
    # selection survives as memory only — the highlight never jumps onto rows
    # the user did not click in this event (spec: wash follows the click).
    vm = DetailPanelViewModel()
    vm.show_event(_event())
    vm.select("organization", 1)

    vm.show_event(_event())

    assert _selection_flags(vm.organizations) == [False]
    assert vm.last_selected == ("organization", 1)


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
