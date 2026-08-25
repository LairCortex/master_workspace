"""Tests for CharacterSheetService: CRUD, stable field ids, JSON project
export/import (tasks 3.3/3.4)."""
import pytest

from app.application.services.character_sheet_service import (
    CharacterSheetImportError,
    CharacterSheetNameConflict,
    CharacterSheetService,
)
from app.domain.entities.character_sheet import SheetField, SheetPage, SheetTemplate
from app.domain.enums.field_type import FieldType
from app.domain.enums.sheet_orientation import SheetOrientation
from app.infrastructure.repositories.character_sheet_repository import CharacterSheetRepository


def make_field(**overrides) -> SheetField:
    params = dict(
        id="",
        type=FieldType.SHORT_TEXT,
        x=10.5,
        y=20.25,
        w=100.0,
        h=24.0,
        label="Имя",
        default_value="Без",
        font_size=12.0,
    )
    params.update(overrides)
    return SheetField(**params)


def make_template(name: str = "Лист", field: SheetField | None = None) -> SheetTemplate:
    return SheetTemplate(
        name=name,
        orientation=SheetOrientation.LANDSCAPE,
        pages=[SheetPage(name="ОСН", fields=[field or make_field()])],
    )


@pytest.fixture
def repo(async_session):
    return CharacterSheetRepository(async_session)


@pytest.fixture
def service(repo):
    return CharacterSheetService(repo)


# ── create / load / update / delete ───────────────────────────────────────


class TestCrud:
    async def test_create_then_load_round_trip(self, service):
        template = make_template(field=make_field(id="a" * 32, default_value="Герой"))
        row = await service.create(template)
        assert row.name == "Лист"
        assert row.orientation == "landscape"

        loaded = await service.load(row.id)
        assert loaded == template
        assert loaded.pages[0].fields[0].id == "a" * 32
        assert loaded.pages[0].fields[0].default_value == "Герой"

    async def test_create_rejects_duplicate_name(self, service):
        await service.create(make_template("Лист"))
        with pytest.raises(CharacterSheetNameConflict):
            await service.create(make_template("Лист"))
        assert len(await service.get_all()) == 1

    async def test_fields_get_stable_uuid_ids_on_create(self, service):
        template = make_template()  # field id = ""
        row = await service.create(template)
        id_after_create = template.pages[0].fields[0].id
        assert id_after_create == format(int(id_after_create, 16), "032x")  # hex32

        loaded = await service.load(row.id)
        assert loaded.pages[0].fields[0].id == id_after_create

    async def test_ids_stable_across_saves(self, service):
        template = make_template(field=make_field(id="f" * 32))
        row = await service.create(template)

        reloaded = await service.load(row.id)
        await service.update(row.id, reloaded)
        again = await service.load(row.id)
        assert again.pages[0].fields[0].id == "f" * 32

    async def test_update_assigns_ids_to_new_empty_fields(self, service):
        template = make_template(field=make_field(id="e" * 32))
        row = await service.create(template)

        # "user adds a field" — viewmodel leaves id empty, service fills it
        template.pages[0].fields.append(make_field(type=FieldType.NUMBER, x=300.0, y=300.0))
        await service.update(row.id, template)
        loaded = await service.load(row.id)
        ids = [f.id for f in loaded.pages[0].fields]
        assert ids[0] == "e" * 32  # existing id preserved
        assert len(ids[1]) == 32 and int(ids[1], 16) >= 0  # empty id got a uuid

    async def test_update_rejects_conflicting_rename(self, service):
        first = await service.create(make_template("А"))
        await service.create(make_template("Б"))
        template = await service.load(first.id)
        template.name = "Б"
        with pytest.raises(CharacterSheetNameConflict):
            await service.update(first.id, template)

    async def test_update_not_found(self, service):
        assert await service.update(999, make_template()) is None

    async def test_delete(self, service):
        row = await service.create(make_template())
        assert await service.delete(row.id) is True
        assert await service.load(row.id) is None

    async def test_geometry_rounded_to_2_decimals_on_save(self, service):
        template = make_template(field=make_field(id="g" * 32, x=100.123456))
        row = await service.create(template)
        loaded = await service.load(row.id)
        assert loaded.pages[0].fields[0].x == 100.12


# ── JSON project export/import ─────────────────────────────────────────────


class TestProjectJson:
    def test_export_contains_marker_version_and_sheets(self, service):
        text = service.export_project([make_template(field=make_field(id="c" * 32))])
        assert '"format": "nri-charsheet"' in text
        assert '"version": 1' in text
        assert '"nri-charsheet"' in text

    def test_round_trip_preserves_all_properties_and_ids(self, service):
        t1 = make_template("Первый", field=make_field(id="1" * 32, default_value="Х"))
        t2 = make_template(
            "Второй",
            field=make_field(
                id="2" * 32,
                type=FieldType.DROPDOWN,
                options=["А", "Б"],
                min_value=5,
                max_value=40,
                initial_checked=True,
            ),
        )
        restored = CharacterSheetService.parse_project(service.export_project([t1, t2]))
        assert restored == [t1, t2]

    async def test_import_creates_template_with_same_ids(self, service):
        original = make_template(field=make_field(id="d" * 32))
        created = await service.import_project(CharacterSheetService.export_project([original]))
        assert len(created) == 1
        loaded = await service.load(created[0].id)
        assert loaded == original
        assert loaded.pages[0].fields[0].id == "d" * 32

    async def test_import_name_conflict_gets_copy_suffix(self, service):
        await service.create(make_template("Лист"))
        original_row = (await service.get_all())[0]
        existing = await service.load(original_row.id)

        created = await service.import_project(
            CharacterSheetService.export_project([make_template("Лист")])
        )
        assert created[0].name == "Лист (копия)"

        created2 = await service.import_project(
            CharacterSheetService.export_project([make_template("Лист")])
        )
        assert created2[0].name == "Лист (копия 2)"

        # the original sheet is untouched
        assert await service.load(original_row.id) == existing
        names = {s.name for s in await service.get_all()}
        assert names == {"Лист", "Лист (копия)", "Лист (копия 2)"}

    @pytest.mark.parametrize(
        ("payload", "reason"),
        [
            ("это не json", "JSON"),
            ("[1, 2, 3]", "структур"),
            ('{"format": "foreign", "version": 1, "sheets": []}', "метки формата"),
            ('{"format": "nri-charsheet", "version": 99, "sheets": []}', "версия"),
            ('{"format": "nri-charsheet", "version": 1}', "sheets"),
            ('{"format": "nri-charsheet", "version": 1, "sheets": [42]}', "object"),
        ],
        ids=["bad-json", "not-object", "wrong-marker", "wrong-version", "no-sheets", "bad-sheet"],
    )
    async def test_broken_project_rejected_with_reason(self, service, payload, reason):
        with pytest.raises(CharacterSheetImportError, match=reason):
            await service.import_project(payload)
        assert len(await service.get_all()) == 0


# ── integrity race guard ────────────────────────────────────────────────────


class TestCreateIntegrityRace:
    async def test_unique_violation_maps_to_name_conflict(self, service, monkeypatch):
        from unittest.mock import AsyncMock

        await service.create(make_template())
        # Simulate a stale read: the pre-check misses the existing row, so the
        # flush trips the UNIQUE constraint — must map to a conflict, and the
        # session must be rolled back to a usable state.
        monkeypatch.setattr(service._repo, "get_by_name", AsyncMock(return_value=None))
        with pytest.raises(CharacterSheetNameConflict):
            await service.create(make_template())
        # the session is still usable after the rollback
        assert len(await service.get_all()) == 1
