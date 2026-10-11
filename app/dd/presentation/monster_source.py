"""The bestiary source of the game showcase (add-dnd-game-face task 10.2).

The monster is the game's OWN entity (spec dnd-bestiary «Монстр — сущность
игры»): its records surface through the same generic doors as the reference
records — search rows, mention candidates, the read-only preview card, pins —
but the reference toggle NEVER touches them (spec «Монстры всегда в выдаче»:
the switch decides the dataset shelves, this source is not one of them). The
visibility the source carries is its own and thinner: the module-lifetime
gate (the façade's ``set_attached`` door, the character-tab source's
posture) — while the module is off its records are hidden data, exactly like
its card tabs.

The list is small by product shape (hand-written monsters, no SRD import —
spec bars it), so the source caches the whole bestiary: the async doors
(``warm``/``search``) reconcile the cache from the service, the SYNC doors
(``card_source``/``resolve_mention``) answer from it — the protocol's pin
restore calls the sync door before any async read, and ``warm`` at game open
is what makes that honest (protocol task 6.2). Preview file paths are cached
per image id too: resolving a preview is async, a card asks the sync door.

Nothing registers here: the composition root alone calls ``register_external``
with the descriptors this source declares (guard
tests/test_dd_module_isolation.py rule 3).
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.dd.domain.monster import DdMonster
from app.domain.entity_registry import ExternalTypeDescriptor
from app.presentation.modules.protocol import (
    CardTabSpec,
    CardTabTarget,
    ExternalCardSource,
    ExternalHit,
    ExternalTextBlock,
)

if TYPE_CHECKING:
    from app.dd.application.monster_service import DdMonsterService

#: The bestiary type (design Д6): the module's own card entity in the
#  kernel's generic surfaces. ``reference`` stays False — the lookup-record
#:  flag is what the search toggle consults (spec «переключатель… монстров
#:  не касается»), a monster is not a lookup record. The glyph is a plain
#:  icons.js key: the kernel's characteristic glyphs stay untouched (guard
#:  tests/presentation/test_entity_icons.py, second-type-dictionary bar).
MONSTER_TYPE = ExternalTypeDescriptor("dd_monster", "Монстр", "Монстры", "eye")

#: The preview card's leading block: the rating is one of the three common
#: card fields (spec «общие поля карточки») and the preview assembles no
#: widget of its own — the number rides the block list, ahead of the user's
#: named blocks. A user block that happens to be titled «Рейтинг» too simply
#: follows; the protocol's block tuple allows repeated titles.
_RATING_BLOCK_TITLE = "Рейтинг"


class DndMonsterSource:
    """The ``dd_monster`` type, surfaced from the game's bestiary table."""

    def __init__(self, service: "DdMonsterService") -> None:
        self._service = service
        # Module-lifetime gate (façade's set_attached door): a detached
        # module's records are hidden data, not missing data — the sync and
        # async doors alike answer the empty posture below.
        self._attached = False
        self._monsters: list[DdMonster] = []
        # image id → preview file path (str) or None — resolved through the
        # service's async door, read by the sync card door.
        self._preview_paths: dict[int, str | None] = {}
        self._by_id: dict[int, DdMonster] = {}

    # ── protocol face ─────────────────────────────────────────────────────────

    @property
    def type_descriptors(self) -> tuple[ExternalTypeDescriptor, ...]:
        """The one declared type (registration happens at the composition)."""
        return (MONSTER_TYPE,)

    @property
    def visible(self) -> bool:
        """While the module is attached (protocol: the source owns its own
        condition; the reference toggle is NOT consulted — spec scenario
        «Справочник выключен, монстр находится»)."""
        return self._attached

    def set_attached(self, attached: bool) -> None:
        """The façade's module-lifetime door (the character-tab source's
        duck; the façade owns it because only its attach/detach pair knows
        when the module joins and leaves the live composition)."""
        self._attached = attached

    async def warm(self) -> None:
        """Reconcile the cache (protocol task 6.2): the pin restore calls the
        sync card door before any surface performed an async read, so the
        bestiary is brought current here — a whole-table select of a
        hand-written list is cheap by product shape (repo docstring)."""
        await self._refresh()

    async def search(self, query: str) -> tuple[ExternalHit, ...]:
        """Substring match over monster names (the search group's rows), the
        attachment gate consulted at the door — a surface forgetting the
        ``visible`` check still gets the honest empty answer. The id prints
        in the needle comparison too: «монстр 12» finding row 12 is the same
        courtesy the reference search gives its entry ids."""
        if not self._attached:
            return ()
        await self._refresh()
        needle = query.strip().lower()
        return tuple(
            ExternalHit(
                key=MONSTER_TYPE.key,
                source_id=str(monster.id),
                name=monster.name,
                # One visible home — the game itself (the protocol's empty
                # origin paints no label; unlike dataset records a monster
                # has no shelf to be signed with).
                origin="",
            )
            for monster in self._monsters
            if not needle
            or needle in monster.name.lower()
            or needle in str(monster.id)
        )

    def card_source(self, key: str, source_id: str) -> ExternalCardSource | None:
        """The read-only card from the cache (the protocol's sync door):
        foreign key, unparseable id, hidden module and a monster the cache
        does not hold all answer ``None`` — the same unavailable posture the
        reference source keeps for a vanished dataset record."""
        if not self._attached or key != MONSTER_TYPE.key:
            return None
        try:
            monster_id = int(source_id)
        except ValueError:
            return None
        monster = self._by_id.get(monster_id)
        if monster is None:
            return None
        picture = (
            self._preview_paths.get(monster.image_id)
            if monster.image_id is not None
            else None
        )
        blocks = [ExternalTextBlock(_RATING_BLOCK_TITLE, str(monster.rating))]
        blocks.extend(ExternalTextBlock(title, text) for title, text in monster.blocks.items())
        return ExternalCardSource(
            name=monster.name,
            origin="",
            blocks=tuple(blocks),
            picture_path=picture,
        )

    async def mention_candidates(self, query: str) -> tuple[ExternalHit, ...]:
        """The @-popup candidates — the search's answer, gate included."""
        return await self.search(query)

    def resolve_mention(self, key: str, source_id: str) -> ExternalCardSource | None:
        """An activated mention's card — the very card ``card_source``
        assembles; a monster deleted… (the product has no removal path, but
        a cache older than the row's last save answers ``None`` honestly for
        the existing «Упоминание не найдено» channel)."""
        return self.card_source(key, source_id)

    def card_tabs(self, target: CardTabTarget) -> tuple[CardTabSpec, ...]:
        """No additional tabs: the monster's own card is the module's sheet,
        not a tab on somebody else's card."""
        return ()

    def event_marks(self, event_ids: Sequence[int]) -> dict[int, str]:
        """No ladder marks (encounters are group 11's affair)."""
        return {}

    # ── cache ─────────────────────────────────────────────────────────────────

    async def _refresh(self) -> None:
        """Whole-table read + preview resolution for the pictures the kernel
        store can show. An image the store no longer has resolves to ``None``
        once and stays cached (the card then reads «нет изображения», never
        a broken frame)."""
        self._monsters = await self._service.list_monsters()
        self._by_id = {monster.id: monster for monster in self._monsters}
        for monster in self._monsters:
            if monster.image_id is None or monster.image_id in self._preview_paths:
                continue
            path = await self._service.image_preview_path(monster.image_id)
            self._preview_paths[monster.image_id] = None if path is None else str(path)
