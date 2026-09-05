"""SheetFieldModel feeding the QML canvas (change Q3b 1.1, design D4).

Spec qml-shell scenario «Поля канваса идут из модели»: rows are the live
domain field objects delivered incrementally through the VM's own signals —
add/remove announce row insertions/removals, granular edits emit
role-scoped dataChanged, page-structure/orientation/full reloads reset the
model. "There is no copy of the set in QML" is proven Python-side as the
absence of a second source: after every transition the model's rows are the
template's own field objects (identity), in the template's flat order.

Fill rows additionally prove the no-second-value-implementation rule: the
content/imageKey roles must equal whatever the domain's single
``resolve_display`` computes for the same field and value map.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.entities.character_sheet import FieldType
from app.domain.entities.character_sheet_instance import resolve_display
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.viewmodels.character_sheet_fill_viewmodel import (
    CharacterSheetFillViewModel,
)
from app.presentation.viewmodels.character_sheet_viewmodel import (
    CharacterSheetViewModel,
    SheetFieldModel,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def service(async_session):
    return CharacterSheetService(CharacterSheetRepository(async_session))


@pytest.fixture
async def vm(service):
    row = await service.create("Лист")
    vm = CharacterSheetViewModel(service)
    await vm.load(row.id)
    return vm


# ── test helpers ─────────────────────────────────────────────────────────────


def record(model: SheetFieldModel) -> list:
    """Collect the model's change protocol into an event list."""
    events: list = []
    model.modelReset.connect(lambda: events.append(("reset",)))
    model.rowsInserted.connect(
        lambda parent, first, last: events.append(("insert", first, last))
    )
    model.rowsRemoved.connect(
        lambda parent, first, last: events.append(("remove", first, last))
    )
    model.dataChanged.connect(
        lambda top, bottom, roles=None: events.append(
            ("data", top.row(), bottom.row(), list(roles) if roles else [])
        )
    )
    return events


def snapshot(model: SheetFieldModel) -> list[tuple[str, int]]:
    """(id, page) of every row as QML sees it (through the roles only)."""
    out = []
    for row in range(model.rowCount(QModelIndex())):
        index = model.index(row)
        out.append(
            (
                model.data(index, SheetFieldModel.ID_ROLE),
                model.data(index, SheetFieldModel.PAGE_ROLE),
            )
        )
    return out


def template_truth(vm) -> list[tuple[str, int]]:
    """The template's own order — the single source the model must mirror."""
    truth = []
    if vm.template is not None:
        for page_index, page in enumerate(vm.template.pages):
            for field in page.fields:
                truth.append((field.id, page_index))
    return truth


def assert_mirrors_template(vm) -> None:
    model = vm.field_model
    assert snapshot(model) == template_truth(vm)
    # No second set: the rows ARE the domain fields (identity, not copies).
    fields = [f for page in vm.template.pages for f in page.fields] if vm.template else []
    assert list(model.rows) == fields
    for row, field in enumerate(fields):
        assert model.rows[row] is field


def row_of(model: SheetFieldModel, field_id: str) -> int:
    for row in range(model.rowCount(QModelIndex())):
        if model.data(model.index(row), SheetFieldModel.ID_ROLE) == field_id:
            return row
    raise AssertionError(f"{field_id} is not a row")


# ── design VM transitions ────────────────────────────────────────────────────


async def test_add_is_incremental_insert_with_roles(vm, service):
    model = vm.field_model
    events = record(model)

    field_id = vm.place("text", 100, 200, page_index=0)
    assert events == [("insert", 0, 0)]
    index = model.index(0)
    assert model.data(index, SheetFieldModel.ID_ROLE) == field_id
    assert model.data(index, SheetFieldModel.TYPE_ROLE) == "text"
    assert model.data(index, SheetFieldModel.PAGE_ROLE) == 0
    assert model.data(index, SheetFieldModel.X_ROLE) == 100
    assert model.data(index, SheetFieldModel.Y_ROLE) == 200
    assert model.data(index, SheetFieldModel.W_ROLE) == 120
    assert model.data(index, SheetFieldModel.H_ROLE) == 18
    assert model.data(index, SheetFieldModel.FONT_SIZE_ROLE)
    assert model.data(index, SheetFieldModel.CONTENT_ROLE) == ""
    assert model.data(index, SheetFieldModel.OPTIONS_COUNT_ROLE) == 0
    assert model.data(index, SheetFieldModel.DISABLED_ROLE) is False
    assert_mirrors_template(vm)


async def test_geometry_edit_emits_geometry_roles_only(vm):
    model = vm.field_model
    field_id = vm.place("text", 50, 60)
    events = record(model)

    vm.move(field_id, 70, 80)
    data_events = [e for e in events if e[0] == "data"]
    assert len(data_events) == 1
    _, first, last, roles = data_events[0]
    assert (first, last) == (0, 0)
    assert set(roles) == set(SheetFieldModel.GEOMETRY_ROLES)
    index = model.index(0)
    assert model.data(index, SheetFieldModel.X_ROLE) == 70
    assert model.data(index, SheetFieldModel.Y_ROLE) == 80
    assert_mirrors_template(vm)


async def test_content_and_font_edits_target_their_roles(vm):
    model = vm.field_model
    field_id = vm.place("text", 10, 10)
    events = record(model)

    vm.set_content(field_id, "Имя героя")
    assert [e for e in events if e[0] == "data"] == [
        ("data", 0, 0, [SheetFieldModel.CONTENT_ROLE])
    ]
    assert model.data(model.index(0), SheetFieldModel.CONTENT_ROLE) == "Имя героя"

    events.clear()
    vm.set_font_size(field_id, 20)
    assert [e for e in events if e[0] == "data"] == [
        ("data", 0, 0, [SheetFieldModel.FONT_SIZE_ROLE])
    ]
    assert model.data(model.index(0), SheetFieldModel.FONT_SIZE_ROLE) == 20


async def test_per_type_extras_emit_props_roles(vm):
    model = vm.field_model
    check_id = vm.place("checkbox", 10, 10)
    drop_id = vm.place("dropdown", 10, 40)
    events = record(model)

    vm.toggle_checkbox(check_id)
    assert [e for e in events if e[0] == "data"] == [
        (
            "data",
            0,
            0,
            [
                SheetFieldModel.CONTENT_ROLE,
                SheetFieldModel.IMAGE_KEY_ROLE,
                SheetFieldModel.OPTIONS_COUNT_ROLE,
            ],
        )
    ]
    assert model.data(model.index(row_of(model, check_id)), SheetFieldModel.CONTENT_ROLE) == "true"
    events.clear()
    vm.set_options(drop_id, ["да", "нет", "может"])
    assert model.data(
        model.index(row_of(model, drop_id)), SheetFieldModel.OPTIONS_COUNT_ROLE
    ) == 3
    events.clear()
    image_id = vm.place("image", 10, 70)
    vm.set_image_id(image_id, 4)
    assert [e for e in events if e[0] == "data"] != []
    assert model.data(
        model.index(row_of(model, image_id)), SheetFieldModel.IMAGE_KEY_ROLE
    ) == "4"
    assert_mirrors_template(vm)


async def test_remove_is_incremental_remove_row(vm):
    model = vm.field_model
    first = vm.place("text", 10, 10)
    vm.place("text", 10, 40)
    events = record(model)

    vm.remove(first)
    assert events == [("remove", 0, 0)]
    assert model.rowCount(QModelIndex()) == 1
    assert_mirrors_template(vm)


async def test_page_structure_edits_reset(vm):
    model = vm.field_model
    page1 = vm.add_page()
    field_id = vm.place("text", 10, 20, page_index=page1)
    events = record(model)

    vm.add_page()  # pages_changed
    assert ("reset",) in events
    vm.move_page(0, 1)  # pages_changed
    vm.rename_page(2, "Лист 3")  # pages_changed
    vm.remove_page(1, confirmed=True)  # pages_changed + field_removed(reset fallback)
    assert_mirrors_template(vm)
    # the reset after remove_page keeps the model truthful about the moved field
    assert row_of(model, field_id) >= 0


async def test_orientation_change_resets_and_keeps_rows_true(vm):
    model = vm.field_model
    field_id = vm.place("text", 10, 10)
    events = record(model)
    assert vm.set_orientation("landscape") is True
    assert ("reset",) in events
    assert_mirrors_template(vm)
    index = model.index(row_of(model, field_id))
    assert model.data(index, SheetFieldModel.X_ROLE) == vm.template.get_field(field_id).x


async def test_field_reordering_resyncs_honestly(vm):
    # z-order moves re-structure rows within the flat order; the model must
    # not leave the view with a stale position (dataChanged cannot reorder).
    model = vm.field_model
    a = vm.place("text", 10, 10)
    b = vm.place("text", 40, 10)
    vm.select_ids([b])
    vm.send_to_back()  # reorders the page's fields + pages_changed (reset)
    assert_mirrors_template(vm)
    ids = [pid for pid, _ in snapshot(model)]
    assert ids == [b, a]


async def test_unknown_ids_are_harmless(vm):
    model = vm.field_model
    events = record(model)
    assert vm.move("nope", 1, 1) is False
    assert vm.set_content("nope", "x") is False
    # feeding handlers for ids outside the projection must not emit or raise
    model.on_geometry_changed("nope")
    model.on_field_removed("nope")  # falls back to a resync, no invalid rows
    assert all(e[0] in ("reset",) for e in events)
    assert_mirrors_template(vm)


# ── fill VM: roles through the domain's single value resolution ──────────────


@pytest.fixture
def services(async_session):
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    return sheet_svc, inst_svc


async def _seed_instance(services):
    sheet_svc, inst_svc = services
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    text_f = template.add_field(FieldType.TEXT, (10.0, 10.0))
    text_f.content = "Иван"
    chk = template.add_field(FieldType.CHECKBOX, (10.0, 40.0))
    chk.content = "false"
    num = template.add_field(FieldType.NUMBER, (10.0, 70.0))
    num.content = "5"
    img = template.add_field(FieldType.IMAGE, (10.0, 100.0))
    lab = template.add_field(FieldType.LABEL, (10.0, 130.0))
    lab.content = "Имя"
    fields = {"text": text_f, "chk": chk, "num": num, "img": img, "lab": lab}
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист", row.id)
    return inst.id, fields, template


@pytest.fixture
async def fill_vm(services):
    instance_id, fields, _ = await _seed_instance(services)
    sheet_svc, inst_svc = services
    vm = CharacterSheetFillViewModel(inst_svc, sheet_svc)
    await vm.load(instance_id)
    return vm, fields


async def test_fill_rows_start_with_resolved_display(fill_vm):
    vm, fields = fill_vm
    model = vm.field_model
    assert model.rowCount(QModelIndex()) == len(template_truth(vm))
    # every fillable row shows exactly what the domain rule computes — the
    # model resolves, it does not re-implement (no second value source)
    for page in vm.template.pages:
        for field in page.fields:
            index = model.index(row_of(model, field.id))
            expected = resolve_display(field, vm.values)
            content = model.data(index, SheetFieldModel.CONTENT_ROLE)
            if field.type is FieldType.IMAGE:
                assert content == ""  # image goes through imageKey
            elif expected is True:
                assert content == "true"
            elif expected is False:
                assert content == "false"
            else:
                assert content == ("" if expected is None else str(expected))
    image_row = row_of(model, fields["img"].id)
    assert model.data(model.index(image_row), SheetFieldModel.IMAGE_KEY_ROLE) == ""
    assert_mirrors_template(vm)


async def test_fill_value_edits_notify_the_roles(fill_vm):
    vm, fields = fill_vm
    model = vm.field_model
    events = record(model)

    vm.set_text(fields["text"].id, "Пётр")
    assert [e for e in events if e[0] == "data"] == [
        ("data", 0, 0, [SheetFieldModel.CONTENT_ROLE])
    ]
    assert model.data(model.index(0), SheetFieldModel.CONTENT_ROLE) == "Пётр"

    events.clear()
    vm.toggle_checkbox(fields["chk"].id)
    assert model.data(
        model.index(row_of(model, fields["chk"].id)), SheetFieldModel.CONTENT_ROLE
    ) == "true"

    events.clear()
    vm.set_image(fields["img"].id, 9)
    data = [e for e in events if e[0] == "data"]
    assert data
    image_row = row_of(model, fields["img"].id)
    assert model.data(model.index(image_row), SheetFieldModel.IMAGE_KEY_ROLE) == "9"
    # the value arrived from QML as a double — the VM normalizes to int
    vm.set_image(fields["img"].id, 10.0)
    assert model.data(model.index(image_row), SheetFieldModel.IMAGE_KEY_ROLE) == "10"
    assert isinstance(vm.values[fields["img"].id], int)

    events.clear()
    vm.clear_image(fields["img"].id)
    assert model.data(model.index(image_row), SheetFieldModel.IMAGE_KEY_ROLE) == ""


async def test_fill_undo_redo_notifies_all_value_roles(fill_vm):
    vm, fields = fill_vm
    model = vm.field_model
    vm.set_text(fields["text"].id, "Пётр")
    events = record(model)

    vm.undo()
    data = [e for e in events if e[0] == "data"]
    assert len(data) == 1
    _, first, last, roles = data[0]
    assert (first, last) == (0, model.rowCount(QModelIndex()) - 1)
    assert set(roles) >= {SheetFieldModel.CONTENT_ROLE, SheetFieldModel.IMAGE_KEY_ROLE}
    assert model.data(model.index(0), SheetFieldModel.CONTENT_ROLE) == "Иван"


async def test_fill_read_only_flips_the_disabled_role(fill_vm):
    vm, _ = fill_vm
    model = vm.field_model
    assert all(
        model.data(model.index(r), SheetFieldModel.DISABLED_ROLE) is False
        for r in range(model.rowCount(QModelIndex()))
    )
    events = record(model)
    vm.set_read_only(True)
    data = [e for e in events if e[0] == "data"]
    assert len(data) == 1
    assert data[0][3] == [SheetFieldModel.DISABLED_ROLE]
    assert all(
        model.data(model.index(r), SheetFieldModel.DISABLED_ROLE) is True
        for r in range(model.rowCount(QModelIndex()))
    )


async def test_fill_reload_layout_resets(services):
    sheet_svc, inst_svc = services
    instance_id, _, template = await _seed_instance(services)
    vm = CharacterSheetFillViewModel(inst_svc, sheet_svc)
    await vm.load(instance_id)
    model = vm.field_model
    # add a field to the saved template behind the VM's back…
    fresh = await sheet_svc.load(template.id)
    field = fresh.add_field(FieldType.TEXT, (10.0, 160.0))
    await sheet_svc.update_pages(template.id, fresh)
    events = record(model)
    await vm.reload_layout()
    assert ("reset",) in events
    assert row_of(model, field.id) >= 0


# ── meta: the model really is a QAbstractListModel for QML ───────────────────


async def test_field_model_exposed_as_qml_constant_property(vm, service):
    from PySide6.QtCore import QMetaType

    meta = vm.metaObject()
    idx = meta.indexOfProperty("fieldModel")
    assert idx >= 0  # reachable from QML through the meta-object
    prop = meta.property(idx)
    assert prop.typeId() == int(QMetaType.Type.QVariant)
    assert prop.isConstant()  # the model reference never changes (Q2.5a precedent)
    # The Python contract property also resolves through the QVariant alias.
    assert prop.read(vm) is vm.field_model
    assert isinstance(vm.field_model, SheetFieldModel)


async def test_role_names_are_bytes_for_qml(vm):
    names = vm.field_model.roleNames()
    assert set(names.values()) == {
        b"id", b"type", b"page", b"x", b"y", b"w", b"h",
        b"fontSize", b"content", b"imageKey", b"optionsCount", b"disabled",
    }
    assert all(isinstance(n, bytes) for n in names.values())


# ── 4.3 acceptance: the model's defensive resync guards ───────────────────────
# Every surprise that can desync the QML view from the template must end in an
# honest full rebuild (or an honest no-op) — a wrong incremental notification
# would leave delegates showing fields that do not exist.


async def test_field_added_surprises_fall_back_to_reset(vm):
    model = vm.field_model
    a = vm.place("label", 10, 10)
    b = vm.place("label", 10, 30)   # both rows are live in the projection
    events = record(model)

    # (1) an add signal for an id the projection already carries — the only
    # safe reading is "something structural happened outside a clean pair"
    model.on_field_added(a)
    assert ("reset",) in events
    assert_mirrors_template(vm)

    # (2) the id exists in the template but beyond the projection length —
    # announcing insertRows at a phantom row would corrupt the view
    events.clear()
    model._rows = ()
    model._page_of_row = []
    model.on_field_added(b)
    assert ("reset",) in events
    assert_mirrors_template(vm)

    # (3) the add raced with a removal: the id is gone — silently skip, the
    # remove path (field_removed) is what rebuilds reality here
    events.clear()
    model.on_field_added("no-such-field")
    assert events == []


def test_flat_position_helpers_answer_none_when_there_is_nothing_to_find():
    from app.presentation.viewmodels.character_sheet_viewmodel import (
        SheetFieldModel as Model,
    )

    assert Model._flat_index_of(None, "x") == -1       # no template yet
    template = _template_with_two_fields()
    ids = [f.id for page in template.pages for f in page.fields]
    assert Model._flat_index_of(template, ids[0]) == 0
    assert Model._flat_index_of(template, ids[-1]) == len(ids) - 1
    assert Model._flat_index_of(template, "ghost") == -1
    # a row beyond the flat space is a programming error, not a silent -1
    with pytest.raises(IndexError):
        Model._flat_index_page(template, len(ids))


def _template_with_two_fields():
    from app.domain.entities.character_sheet import SheetTemplate

    template = SheetTemplate(name="Тест")
    t = template.add_field(FieldType.TEXT, (10.0, 10.0))
    lb = template.add_field(FieldType.LABEL, (10.0, 40.0))
    assert t.id and lb.id
    return template


async def test_data_and_get_answer_quietly_outside_the_row_space(vm):
    model = vm.field_model
    vm.place("label", 10, 10)
    # invalid index (the QML delegate can query during a reset) — None
    assert model.data(QModelIndex(), SheetFieldModel.ID_ROLE) is None
    # an out-of-range index must not leak a row nor raise
    assert model.data(model.index(999), SheetFieldModel.ID_ROLE) is None
    # unknown role ids (QML never invents them, but data() answers everything)
    assert model.data(model.index(0), 123456) is None
    # the get() seam mirrors the same guard for the panel/bridge callers
    assert model.get(-1) == {}
    assert model.get(model.rowCount(QModelIndex())) == {}
