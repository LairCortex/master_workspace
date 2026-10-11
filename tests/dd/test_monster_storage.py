"""Бестиарий под виджетом (add-dnd-game-face task 10.1; spec dnd-bestiary).

Три этажа, как в test_character_extension:

* домен — ворота имени и рейтинга с русскими отказами, нормализация блоков
  (заголовок срежется, безымянный выпадает, одинаковые сворачиваются);
* репозиторий + сервис на общём тестовом unit-of-work: монстр появляется
  первым сохранением, правка живёт в тех же строках, отказ не трогает ни
  одной строки, картинка входит через дверь хранилища ядра, а старая/убранная
  картинка уезжает в GC пост-хуком транзакции;
* бутстрап Д6 — волна ``ensure_dd_tables`` добавляет и ``dd_monster``.

Хранилище картинок тут утка: сервис зовёт ровно три её двери (store,
preview_file_path, gc_after_commit), и тесты считают именно вызовы — что
постановка картинки в строку и сборка старой картинки идут через ядро, а не
мимо него. Сквозная GC-правда двери ``add_referring_model`` (картинка
монстра не собираема) закреплена в tests/test_image_gc.py.
"""
from __future__ import annotations

import json

import pytest

from app.dd.application.monster_service import (
    IMAGES_UNAVAILABLE_REFUSAL,
    MONSTER_GONE_REFUSAL,
    DdMonsterService,
)
from app.dd.domain.monster import (
    NAME_REFUSAL,
    RATING_REFUSAL,
    DdMonster,
    normalize_blocks,
    normalize_name,
    validate_rating,
)
from app.dd.infrastructure.db.dd_models import DdMonsterModel, encode_text_blocks
from app.dd.infrastructure.db.dd_schema import ensure_dd_tables
from app.dd.infrastructure.repositories.dd_monster_repository import (
    DdMonsterRepository,
    monster_to_domain,
)
from app.infrastructure.db.database import create_engine as app_create_engine


# ── домен ─────────────────────────────────────────────────────────────────


def test_validate_rating_accepts_the_whole_band():
    assert validate_rating(1) == 1
    assert validate_rating(20) == 20


@pytest.mark.parametrize("bad", [0, 21, -1, True, False, 1.5, "5"])
def test_validate_rating_refuses_in_russian(bad):
    with pytest.raises(ValueError) as exc:
        validate_rating(bad)
    assert str(exc.value) == RATING_REFUSAL


def test_normalize_name_strips_and_refuses_empty():
    assert normalize_name("  Гоблин ") == "Гоблин"
    for bad in ("", "   ", "\n"):
        with pytest.raises(ValueError) as exc:
            normalize_name(bad)
        assert str(exc.value) == NAME_REFUSAL


def test_normalize_blocks_trims_drops_and_folds():
    folded = normalize_blocks(
        {
            " Броня ": "16 (естественный доспех)",
            "": "потерян — нет заголовка",
            " Атаки ": "Короткий лук.",
            "Атаки": "Дубина.",  # тот же заголовок: словарь сворачивает,
        }
    )  # последний заголовок побеждает (codec хранит словарь)
    assert folded == {
        "Броня": "16 (естественный доспех)",
        "Атаки": "Дубина.",
    }


# ── репозиторий/сервис на настоящем unit-of-work ──────────────────────────


class _FakeImages:
    """Утка ImageStore ровно в объёме двери сервиса: ingest, превью, GC."""

    def __init__(self) -> None:
        self.stored: list[bytes] = []
        self.gced: list[int] = []
        self.next_id = 90
        self.previews: dict[int, object] = {}

    async def store(self, data: bytes) -> int:
        self.stored.append(data)
        self.next_id += 1
        return self.next_id

    async def preview_file_path(self, image_id: int):
        return self.previews.get(image_id)

    async def gc_after_commit(self, *image_ids: int | None) -> None:
        self.gced.extend(i for i in image_ids if i)


async def test_list_empty_and_get_missing(uow):
    service = DdMonsterService(uow)
    assert await service.list_monsters() == []
    assert await service.get_monster(4242) is None


async def test_creation_defaults_and_stable_id(uow):
    """Первое сохранение создаёт строку с дефолтами модели (рейтинг 1, без
    блоков и картинки); имя приезжает обрезанным; id стабилен между чтениями."""
    service = DdMonsterService(uow)
    created = await service.save_monster(monster_id=None, name="  Гоблин ", rating=1, blocks={})
    assert isinstance(created, DdMonster)
    assert created.name == "Гоблин"
    assert created.rating == 1
    assert created.blocks == {}
    assert created.image_id is None
    listed = await service.list_monsters()
    assert listed == [created]
    assert (await service.get_monster(created.id)) == created
    # правка не плодит строк
    edited = await service.save_monster(
        monster_id=created.id, name="Гоблин-вождь", rating=2, blocks={"Тактика": "Стая"}
    )
    assert edited.id == created.id
    assert [m.name for m in await service.list_monsters()] == ["Гоблин-вождь"]


async def test_blocks_roundtrip_through_codec(uow):
    service = DdMonsterService(uow)
    blocks = {"Броня": "16 (натур.)", "Атаки": "Короткий лук: 1d6+3."}
    created = await service.save_monster(
        monster_id=None, name="Скелет", rating=1, blocks=blocks
    )
    assert (await service.get_monster(created.id)).blocks == blocks


async def test_corrupt_blocks_body_reads_empty(uow):
    """Codec-постуля модуля: побитый JSON читается как «нет блоков» — сервис
    не падает на чтении чужой порчи (строку писали не мы)."""
    service = DdMonsterService(uow)
    created = await service.save_monster(
        monster_id=None, name="Лич", rating=10, blocks={"Заклинания": "..."})
    row = await DdMonsterRepository(uow.session).get_row(created.id)
    row.blocks = "{не json"
    await uow.session.commit()
    assert (await service.get_monster(created.id)).blocks == {}
    # monster_to_domain жив и на прямом чтении ряда
    fresh = await DdMonsterRepository(uow.session).get_row(created.id)
    assert monster_to_domain(fresh).blocks == {}


async def test_refused_values_never_open_the_unit(uow):
    """Ворота домена стоят ДО транзакции: отказанное имя/рейтинг не создают
    ни строки, ни незакрытого юнита."""
    service = DdMonsterService(uow)
    with pytest.raises(ValueError):
        await service.save_monster(monster_id=None, name=" ", rating=1, blocks={})
    with pytest.raises(ValueError):
        await service.save_monster(monster_id=None, name="Кто-то", rating=99, blocks={})
    assert await service.list_monsters() == []


async def test_editing_a_gone_monster_refuses_and_changes_nothing(uow):
    service = DdMonsterService(uow)
    created = await service.save_monster(
        monster_id=None, name="Огр", rating=2, blocks={})
    with pytest.raises(ValueError) as exc:
        await service.save_monster(
            monster_id=created.id + 999, name="Призрак", rating=1, blocks={}
        )
    assert str(exc.value) == MONSTER_GONE_REFUSAL
    assert [m.name for m in await service.list_monsters()] == ["Огр"]


# ── картинки: дверь хранилища ядра ────────────────────────────────────────


async def test_picture_ingest_replacement_and_clear(uow, tmp_path):
    """Картинка входит настоящим ``ImageStore.store()`` внутри транзакции;
    замена и «убрать» отпускают старую пост-хуком транзакции
    (``after_write``), который юнит исполняет на её коммите — файл старой
    картинки исчезает, новой остаётся (coding principle 3: файл трогается
    только когда ссылка в строке уже уехала)."""
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    from app.infrastructure.db.models import ImageModel
    from app.infrastructure.images.paths import original_path
    from app.infrastructure.images.store import ImageStore

    def _png(color: QColor) -> bytes:
        img = QImage(24, 18, QImage.Format.Format_RGB32)
        img.fill(color)
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        return bytes(data.data())

    image_dir = tmp_path / "images"
    images = ImageStore(uow.session, image_dir)
    service = DdMonsterService(uow, image_store=images)
    first = await service.save_monster(
        monster_id=None,
        name="Волк",
        rating=1,
        blocks={},
        image_data=_png(QColor("red")),
    )
    row1 = await uow.session.get(ImageModel, first.image_id)
    path1 = original_path(image_dir, row1.sha256, row1.ext)
    assert path1.exists()
    second = await service.save_monster(
        monster_id=first.id,
        name="Волк",
        rating=1,
        blocks={},
        image_data=_png(QColor("blue")),
    )
    assert second.image_id != first.image_id
    assert not path1.exists()  # коммит замены уже отпустил старую
    row2 = await uow.session.get(ImageModel, second.image_id)
    path2 = original_path(image_dir, row2.sha256, row2.ext)
    assert path2.exists()
    cleared = await service.save_monster(
        monster_id=first.id, name="Волк", rating=1, blocks={}, clear_image=True
    )
    assert cleared.image_id is None
    assert not path2.exists()
    assert (await service.get_monster(first.id)).image_id is None


async def test_picture_bytes_without_a_store_refuse_before_the_unit(uow):
    service = DdMonsterService(uow)  # композиция без хранилища
    with pytest.raises(ValueError) as exc:
        await service.save_monster(
            monster_id=None, name="Кто-то", rating=1, blocks={}, image_data=b"png"
        )
    assert str(exc.value) == IMAGES_UNAVAILABLE_REFUSAL
    assert await service.list_monsters() == []


async def test_preview_door_passthrough(uow):
    from pathlib import Path

    service_no_store = DdMonsterService(uow)
    assert await service_no_store.image_preview_path(5) is None
    images = _FakeImages()
    images.previews[5] = Path("/tmp/prev-5.jpg")
    service = DdMonsterService(uow, image_store=images)
    assert await service.image_preview_path(5) == Path("/tmp/prev-5.jpg")
    assert await service.image_preview_path(6) is None


# ── бутстрап Д6: dd_monster в общей волне ─────────────────────────────────


async def test_dd_monster_table_is_in_the_additive_wave(tmp_path):
    """Волна ``ensure_dd_tables`` поверх схемы-без-модуля добавляет и таблицу
    монстров; вторая волна ничего не меняет, строка между волнами живёт."""
    db_path = tmp_path / "game.db"
    engine = app_create_engine(f"sqlite+aiosqlite:///{db_path}")
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.infrastructure.db.models import Base as KernelBase

    async with engine.begin() as conn:
        await conn.run_sync(KernelBase.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _wave() -> None:
        from app.infrastructure.db.uow import GameSessionUoW

        async with maker() as session:
            await ensure_dd_tables(GameSessionUoW(session))

    await _wave()
    async with engine.connect() as conn:
        names = {
            row[0]
            for row in (
                await conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            ).all()
        }
    assert "dd_monster" in names
    # строка между волнами
    async with maker() as session:
        session.add(DdMonsterModel(name="Межволновой"))
        await session.commit()
    await _wave()
    async with maker() as session:
        rows = await DdMonsterRepository(session).list_rows()
    assert [m.name for m in rows] == ["Межволновой"]
    # колонки-детали ровно как задумано Д6: рейтинг по умолчанию 1
    async with maker() as session:
        stored = await session.get(DdMonsterModel, rows[0].id)
        assert stored.rating == 1
        assert stored.image_id is None
        assert stored.blocks is None
    # JSON-кодек общий с группой 9: тело пишется им же
    assert encode_text_blocks({}) == "{}"
    assert json.loads(encode_text_blocks({"а": "б"})) == {"а": "б"}
    await engine.dispose()
