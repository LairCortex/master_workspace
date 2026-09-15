"""Tests for applying an ImportPlan (task group 3, rework-xlsx-import).

Covers ``XlsxImportService.apply_plan``:

* 3.1 — pass 1: create/update of all entity types (upsert applies only
  non-empty fields, ambiguous DB names create a new entity), ghost link
  targets materialized with min-start/max-end dates of the referring rows
  (several different dates), missing ``event_types`` auto-created with the
  first free color_index (cyclic when all eight are taken) — every ghost and
  new type recorded in ``report.decisions`` (mutual cross-sheet references
  included);
* 3.2 — pass 2: links added through the ORM relationships with dedup and
  without ever unlinking (re-import scenario);
* 3.3 — one commit on success / rollback on failure through the explicit
  session + commit/rollback seam, persistence proven with a fresh engine and
  session over the same DB file;
* 3.4 — the ``Изображение`` column ingested through ``ImageStore`` (relative
  and absolute paths; unreadable file → entity without image + warning).
"""
from datetime import date

import pytest
from openpyxl import Workbook
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from sqlalchemy import func, select

from app.application.services.xlsx_import_service import LINK_TO_DB, XlsxImportService
from app.infrastructure.db.database import create_engine, create_session_factory
from app.infrastructure.db import models
from app.infrastructure.db.models import (
    Base,
    CharacterModel,
    DescriptionModel,
    EventModel,
    EventTypeModel,
    ImageModel,
    ItemModel,
    LocationModel,
    OrganizationModel,
)
from app.infrastructure.images.store import ImageStore


@pytest.fixture(scope="session")
def qapp():
    # ImageStore decodes via QImageReader — a QApplication must exist.
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _svc(image_store: ImageStore | None = None) -> XlsxImportService:
    # apply_plan writes through the session/ORM directly — the service has
    # no per-type service dependency since the single-sheet API removal.
    return XlsxImportService(image_store=image_store)


def _new_workbook() -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)
    return wb


def _sheet(wb: Workbook, title: str, headers, rows) -> None:
    ws = wb.create_sheet(title)
    ws.append(headers)
    for row in rows:
        ws.append(row)


def _save(tmp_path, wb: Workbook, name: str = "import.xlsx"):
    path = tmp_path / name
    wb.save(path)
    return path


CHAR_HEADERS = ["Имя", "Дата начала"]
EVENT_HEADERS = ["Имя", "Дата начала"]


async def _count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar()


async def _one(session, model, **filters):
    stmt = select(model)
    for attr, value in filters.items():
        stmt = stmt.where(getattr(model, attr) == value)
    return (await session.execute(stmt)).scalars().one()


async def _names(session, model) -> set[str]:
    return {n for (n,) in (await session.execute(select(model.name))).all()}


# ── 3.1 — pass 1: entities, ghosts, auto event types ──────────────────────

class TestPass1Entities:
    async def test_all_five_sheet_types_created_with_descriptions(
        self, tmp_path, async_session
    ):
        wb = _new_workbook()
        full = CHAR_HEADERS + ["Дата конца", "Характеристики", "Предыстория"]
        _sheet(wb, "События", full, [["Бал", "1815-01-10", "1815-02-01", "Х-Е", "Б-Е"]])
        _sheet(wb, "Персонажи", full + ["personality", "tasks"],
                 [["Иван", "1800-01-01", None, "Х-Ч", "Б-Ч", "Смелый", "Т1"]])
        _sheet(wb, "Локации", full + ["tasks"],
                 [["Парк", "1700-01-01", None, "Х-Л", "Б-Л", "Т2"]])
        _sheet(wb, "Организации", full, [["Цех", "1750-01-01", None, "Х-О", "Б-О"]])
        _sheet(wb, "Предметы", full, [["Амулет", "1600-01-01", None, "Х-П", "Б-П"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        report = await _svc().apply_plan(plan, async_session)

        assert (report.created, report.updated) == (5, 0)
        event = await _one(async_session, EventModel, name="Бал")
        assert (event.start_date, event.end_date) == (date(1815, 1, 10), date(1815, 2, 1))
        assert event.description.characteristics == "Х-Е"
        assert event.description.backstory == "Б-Е"
        char = await _one(async_session, CharacterModel, name="Иван")
        assert (char.personality, char.tasks) == ("Смелый", "Т1")
        assert char.description.backstory == "Б-Ч"
        assert await _names(async_session, LocationModel) == {"Парк"}
        assert await _names(async_session, OrganizationModel) == {"Цех"}
        assert await _names(async_session, ItemModel) == {"Амулет"}

    async def test_event_rating_ignored_event_has_no_rating_column(
        self, tmp_path, async_session
    ):
        wb = _new_workbook()
        _sheet(wb, "События", CHAR_HEADERS + ["Рейтинг"], [["Бал", "1815-01-10", 4]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        assert plan.planned_rows[0].fields["rating"] == 4  # carried by the plan
        report = await _svc().apply_plan(plan, async_session)
        assert report.created == 1
        event = await _one(async_session, EventModel, name="Бал")
        assert not hasattr(event, "rating")  # the events model has no rating field

    async def test_rating_column_written_on_entities_that_have_it(
        self, tmp_path, async_session
    ):
        wb = _new_workbook()
        _sheet(wb, "Персонажи", CHAR_HEADERS + ["Рейтинг"], [["Иван", "2001-01-01", 3]])
        _sheet(wb, "Предметы", CHAR_HEADERS + ["Рейтинг"], [["Амулет", "2001-01-01", 5]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        await _svc().apply_plan(plan, async_session)
        assert (await _one(async_session, CharacterModel, name="Иван")).rating == 3
        assert (await _one(async_session, ItemModel, name="Амулет")).rating == 5

    async def test_upsert_updates_only_non_empty_fields(self, tmp_path, async_session):
        existing = CharacterModel(name="Уникал", start_date=date(1900, 1, 1))
        existing.description = DescriptionModel(characteristics="старые", backstory="старая")
        async_session.add(existing)
        await async_session.flush()

        wb = _new_workbook()
        _sheet(wb, "Персонажи", CHAR_HEADERS + ["Дата конца", "Характеристики"],
                 [["уникал", "1901-02-02", None, "новые"]])  # Дата конца/Предыстория пустые
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        report = await _svc().apply_plan(plan, async_session)

        assert (report.created, report.updated) == (0, 1)
        assert await _count(async_session, CharacterModel) == 1  # no duplicate row
        char = await async_session.get(CharacterModel, existing.id)
        assert char.start_date == date(1901, 2, 2)          # non-empty overrides
        assert char.description.characteristics == "новые"  # non-empty overrides
        assert char.description.backstory == "старая"       # empty never erases
        assert char.name == "Уникал"                        # upsert key is not renamed

    async def test_update_of_entity_without_description_creates_it(
        self, tmp_path, async_session
    ):
        # Старая запись может жить без строки описания — апдейт характеристик
        # создаёт её, а не падает.
        existing = CharacterModel(name="Уникал", start_date=date(1900, 1, 1))
        async_session.add(existing)
        await async_session.flush()

        wb = _new_workbook()
        _sheet(wb, "Персонажи", CHAR_HEADERS + ["Характеристики", "Предыстория"],
               [["уникал", "1901-02-02", "новые", "новая"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        report = await _svc().apply_plan(plan, async_session)

        assert (report.created, report.updated) == (0, 1)
        char = await async_session.get(CharacterModel, existing.id)
        assert char.description.characteristics == "новые"
        assert char.description.backstory == "новая"

    async def test_ambiguous_db_name_creates_new_entity(self, tmp_path, async_session):
        async_session.add_all([
            CharacterModel(name="Иван", start_date=date(1900, 1, 1)),
            CharacterModel(name="иван", start_date=date(1901, 1, 1)),
        ])
        await async_session.flush()
        wb = _new_workbook()
        _sheet(wb, "Персонажи", CHAR_HEADERS, [["Иван", "2001-01-01"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        report = await _svc().apply_plan(plan, async_session)
        assert (report.created, report.updated) == (1, 0)
        assert await _count(async_session, CharacterModel) == 3

    async def test_ghost_created_with_min_start_max_end_of_referring_rows(
        self, tmp_path, async_session
    ):
        wb = _new_workbook()
        # Spec scenario «Противоречивые даты»: 1820-05-01 (no end) + 1815-01-10..1816-06-01.
        _sheet(wb, "События", ["Имя", "Дата начала", "Дата конца", "Связь предметами"],
               [
                   ["Бал", "1820-05-01", None, "Амулет"],
                   ["Охота", "1815-01-10", "1816-06-01", "Амулет"],
               ])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        report = await _svc().apply_plan(plan, async_session)

        assert report.created == 3  # two events + one ghost item
        item = await _one(async_session, ItemModel, name="Амулет")
        assert (item.start_date, item.end_date) == (date(1815, 1, 10), date(1820, 5, 1))
        # Both referring rows are attached to the ghost in pass 2.
        assert report.links == 2
        ball = await _one(async_session, EventModel, name="Бал")
        assert [i.name for i in ball.items] == ["Амулет"]

    async def test_ghost_decision_entry_lists_name_dates_and_referrers(
        self, tmp_path, async_session
    ):
        wb = _new_workbook()
        _sheet(wb, "События", ["Имя", "Дата начала", "Связь предметами"],
               [["Бал", "1820-05-01", "Амулет"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        report = await _svc().apply_plan(plan, async_session)
        decision, = report.decisions
        assert "Амулет" in decision
        assert "1820-05-01" in decision
        assert "Предметы" in decision          # target sheet named
        assert "События" in decision and "2" in decision  # referring sheet/row

    async def test_ghost_link_target_of_event_type(self, tmp_path, async_session):
        # Link columns of non-event sheets may target events; a ghost event
        # gets the dates (min/max) of the referring rows.
        wb = _new_workbook()
        _sheet(wb, "Персонажи", ["Имя", "Дата начала", "Дата конца", "Связь событиями"],
               [["Иван", "1800-01-01", "1850-01-01", "Тайна"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        report = await _svc().apply_plan(plan, async_session)
        ghost = await _one(async_session, EventModel, name="Тайна")
        assert (ghost.start_date, ghost.end_date) == (date(1800, 1, 1), date(1850, 1, 1))
        assert any("Тайна" in d for d in report.decisions)
        assert report.links == 1

    async def test_mutual_cross_sheet_references_applied_regardless_of_tab_order(
        self, tmp_path, async_session
    ):
        wb = _new_workbook()
        # «Предметы» listed before «События» — links still resolve both ways.
        _sheet(wb, "Предметы", CHAR_HEADERS + ["Связь событиями"],
               [["Амулет", "1800-01-01", "Бал"]])
        _sheet(wb, "События", CHAR_HEADERS + ["Связь предметами"],
               [["Бал", "1820-05-01", "Амулет"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        report = await _svc().apply_plan(plan, async_session)
        # Both referencing rows are honoured; the second one sees the edge
        # already established from the other side and deduplicates it.
        assert report.links == 1
        ball = await _one(async_session, EventModel, name="Бал")
        amulet = await _one(async_session, ItemModel, name="Амулет")
        assert [i.name for i in ball.items] == ["Амулет"]
        assert [e.name for e in amulet.events] == ["Бал"]
        assert (await async_session.execute(
            select(func.count()).select_from(models.event_item)
        )).scalar() == 1


class TestPass1EventTypes:
    async def _seed_types(self, session, *specs):
        for i, (name, color) in enumerate(specs):
            session.add(EventTypeModel(name=name, color_index=color, sort_order=i))
        await session.flush()

    async def _one_event_row_wb(self, tmp_path, type_label):
        wb = _new_workbook()
        _sheet(wb, "События", CHAR_HEADERS + ["Тип"], [["Бал", "1815-01-10", type_label]])
        return _save(tmp_path, wb)

    async def test_missing_type_auto_created_with_first_free_color_index(
        self, tmp_path, async_session
    ):
        await self._seed_types(async_session, ("Битва", 1), ("Пир", 2), ("Свадьба", 3))
        path = await self._one_event_row_wb(tmp_path, "Дуэль")
        plan = await _svc().analyze_file(path, async_session)
        report = await _svc().apply_plan(plan, async_session)

        duel = await _one(async_session, EventTypeModel, name="Дуэль")
        assert duel.color_index == 4        # smallest free index of 1..8
        ball = await _one(async_session, EventModel, name="Бал")
        assert ball.event_type_id == duel.id
        decision, = report.decisions
        assert "Дуэль" in decision and "Бал" in decision

    async def test_two_new_types_get_distinct_increasing_indices(
        self, tmp_path, async_session
    ):
        wb = _new_workbook()
        _sheet(wb, "События", CHAR_HEADERS + ["Тип"],
               [["Бал", "1815-01-10", "Дуэль"], ["Охота", "1815-02-10", "Маскарад"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        await _svc().apply_plan(plan, async_session)
        duel = await _one(async_session, EventTypeModel, name="Дуэль")
        mask = await _one(async_session, EventTypeModel, name="Маскарад")
        assert {duel.color_index, mask.color_index} == {1, 2}
        assert duel.sort_order != mask.sort_order

    async def test_all_colors_taken_cycles_into_palette_range(self, tmp_path, async_session):
        await self._seed_types(async_session, *[(f"T{i}", i) for i in range(1, 9)])
        path = await self._one_event_row_wb(tmp_path, "Дуэль")
        plan = await _svc().analyze_file(path, async_session)
        await _svc().apply_plan(plan, async_session)
        duel = await _one(async_session, EventTypeModel, name="Дуэль")
        assert 1 <= duel.color_index <= 8
        assert duel.color_index == 1  # rotate past the highest used (8 % 8) + 1

    async def test_existing_type_reused_case_insensitively(self, tmp_path, async_session):
        await self._seed_types(async_session, ("дуэль", 3))
        path = await self._one_event_row_wb(tmp_path, "Дуэль")
        plan = await _svc().analyze_file(path, async_session)
        report = await _svc().apply_plan(plan, async_session)
        assert await _count(async_session, EventTypeModel) == 1
        assert report.decisions == []
        ball = await _one(async_session, EventModel, name="Бал")
        assert ball.event_type_id == (await _one(async_session, EventTypeModel)).id

    async def test_type_assigned_while_updating_existing_event(self, tmp_path, async_session):
        async_session.add(EventModel(name="Бал", start_date=date(1700, 1, 1)))
        await async_session.flush()
        path = await self._one_event_row_wb(tmp_path, "Дуэль")
        plan = await _svc().analyze_file(path, async_session)
        report = await _svc().apply_plan(plan, async_session)
        assert (report.created, report.updated) == (0, 1)
        ball = await _one(async_session, EventModel, name="Бал")
        assert ball.event_type.name == "Дуэль"


# ── 3.2 — pass 2: links are only added, never removed ─────────────────────

class TestPass2Links:
    ALL_FACTS = (
        models.event_character, models.event_organization, models.event_item,
        models.event_location, models.organization_character, models.organization_item,
        models.organization_location, models.character_item, models.character_location,
        models.item_location,
    )

    async def test_link_matrix_covers_every_m2m_except_ratings(self, tmp_path, async_session):
        wb = _new_workbook()
        _sheet(wb, "События",
               ["Имя", "Дата начала", "Связь персонажами", "Связь организациями",
                "Связь предметами", "Связь локациями"],
               [["Е", "2000-01-01", "Ч", "О", "П", "Л"]])
        _sheet(wb, "Персонажи",
               ["Имя", "Дата начала", "Связь организациями", "Связь предметами",
                "Связь локациями"],
               [["Ч", "2000-01-01", "О", "П", "Л"]])
        _sheet(wb, "Организации",
               ["Имя", "Дата начала", "Связь предметами", "Связь локациями"],
               [["О", "2000-01-01", "П", "Л"]])
        _sheet(wb, "Локации", ["Имя", "Дата начала"], [["Л", "2000-01-01"]])
        _sheet(wb, "Предметы", ["Имя", "Дата начала", "Связь локациями"],
               [["П", "2000-01-01", "Л"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        report = await _svc().apply_plan(plan, async_session)

        assert report.created == 5
        assert report.links == 10
        for table in self.ALL_FACTS:  # all 10 importable M2M tables, *_rating excluded
            assert (await async_session.execute(
                select(func.count()).select_from(table)
            )).scalar() == 1

    async def test_same_edge_from_both_sheets_added_once(self, tmp_path, async_session):
        # Event links the character and the character links back the same event:
        # one DB edge, deduplicated by the opposite collection (backref).
        wb = _new_workbook()
        _sheet(wb, "События", ["Имя", "Дата начала", "Связь персонажами"],
               [["Е", "2000-01-01", "Ч"]])
        _sheet(wb, "Персонажи", ["Имя", "Дата начала", "Связь событиями"],
               [["Ч", "2000-01-01", "Е"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        report = await _svc().apply_plan(plan, async_session)
        assert report.links == 1
        assert (await async_session.execute(
            select(func.count()).select_from(models.event_character)
        )).scalar() == 1

    async def test_reimport_keeps_foreign_links_and_never_unlinks(
        self, tmp_path, async_session
    ):
        # Spec scenario «Связи не отвязываются»: the event already has «Пётр»;
        # the imported row links «Иван; Пётр» — afterwards both are still linked.
        ivan = CharacterModel(name="Иван", start_date=date(1800, 1, 1))
        pyotr = CharacterModel(name="Пётр", start_date=date(1801, 1, 1))
        ball = EventModel(name="Бал", start_date=date(1700, 1, 1))
        ball.characters = [pyotr]
        async_session.add_all([ivan, pyotr, ball])
        await async_session.flush()

        wb = _new_workbook()
        _sheet(wb, "События", ["Имя", "Дата начала", "Связь персонажами"],
               [["Бал", "1820-05-01", "Иван; Пётр"]])
        path = _save(tmp_path, wb)

        report = await _svc().apply_plan(
            await _svc().analyze_file(path, async_session), async_session
        )
        assert report.updated == 1
        assert report.links == 1  # only Иван is new, Пётр already linked
        chars = (await async_session.execute(
            select(func.count()).select_from(models.event_character)
        )).scalar()
        assert chars == 2
        ball = await _one(async_session, EventModel, name="Бал")
        assert {c.name for c in ball.characters} == {"Иван", "Пётр"}

        # Повторный импорт того же файла: ничего не отвязывается и не дублируется.
        report2 = await _svc().apply_plan(
            await _svc().analyze_file(path, async_session), async_session
        )
        assert report2.links == 0
        assert (await async_session.execute(
            select(func.count()).select_from(models.event_character)
        )).scalar() == 2
        ball = await _one(async_session, EventModel, name="Бал")
        assert {c.name for c in ball.characters} == {"Иван", "Пётр"}

    async def test_db_resolved_link_target_uses_name_index_id(self, tmp_path, async_session):
        item = ItemModel(name="Фонарь", start_date=date(1900, 1, 1))
        async_session.add(item)
        await async_session.flush()
        wb = _new_workbook()
        _sheet(wb, "События", ["Имя", "Дата начала", "Связь предметами"],
               [["Бал", "1820-05-01", "фонарь"]])  # LINK_TO_DB, case-insensitive
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        report = await _svc().apply_plan(plan, async_session)
        assert report.links == 1
        ball = await _one(async_session, EventModel, name="Бал")
        assert [i.id for i in ball.items] == [item.id]

    async def test_db_target_deleted_after_analysis_warns_and_skips_link(
        self, tmp_path, async_session
    ):
        # Цель LINK_TO_DB исчезла из базы между анализом и применением:
        # связь не устанавливается, строка остаётся с предупреждением.
        item = ItemModel(name="Фонарь", start_date=date(1900, 1, 1))
        async_session.add(item)
        await async_session.flush()
        wb = _new_workbook()
        _sheet(wb, "События", ["Имя", "Дата начала", "Связь предметами"],
               [["Бал", "1820-05-01", "фонарь"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        ref = plan.lookup_row("event", "Бал").links["item"][0]
        assert ref.resolution == LINK_TO_DB and ref.db_id == item.id

        await async_session.delete(item)
        await async_session.flush()

        report = await _svc().apply_plan(plan, async_session)
        assert (report.created, report.links) == (1, 0)
        warning, = report.warnings
        assert "«фонарь»" in warning and "цель связи" in warning

    async def test_link_reference_of_skipped_row_is_not_applied(self, tmp_path, async_session):
        # A planned-skip row contributes neither an entity nor its links.
        wb = _new_workbook()
        _sheet(wb, "События", ["Имя", "Дата начала", "Связь персонажами"],
               [["Бал", None, "Иван"], ["Охота", "1815-01-10", "Мария"]])
        _sheet(wb, "Персонажи", CHAR_HEADERS, [["Иван", "1800-01-01"], ["Мария", "1800-01-01"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        report = await _svc().apply_plan(plan, async_session)
        assert report.created == 3  # one event + both characters
        assert report.links == 1
        assert [i.sheet for i in report.skipped] == ["События"]
        assert await _count(async_session, EventModel) == 1


# ── 3.3 — one commit / rollback, explicit session + commit seam ───────────

class TestTransaction:
    async def _plan(self, tmp_path, session):
        wb = _new_workbook()
        _sheet(wb, "События", ["Имя", "Дата начала", "Связь персонажами"],
               [["Бал", "1820-05-01", "Иван"]])
        _sheet(wb, "Персонажи", CHAR_HEADERS, [["Иван", "1800-01-01"]])
        return await _svc().analyze_file(_save(tmp_path, wb), session)

    async def test_success_commits_exactly_once_and_rolls_back_nothing(
        self, tmp_path, async_session
    ):
        commits, rollbacks = [], []
        async def commit():
            commits.append(True)
            await async_session.commit()
        async def rollback():
            rollbacks.append(True)
            await async_session.rollback()

        plan = await self._plan(tmp_path, async_session)
        report = await _svc().apply_plan(
            plan, async_session, commit=commit, rollback=rollback
        )
        assert commits == [True] and rollbacks == []
        assert (report.created, report.links) == (2, 1)
        # The data is visible through the same (now committed) session.
        assert await _count(async_session, EventModel) == 1
        assert await _count(async_session, CharacterModel) == 1
        assert (await async_session.execute(
            select(func.count()).select_from(models.event_character)
        )).scalar() == 1

    async def test_failure_in_pass_2_rolls_everything_back(self, tmp_path, async_session, monkeypatch):
        commits, rollbacks = [], []
        async def commit():
            commits.append(True)
            await async_session.commit()
        async def rollback():
            rollbacks.append(True)
            await async_session.rollback()

        svc = _svc()
        async def boom(ref, instances, session):
            raise RuntimeError("технический сбой прохода 2")
        monkeypatch.setattr(svc, "_resolve_link_target", boom)

        plan = await self._plan(tmp_path, async_session)
        with pytest.raises(RuntimeError, match="сбой"):
            await svc.apply_plan(plan, async_session, commit=commit, rollback=rollback)

        assert commits == [] and rollbacks == [True]
        # База остаётся в состоянии до импорта (spec «Откат при сбое»).
        assert await _count(async_session, EventModel) == 0
        assert await _count(async_session, CharacterModel) == 0

    async def test_update_of_row_deleted_between_analysis_and_apply_aborts(
        self, tmp_path, async_session
    ):
        # План обещает update, а строки в базе уже нет — импорт падает целиком
        # (транзакция откатана), а не пишет «в никуда».
        existing = CharacterModel(name="Уникал", start_date=date(1900, 1, 1))
        async_session.add(existing)
        await async_session.flush()
        wb = _new_workbook()
        _sheet(wb, "Персонажи", CHAR_HEADERS, [["уникал", "1901-02-02"]])
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        assert plan.lookup_row("character", "уникал").is_update

        await async_session.delete(existing)
        await async_session.flush()
        async_session.expunge_all()  # никаких ответов из identity map

        with pytest.raises(ValueError, match="исчезла из базы"):
            await _svc().apply_plan(plan, async_session)

    async def test_fatal_plan_is_refused_without_touching_the_database(
        self, tmp_path, async_session
    ):
        commits = []
        async def commit():
            commits.append(True)
            await async_session.commit()

        wb = _new_workbook()
        _sheet(wb, "Персонажи", ["Дата начала"], [[date(2001, 1, 1)]])  # no «Имя»
        plan = await _svc().analyze_file(_save(tmp_path, wb), async_session)
        with pytest.raises(ValueError, match="Импорт невозможен"):
            await _svc().apply_plan(plan, async_session, commit=commit)
        assert commits == []
        assert await _count(async_session, CharacterModel) == 0

    async def test_progress_counts_all_units_and_ends_at_total(self, tmp_path, async_session):
        plan = await self._plan(tmp_path, async_session)  # 2 entities + 1 link
        calls: list[tuple[int, int]] = []
        await _svc().apply_plan(plan, async_session,
                                progress_callback=lambda done, total: calls.append((done, total)))
        assert calls[-1] == (3, 3)

    async def test_committed_data_visible_to_a_fresh_session_and_engine(
        self, tmp_path
    ):
        """E2E-доказательство task 3.3: commit of apply_plan persists — a
        brand-new engine + session (the "app restarted") sees entities,
        links, the ghost dates and the auto-created event type."""
        wb = _new_workbook()
        _sheet(wb, "События", ["Имя", "Дата начала", "Связь персонажами", "Тип"],
               [["Бал", "1820-05-01", "Иван", "Дуэль"]])
        _sheet(wb, "Персонажи", ["Имя", "Дата начала", "Связь предметами"],
               [["Иван", "1800-01-01", "Амулет"]])
        path = _save(tmp_path, wb)

        url = f"sqlite+aiosqlite:///{tmp_path / 'game.db'}"
        engine = create_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            plan = await _svc().analyze_file(path, session)
            report = await _svc().apply_plan(plan, session)
            assert report.created == 3 and report.links == 2
        await engine.dispose()

        # "App restart": new engine, new session, same file.
        engine2 = create_engine(url)
        factory2 = create_session_factory(engine2)
        async with factory2() as session:
            assert await _count(session, EventModel) == 1
            assert await _count(session, CharacterModel) == 1
            ghost = await _one(session, ItemModel, name="Амулет")
            assert (ghost.start_date, ghost.end_date) == (date(1800, 1, 1), date(1800, 1, 1))
            assert (await _one(session, EventTypeModel, name="Дуэль")).color_index == 1
            assert (await session.execute(
                select(func.count()).select_from(models.event_character)
            )).scalar() == 1
            assert (await session.execute(
                select(func.count()).select_from(models.character_item)
            )).scalar() == 1
        await engine2.dispose()


# ── 3.4 — the Изображение column through the ImageStore pipeline ──────────

def _png_bytes(w: int = 100, h: int = 80, color=Qt.GlobalColor.red) -> bytes:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(color)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data.data())


def _char_image_wb(tmp_path, cell_value, name="Иван"):
    wb = _new_workbook()
    _sheet(wb, "Персонажи", CHAR_HEADERS + ["Изображение"], [[name, "2001-01-01", cell_value]])
    return _save(tmp_path, wb)


class TestImages:
    async def _apply(self, tmp_path, async_session, cell_value):
        store = ImageStore(async_session, tmp_path / "images")
        svc = _svc(image_store=store)
        path = _char_image_wb(tmp_path, cell_value)
        plan = await svc.analyze_file(path, async_session)
        report = await svc.apply_plan(plan, async_session)
        return store, report, await _one(async_session, CharacterModel, name="Иван")

    async def test_relative_path_ingested(self, tmp_path, async_session, qapp):
        (tmp_path / "img").mkdir()
        data = _png_bytes()
        (tmp_path / "img" / "portret.png").write_bytes(data)
        store, report, char = await self._apply(tmp_path, async_session, "img/portret.png")
        assert report.created == 1 and report.warnings == []
        assert char.image_id is not None
        assert await _count(async_session, ImageModel) == 1
        original = await store.original_file_path(char.image_id)
        assert original is not None and original.read_bytes() == data

    async def test_absolute_path_ingested(self, tmp_path, async_session, qapp):
        data = _png_bytes(color=Qt.GlobalColor.blue)
        pic = tmp_path / "abs_portret.png"
        pic.write_bytes(data)
        _, report, char = await self._apply(tmp_path, async_session, str(pic))
        assert report.warnings == [] and char.image_id is not None

    async def test_missing_file_keeps_row_and_warns(self, tmp_path, async_session, qapp):
        _, report, char = await self._apply(tmp_path, async_session, "нет.png")
        assert report.created == 1
        assert char.image_id is None
        warning, = report.warnings
        assert "нет.png" in warning and "без изображения" in warning

    async def test_image_column_without_configured_store_warns(
        self, tmp_path, async_session, qapp
    ):
        (tmp_path / "p.png").write_bytes(_png_bytes())
        svc = _svc()  # ImageStore не подключён — колонка «Изображение» не игнорируется молча
        plan = await svc.analyze_file(_char_image_wb(tmp_path, "p.png"), async_session)
        report = await svc.apply_plan(plan, async_session)
        assert report.created == 1
        assert (await _one(async_session, CharacterModel, name="Иван")).image_id is None
        warning, = report.warnings
        assert "p.png" in warning

    async def test_unsupported_extension_keeps_row_and_warns(
        self, tmp_path, async_session, qapp
    ):
        pic = tmp_path / "zametka.txt"
        pic.write_bytes(b"not an image")
        _, report, char = await self._apply(tmp_path, async_session, "zametka.txt")
        assert report.created == 1
        assert char.image_id is None
        warning, = report.warnings
        assert "zametka.txt" in warning

    async def test_undecodable_file_keeps_row_and_warns(self, tmp_path, async_session, qapp):
        pic = tmp_path / "broken.png"
        pic.write_bytes(b"definitely not a png")
        _, report, char = await self._apply(tmp_path, async_session, "broken.png")
        assert report.created == 1
        assert char.image_id is None
        warning, = report.warnings
        assert "broken.png" in warning

    async def test_update_replaces_image_and_gc_reclaims_the_old_one(
        self, tmp_path, async_session, qapp
    ):
        store = ImageStore(async_session, tmp_path / "images")
        old_id = await store.store(_png_bytes(color=Qt.GlobalColor.red))
        char = CharacterModel(name="Иван", start_date=date(1900, 1, 1))
        char.image_id = old_id
        async_session.add(char)
        await async_session.flush()

        new_bytes = _png_bytes(50, 50, color=Qt.GlobalColor.blue)
        (tmp_path / "new.png").write_bytes(new_bytes)
        svc = _svc(image_store=store)
        plan = await svc.analyze_file(_char_image_wb(tmp_path, "new.png"), async_session)
        report = await svc.apply_plan(plan, async_session)

        assert report.updated == 1 and report.warnings == []
        assert char.image_id is not None and char.image_id != old_id
        # Post-commit GC: the replaced, unreferenced image row is reclaimed.
        assert await async_session.get(ImageModel, old_id) is None
