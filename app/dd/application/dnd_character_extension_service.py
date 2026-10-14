"""The D&D character-extension service (add-dnd-game-face task 8.1, design Д6;
spec dnd-character-extension).

The module's face of a character travels through this one door. It owns the
domain rules (the 1…20 level gate, the one-row-per-character upsert, the
idempotent spell-link add/remove) and the transaction finish: every write is
exactly one ``GameSessionUoW.transaction()`` — the same single finish point
every other write of the game shares (coding principle 3). Reads are plain
selects, no transaction, matching the kernel's read discipline.

The service NEVER reads a dataset: it stores whatever triple it is handed.
What a disconnected source means is the tab's reading rule (the snapshot
survives untouched); the service only knows the value is there to keep.
"""
from __future__ import annotations

from typing import Collection, Mapping, Sequence

from app.dd.domain.character import (
    DdCharacterExt,
    DdFeatLink,
    DdSpellLink,
    ReferenceLink,
    validate_level,
)
from app.dd.domain.character_mechanics import (
    ABILITY_KEYS,
    CharacterMechanics,
    resolve_saving_throw_profs,
    validate_ability_scores,
    validate_alignment,
    validate_saving_throw_keys,
    validate_skill_keys,
    validate_spell_slots,
)
from app.dd.infrastructure.db.dd_models import (
    decode_text_blocks,
    encode_text_blocks,
)
from app.dd.infrastructure.repositories.dd_character_repository import (
    DdCharacterRepository,
    ext_to_domain,
    mechanics_from_row,
)
from app.infrastructure.db.uow import GameSessionUoW

#: Russian refusal of a nameless block (the module's message posture).
TEXT_BLOCK_KEY_REFUSAL = "имя текстового блока персонажа не может быть пустым"


class DndCharacterExtensionService:
    """Read/write face of ``dd_character_ext`` / ``dd_character_spell_link``
    / ``dd_character_feat_link`` (the feat links and the mechanics columns
    joined in dd-card-redesign task 2.3, design Д6/Д8)."""

    def __init__(self, uow: GameSessionUoW) -> None:
        self._uow = uow

    # ── reads (plain, no transaction) ────────────────────────────────────────

    async def get_ext(self, character_id: int) -> DdCharacterExt:
        """The character's D&D face; a character with no row (never edited,
        or an ordinary game's row that never gained one) reads empty."""
        return ext_to_domain(
            await DdCharacterRepository(self._uow.session).get_ext(character_id)
        )

    async def ensure_ext(self, character_id: int) -> None:
        """Stand the extension row up for a freshly created character
        (dd-card-redesign, checkpoint-2 audit; spec «Новая карточка с
        пустыми разделами» — «сохранение создаёт персонажа и расширение»).
        An existing row is left exactly as it was — the door is idempotent."""
        async with self._uow.transaction():
            repo = DdCharacterRepository(self._uow.session)
            if await repo.get_ext(character_id) is None:
                await repo.insert_ext(character_id)

    async def get_spell_links(self, character_id: int) -> list[DdSpellLink]:
        return await DdCharacterRepository(self._uow.session).list_spell_links(
            character_id
        )

    async def get_mechanics(self, character_id: int) -> CharacterMechanics:
        """The structured mechanics block (dd-card-redesign, spec
        dnd-character-mechanics); a character with no row — or a row that
        predates the mechanics columns — reads as the empty value, the card
        opens with nothing but empty fields."""
        return mechanics_from_row(
            await DdCharacterRepository(self._uow.session).get_ext(character_id)
        )

    async def get_feat_links(self, character_id: int) -> list[DdFeatLink]:
        return await DdCharacterRepository(self._uow.session).list_feat_links(
            character_id
        )

    async def get_text_blocks(self, character_id: int) -> dict[str, str]:
        """The character's named text blocks (dd-card-redesign task 5.3):
        the same column the LSS importer fills and the document builder
        reads — the «Личность» fields are stable keys in it, no second
        store. An absent row or an empty column reads as the empty map."""
        row = await DdCharacterRepository(self._uow.session).get_ext(
            character_id
        )
        return decode_text_blocks(row.text_blocks if row is not None else None)

    async def get_saving_throw_profs(
        self, character_id: int, class_saves: Sequence[str] | None = None
    ) -> frozenset[str]:
        """Saving-throw ownership per design Д8: the caller hands the saves
        the connected dataset's class record names (``None``/empty when the
        class is absent or its record names none) and the class's set wins;
        otherwise the master's stored manual set answers. The resolution is
        recomputed at every read and nothing here rewrites the stored
        manual set — a dataset swap therefore destroys no data (spec «Класс
        задал спасброски» / «Без класса — мастер волен»)."""
        mechanics = await self.get_mechanics(character_id)
        return resolve_saving_throw_profs(class_saves, mechanics.manual_saving_throws)

    # ── writes (each one transaction) ────────────────────────────────────────

    async def set_reference_link(
        self, character_id: int, slot: str, link: ReferenceLink
    ) -> None:
        """Store one triple verbatim (the pair plus the snapshot the tab
        captured). A disconnected source's triple is stored exactly like a
        live one — nothing here re-resolves or clears it (spec «Снятый
        датасет не калечит карточку»)."""
        async with self._uow.transaction():
            repo = DdCharacterRepository(self._uow.session)
            row = await repo.get_ext(character_id) or await repo.insert_ext(character_id)
            setattr(row, f"{slot}_source_key", link.source_key)
            setattr(row, f"{slot}_ref_id", link.ref_id)
            setattr(row, f"{slot}_snapshot_name", link.snapshot_name)

    async def set_level(self, character_id: int, level: int | None) -> None:
        """The 1…20 gate runs before any row is touched: a refused value
        leaves the row (and the flag of the operation) exactly as it was."""
        validated = validate_level(level)
        async with self._uow.transaction():
            repo = DdCharacterRepository(self._uow.session)
            row = await repo.get_ext(character_id) or await repo.insert_ext(character_id)
            row.level = validated

    async def set_lss_sheet_id(self, character_id: int, sheet_id: str) -> None:
        """Empty string stores NULL: «no sheet» is one stored fact, and the
        tab hides «Открыть в браузере» while it is empty."""
        async with self._uow.transaction():
            repo = DdCharacterRepository(self._uow.session)
            row = await repo.get_ext(character_id) or await repo.insert_ext(character_id)
            row.lss_sheet_id = sheet_id or None

    async def add_spell_link(
        self, character_id: int, link: DdSpellLink
    ) -> None:
        """Bind a spell — reference, never a text copy. Adding a pair that
        is already bound is a no-op (no duplicate row, no second write)."""
        async with self._uow.transaction():
            repo = DdCharacterRepository(self._uow.session)
            if await repo.has_spell_link(character_id, link.source_key, link.slug):
                return
            await repo.insert_spell_link(
                character_id, link.source_key, link.slug, link.snapshot_name
            )

    async def remove_spell_link(
        self, character_id: int, source_key: str, slug: str
    ) -> None:
        """Unbind a spell (spec scenario «снятая и сохранённая привязка
        пропадает»); removing an absent pair is a no-op."""
        async with self._uow.transaction():
            await DdCharacterRepository(self._uow.session).delete_spell_link(
                character_id, source_key, slug
            )

    # ── mechanics writes (dd-card-redesign task 2.3, design Д6/Д8) ──────────

    async def set_ability_scores(
        self, character_id: int, scores: Mapping[str, int] | None
    ) -> None:
        """The six ability values, all-or-nothing (spec «Непустой набор шести
        значений SHALL храниться целиком или не храниться вовсе»): the domain
        gate runs before the row is touched, a partial or out-of-band set is
        refused with the Russian sentence and changes nothing; ``None`` (or
        an empty mapping) clears all six columns back to «не задано»."""
        validated = validate_ability_scores(scores)
        async with self._uow.transaction():
            repo = DdCharacterRepository(self._uow.session)
            row = await repo.get_ext(character_id) or await repo.insert_ext(character_id)
            for key in ABILITY_KEYS:
                setattr(row, key, None if validated is None else validated[key])

    async def set_speed(self, character_id: int, speed: int | None) -> None:
        """Speed in feet — the master's own number (the tab prefills 30,
        the import fills what the document carries); ``None`` stores the
        honest absence. Jumps and carry are computed from the STRENGTH value
        and never read this column (spec «от скорости НЕ SHALL зависеть»)."""
        async with self._uow.transaction():
            repo = DdCharacterRepository(self._uow.session)
            row = await repo.get_ext(character_id) or await repo.insert_ext(character_id)
            row.speed = speed

    async def set_alignment(self, character_id: int, alignment: str | None) -> None:
        """One of the fixed nine (spec «Девять мировоззрений и „не задано“»,
        «ручного ввода нет» — anything else is refused before the row)."""
        validated = validate_alignment(alignment)
        async with self._uow.transaction():
            repo = DdCharacterRepository(self._uow.session)
            row = await repo.get_ext(character_id) or await repo.insert_ext(character_id)
            row.alignment = validated

    async def set_spell_slots(
        self, character_id: int, slots: Mapping[int, int] | None
    ) -> None:
        """The slots grid (levels 1…9, counts 0…99): the domain gate runs
        before the row; an empty mapping stores NULL — «не задано»."""
        validated = validate_spell_slots(slots)
        async with self._uow.transaction():
            repo = DdCharacterRepository(self._uow.session)
            row = await repo.get_ext(character_id) or await repo.insert_ext(character_id)
            repo.write_spell_slots(row, validated)

    async def set_skill_proficiencies(
        self, character_id: int, skills: Collection[str]
    ) -> None:
        """Replace the skill-proficiency set (the circles under each ability,
        spec «владение каждым SHALL переключаться кружком-переключателем»);
        the manual saving-throw half of the stored body survives untouched."""
        validated = validate_skill_keys(skills)
        async with self._uow.transaction():
            repo = DdCharacterRepository(self._uow.session)
            row = await repo.get_ext(character_id) or await repo.insert_ext(character_id)
            current = mechanics_from_row(row)
            repo.write_proficiencies(row, validated, current.manual_saving_throws)

    async def set_saving_throw_proficiencies(
        self, character_id: int, saving_throws: Collection[str]
    ) -> None:
        """Replace the manual saving-throw set (design Д8's stored manual
        half — read it back through :meth:`get_saving_throw_profs`, which
        lets the class record win when it names its saves); the skill half
        survives untouched."""
        validated = validate_saving_throw_keys(saving_throws)
        async with self._uow.transaction():
            repo = DdCharacterRepository(self._uow.session)
            row = await repo.get_ext(character_id) or await repo.insert_ext(character_id)
            current = mechanics_from_row(row)
            repo.write_proficiencies(row, current.skill_proficiencies, validated)

    # ── feat links (spec «Черты — ссылки на записи датасетов») ───────────────

    async def add_feat_link(self, character_id: int, link: DdFeatLink) -> None:
        """Choose a feat — a reference into a connected dataset's record,
        never a text copy. Adding a pair that is already chosen is a no-op
        (the spell link's idempotence, the same «пара = идентичность»)."""
        async with self._uow.transaction():
            repo = DdCharacterRepository(self._uow.session)
            if await repo.has_feat_link(character_id, link.source_key, link.ref_id):
                return
            await repo.insert_feat_link(
                character_id, link.source_key, link.ref_id, link.snapshot_name
            )

    async def remove_feat_link(
        self, character_id: int, source_key: str, ref_id: str
    ) -> None:
        """Unchoose a feat; removing an absent pair is a no-op. The snapshot
        of a feat whose DATASET was disconnected is kept verbatim (spec
        «Датасет сняли — имена целы»): only an explicit removal erases a
        row, nothing here re-resolves sources."""
        async with self._uow.transaction():
            await DdCharacterRepository(self._uow.session).delete_feat_link(
                character_id, source_key, ref_id
            )

    # ── text blocks (dd-card-redesign task 5.3, design Д6: «Личность» rides
    # the existing named-blocks column — stable keys, no second store) ───────

    async def set_text_block(self, character_id: int, key: str, text: str) -> None:
        """Upsert one named block: empty text removes the key, an emptied
        map stores NULL (the honest absence the codecs already speak). The
        other blocks ride through untouched — one key, one transaction,
        never a wholesale rewrite of the column from half a frame."""
        name = key.strip()
        if not name:
            raise ValueError(TEXT_BLOCK_KEY_REFUSAL)
        async with self._uow.transaction():
            repo = DdCharacterRepository(self._uow.session)
            row = await repo.get_ext(character_id) or await repo.insert_ext(character_id)
            blocks = decode_text_blocks(row.text_blocks)
            if text == "":
                blocks.pop(name, None)
            else:
                blocks[name] = text
            row.text_blocks = encode_text_blocks(blocks) if blocks else None
