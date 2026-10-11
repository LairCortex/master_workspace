"""The module's tables on the kernel's Base (add-dnd-game-face task 8.1, design Д6).

Design Д6: the D&D face of a character (five reference links, level, LSS sheet
id) and the spell bindings live in the MODULE's tables; the kernel schema is
never touched. Declaring them on the kernel ``Base`` is the legal downward
import (the module knows the kernel, never the reverse); in the profile
without the module the package is never imported, the metadata stays clean
and the kernel's ``create_all`` keeps its byte-for-byte schema (design Д11).

Creation is the module's own door, never a kernel migration (Д6 rejected the
``_MIGRATIONS`` route: DDL must not leak from the module into the kernel) —
:meth:`ModuleSettingsService.enable` and the game-open bootstrap create these
tables through :func:`app.dd.infrastructure.db.dd_schema.ensure_dd_tables`,
additively (``checkfirst``): an existing table, its rows and every kernel
table survive untouched, which is exactly the spec's «Данные переживают
выключение модуля» floor — disabling keeps the tables, re-enabling returns
the data without restoration.

Link triples follow Д6: every reference link stores the pair «source + id»
together with the name snapshot taken at the moment of the choice
(``<slot>_source_key`` / ``<slot>_ref_id`` / ``<slot>_snapshot_name``). An
unset link is a triple of empty strings; a triple whose source later vanishes
keeps its snapshot verbatim (spec «Снятый датасет не калечит карточку» — the
reader loses nothing, the frame only annotates it).
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.models import Base

#: The dd subset :func:`app.dd.infrastructure.db.dd_schema.ensure_dd_tables`
#: creates — every table the module owns. Group 10 grew the bestiary table
#: (dd_monster, task 10.1); group 11 (encounter) joins when its task does.
DD_TABLES = []  # populated below, after the classes are declared

#: JSON codec journal name (the corrupt-value posture of every module codec:
#: read as empty, journal line, the stored row is never rewritten here).
_CODEC_LOGGER = "app.dd.character_codec"


class DdCharacterExtModel(Base):
    """One D&D face row per character (PK doubles as the FK: one row per
    character, row appears on the first write, Д6)."""

    __tablename__ = "dd_character_ext"
    # The module's tables sit on the kernel ``Base`` (Д6); a module-purging
    # import (the profile tests drop ``app.dd`` from ``sys.modules`` while the
    # kernel Base and its metadata live on — tests/test_dd_module_profile.py's
    # module_cache_purged) therefore re-runs this class body over a metadata
    # that already carries the table. ``extend_existing`` reuses that table
    # instead of raising «Table is already defined», keeping ONE Table object
    # per name (the reload-safe declarative pattern; no second table, no
    # shadow schema).
    __table_args__ = {"extend_existing": True}

    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True
    )
    # The five reference links (design Д6's triple each: вид/подвид/класс/
    # подкласс/предыстория — the spec's field set; черты are not a character
    # field in this slice). The kernel's characters table — and every other
    # game row — stays exactly as it was.
    race_source_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    race_ref_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    race_snapshot_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    subrace_source_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    subrace_ref_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    subrace_snapshot_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    class_source_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    class_ref_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    class_snapshot_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    subclass_source_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    subclass_ref_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    subclass_snapshot_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    background_source_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    background_ref_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    background_snapshot_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    # Level: NULL = «не указан» (the character may exist before its build is
    # known); the 1…20 gate is the service's domain rule (spec «уровень
    # (целое 1…20)»). One class, one level — no multiclass column exists
    # (spec «Мультикласса SHALL NOT быть»).
    level: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # The digital LSS sheet id; empty/NULL both mean «no sheet» (the tab's
    # «Открыть в браузере» button hides while it is empty).
    lss_sheet_id: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Group-9 columns ship with the table (Д6): the raw LSS export and the
    # named text blocks ride here from the first schema this version creates;
    # the import flow is what fills them, the codec below is their wrapper.
    raw_document: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    text_blocks: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)


class DdCharacterSpellLinkModel(Base):
    """One spell binding of one character (Д6): the link is a REFERENCE to
    the reference entity — «slug + source» plus the name snapshot, never a
    copy of the spell text (spec «Привязка SHALL быть ссылкой … а не
    копией её текста»)."""

    __tablename__ = "dd_character_spell_link"
    # Reload-safe over a module-purging import — see DdCharacterExtModel's
    # __table_args__ comment (one Table per name on the shared kernel Base).
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    source_key: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_name: Mapped[str] = mapped_column(String, nullable=False, default="")


class DdMonsterModel(Base):
    """One bestiary monster (add-dnd-game-face task 10.1, design Д6): the
    game's OWN entity — the LSS datasets carry no monsters — with the three
    common card fields: named text blocks, an image from the kernel store,
    the 1…20 rating. Mechanics (AC, hits, attacks) live in the blocks (spec
    dnd-bestiary «Механика — текстом»); no typed mechanic column exists."""

    __tablename__ = "dd_monster"
    # Reload-safe over a module-purging import — see DdCharacterExtModel's
    # __table_args__ comment (one Table per name on the shared kernel Base).
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The name is the bestiary row, the search row and the mention display:
    # the service's gate bars empty before the row is ever written.
    name: Mapped[str] = mapped_column(String, nullable=False)
    # The kernel image store's door (Д6 «image_id→images»): SET NULL mirrors
    # the kernel entity FKs — when the image row is dropped (boot GC), the
    # monster keeps its row and loses only the picture, no id dangles.
    image_id: Mapped[int | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL"), nullable=True, default=None
    )
    # The card's rating: the same whole 1…20 the kernel card field prints
    # (the domain gate in app/dd/domain/monster.py mirrors validate_level).
    rating: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Named text blocks in the group-9 codec's JSON body (the same
    # «имя→текст» shape as dd_character_ext.text_blocks, one codec).
    blocks: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

class DdEncounterModel(Base):
    """One encounter overlay per event (add-dnd-game-face task 11.1, design
    Д6): the PK doubles as the FK to the kernel ``events`` row — one overlay
    row per event, the row appears on the first save of the «Встреча» tab.
    ``ON DELETE CASCADE`` is the spec's formality («удаление события каскадом
    убирает надстройку»; the product has no event removal, NRI-0023 wrote the
    same sentence about the parent self-FK). The composition is the JSON body
    of «монстр × количество» rows with the name snapshot taken at the moment
    of the choice (Д6's snapshot rule); a monster the bestiary lost keeps its
    snapshot verbatim. An EMPTY composition means no encounter (the task's
    rule «пустой состав = нет встречи») — such a row is deleted by the
    service, it never lingers as a half-overlay."""

    __tablename__ = "dd_encounter"
    # Reload-safe over a module-purging import — see DdCharacterExtModel's
    # __table_args__ comment (one Table per name on the shared kernel Base).
    __table_args__ = {"extend_existing": True}

    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    # JSON list of «{monster_id, count, name}» rows (the codec below); NULL
    # and a body that no longer parses both read as an empty composition.
    composition: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # The encounter's note — free text, rides with the composition (the
    # composition alone decides whether the overlay exists at all).
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


DD_TABLES.append(DdCharacterExtModel.__table__)
DD_TABLES.append(DdCharacterSpellLinkModel.__table__)
DD_TABLES.append(DdMonsterModel.__table__)
DD_TABLES.append(DdEncounterModel.__table__)


# ── the text_blocks codec (task 8.1 «codec-обвязка») ─────────────────────────


def encode_text_blocks(blocks: dict[str, str]) -> str:
    """The named blocks («имя→текст», Д6) as the column's JSON body."""
    return json.dumps(blocks, ensure_ascii=False)


def decode_text_blocks(raw: str | None) -> dict[str, str]:
    """The stored named blocks, tolerant the way every module codec is:
    an absent value reads as no blocks; bytes that no longer parse, a body
    that is not a mapping, and non-string halves read as empty with one
    journal line — the stored row is never rewritten by a read (the preview
    pins' posture, design Д6/Д7)."""
    if not raw:
        return {}
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        logging.getLogger(_CODEC_LOGGER).warning(
            "dd text_blocks: сохранённое значение не разобрано — читаем как пусто"
        )
        return {}
    if not isinstance(document, dict):
        logging.getLogger(_CODEC_LOGGER).warning(
            "dd text_blocks: значение — не объект, читаем как пусто"
        )
        return {}
    blocks: dict[str, str] = {}
    for name, text in document.items():
        if isinstance(name, str) and isinstance(text, str):
            blocks[name] = text
    return blocks


# ── the dd_encounter.composition codec (task 11.1) ──────────────────────────


def encode_composition(entries: list[dict]) -> str:
    """The composition rows («монстр × количество» + снимок имени) as the
    column's JSON body — the service hands clean dicts (its gate ran before
    the transaction opened)."""
    return json.dumps(entries, ensure_ascii=False)


def decode_composition(raw: str | None) -> list[dict]:
    """The stored composition, tolerant the way every module codec is: an
    absent value reads as no rows; bytes that no longer parse and a body that
    is not a list read as empty with one journal line — the stored row is
    never rewritten by a read. A row that is not a clean triple (whole
    monster_id, whole positive count, string name) is dropped as the garbage
    it is: the encounter keeps the rows it can honestly show (the preview
    pins' posture, design Д6)."""
    if not raw:
        return []
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        logging.getLogger(_CODEC_LOGGER).warning(
            "dd composition: сохранённое значение не разобрано — читаем как пусто"
        )
        return []
    if not isinstance(document, list):
        logging.getLogger(_CODEC_LOGGER).warning(
            "dd composition: значение — не список, читаем как пусто"
        )
        return []
    entries: list[dict] = []
    for entry in document:
        if not isinstance(entry, dict):
            continue
        monster_id = entry.get("monster_id")
        count = entry.get("count")
        name = entry.get("name")
        if isinstance(monster_id, bool) or not isinstance(monster_id, int):
            continue
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            continue
        if not isinstance(name, str):
            continue
        entries.append({"monster_id": monster_id, "count": count, "name": name})
    return entries
