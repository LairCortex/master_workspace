"""Словарь слогов из подключённых гримуаров (add-dnd-game-face, task 4.3;
design Д5/Д8; spec dnd-grimoire-import «Слаги гримуаров расширяют словарь
валидатора»).

Дверь чтения вместо диска: порядок подключения, внутри файла — порядок записей,
повторы схлопнуты; пропавший файл, неразбираемые байты и документ без заклинаний
не добавляют НИЧЕГО (голос сломанного гримуара — его отчёт импорта, а не этот
читатель). Пустой список связей — пустой ответ без обращения к диску.
"""
from __future__ import annotations

import json

from app.dd.application.grimoire_connections_service import (
    GrimoireConnectionsService,
)
from app.dd.application.grimoire_index_service import GrimoireIndexService
from app.dd.infrastructure.grimoire_storage import GrimoireStorage


class _Stack:
    """Тройка одной игры: полка, список её связей и дверь чтения над ними."""

    def __init__(self, uow, tmp_path) -> None:
        self.storage = GrimoireStorage(tmp_path / "grimoires")
        self.connections = GrimoireConnectionsService(uow, self.storage)
        self.index = GrimoireIndexService(self.connections, self.storage)

    def save(self, grimoire_id: str, document) -> None:
        self.storage.save(grimoire_id, json.dumps(document, ensure_ascii=False))

    async def connect(self, *grimoire_ids: str) -> None:
        for grimoire_id in grimoire_ids:
            await self.connections.connect(grimoire_id)


async def test_no_connections_is_an_empty_answer(uow, tmp_path):
    """Ни одного подключённого гримуара — пустой словарь и ни одного обращения
    к каталогу (ленивость Д4: каталога как будто нет)."""
    stack = _Stack(uow, tmp_path)

    assert await stack.index.spell_slugs() == ()
    assert not stack.storage.root.exists()


async def test_slugs_follow_connection_order_then_file_order(uow, tmp_path):
    """Порядок словаря: сначала связи в порядке подключения, внутри файла —
    порядок записей; повторы схлопнуты (словарь отвечает лишь «известен ли
    слаг?»)."""
    stack = _Stack(uow, tmp_path)
    stack.save(
        "second",
        [
            {"name": "Дым", "slug": "smoke"},
            {"name": "Дым второй", "slug": "smoke"},  # дубль того же файла
            {"name": "Тихий знак", "slug": "quiet-sign"},
        ],
    )
    stack.save(
        "first",
        {"name": "Первый", "items": [{"name": "Лунный питомец", "slug": "moon-pet"}]},
    )

    await stack.connect("second", "first")

    assert await stack.index.spell_slugs() == ("smoke", "quiet-sign", "moon-pet")


async def test_broken_and_missing_grimoires_contribute_nothing(uow, tmp_path):
    """Пропавший id, битые байты и документ без заклинаний не роняют словарь и
    не добавляют в него мусора — здоровый гримуар отдаёт своё."""
    stack = _Stack(uow, tmp_path)
    stack.storage.save("broken", "{ это не json")
    stack.save("featsonly", [{"type": "feat", "name": "Подвиг"}])
    stack.save("healthy", [{"name": "Лунный питомец", "slug": "moon-pet"}])

    await stack.connect("vanished", "broken", "featsonly", "healthy")

    assert await stack.index.spell_slugs() == ("moon-pet",)


# ── task 6.1: снимок целых записей (двери карточек/поиска) ────────────────────


async def test_snapshot_carries_records_titles_and_sync_door(uow, tmp_path):
    """Снимок — slug → запись с именем и plain-text описанием, заголовок из
    документа, адрес пары через spell(); sync-дверь отдаёт последний снимок
    без перестройки; повторы слага схлопнуты в пользу первой записи."""
    stack = _Stack(uow, tmp_path)
    stack.save(
        "home",
        {
            "name": "Домашний",
            "items": [
                {
                    "name": "Истинное зрение",
                    "slug": "true-sight",
                    "system": {"description": {"value": "<p>Видеть&nbsp;сквозь</p>"}},
                },
                {"name": "Первый дубль", "slug": "dup"},
                {"name": "Второй дубль", "slug": "dup"},
            ],
        },
    )
    await stack.connect("home")

    snap = await stack.index.snapshot()
    assert snap.ids == ("home",)
    assert snap.titles == {"home": "Домашний"}
    spell = snap.spell("home", "true-sight")
    assert spell is not None and spell.name == "Истинное зрение"
    assert spell.description == "Видеть сквозь"
    assert snap.spell("home", "dup").name == "Первый дубль"
    assert snap.spell("home", "nope") is None
    assert snap.spell("other", "true-sight") is None
    # sync-дверь — тот же снимок без await
    assert stack.index.snapshot_now() is snap


async def test_snapshot_reconciles_edits_and_disconnections(uow, tmp_path):
    """Порядок Д5: правка файла между чтениями переразбирается по digest,
    отключение убирает гримуар из снимка при следующем async-чтении; sync-дверь
    до этого чтенияstill отдаёт старый снимок — честное зеркало перестройки."""
    stack = _Stack(uow, tmp_path)
    stack.save("home", [{"name": "Дым", "slug": "smoke"}])
    await stack.connect("home")
    assert (await stack.index.snapshot()).spell("home", "smoke").name == "Дым"

    stack.save("home", [{"name": "Густой дым", "slug": "smoke"}])
    snap = await stack.index.snapshot()
    assert snap.spell("home", "smoke").name == "Густой дым"
    # digest не двигался — повторное чтение не переразбирает (кэш цел)
    assert stack.index.snapshot_now().spell("home", "smoke").name == "Густой дым"

    await stack.connections.disconnect("home")
    snap = await stack.index.snapshot()
    assert snap.ids == () and snap.spell("home", "smoke") is None


async def test_unsafe_stored_id_reads_as_vanished(uow, tmp_path):
    """Битый/ручной id в списке связей: файла под таким именем быть не может
    — тот же пропавший гримуар, молча и без raise (protocol warm)."""
    stack = _Stack(uow, tmp_path)
    stack.save("healthy", [{"name": "Лунный питомец", "slug": "moon-pet"}])
    await stack.connect("хом-пак", "healthy")

    snap = await stack.index.snapshot()
    assert snap.ids == ("healthy",)
    assert snap.spell("хом-пак", "moon-pet") is None
