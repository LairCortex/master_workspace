"""The character-import flow over a real database (add-dnd-game-face task 9.3;
spec dnd-character-import).

The decision tree is pinned at the storage floor, not with mocks of itself:

* errors stop the write before anything is touched (BLOCKED — the character
  catalog was never asked);
* a replacement without confirmation answers NEEDS_CONFIRMATION and the
  person, the fields and the file-snapshot stay exactly as they stood;
* a clean create lays everything out: the kernel row (name, avatar image
  through the single ingest door), the five triples — live pair and live name
  for a connected record, the FILE's snapshot with an empty source when the
  record is absent (Д7) — the level, the structural render, the document's
  own text blocks (a block of a structural name merges below the render),
  and the RAW FILE VERBATIM in ``raw_document`` (spec «сырой файл всегда»);
* the confirmed overwrite replaces the fields, leaves spell links and the
  sheet id untouched, and answers OVERWRITTEN;
* ``save_raw_document`` writes the stored bytes byte-for-byte and answers
  ``False`` for a character that never imported a file.
"""
from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.entity_service import EntityService
from app.dd.application.character_import_service import (
    BLOCK_AVATAR,
    OVERWRITE_CONFIRM_BODY,
    CharacterImportService,
    CharacterImportStatus,
)
from app.dd.application.dataset_index_service import DatasetEntry, IndexSnapshot
from app.dd.domain.character import LINK_SLOTS
from app.dd.domain.character_checks import CODE_CHAR_AVATAR
from app.dd.infrastructure.db.dd_models import DdCharacterExtModel, decode_text_blocks
from app.dd.infrastructure.db.dd_schema import ensure_dd_tables
from app.dd.infrastructure.repositories.dd_character_repository import (
    DdCharacterRepository,
    mechanics_from_row,
)
from app.domain.entity_registry import EntityType
from app.infrastructure.db.models import CharacterModel, DescriptionModel
from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories.base_repository import BaseRepository

D1 = date(1300, 1, 1)


def _png_data_uri(color=Qt.GlobalColor.red) -> str:
    img = QImage(8, 8, QImage.Format.Format_RGB32)
    img.fill(color)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return "data:image/png;base64," + base64.b64encode(bytes(data)).decode()


def _envelope(data: dict) -> str:
    return json.dumps(
        {"jsonType": "character", "version": "2", "data": data},
        ensure_ascii=False,
    )


def _rich_data(**over) -> dict:
    """A live-looking export: refs, level, a structural family, a text block
    colliding with a structural name, a plain block and an avatar."""
    data = {
        "name": "  Грог  ",
        "level": 3,
        "avatar": _png_data_uri(),
        "info": {
            "race": {"id": "orc", "name": "Полуорк"},
            "charClass": {"id": "barbarian", "name": "Варвар"},
            "background": {"id": "soldier", "name": "Солдат"},
        },
        "stats": {"str": {"value": 17, "save": True}},
        "blocks": {
            "Характеристики": "Сила — вся жизнь.",
            "Биография": "Родился в степи.",
        },
    }
    data.update(over)
    return data


class _StubIndex:
    def __init__(self, snap: IndexSnapshot | None) -> None:
        self._snap = snap

    async def snapshot(self):
        return self._snap


def _connected_index() -> IndexSnapshot:
    return IndexSnapshot(
        ids=("srd",),
        titles={"srd": "SRD-5.1"},
        sections={
            "races": {"srd": (DatasetEntry("srd", "orc", "Орк", {}),)},
            "classes": {"srd": (DatasetEntry("srd", "barbarian", "Варвар", {}),)},
        },
        slugs={},
    )


async def _make_service(
    uow,
    *,
    images_dir: Path | None = None,
    index: IndexSnapshot | None = None,
    catalog: dict | None = None,
):
    """Real EntityService catalog over the test session — the write path is
    exercised for real, the index door is the stub of the frames' pattern."""
    await ensure_dd_tables(uow)
    if catalog is None:
        desc_repo = BaseRepository(uow.session, DescriptionModel)
        from app.infrastructure.repositories.character_repository import (
            CharacterRepository,
        )

        catalog = {
            EntityType.CHARACTER.value: EntityService(CharacterRepository(uow.session), desc_repo)
        }
    image_store = ImageStore(uow.session, images_dir) if images_dir is not None else None
    service = CharacterImportService(
        uow=uow,
        entity_services=lambda: catalog,
        image_store=image_store,
        dataset_index=_StubIndex(index),
        now=lambda: D1,
    )
    return service


async def _ext_row(session: AsyncSession, character_id: int):
    return await DdCharacterRepository(session).get_ext(character_id)


# ── BLOCKED / NEEDS_CONFIRMATION: nothing is touched ──────────────────────


async def test_blocked_report_never_asks_the_catalog(uow):
    def _forbidden_catalog():  # not even called
        raise AssertionError("каталог не должен спрашиваться при BLOCKED")

    service = CharacterImportService(
        uow=uow, entity_services=_forbidden_catalog, now=lambda: D1
    )
    outcome = await service.import_character("не json {{{")
    assert outcome.status is CharacterImportStatus.BLOCKED
    assert outcome.character_id is None
    assert outcome.report is not None and not outcome.report.import_allowed


async def test_confirmation_request_touches_person_and_snapshot_not_at_all(uow):
    await ensure_dd_tables(uow)
    char = CharacterModel(name="Прежний", start_date=D1)
    uow.session.add(char)
    await uow.session.commit()
    repo = DdCharacterRepository(uow.session)
    ext = await repo.insert_ext(char.id)
    ext.raw_document = "прежний снимок"
    await uow.session.commit()

    service = await _make_service(uow)
    outcome = await service.import_character(_envelope({"name": "Грог"}), character_id=char.id)
    assert outcome.status is CharacterImportStatus.NEEDS_CONFIRMATION
    assert outcome.character_id == char.id
    assert outcome.message == OVERWRITE_CONFIRM_BODY
    await uow.session.rollback()
    row = await uow.session.get(CharacterModel, char.id)
    assert row.name == "Прежний"
    ext = await _ext_row(uow.session, char.id)
    assert ext.raw_document == "прежний снимок"


# ── CREATED: the full layout ───────────────────────────────────────────────


async def test_create_lays_out_everything_and_keeps_the_file_verbatim(uow, tmp_path):
    content = _envelope(_rich_data())
    service = await _make_service(uow, images_dir=tmp_path, index=_connected_index())
    outcome = await service.import_character(content)
    assert outcome.status is CharacterImportStatus.CREATED
    assert outcome.name == "Грог"  # the envelope's whitespace is trimmed
    assert "Грог" in outcome.message
    character_id = outcome.character_id

    row = await uow.session.get(CharacterModel, character_id)
    assert row.name == "Грог"
    assert row.start_date == D1
    assert row.image_id is not None  # the avatar rode the ingest door

    ext = await _ext_row(uow.session, character_id)
    assert ext.raw_document == content  # byte-for-byte, spec «источник правды»
    assert ext.level == 3
    # Connected records: live pair + live name from the index record…
    assert ext.race_source_key == "srd" and ext.race_ref_id == "orc"
    assert ext.race_snapshot_name == "Орк"  # the record's live name wins
    assert ext.class_source_key == "srd" and ext.class_snapshot_name == "Варвар"
    # …a disconnected id keeps the FILE's snapshot with an empty source…
    assert ext.background_source_key == "" and ext.background_ref_id == "soldier"
    assert ext.background_snapshot_name == "Солдат"
    # …and an absent reference is the empty triple.
    assert ext.subrace_source_key == "" and ext.subrace_snapshot_name == ""
    # The sheet id is nobody's business here (None/"" both read «нет листа»),
    # and the blocks arrived encoded.
    assert not ext.lss_sheet_id
    assert ext.text_blocks.startswith("{")

    blocks = decode_text_blocks(ext.text_blocks)
    # The clash: structural render above, the author's text below (Д7).
    # The six scores did NOT fit (partial set) — «Характеристики» prints.
    assert blocks["Характеристики"] == "Сила: 17\n\nСила — вся жизнь."
    # The boolean save flag DID fit (dd-card-redesign task 6.1): the saving
    # throw is stored structure, not painted as a block.
    assert "Спасброски" not in blocks
    mechanics = mechanics_from_row(ext)
    assert mechanics.scores is None  # one value of six is no set
    assert mechanics.manual_saving_throws == frozenset({"strength"})
    assert blocks["Биография"] == "Родился в степи."


async def test_avatar_other_than_an_image_keeps_a_visible_avatar_block(uow):
    content = _envelope(_rich_data(avatar="https://example.com/grog.png"))
    service = await _make_service(uow)
    outcome = await service.import_character(content)
    row = await uow.session.get(CharacterModel, outcome.character_id)
    assert row.image_id is None
    ext = await _ext_row(uow.session, outcome.character_id)
    blocks = decode_text_blocks(ext.text_blocks)
    assert blocks[BLOCK_AVATAR] == "https://example.com/grog.png"


async def test_unreadable_data_uri_warns_and_the_import_stands(uow, tmp_path):
    broken = "data:image/png;base64,####не base64####"
    content = _envelope(_rich_data(avatar=broken))
    service = await _make_service(uow, images_dir=tmp_path)
    outcome = await service.import_character(content)
    assert outcome.status is CharacterImportStatus.CREATED
    row = await uow.session.get(CharacterModel, outcome.character_id)
    assert row.image_id is None
    codes = [issue.code for issue in outcome.report.issues]
    assert CODE_CHAR_AVATAR in codes
    ext = await _ext_row(uow.session, outcome.character_id)
    assert broken in ext.raw_document  # the file-snapshot kept it anyway


async def test_data_uri_without_an_image_store_warns(uow):
    content = _envelope(_rich_data())
    service = await _make_service(uow)  # no images_dir → image_store is None
    outcome = await service.import_character(content)
    assert outcome.status is CharacterImportStatus.CREATED
    codes = [issue.code for issue in outcome.report.issues]
    assert CODE_CHAR_AVATAR in codes


async def test_empty_name_imports_as_an_empty_kernel_name(uow):
    # The schema allows a name that is only whitespace; the layout trims to
    # "" — an honest mirror of a nameless export, the file stays the truth.
    content = _envelope({"name": "   "})
    service = await _make_service(uow)
    outcome = await service.import_character(content)
    assert outcome.status is CharacterImportStatus.CREATED
    ext = await _ext_row(uow.session, outcome.character_id)
    assert ext.level is None


async def test_level_shaped_garbage_lands_as_no_level(uow):
    # JSON-Schema's «integer» accepts 3.0; the kernel column wants a whole
    # number — the float answer lands as no level rather than a lie.
    content = _envelope({"name": "Грог", "level": 3.0})
    service = await _make_service(uow)
    outcome = await service.import_character(content)
    assert outcome.status is CharacterImportStatus.CREATED
    ext = await _ext_row(uow.session, outcome.character_id)
    assert ext.level is None


# ── OVERWRITTEN: fields replaced, module-foreign halves kept ──────────────


async def test_confirmed_overwrite_replaces_fields_and_keeps_sheet_id(uow):
    await ensure_dd_tables(uow)
    char = CharacterModel(name="Прежний", start_date=D1)
    uow.session.add(char)
    await uow.session.commit()
    repo = DdCharacterRepository(uow.session)
    ext = await repo.insert_ext(char.id)
    ext.lss_sheet_id = "abc123"
    ext.race_source_key = "srd"
    ext.race_ref_id = "old-orc"
    ext.race_snapshot_name = "Старый орк"
    await uow.session.commit()

    service = await _make_service(uow, index=_connected_index())
    content = _envelope({"name": "Грог", "level": 5, "stats": {"dex": {"value": 14}}})
    outcome = await service.import_character(content, character_id=char.id)
    assert outcome.status is CharacterImportStatus.NEEDS_CONFIRMATION
    outcome = await service.import_character(
        content, character_id=char.id, confirmed=True
    )
    assert outcome.status is CharacterImportStatus.OVERWRITTEN
    assert "перезаписан" in outcome.message

    row = await uow.session.get(CharacterModel, char.id)
    assert row.name == "Грог"
    ext = await _ext_row(uow.session, char.id)
    assert ext.lss_sheet_id == "abc123"  # not derivable from the file — kept
    assert ext.level == 5
    assert ext.raw_document == content
    # The old race link is replaced by the file's answer (absent → empty).
    assert ext.race_ref_id == "" and ext.race_snapshot_name == ""
    assert decode_text_blocks(ext.text_blocks) == {"Характеристики": "Ловкость: 14"}


# ── the way back out ───────────────────────────────────────────────────────


async def test_save_raw_document_writes_verbatim_or_refuses_silently(uow, tmp_path):
    service = await _make_service(uow)
    assert await service.save_raw_document(9999, str(tmp_path / "x.json")) is False

    content = _envelope({"name": "Грог"})
    outcome = await service.import_character(content)
    target = tmp_path / "гrog.json"
    assert await service.save_raw_document(outcome.character_id, str(target)) is True
    assert target.read_bytes() == content.encode("utf-8")

    await service.import_character(_envelope({"name": "Другой"}))
    fresh_ext = await _ext_row(uow.session, outcome.character_id)
    assert fresh_ext.raw_document == content


async def test_catalog_without_characters_raises(uow):
    service = await _make_service(uow, catalog={})
    with pytest.raises(RuntimeError, match="не знает персонажей"):
        await service.import_character(_envelope({"name": "Грог"}))


async def test_ext_row_is_created_once_and_slots_covered(uow):
    # The second import over the same person reuses the ext row (no unique
    # violation) and rewrites every slot column of the LINK_SLOTS table.
    await ensure_dd_tables(uow)
    char = CharacterModel(name="Прежний", start_date=D1)
    uow.session.add(char)
    await uow.session.commit()
    service = await _make_service(uow)
    first = _envelope(_rich_data())
    outcome = await service.import_character(first, character_id=char.id, confirmed=True)
    assert outcome.status is CharacterImportStatus.OVERWRITTEN
    outcome = await service.import_character(
        _envelope({"name": "Грог-младший"}), character_id=char.id, confirmed=True
    )
    assert outcome.status is CharacterImportStatus.OVERWRITTEN
    ext = await _ext_row(uow.session, char.id)
    for slot, _section, _key in LINK_SLOTS:
        assert getattr(ext, f"{slot}_source_key") == ""
    count = (
        await uow.session.execute(
            select(func.count())
            .select_from(DdCharacterExtModel)
            .where(DdCharacterExtModel.character_id == char.id)
        )
    ).scalar_one()
    assert count == 1


async def test_overwrite_with_avatar_repaints_the_portrait(uow, tmp_path):
    """The update branch with a picture: overwriting an existing person with
    a file that carries an avatar pushes the fresh image_id through the same
    catalog door the create path uses (a stale portrait after a confirmed
    перезапись would silently lie about who the sheet depicts)."""
    await ensure_dd_tables(uow)
    char = CharacterModel(name="Прежний", start_date=D1)
    uow.session.add(char)
    await uow.session.commit()
    service = await _make_service(uow, images_dir=tmp_path)
    outcome = await service.import_character(
        _envelope({"name": "Грог", "avatar": _png_data_uri()}),
        character_id=char.id,
        confirmed=True,
    )
    assert outcome.status is CharacterImportStatus.OVERWRITTEN
    row = await uow.session.get(CharacterModel, char.id)
    assert row.name == "Грог" and row.image_id is not None


async def test_nameless_block_key_is_dropped_in_silence(uow):
    """A block under the empty key is a broken document, not a broken import:
    the row is skipped, its honest siblings reach the card (line-300 gate)."""
    service = await _make_service(uow)
    outcome = await service.import_character(
        _envelope({"name": "Грог", "blocks": {"": "мусор", "Живой": "текст"}})
    )
    ext = await _ext_row(uow.session, outcome.character_id)
    assert decode_text_blocks(ext.text_blocks) == {"Живой": "текст"}


# ── mechanics intake (dd-card-redesign task 6.1; spec «Механики легли
# структурой») ───────────────────────────────────────────────────────────────


def _full_mechanics_doc(**over) -> dict:
    """A document whose every mechanics family fits: whole six values,
    boolean flags, a known alignment, a whole speed, a legal slot grid and
    well-formed feat references."""
    data = {
        "name": "Грог Профиль",
        "level": 5,
        "stats": {
            "str": {"value": 18, "save": True},
            "dex": {"value": 14},
            "con": {"value": 16, "save": True},
            "int": {"value": 10},
            "wis": {"value": 12},
            "cha": {"value": 8},
        },
        "skills": {
            "athletics": {"proficient": True},
            "stealth": {"proficient": False},
        },
        "speed": 25,
        "alignment": "хаотично-добрый",
        "feats": [
            {"id": "alert", "name": "Наблюдательность"},
            {"id": "lucky", "name": "Везунчик"},
        ],
        "spells": {
            "list": ["fire-ball"],
            "slots": [{"level": 1, "value": 4, "max": 4}],
        },
        "coins": {"gp": 5},
    }
    data.update(over)
    return data


def _index_with_feats(*, connected: tuple[str, ...] = ("alert",)) -> IndexSnapshot:
    snap = _connected_index()
    entries = tuple(
        DatasetEntry("srd", ref_id, f"Черта {ref_id}", {}) for ref_id in connected
    )
    return IndexSnapshot(
        ids=snap.ids,
        titles=snap.titles,
        sections={**snap.sections, "feats": {"srd": entries}},
        slugs={},
    )


async def test_fitted_mechanics_lay_structured_and_lose_their_blocks(uow):
    """Spec scenario «Механики легли структурой»: values arrive in the
    structured fields, their readable blocks are NOT painted, and the
    sections that never ride the structure (coins) keep their block."""
    content = _envelope(_full_mechanics_doc())
    service = await _make_service(uow, index=_index_with_feats())
    outcome = await service.import_character(content)
    assert outcome.status is CharacterImportStatus.CREATED
    ext = await _ext_row(uow.session, outcome.character_id)

    mechanics = mechanics_from_row(ext)
    assert mechanics.scores == {
        "strength": 18,
        "dexterity": 14,
        "constitution": 16,
        "intelligence": 10,
        "wisdom": 12,
        "charisma": 8,
    }
    assert mechanics.manual_saving_throws == frozenset({"strength", "constitution"})
    assert mechanics.skill_proficiencies == frozenset({"athletics"})
    assert mechanics.speed == 25
    assert mechanics.alignment == "хаотично-добрый"
    assert mechanics.spell_slots == {1: 4}

    blocks = decode_text_blocks(ext.text_blocks)
    for fitted in ("Характеристики", "Спасброски", "Навыки", "Ячейки заклинаний"):
        assert fitted not in blocks
    assert blocks["Монеты"] == "gp: 5"  # не механика — блок как прежде

    # Feats resolve through the connected index like the face triples:
    # «alert» answers the set (live pair + live name), «lucky» is absent →
    # the file's snapshot with an empty source.
    links = await DdCharacterRepository(uow.session).list_feat_links(
        outcome.character_id
    )
    assert [(lnk.source_key, lnk.ref_id, lnk.snapshot_name) for lnk in links] == [
        ("srd", "alert", "Черта alert"),
        ("", "lucky", "Везунчик"),
    ]
    # The spell slug list is not the importer's to bind — no spell links.
    assert await DdCharacterRepository(uow.session).list_spell_links(
        outcome.character_id
    ) == []


async def test_overwrite_replaces_feat_wall_and_clears_absent_families(uow):
    """The file replaces the card: an overwrite whose document stops naming
    feats/speed/alignment un-chooses the stored ones (the same replacement
    an absent level already obeys)."""
    service = await _make_service(uow, index=_index_with_feats())
    first = await service.import_character(_envelope(_full_mechanics_doc()))
    character_id = first.character_id

    second = await service.import_character(
        _envelope({"name": "Грог-младший"}), character_id=character_id, confirmed=True
    )
    assert second.status is CharacterImportStatus.OVERWRITTEN
    ext = await _ext_row(uow.session, character_id)
    mechanics = mechanics_from_row(ext)
    assert mechanics.scores is None
    assert mechanics.speed is None and mechanics.alignment is None
    assert mechanics.spell_slots == {}
    assert mechanics.skill_proficiencies == frozenset()
    assert mechanics.manual_saving_throws == frozenset()
    assert await DdCharacterRepository(uow.session).list_feat_links(character_id) == []


async def test_unreadable_families_keep_their_readable_blocks(uow):
    """A family the intake refuses is NOT invented away: the numeric save
    rides the «Спасброски» block, the string speed — «Скорость», the foreign
    alignment — «Мировоззрение», the valueless slot entry — «Ячейки
    заклинаний», while the fitting siblings are still stored structured."""
    content = _envelope(
        _full_mechanics_doc(
            stats={
                "str": {"value": 18, "save": 5},
                "dex": {"value": 14},
                "con": {"value": 16},
                "int": {"value": 10},
                "wis": {"value": 12},
                "cha": {"value": 8},
            },
            speed="босая быстрые ноги",
            alignment="нейтралитет как призвание",
            spells={"slots": [{"level": 1}]},
        )
    )
    service = await _make_service(uow, index=_index_with_feats())
    outcome = await service.import_character(content)
    ext = await _ext_row(uow.session, outcome.character_id)

    mechanics = mechanics_from_row(ext)
    assert mechanics.scores == {
        "strength": 18,
        "dexterity": 14,
        "constitution": 16,
        "intelligence": 10,
        "wisdom": 12,
        "charisma": 8,
    }  # values fit on their own
    assert mechanics.manual_saving_throws == frozenset()  # numeric save refused
    assert mechanics.speed is None and mechanics.alignment is None
    assert mechanics.spell_slots == {}  # an entry without a count is no grid

    blocks = decode_text_blocks(ext.text_blocks)
    assert blocks["Спасброски"] == "Сила: +5"
    assert blocks["Скорость"] == "босая быстрые ноги"
    assert blocks["Мировоззрение"] == "нейтралитет как призвание"
    assert blocks["Ячейки заклинаний"] == "- 1-й круг"


async def test_alignment_alias_and_garbage_feat_entries_ride_the_tolerances(uow):
    """English «Chaotic Good» normalizes to the stored nine; a string feat
    and a dict without an id are refused per entry and print under «Черты»,
    while the good references still bind."""
    content = _envelope(
        _full_mechanics_doc(
            alignment="Chaotic Good",
            feats=[{"id": "alert"}, "Удача на верёвочке", {"name": "без id"}],
        )
    )
    service = await _make_service(uow, index=_index_with_feats())
    outcome = await service.import_character(content)
    ext = await _ext_row(uow.session, outcome.character_id)
    assert ext.alignment == "хаотично-добрый"
    links = await DdCharacterRepository(uow.session).list_feat_links(
        outcome.character_id
    )
    assert [lnk.ref_id for lnk in links] == ["alert"]
    blocks = decode_text_blocks(ext.text_blocks)
    assert blocks["Черты"] == '- Удача на верёвочке\n- {"name": "без id"}'


async def test_unknown_sections_print_under_their_original_name(uow):
    """Spec «Ни один текстовый блок документа НЕ SHALL быть потерян молча»:
    a section the format does not know arrives as a block with its own name,
    non-string content as its JSON."""
    content = _envelope(
        _full_mechanics_doc(hobby="Резная фигурка", customCounter={"left": 3})
    )
    service = await _make_service(uow, index=_index_with_feats())
    outcome = await service.import_character(content)
    ext = await _ext_row(uow.session, outcome.character_id)
    blocks = decode_text_blocks(ext.text_blocks)
    assert blocks["hobby"] == "Резная фигурка"
    assert blocks["customCounter"] == '{"left": 3}'
