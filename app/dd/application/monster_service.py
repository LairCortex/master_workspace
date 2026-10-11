"""The bestiary service (add-dnd-game-face task 10.1; spec dnd-bestiary).

The single door over ``dd_monster``. It owns the domain rules (the name and
rating gates run BEFORE the unit opens — a refused value never touches a row)
and the one transaction finish every write of the game shares (coding
principle 3). The picture rides the kernel's image store (design Д6
«image_id→images»): ingest goes through ``ImageStore.store`` (dedup, files,
row), and the GC of a replaced or cleared picture is a post-write hook — the
kernel's own posture, files are touched only once the reference mutation
committed.

Reads are plain selects, no transaction, like every other service here.
Deletion does not exist: the product has no removal path for entities (the
module's change repeats the kernel's rule at its own floor).
"""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from app.dd.domain.monster import (
    DdMonster,
    normalize_blocks,
    normalize_name,
    validate_rating,
)
from app.dd.infrastructure.db.dd_models import encode_text_blocks
from app.dd.infrastructure.repositories.dd_monster_repository import (
    DdMonsterRepository,
    monster_to_domain,
)

if TYPE_CHECKING:
    from app.infrastructure.db.uow import GameSessionUoW
    from app.infrastructure.images.store import ImageStore

#: The row a save names no longer exists (its card stayed open over a game
#: switch): the Russian refusal the card prints, the transaction rolls back.
MONSTER_GONE_REFUSAL = "монстр больше не существует — правка не сохранена"

#: A card composed without the image store cannot accept picture bytes; the
#: refusal says what is missing instead of dropping the pick silently.
IMAGES_UNAVAILABLE_REFUSAL = (
    "хранилище картинок недоступно — изображение не сохранено"
)


class DdMonsterService:
    """Read/write face of ``dd_monster``."""

    def __init__(
        self, uow: "GameSessionUoW", image_store: "ImageStore | None" = None
    ) -> None:
        self._uow = uow
        self._images = image_store

    # ── reads (plain, no transaction) ────────────────────────────────────────

    async def list_monsters(self) -> list[DdMonster]:
        """The whole bestiary, creation order; the filter is the sheet's."""
        return [
            monster_to_domain(row)
            for row in await DdMonsterRepository(self._uow.session).list_rows()
        ]

    async def get_monster(self, monster_id: int) -> DdMonster | None:
        """One monster; ``None`` is the honest «the row is gone» answer the
        card prints as its refusal."""
        row = await DdMonsterRepository(self._uow.session).get_row(monster_id)
        return None if row is None else monster_to_domain(row)

    async def image_preview_path(self, image_id: int) -> Path | None:
        """The preview file of one stored picture (the card's thumbnail);
        ``None`` without a composed store or for a row the store does not
        have — the card then reads «нет изображения», never a broken frame."""
        if self._images is None:
            return None
        return await self._images.preview_file_path(image_id)

    # ── writes (each one transaction) ────────────────────────────────────────

    async def save_monster(
        self,
        *,
        monster_id: int | None,
        name: str,
        rating: int,
        blocks: dict[str, str],
        image_data: bytes | None = None,
        clear_image: bool = False,
    ) -> DdMonster:
        """Create (``monster_id`` is ``None``) or edit one monster — one
        transaction, one answer. The gates (name, rating, block titles) run
        before the unit opens; picture bytes go through the kernel's ingest
        door INSIDE the transaction, so a file that is not an image rolls the
        whole save back rather than half-writing the card. The replaced or
        cleared picture is collected for GC through the unit's after-write
        hook: the store counts every referrer first, and only a picture
        nobody (kernel entity, sheet, instance, monster) still holds leaves
        the disk."""
        clean_name = normalize_name(name)
        clean_rating = validate_rating(rating)
        clean_blocks = normalize_blocks(blocks)
        if image_data is not None and self._images is None:
            raise ValueError(IMAGES_UNAVAILABLE_REFUSAL)
        async with self._uow.transaction():
            repo = DdMonsterRepository(self._uow.session)
            row = None if monster_id is None else await repo.get_row(monster_id)
            if monster_id is not None and row is None:
                raise ValueError(MONSTER_GONE_REFUSAL)
            if row is None:
                row = await repo.insert_row(clean_name)
            else:
                row.name = clean_name
            row.rating = clean_rating
            row.blocks = encode_text_blocks(clean_blocks)
            old_image = row.image_id
            if image_data is not None:
                row.image_id = await self._images.store(image_data)
            elif clear_image:
                row.image_id = None
            if old_image is not None and row.image_id != old_image:
                assert self._images is not None  # an old picture implies the store composed
                self._uow.after_write(
                    partial(self._images.gc_after_commit, old_image)
                )
            return monster_to_domain(row)
