"""Источник витрины «dd_monster» (add-dnd-game-face task 10.2; spec
dnd-bestiary «Монстры всегда в выдаче»).

Синхронные двери протокола (card_source/resolve_mention) читают кэш, который
греют асинхронные (warm/search), — тесты считают и это: превью картинки
резолвится один раз и переиспользуется. Ворота видимости —Attach-дверь
фасада, НЕ рубильник справочных (специальный пин «Справочник выключен,
монстр находится» живёт на настоящем составе в
tests/test_dnd_module_lifecycle.py; здесь — дверь самого источника).
"""
from __future__ import annotations

from pathlib import Path

from app.dd.domain.monster import DdMonster
from app.dd.presentation.monster_source import MONSTER_TYPE, DndMonsterSource


class _Service:
    """Утка DdMonsterService в объёме двери источника: list + preview."""

    def __init__(self, monsters=None, previews=None) -> None:
        self.monsters = list(monsters or [])
        self.previews = dict(previews or {})
        self.list_calls = 0
        self.preview_calls: list[int] = []

    async def list_monsters(self):
        self.list_calls += 1
        return list(self.monsters)

    async def image_preview_path(self, image_id: int):
        self.preview_calls.append(image_id)
        return self.previews.get(image_id)


def _monster(mid=1, name="Гоблин", rating=1, blocks=None, image_id=None):
    return DdMonster(
        id=mid,
        name=name,
        rating=rating,
        blocks=dict(blocks or {}),
        image_id=image_id,
    )


def _attached_source(service) -> DndMonsterSource:
    source = DndMonsterSource(service)
    source.set_attached(True)
    return source


def test_descriptor_is_a_game_entity_not_a_reference():
    """Пин спеки «Монстры SHALL NOT подчиняться переключателю»: флаг
    reference — ровно тот, на который смотрит рубильник, — у монстра выключен."""
    assert MONSTER_TYPE.key == "dd_monster"
    assert MONSTER_TYPE.label == "Монстр"
    assert MONSTER_TYPE.plural_label == "Монстры"
    assert MONSTER_TYPE.reference is False


async def test_unattached_source_is_silent_everywhere():
    service = _Service([_monster()])
    source = DndMonsterSource(service)
    assert source.visible is False
    assert await source.search("") == ()
    assert source.card_source(MONSTER_TYPE.key, "1") is None
    source.set_attached(True)
    assert source.visible is True
    assert len(await source.search("")) == 1


async def test_search_matches_name_case_insensitive_and_id():
    service = _Service([_monster(1, "Гоблин"), _monster(2, "Огр")])
    source = _attached_source(service)
    assert [hit.name for hit in await source.search("гоб")] == ["Гоблин"]
    assert [hit.name for hit in await source.search("ГОБЛИН")] == ["Гоблин"]
    assert [hit.name for hit in await source.search(" 2 ")] == ["Огр"]  # id в деле
    assert await source.search("нет такого") == ()
    hit = (await source.search(""))[0]
    # одна витрина — один дом: origin пуст, строку не чем подписывать
    assert hit.origin == "" and hit.source_id == "1" and hit.key == "dd_monster"


async def test_warm_greets_the_sync_door_and_preview_is_cached_once():
    """Pin-restore зовёт SYNC card_source до всякого async-чтения; warm —
    единственная гарантия честности (protocol task 6.2). Путь превью — тоже
    кэш: одно обращение к сервису на картинку, дальше синхронная дверь."""
    service = _Service([_monster(1, "Волк", 2, {"Нрав": "Стая."}, image_id=77)],
                       previews={77: Path("/tmp/prev-77.png")})
    source = _attached_source(service)
    assert source.card_source(MONSTER_TYPE.key, "1") is None  # до warm — нет
    await source.warm()
    card = source.card_source(MONSTER_TYPE.key, "1")
    assert card is not None
    assert card.name == "Волк" and card.source_id == ""  # id печатает ядро
    assert card.picture_path == "/tmp/prev-77.png"
    # рейтинг — общий поле карточки, приезжает первым блоком; блоки мастера —
    # за ним, в порядке заведения
    assert card.blocks[0].title == "Рейтинг" and card.blocks[0].text == "2"
    assert (card.blocks[1].title, card.blocks[1].text) == ("Нрав", "Стая.")
    assert source.card_source(MONSTER_TYPE.key, "1") is not None
    assert service.preview_calls == [77]  # не повторно: путь из кэша


async def test_card_door_refuses_foreign_key_broken_id_and_missing_row():
    service = _Service([_monster(1)])
    source = _attached_source(service)
    await source.warm()
    assert source.card_source("dd_spell", "1") is None
    assert source.card_source(MONSTER_TYPE.key, "не-число") is None
    assert source.card_source(MONSTER_TYPE.key, "42") is None


async def test_picture_without_a_stored_preview_reads_no_image():
    """Картинка, которой хранилище уже не отдаёт превью, — «нет изображения»,
    а не разбитая рамка: None кэшируется и больше не резолвится."""
    service = _Service([_monster(1, image_id=5)], previews={})
    source = _attached_source(service)
    await source.warm()
    card = source.card_source(MONSTER_TYPE.key, "1")
    assert card is not None and card.picture_path is None
    await source.warm()
    assert service.preview_calls == [5]


async def test_mention_doors_delegate_and_extra_doors_are_empty():
    service = _Service([_monster(1, "Огр")])
    source = _attached_source(service)
    candidates = await source.mention_candidates("огр")
    assert [hit.name for hit in candidates] == ["Огр"]
    assert source.resolve_mention(MONSTER_TYPE.key, "1") == source.card_source(
        MONSTER_TYPE.key, "1"
    )
    assert source.resolve_mention(MONSTER_TYPE.key, "99") is None
    from app.dd.presentation.monster_source import CardTabTarget

    assert source.card_tabs(CardTabTarget(MONSTER_TYPE.key, "1")) == ()
    assert source.event_marks([1, 2]) == {}
    assert source.type_descriptors == (MONSTER_TYPE,)
