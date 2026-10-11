"""The module's character face below the widget (add-dnd-game-face task 8.1).

Three floors tested together, each through its own door:

* the domain values — the level gate with its Russian refusal, the link
  triple's «is set», the empty value an absent row reads as;
* the codec-обвязка of the group-9 columns — every module codec's tolerant
  posture (read as empty, one journal line, the stored row never rewritten);
* the repository + service over the shared test unit-of-work: the row appears
  on the first write, every write is exactly one transaction finish, the
  spell-link add/remove are idempotent, and the refused level never touches
  a row (the gate stands before the unit opens).

The bootstrap floor (design Д6) proves the additive promise on a file that
knows only the kernel schema: one ``ensure_dd_tables`` wave grows exactly
the module's two tables, a second wave changes nothing, and rows written
between the waves survive it — which is the storage half of «Данные
переживают выключение модуля» (the UI half rides the lifecycle tests).
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dd.application.dnd_character_extension_service import (
    DndCharacterExtensionService,
)
from app.dd.domain.character import (
    LEVEL_REFUSAL,
    LINK_SLOTS,
    DdCharacterExt,
    DdSpellLink,
    ReferenceLink,
    empty_ext,
    validate_level,
)
from app.dd.infrastructure.db.dd_models import (
    DdCharacterExtModel,
    decode_text_blocks,
    encode_text_blocks,
)
from app.dd.infrastructure.db.dd_schema import ensure_dd_tables
from app.dd.infrastructure.repositories.dd_character_repository import (
    DdCharacterRepository,
    ext_to_domain,
)
from app.dd.module import DndModule
from app.infrastructure.db.database import create_engine as app_create_engine
from app.infrastructure.db.models import Base, CharacterModel

D1 = date(1300, 1, 1)


async def _add_character(async_session: AsyncSession, name: str = "Грог") -> int:
    char = CharacterModel(name=name, start_date=D1)
    async_session.add(char)
    await async_session.commit()
    return char.id


# ── domain values ─────────────────────────────────────────────────────────


def test_reference_link_is_set_reads_the_pair():
    assert ReferenceLink("", "", "").is_set is False
    # A stored pair is «set» even when its source has since vanished — the
    # value exists to keep; annotation is the tab's reading rule, not here.
    assert ReferenceLink("gone", "x", "Дворф").is_set is True


def test_validate_level_accepts_the_whole_band_and_none():
    assert validate_level(None) is None
    assert validate_level(1) == 1
    assert validate_level(20) == 20


@pytest.mark.parametrize("bad", [0, 21, -1, 999])
def test_validate_level_refuses_out_of_range_with_the_russian_sentence(bad):
    with pytest.raises(ValueError) as caught:
        validate_level(bad)
    assert str(caught.value) == LEVEL_REFUSAL


@pytest.mark.parametrize("bad", [True, False, "7", 7.0])
def test_validate_level_refuses_non_wholes(bad):
    # bool is an int subclass — a checkbox answer must not pass as a level.
    with pytest.raises(ValueError):
        validate_level(bad)


def test_empty_ext_carries_every_slot_empty():
    ext = empty_ext()
    assert ext.level is None
    assert ext.lss_sheet_id == ""
    assert set(ext.links) == {slot for slot, _section, _key in LINK_SLOTS}
    assert all(not link.is_set for link in ext.links.values())


# ── the text_blocks codec (task 8.1 «codec-обвязка») ──────────────────────


def test_codec_roundtrips_named_blocks_verbatim():
    blocks = {"Биография": "Родился в Атмаске.\nРодителей звали…", "Внешность": "Шрам"}
    import json

    raw = encode_text_blocks(blocks)
    assert json.loads(raw) == blocks  # unicode stays readable, not escaped
    assert decode_text_blocks(raw) == blocks


@pytest.mark.parametrize("raw", [None, ""])
def test_codec_absent_reads_as_no_blocks(raw):
    assert decode_text_blocks(raw) == {}


def test_codec_unparsable_body_reads_empty_with_one_journal_line(caplog):
    with caplog.at_level("WARNING"):
        assert decode_text_blocks("{не json") == {}
    assert any("не разобрано" in record.getMessage() for record in caplog.records)


def test_codec_non_object_body_reads_empty_with_one_journal_line(caplog):
    with caplog.at_level("WARNING"):
        assert decode_text_blocks('["список", "а не объект"]') == {}
    assert any("не объект" in record.getMessage() for record in caplog.records)


def test_codec_drops_non_string_halves_of_an_object():
    # A JSON object's keys are strings by construction; the guarded half that
    # lives is the value — a number never reaches the reader's dict.
    assert decode_text_blocks('{"kept": "текст", "k": 5}') == {"kept": "текст"}


# ── the service over the shared unit-of-work ──────────────────────────────


async def test_get_ext_without_a_row_reads_the_empty_face(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    ext = await service.get_ext(char_id)
    assert ext == empty_ext()


async def test_set_reference_link_appears_on_first_write_and_updates(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    await service.set_reference_link(
        char_id, "race", ReferenceLink("srd", "dwarf", "Дворф")
    )
    ext = await service.get_ext(char_id)
    assert ext.links["race"] == ReferenceLink("srd", "dwarf", "Дворф")
    # The second write edits the same row (PK = FK: one face per character).
    await service.set_reference_link(
        char_id, "class", ReferenceLink("srd", "fighter", "Воин")
    )
    ext = await service.get_ext(char_id)
    assert ext.links["class"].snapshot_name == "Воин"
    assert ext.links["race"].snapshot_name == "Дворф"
    rows = (
        await uow.session.execute(
            select(DdCharacterExtModel).where(
                DdCharacterExtModel.character_id == char_id
            )
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_set_reference_link_stores_a_dead_triple_verbatim(uow):
    # «Снятый датасет не калечит карточку» at the storage floor: the service
    # never re-resolves — the triple it is handed is the triple it keeps.
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    dead = ReferenceLink("removed-set", "x/42", "Забытая раса")
    await service.set_reference_link(char_id, "background", dead)
    assert (await service.get_ext(char_id)).links["background"] == dead


async def test_set_level_roundtrip_and_unset(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    await service.set_level(char_id, 7)
    assert (await service.get_ext(char_id)).level == 7
    await service.set_level(char_id, None)
    assert (await service.get_ext(char_id)).level is None


async def test_refused_level_never_touches_a_row(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    with pytest.raises(ValueError) as caught:
        await service.set_level(char_id, 21)
    assert str(caught.value) == LEVEL_REFUSAL
    assert await DdCharacterRepository(uow.session).get_ext(char_id) is None


async def test_sheet_id_empty_stores_one_no_sheet_fact(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    await service.set_lss_sheet_id(char_id, "abc123")
    assert (await service.get_ext(char_id)).lss_sheet_id == "abc123"
    await service.set_lss_sheet_id(char_id, "")
    # NULL and "" both read as «no sheet»; the button hides on that reading.
    ext = await service.get_ext(char_id)
    assert ext.lss_sheet_id == ""
    row = await DdCharacterRepository(uow.session).get_ext(char_id)
    assert row.lss_sheet_id is None


async def test_spell_link_add_is_idempotent_and_keeps_order(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    first = DdSpellLink("srd", "fire-bolt", "Fire bolt")
    second = DdSpellLink("grim", "witch-sight", "Ведьмин глаз")
    await service.add_spell_link(char_id, first)
    await service.add_spell_link(char_id, first)  # the same pair: a no-op
    await service.add_spell_link(char_id, second)
    assert await service.get_spell_links(char_id) == [first, second]
    # Same slug under another source is another binding (the pair is identity).
    await service.add_spell_link(char_id, DdSpellLink("grim", "fire-bolt", "Друг"))
    assert len(await service.get_spell_links(char_id)) == 3


async def test_spell_link_remove_and_absent_noop(uow):
    service = DndCharacterExtensionService(uow)
    char_id = await _add_character(uow.session)
    link = DdSpellLink("srd", "mage-hand", "Mage hand")
    await service.add_spell_link(char_id, link)
    await service.remove_spell_link(char_id, link.source_key, "нет-такого")
    assert await service.get_spell_links(char_id) == [link]
    await service.remove_spell_link(char_id, link.source_key, link.slug)
    assert await service.get_spell_links(char_id) == []


def test_ext_to_domain_reads_a_null_sheet_as_empty():
    row = DdCharacterExtModel(
        character_id=1, race_source_key=None, race_ref_id=None, race_snapshot_name=None,
        lss_sheet_id=None, level=None,
    )
    ext = ext_to_domain(row)
    assert isinstance(ext, DdCharacterExt)
    assert ext.links["race"] == ReferenceLink("", "", "")
    assert ext.lss_sheet_id == ""


# ── bootstrap (design Д6): additive create over a kernel-only file ────────


async def test_ensure_dd_tables_is_additive_idempotent_and_data_safe(tmp_path):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.infrastructure.db.uow import GameSessionUoW

    db_path = tmp_path / "game.db"
    engine = app_create_engine(f"sqlite+aiosqlite:///{db_path}")
    kernel_tables = [
        table
        for name, table in Base.metadata.tables.items()
        if not name.startswith("dd_")
    ]
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=kernel_tables, checkfirst=True
            )
        )
    try:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async def table_names(session) -> set[str]:
            rows = (
                await session.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            ).scalars().all()
            return set(rows)

        # Wave one over a game that predates the module's tables.
        async with factory() as session:
            unit = GameSessionUoW(session)
            await ensure_dd_tables(unit)
            names = await table_names(session)
            assert {"dd_character_ext", "dd_character_spell_link"} <= names

            # A character's face is written through the service door…
            async with unit.transaction():
                char = CharacterModel(name="Мия", start_date=D1)
                session.add(char)
            service = DndCharacterExtensionService(unit)
            await service.set_level(char.id, 3)

            # …wave two (a restart bootstrap) changes neither rows nor schema.
            await ensure_dd_tables(unit)
            assert (await service.get_ext(char.id)).level == 3
            assert await table_names(session) == names
    finally:
        await engine.dispose()


async def test_module_ensure_tables_stays_silent_without_a_settings_door():
    # The façade composed without a settings service has no unit to create
    # on (module.py bootstrap door) — silence, not an attribute error.
    module = DndModule(None, None, None, None, None, None, ())
    await module.ensure_tables()
