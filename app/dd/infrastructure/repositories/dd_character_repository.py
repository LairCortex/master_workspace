"""The module's character-extension repository (add-dnd-game-face task 8.1).

Same discipline as every kernel repository: it moves rows, it never commits
— the transaction finish belongs to the service through
``GameSessionUoW.transaction()`` (coding principle 3). The ORM classes stay
inside this function's returns only insofar as the service needs them; the
domain mappers below are the door the service actually reads through.
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dd.domain.character import (
    LINK_SLOTS,
    DdCharacterExt,
    DdFeatLink,
    DdSpellLink,
    ReferenceLink,
    empty_ext,
)
from app.dd.domain.character_mechanics import (
    ABILITY_KEYS,
    CharacterMechanics,
    empty_mechanics,
)
from app.dd.infrastructure.db.dd_models import (
    DdCharacterExtModel,
    DdCharacterFeatLinkModel,
    DdCharacterSpellLinkModel,
    decode_proficiencies,
    decode_spell_slots,
    encode_proficiencies,
    encode_spell_slots,
)


def ext_to_domain(row: DdCharacterExtModel | None) -> DdCharacterExt:
    """Row → value; ``None`` (no row yet) reads as the empty face."""
    if row is None:
        return empty_ext()
    links = {
        slot: ReferenceLink(
            source_key=getattr(row, f"{slot}_source_key") or "",
            ref_id=getattr(row, f"{slot}_ref_id") or "",
            snapshot_name=getattr(row, f"{slot}_snapshot_name") or "",
        )
        for slot, _, _ in LINK_SLOTS
    }
    return DdCharacterExt(links=links, level=row.level, lss_sheet_id=row.lss_sheet_id or "")


def mechanics_from_row(row: DdCharacterExtModel | None) -> CharacterMechanics:
    """Row → the mechanics value (dd-card-redesign task 2.3). ``None`` (no
    row yet) reads as the empty block. The six ability columns are the
    spec's all-or-nothing set: unless ALL six carry a value the block reads
    as no set — «частичный набор не показывает полусчитанных строк» (a
    half-written row can only be storage corruption; the service never
    writes one). The JSON columns decode through the module codecs."""
    if row is None:
        return empty_mechanics()
    values = {key: getattr(row, key) for key in ABILITY_KEYS}
    scores = values if all(value is not None for value in values.values()) else None
    skill_profs, saving_throw_profs = decode_proficiencies(row.prof_json)
    return CharacterMechanics(
        scores=scores,
        speed=row.speed,
        alignment=row.alignment,
        spell_slots=decode_spell_slots(row.slots_json),
        skill_proficiencies=skill_profs,
        manual_saving_throws=saving_throw_profs,
    )


class DdCharacterRepository:
    """Row face of ``dd_character_ext`` / ``dd_character_spell_link``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_ext(self, character_id: int) -> DdCharacterExtModel | None:
        return await self._session.get(DdCharacterExtModel, character_id)

    async def insert_ext(self, character_id: int) -> DdCharacterExtModel:
        """The row appears on the first write (PK = FK: one face per
        character); flush only — the service's transaction commits."""
        row = DdCharacterExtModel(character_id=character_id)
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_spell_links(self, character_id: int) -> list[DdSpellLink]:
        rows = (
            await self._session.execute(
                select(DdCharacterSpellLinkModel)
                .where(DdCharacterSpellLinkModel.character_id == character_id)
                .order_by(DdCharacterSpellLinkModel.id)
            )
        ).scalars().all()
        return [
            DdSpellLink(
                source_key=row.source_key,
                slug=row.slug,
                snapshot_name=row.snapshot_name,
            )
            for row in rows
        ]

    async def has_spell_link(
        self, character_id: int, source_key: str, slug: str
    ) -> bool:
        row = (
            await self._session.execute(
                select(DdCharacterSpellLinkModel)
                .where(
                    DdCharacterSpellLinkModel.character_id == character_id,
                    DdCharacterSpellLinkModel.source_key == source_key,
                    DdCharacterSpellLinkModel.slug == slug,
                )
                .limit(1)
            )
        ).scalars().first()
        return row is not None

    async def insert_spell_link(
        self, character_id: int, source_key: str, slug: str, snapshot_name: str
    ) -> None:
        self._session.add(
            DdCharacterSpellLinkModel(
                character_id=character_id,
                source_key=source_key,
                slug=slug,
                snapshot_name=snapshot_name,
            )
        )
        await self._session.flush()

    async def delete_spell_link(
        self, character_id: int, source_key: str, slug: str
    ) -> None:
        await self._session.execute(
            delete(DdCharacterSpellLinkModel).where(
                DdCharacterSpellLinkModel.character_id == character_id,
                DdCharacterSpellLinkModel.source_key == source_key,
                DdCharacterSpellLinkModel.slug == slug,
            )
        )

    # ── the mechanics columns (dd-card-redesign task 2.3, design Д6/Д8) ─────

    def write_spell_slots(
        self, row: DdCharacterExtModel, slots: dict[int, int] | None
    ) -> None:
        """Encode through the module codec at the storage boundary (the
        application layer never imports the ORM module — the codecs ride
        this repository's door). Empty stores NULL: «не задано»."""
        row.slots_json = encode_spell_slots(slots) if slots else None

    def write_proficiencies(
        self,
        row: DdCharacterExtModel,
        skills: frozenset[str],
        saving_throws: frozenset[str],
    ) -> None:
        """Store the whole prof body (skills + the manual saving-throw set)
        — design Д8 keeps the manual set in storage even while a class owns
        the saves, so a dataset swap destroys no master's choice."""
        row.prof_json = encode_proficiencies(skills, saving_throws)

    # ── feat links (dd-card-redesign task 2.3, spec «Черты — ссылки…») ──────

    async def list_feat_links(self, character_id: int) -> list[DdFeatLink]:
        rows = (
            await self._session.execute(
                select(DdCharacterFeatLinkModel)
                .where(DdCharacterFeatLinkModel.character_id == character_id)
                .order_by(DdCharacterFeatLinkModel.id)
            )
        ).scalars().all()
        return [
            DdFeatLink(
                source_key=row.source_key,
                ref_id=row.ref_id,
                snapshot_name=row.snapshot_name,
            )
            for row in rows
        ]

    async def has_feat_link(
        self, character_id: int, source_key: str, ref_id: str
    ) -> bool:
        row = (
            await self._session.execute(
                select(DdCharacterFeatLinkModel)
                .where(
                    DdCharacterFeatLinkModel.character_id == character_id,
                    DdCharacterFeatLinkModel.source_key == source_key,
                    DdCharacterFeatLinkModel.ref_id == ref_id,
                )
                .limit(1)
            )
        ).scalars().first()
        return row is not None

    async def insert_feat_link(
        self, character_id: int, source_key: str, ref_id: str, snapshot_name: str
    ) -> None:
        self._session.add(
            DdCharacterFeatLinkModel(
                character_id=character_id,
                source_key=source_key,
                ref_id=ref_id,
                snapshot_name=snapshot_name,
            )
        )
        await self._session.flush()

    async def delete_feat_link(
        self, character_id: int, source_key: str, ref_id: str
    ) -> None:
        await self._session.execute(
            delete(DdCharacterFeatLinkModel).where(
                DdCharacterFeatLinkModel.character_id == character_id,
                DdCharacterFeatLinkModel.source_key == source_key,
                DdCharacterFeatLinkModel.ref_id == ref_id,
            )
        )

    async def delete_all_feat_links(self, character_id: int) -> None:
        """Take the whole feat wall down (dd-card-redesign task 6.1): the
        import replaces the card with the file's contents, and the feats are
        the file's to name — the rows it does not speak are un-chosen in the
        same one transaction the rest of the replacement rides."""
        await self._session.execute(
            delete(DdCharacterFeatLinkModel).where(
                DdCharacterFeatLinkModel.character_id == character_id
            )
        )
