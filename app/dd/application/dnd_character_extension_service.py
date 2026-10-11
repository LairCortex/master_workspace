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

from app.dd.domain.character import (
    DdCharacterExt,
    DdSpellLink,
    ReferenceLink,
    validate_level,
)
from app.dd.infrastructure.repositories.dd_character_repository import (
    DdCharacterRepository,
    ext_to_domain,
)
from app.infrastructure.db.uow import GameSessionUoW


class DndCharacterExtensionService:
    """Read/write face of ``dd_character_ext`` / ``dd_character_spell_link``."""

    def __init__(self, uow: GameSessionUoW) -> None:
        self._uow = uow

    # ── reads (plain, no transaction) ────────────────────────────────────────

    async def get_ext(self, character_id: int) -> DdCharacterExt:
        """The character's D&D face; a character with no row (never edited,
        or an ordinary game's row that never gained one) reads empty."""
        return ext_to_domain(
            await DdCharacterRepository(self._uow.session).get_ext(character_id)
        )

    async def get_spell_links(self, character_id: int) -> list[DdSpellLink]:
        return await DdCharacterRepository(self._uow.session).list_spell_links(
            character_id
        )

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
