from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QModelIndex, Qt

from app.domain.game_calendar import MonthDay
from app.presentation.viewmodels.now_date_view_model import NowDateViewModel
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
    parent_id=None,
    start_time=None,
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
        # NRI-0023 duck-typed optionals (tasks 8.1/8.3): the parent self-FK
        # and the domain-face start time; None reads as «top-level» / «без
        # времени» exactly as the NULLable columns do.
        parent_id=parent_id,
        start_time=start_time,
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
            "tooltipHtml", "iconName",
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


def test_ordering_icon_name_boldness_and_selection(qapp):
    # Lucide pass 2026-09-30: the icon slots carry the library glyph NAME the
    # QML ThemeIcon paints (the emoji-rendered QIcon and its photo-preview
    # monkeypatch retired with the mute-text icon practice).
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
    assert character_row["iconName"] == "user-round"
    assert character_row["iconSize"] == 24
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


# ── NRI-0021 task 6.2 — the field starts at the game's «now» ───────────────
# Spec world-snapshot (modified «Снимок собирается по дате игрового мира»):
# «Поле стартует с игровой даты», «Сброс возвращает исходное состояние» (the
# date field included) and «Выбранная дата не сбивается правкой „сейчас“».


def _now_vm(coord, is_bc=False):
    return NowDateViewModel(coord, is_bc)


def test_date_field_starts_at_the_game_now(qapp):
    vm = WorldSnapshotViewModel(now_vm=_now_vm(MonthDay(2091, 5, 1)))
    # scenario «Поле стартует с игровой даты» — not the system today
    assert vm.dateIso == "2091-05-01"
    assert vm.dateDisplay == "01 Май 2091"
    assert vm.dateBc is False


def test_bc_now_seeds_the_era_of_the_field(qapp):
    vm = WorldSnapshotViewModel(now_vm=_now_vm(MonthDay(44, 3, 5), is_bc=True))
    assert vm.dateBc is True
    assert vm.dateDisplay == "05 Март 44 г. до н.э."


def test_without_a_game_the_today_fallback_stays(qapp):
    vm = WorldSnapshotViewModel()
    assert vm.dateIso == date.today().isoformat()


def test_reset_returns_the_field_to_now(qtbot):
    vm = WorldSnapshotViewModel(now_vm=_now_vm(MonthDay(2091, 5, 1)))
    vm.set_date(date(1200, 3, 4))
    assert vm.dateIso == "1200-03-04"
    vm.populate([_event()], None)  # enable «Сброс» like a real first slice
    with qtbot.waitSignal(vm.dateChanged):
        vm.clear()
    # scenario «Сброс возвращает исходное состояние»: field back to «now»
    assert vm.dateIso == "2091-05-01"


def test_chosen_date_survives_now_edits_and_reset_lands_on_the_new_now(qtbot):
    now_vm = _now_vm(MonthDay(2091, 5, 1))
    vm = WorldSnapshotViewModel(now_vm=now_vm)
    vm.set_date(date(1200, 3, 4))
    # scenario «Выбранная дата не сбивается правкой „сейчас“»: the field has
    # no nowChanged subscription — an edit leaves it exactly where the master
    # put it…
    now_vm.applyNow(MonthDay(2093, 7, 8), False)
    assert vm.dateIso == "1200-03-04"
    # …while the next «Сброс» returns it to the «now» served at reset time
    vm.populate([_event()], None)
    vm.clear()
    assert vm.dateIso == "2093-07-08"


def test_reset_on_the_already_now_date_is_silent(qtbot):
    vm = WorldSnapshotViewModel(now_vm=_now_vm(MonthDay(2091, 5, 1)))
    vm.populate([_event()], None)
    with qtbot.assertNotEmitted(vm.dateChanged):
        vm.clear()
    assert vm.dateIso == "2091-05-01"


def test_reset_without_a_game_leaves_the_field(qtbot):
    # legacy no-game posture: clear() knows no «now», the field stays
    vm = WorldSnapshotViewModel()
    vm.set_date(date(1200, 3, 4))
    with qtbot.assertNotEmitted(vm.dateChanged):
        vm.clear()
    assert vm.dateIso == "1200-03-04"


# ── NRI-0023 task 8.3: the «События» section as a two-level tree ────────────

# The tree indent is the non-breaking-space block the child caption opens
# with; the tests spell it the same way the ViewModel does.
INDENT = "\u00a0" * 4


def _event_rows(vm):
    """The «События» section rows only — the section header excluded."""
    return [
        row
        for row in _rows(vm)
        if row["sectionKey"] == "events" and row["rowKind"] != "sectionHeader"
    ]


def test_children_are_indented_directly_under_their_parent(qapp):
    """Spec «Подсобытие отступом под родителем» + «Дети идут сразу за
    родителем»: two parents in slice order, the second's child lands under
    it — indented, not in the common chronological row; always expanded
    (the snapshot never asks to open a section)."""
    vm = WorldSnapshotViewModel()
    vm.populate(
        [
            _event(1, "Первый поход"),
            _event(2, "Вторая война"),
            _event(3, "Осада", parent_id=2),
        ],
        date(1200, 1, 15),
    )
    vm.toggleSection("events")

    event_rows = _event_rows(vm)
    assert [row["name"] for row in event_rows] == [
        "Первый поход",
        "Вторая война",
        "Осада",
    ]
    assert event_rows[2]["displayText"].startswith(INDENT)
    assert not event_rows[0]["displayText"].startswith(INDENT)
    assert not event_rows[1]["displayText"].startswith(INDENT)
    # The indent is display-only: identity and click data are untouched.
    assert event_rows[2]["id"] == 3 and event_rows[2]["rowKind"] == "entityRow"


def test_orphaned_child_gets_a_parent_stub_above_it(qapp):
    """Spec «Осиротевшее в срезе подсобытие получает заглушку»: the parent is
    out of the slice, so its NAME heads the orphan as a stub — and the stats
    count every real event while the stub contributes nothing."""
    vm = WorldSnapshotViewModel()
    vm.populate(
        [
            _event(1, "Родитель с детьми"),
            _event(2, "Первый сын", parent_id=1),
            _event(3, "Второй сын", parent_id=1),
            _event(4, "Сирота", parent_id=9),
        ],
        date(1200, 1, 15),
        {9: "Ушедший отец"},
    )
    vm.toggleSection("events")

    event_rows = _event_rows(vm)
    assert [(row["rowKind"], row["name"]) for row in event_rows] == [
        ("entityRow", "Родитель с детьми"),
        ("entityRow", "Первый сын"),
        ("entityRow", "Второй сын"),
        ("stubRow", "Ушедший отец"),
        ("entityRow", "Сирота"),
    ]
    stub = event_rows[3]
    # Name only: no dates in the stub caption, and it is no click target.
    assert stub["displayText"] == "Ушедший отец"
    assert stub["selectable"] is False
    orphans = [row for row in event_rows if row["displayText"].startswith(INDENT)]
    assert [row["name"] for row in orphans] == ["Первый сын", "Второй сын", "Сирота"]
    # «Подсобытия в счётчике, заглушки — нет»: four real events, one stub.
    assert "Событий: 4" in vm.statsText
    header = next(row for row in _rows(vm) if row["rowKind"] == "sectionHeader")
    # The label is the registry caption with the icon prefix; the count is
    # the four real events — the stub row is not counted.
    assert header["displayText"].endswith("события (4)")


def test_an_unnamed_orphan_stays_a_plain_row(qapp):
    """An orphan whose parent the id → имя card cannot name gets no
    half-empty stub — the row simply reads as it did before the tree."""
    vm = WorldSnapshotViewModel()
    vm.populate([_event(4, "Сирота", parent_id=9)], date(1200, 1, 15), {7: "Чужой"})
    vm.toggleSection("events")

    event_rows = _event_rows(vm)
    assert [row["rowKind"] for row in event_rows] == ["entityRow"]
    assert "Событий: 1" in vm.statsText


def test_child_in_the_slice_without_a_card_never_becomes_a_stub(qapp):
    """The link resolves inside the slice: the child rides under its parent
    even when no card came in at all (nothing to name, nothing to stub)."""
    vm = WorldSnapshotViewModel()
    vm.populate(
        [_event(1, "Родитель"), _event(2, "Дитя", parent_id=1)],
        date(1200, 1, 15),
    )
    vm.toggleSection("events")
    event_rows = _event_rows(vm)
    assert [row["rowKind"] for row in event_rows] == ["entityRow", "entityRow"]
    assert event_rows[1]["displayText"].startswith(INDENT)


def test_a_tree_free_slice_is_the_old_flat_print(qapp):
    """The task's word-for-word pin (empty parents, empty time): with no
    links in the slice the events section is bit-for-bit the pre-NRI-0023
    flat list — same captions, same order, no indent anywhere."""
    vm = WorldSnapshotViewModel()
    events = [_event(1, "Первое"), _event(2, "Второе")]
    vm.populate(events, date(1200, 1, 15))
    vm.toggleSection("events")
    flat = _event_rows(vm)

    def _plain(rows):
        # The print comparison reads the render slots; icon objects left the
        # rows with the Lucide pass, so every key already compares by value.
        return [dict(row) for row in rows]

    reference = WorldSnapshotViewModel()
    # The same slice through the same code path with an explicit empty card:
    # the indent/stub machinery contributes nothing.
    reference.populate(events, date(1200, 1, 15), {})
    reference.toggleSection("events")
    assert _plain(_rows(reference)) == _plain(_rows(vm))
    assert all(not row["displayText"].startswith(INDENT) for row in flat)
    assert flat[0]["displayText"] == "01 Январь 1200 — 01 Февраль 1200  |  Первое"


def test_snapshot_row_prints_the_chosen_time(qapp):
    """Spec world-snapshot «Время в дате строки снимка»: 14:30 rides the
    start as «, 14:30», the end stays a plain day."""
    from app.domain.time_of_day import TimeOfDay

    vm = WorldSnapshotViewModel()
    vm.populate(
        [_event(1, "Совет", start_time=TimeOfDay(14, 30))], date(1200, 1, 15)
    )
    vm.toggleSection("events")
    event_row = _event_rows(vm)[0]
    assert event_row["displayText"] == (
        "01 Январь 1200, 14:30 — 01 Февраль 1200  |  Совет"
    )
