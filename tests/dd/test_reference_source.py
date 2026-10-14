"""Справочный источник модуля (add-dnd-game-face, task 3.2;
spec dnd-reference-records «шесть справочных типов», «Заклинание — слаг плюс
источник», «Одноимённые слаги из разных наборов не сливаются»).

Контур — настоящий дуэт индекс+связи поверх ``tmp_path``-хранилища и штатной
``uow`` (тест индекса даёт ему доверие), рубильник — настоящий сервис
видимости. Покрыты: состав и подписи семи описателей; пары источников
одноимённых слагов с подписью набора; поиск по всем группам и humanize
SRD-слагов; SRD-карточка заклинания — честная строка про LSS, без пустой
заглушки; гримуарные заклинания того же dd_spell-группы (task 6.1 — решение
координатора по пропуску группы 4): строки с подписью гримуара, полнотекстовая
карточка, warm-дверь для sync-чтения пинов (task 6.2); выключение
рубильника убирает и строки, и карточки; чужой ключ/кривой source_id/
несуществующая запись — None; упоминательные методы делегируют поиску и
карточке; табы и пометки лестницы — пусты до своих групп.
"""
from __future__ import annotations

import json

from app.dd.application.dataset_connections_service import (
    DatasetConnectionsService,
)
from app.dd.application.dataset_index_service import DatasetIndexService
from app.dd.application.grimoire_connections_service import (
    GrimoireConnectionsService,
)
from app.dd.application.grimoire_index_service import GrimoireIndexService
from app.dd.application.reference_visibility_service import (
    ReferenceVisibilityService,
)
from app.dd.infrastructure.grimoire_storage import GrimoireStorage
from app.dd.domain.dataset import DatasetMeta, DatasetSource
from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.dd.presentation.reference_source import (
    RECORD_TYPES,
    SRD_SPELL_TEXT_LINE,
    DndReferenceSource,
    humanize_spell_slug,
    make_source_id,
    split_source_id,
)


def _save_all(storage: DatasetStorage) -> None:
    """Один набор с записью каждого из шести типов + списки слагов двух
    редакций (призрак ``fire-ball`` — в обеих)."""
    record = lambda eid, title: {"id": eid, "label": title}  # noqa: E731
    storage.save(
        "srd51",
        json.dumps(
            {
                "id": "srd51",
                "title": "SRD 5.1 (2014)",
                "classes": [record("cleric", "Клейрик")],
                "subclasses": [record("life", "Жизнь")],
                "races": [record("elf", "Эльф")],
                "subraces": [record("high-elf", "Высший эльф")],
                "backgrounds": [record("acolyte", "Аколит")],
                "feats": [record("lucky", "Везучесть")],
            },
            ensure_ascii=False,
        ),
        DatasetMeta(
            source=DatasetSource.SRD, imported_at="2026-10-09", sha256="0" * 64
        ),
    )
    storage.save_spell_slugs("srd51", ("fire-ball", "mage-hand"))
    storage.save(
        "hb",
        json.dumps(
            {
                "id": "hb",
                "title": "Хоумбрю",
                "classes": [record("cleric", "Мой клейрик")],
                "feats": [dict(record("lucky", "Моя везучесть"), desc="Текст черте")],
            },
            ensure_ascii=False,
        ),
        DatasetMeta(
            source=DatasetSource.HOMEBREW,
            imported_at="2026-10-09",
            sha256="1" * 64,
        ),
    )
    storage.save_spell_slugs("srd52", ("fire-ball",))
    storage.save(
        "srd52",
        json.dumps({"id": "srd52", "title": "SRD 5.2 (2024)"}),
        DatasetMeta(
            source=DatasetSource.SRD, imported_at="2026-10-09", sha256="2" * 64
        ),
    )


def _home_grimoire() -> str:
    """Компендиум-обёртка с именем и двумя заклинаниями: одно с HTML-описанием
    (парсер отдаёт plain text), второе — без описания вовсе (карта честна
    пустым блоком, а не заглушкой)."""
    return json.dumps(
        {
            "id": "home-book",
            "name": "Домашний гримуар",
            "items": [
                {
                    "name": "Истинное зрение",
                    "type": "spell",
                    "system": {
                        "description": {"value": "<p>Видеть&nbsp;сквозь</p>"}
                    },
                    "flags": {"lss": {"slug": "true-sight"}},
                },
                {
                    "name": "Без текста",
                    "type": "spell",
                    "flags": {"lss": {"slug": "no-text"}},
                },
            ],
        },
        ensure_ascii=False,
    )


class _Harness:
    def __init__(self, uow, tmp_path, with_grimoire=True):
        self.storage = DatasetStorage(tmp_path / "datasets")
        _save_all(self.storage)
        self.connections = DatasetConnectionsService(uow, self.storage)
        self.index = DatasetIndexService(self.connections, self.storage)
        self.visibility = ReferenceVisibilityService(uow)
        self.grimoire_storage = GrimoireStorage(tmp_path / "grimoires")
        self.grimoire_connections = GrimoireConnectionsService(
            uow, self.grimoire_storage
        )
        self.grimoire_index = GrimoireIndexService(
            self.grimoire_connections, self.grimoire_storage
        )
        self.source = DndReferenceSource(
            self.index,
            self.visibility,
            self.grimoire_index if with_grimoire else None,
        )

    async def connect_all(self) -> None:
        for dataset_id in ("srd51", "hb", "srd52"):
            await self.connections.connect(dataset_id)

    async def connect_grimoire(self, grimoire_id="home-book", document=None) -> None:
        self.grimoire_storage.save(grimoire_id, document or _home_grimoire())
        await self.grimoire_connections.connect(grimoire_id)


async def test_seven_descriptors_parity_flags(uow, tmp_path):
    """Состав декларации: шесть типов записей + заклинания, все — reference
    ( рубильник гасит их все разом), порядок — записи затем заклинания."""
    source = _Harness(uow, tmp_path).source
    descriptors = source.type_descriptors
    # шесть типов записей живут секциями датасета, заклинания — своей
    # декларацией вне секций: в одну dd_spell-группу с task 6.1 приходят и
    # SRD-слаги, и заклинания подключённых гримуаров
    assert len(RECORD_TYPES) == 6
    assert [d.key for d in descriptors] == [
        "dd_class",
        "dd_subclass",
        "dd_race",
        "dd_subrace",
        "dd_background",
        "dd_feat",
        "dd_spell",
    ]
    assert [d.label for d in descriptors] == [
        "Класс",
        "Подкласс",
        "Вид",
        "Подвид",
        "Предыстория",
        "Черта",
        "Заклинание",
    ]
    assert all(d.reference for d in descriptors)
    assert all(d.searchable and d.mentionable and d.pinnable for d in descriptors)
    # ключ пары — слагаемые source_id (дизайн Д4): dataset/entry
    assert make_source_id("srd51", "cleric") == "srd51/cleric"
    assert split_source_id("srd51/cleric") == ("srd51", "cleric")
    # слаг SRD humanlze — механически, без выдумывания (Д7)
    assert humanize_spell_slug("fire-ball") == "Fire ball"
    assert humanize_spell_slug("mage_hand") == "Mage_hand"  # не дефис — как есть
    assert humanize_spell_slug("a") == "A"


async def test_search_covers_every_group_with_origin(uow, tmp_path):
    """Зонд по всем группам: пустой запрос находит каждую запись каждого
    подключённого набора и каждый слаг; строка подписана набором (спека
    «каждая подписана набором-источником»), одноимённые слаги — две пары."""
    harness = _Harness(uow, tmp_path)
    await harness.connect_all()
    hits = await harness.source.search("")
    by_key: dict[str, list[tuple[str, str, str]]] = {}
    for hit in hits:
        by_key.setdefault(hit.key, []).append((hit.source_id, hit.name, hit.origin))
    assert by_key["dd_class"] == [
        ("srd51/cleric", "Клейрик", "SRD 5.1 (2014)"),
        ("hb/cleric", "Мой клейрик", "Хоумбрю"),
    ]
    assert by_key["dd_subclass"] == [("srd51/life", "Жизнь", "SRD 5.1 (2014)")]
    assert by_key["dd_race"] == [("srd51/elf", "Эльф", "SRD 5.1 (2014)")]
    assert by_key["dd_subrace"] == [("srd51/high-elf", "Высший эльф", "SRD 5.1 (2014)")]
    assert by_key["dd_background"] == [("srd51/acolyte", "Аколит", "SRD 5.1 (2014)")]
    assert by_key["dd_feat"] == [
        ("srd51/lucky", "Везучесть", "SRD 5.1 (2014)"),
        ("hb/lucky", "Моя везучесть", "Хоумбрю"),
    ]
    # призрак в двух редакциях — две сущности разных источников (спека)
    assert by_key["dd_spell"] == [
        ("srd51/fire-ball", "Fire ball", "SRD 5.1 (2014)"),
        ("srd51/mage-hand", "Mage hand", "SRD 5.1 (2014)"),
        ("srd52/fire-ball", "Fire ball", "SRD 5.2 (2024)"),
    ]
    # подстрока имени и слага, регистронезависимо
    found = await harness.source.search("КЛЕЙРИК")
    assert [h.source_id for h in found] == ["srd51/cleric", "hb/cleric"]
    found = await harness.source.search("FIRE")
    assert [h.source_id for h in found] == ["srd51/fire-ball", "srd52/fire-ball"]


async def test_toggle_hides_rows_and_cards_alike(uow, tmp_path):
    """Рубильник — условие видимости самого источника (спека external-entity-
    sources): выключенный не отдаёт ни строк, ни карточек; включённый
    возвращает и то и другое; состояние переживает перезапуск сервиса."""
    harness = _Harness(uow, tmp_path)
    await harness.connect_all()
    assert harness.source.visible is True  # отсутствие строки = «показывать»
    await harness.visibility.set_visible(False)
    assert harness.source.visible is False
    assert await harness.source.search("cleric") == ()
    assert harness.source.card_source("dd_class", "srd51/cleric") is None
    await harness.visibility.set_visible(True)
    assert (await harness.source.search("cleric")) != ()
    restarted = ReferenceVisibilityService(harness.visibility._uow)
    await restarted.load()
    assert restarted.visible is True


async def test_card_source_record_and_spell(uow, tmp_path):
    """Карточка записи: имя/источник/текст черте из записи; карточка
    SRD-заклинания — humanize-имя, источник и ЧЕСТНАЯ строка про LSS, без
    пустого блока-заглушки (спека «SRD-заклинание честно без текста»)."""
    harness = _Harness(uow, tmp_path)
    await harness.connect_all()
    await harness.index.entries("feats")  # async-чтение освежает снимок под sync-дверь клика
    card = harness.source.card_source("dd_feat", "hb/lucky")
    assert card is not None and card.name == "Моя везучесть"
    assert card.origin == "Хоумбрю"
    assert [(b.title, b.text) for b in card.blocks] == [("Текст", "Текст черте")]
    assert card.relations == () and card.picture_path is None
    # запись без desc — карточка без текстовых блоков (минимум честен)
    plain = harness.source.card_source("dd_class", "srd51/cleric")
    assert plain is not None and plain.blocks == ()
    spell = harness.source.card_source("dd_spell", "srd51/fire-ball")
    assert spell is not None and spell.name == "Fire ball"
    assert spell.origin == "SRD 5.1 (2014)"
    assert [(b.title, b.text) for b in spell.blocks] == [
        ("Текст", SRD_SPELL_TEXT_LINE)
    ]


async def test_card_source_refuses_every_miss(uow, tmp_path):
    """Чужой ключ, непарный source_id, отсутствующая запись и набор без
    списка слагов — честный None (тот же posture, что пропавшая строка
    ядра); упоминательная дверь делегирует карточке."""
    harness = _Harness(uow, tmp_path)
    await harness.connect_all()
    await harness.index.entries("classes")
    assert harness.source.card_source("character", "srd51/cleric") is None
    assert harness.source.card_source("dd_class", "без-разделителя") is None
    assert harness.source.card_source("dd_class", "/cleric") is None
    assert harness.source.card_source("dd_class", "srd51/") is None
    assert harness.source.card_source("dd_class", "srd51/nope") is None
    assert harness.source.card_source("dd_spell", "hb/fire-ball") is None
    assert harness.source.card_source("dd_spell", "srd52/mage-hand") is None
    # делегирования группы 5 — тот же ответ, что у карточки/поиска
    assert harness.source.resolve_mention("dd_class", "srd51/cleric") is not None
    assert await harness.source.mention_candidates("Клейрик") == (
        await harness.source.search("Клейрик")
    )


async def test_tabs_and_event_marks_are_their_own_groups(uow, tmp_path):
    """Двери будущих групп пусты уже сейчас: табы — группа 7, пометки
    лестницы — группа 8 (справочных событий нет)."""
    from app.presentation.modules.protocol import CardTabTarget

    source = _Harness(uow, tmp_path).source
    assert source.card_tabs(CardTabTarget("dd_feat", "hb/lucky")) == ()
    assert source.event_marks([1, 2]) == {}


async def test_disconnect_takes_records_out_quietly(uow, tmp_path):
    """Отключение набора убирает его строки и карточки при следующем
    чтении — без ошибки, связанный набор продолжает служить."""
    harness = _Harness(uow, tmp_path)
    await harness.connect_all()
    await harness.connections.disconnect("hb")
    hits = await harness.source.search("кл")
    assert [h.source_id for h in hits if h.key == "dd_class"] == ["srd51/cleric"]
    await harness.index.entries("classes")
    assert harness.source.card_source("dd_class", "hb/cleric") is None


# ── task 6.1: заклинания гримуаров входят в dd_spell-группу ──────────────────


async def test_grimoire_spells_join_the_spell_group_rows(uow, tmp_path):
    """Строки гримуара — та же dd_spell-группа после SRD-слагов, имя как в
    файле (без humanize), подпись — заголовок гримуара, id пары «гримуар/слаг»;
    поиск подстрокой по имени и по слага работает по-русски и по-английски."""
    harness = _Harness(uow, tmp_path)
    await harness.connect_all()
    await harness.connect_grimoire()
    hits = await harness.source.search("")
    spells = [(h.source_id, h.name, h.origin) for h in hits if h.key == "dd_spell"]
    assert spells == [
        ("srd51/fire-ball", "Fire ball", "SRD 5.1 (2014)"),
        ("srd51/mage-hand", "Mage hand", "SRD 5.1 (2014)"),
        ("srd52/fire-ball", "Fire ball", "SRD 5.2 (2024)"),
        ("home-book/true-sight", "Истинное зрение", "Домашний гримуар"),
        ("home-book/no-text", "Без текста", "Домашний гримуар"),
    ]
    assert [h.source_id for h in await harness.source.search("истинное")] == [
        "home-book/true-sight"
    ]
    assert [h.source_id for h in await harness.source.search("TRUE-SIGHT")] == [
        "home-book/true-sight"
    ]


async def test_grimoire_spell_card_reads_the_full_plain_text(uow, tmp_path):
    """Хоумбрю-заклинание читается полностью (спека): HTML описания — как plain
    текст блока «Описание», подпись — гримуар; запись без описания — без
    текстового блока; warm перед sync-дверью обязателен (task 6.2): до него
    пустой снимок честно отвечает None."""
    harness = _Harness(uow, tmp_path)
    await harness.connect_all()
    await harness.connect_grimoire()
    assert harness.source.card_source("dd_spell", "home-book/true-sight") is None
    await harness.source.warm()  # warm греет оба индекса — и датасеты тоже
    card = harness.source.card_source("dd_spell", "home-book/true-sight")
    assert card is not None and card.name == "Истинное зрение"
    assert card.origin == "Домашний гримуар"
    assert [(b.title, b.text) for b in card.blocks] == [
        ("Описание", "Видеть сквозь")
    ]
    bare = harness.source.card_source("dd_spell", "home-book/no-text")
    assert bare is not None and bare.blocks == ()
    # warm прогрел и датасетную дверь — карточка черте читается без ручного
    # index.entries (тот же снимок, что грел test_card_source_record_and_spell)
    assert harness.source.card_source("dd_feat", "hb/lucky") is not None


async def test_grimoire_misses_and_half_compositions(uow, tmp_path):
    """None на всё недоступное: слаг вне файла, пропавший гримуар; без
   Composition-двери warm безвреден, строк гримуара нет, SRD-слаги служат;
    без рубильника — ни строк, ни гримуарной карточки."""
    harness = _Harness(uow, tmp_path)
    await harness.connect_grimoire()
    await harness.source.warm()
    assert harness.source.card_source("dd_spell", "home-book/nope") is None
    assert harness.source.card_source("dd_spell", "vanished/true-sight") is None
    await harness.visibility.set_visible(False)
    assert await harness.source.search("истинное") == ()
    assert harness.source.card_source("dd_spell", "home-book/true-sight") is None
    # источник без полки гримуаров (старая композиция) — warm живёт, гримуарных
    # записей честно нет
    plain = _Harness(uow, tmp_path, with_grimoire=False)
    await plain.connect_all()
    await plain.source.warm()
    assert [h.key for h in await plain.source.search("истинное")] == []
    assert plain.source.card_source("dd_spell", "home-book/true-sight") is None


async def test_dataset_door_wins_a_shared_namespace(uow, tmp_path):
    """Общий id у датасета и гримуара (оба — внутренние namespaces модуля):
    строки дают обе двери, а sync-карточку — дверь датасета первой (постановка
    из docstring card_source)."""
    harness = _Harness(uow, tmp_path)
    await harness.connections.connect("srd52")
    await harness.connect_grimoire(
        "srd52",
        json.dumps(
            {
                "name": "Гримуар под именем набора",
                "items": [
                    {
                        "name": "Огненный шар",
                        "type": "spell",
                        "system": {"description": {"value": "Мощный взрыв"}},
                        "flags": {"lss": {"slug": "fire-ball"}},
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    await harness.source.warm()
    rows = [(h.source_id, h.name) for h in await harness.source.search("fire")]
    # обе двери дают свою строку: одна пара имён, два носителя (датасетный
    # слаг и гримуарная запись ищутся каждая в своей двери)
    assert rows == [
        ("srd52/fire-ball", "Fire ball"),
        ("srd52/fire-ball", "Огненный шар"),
    ]
    card = harness.source.card_source("dd_spell", "srd52/fire-ball")
    assert card is not None
    assert [(b.title, b.text) for b in card.blocks] == [
        ("Текст", SRD_SPELL_TEXT_LINE)
    ]  # ответил датасетный слог, не гримуарное описание


# ── entity-preview «Переход по связи записи»: связи-переходы карточки ────────


async def test_child_card_relation_to_parent_in_same_dataset(uow, tmp_path):
    """Связь «подкласс → класс» доезжает до карточки переходом (спека
    entity-preview «Переход по связи записи», TC-PREVD-002): форматный
    classId того же набора становится строкой dd_class с снимком имени;
    subrace/raceId — тот же паттерн. Ребёнок без поля родителя, с id
    отсутствующей записи и сам родитель — связей не имеют (роль родителя
    ничего не порождает). Разрешение — строго внутри своего набора
    (snap ищется по dataset_id ребёнка): парные ключи не склеивают
    одноимённые записи разных наборов (спека dnd-reference-records
    «одноимённые слаги не сливаются»)."""
    harness = _Harness(uow, tmp_path)
    harness.storage.save(
        "kids",
        json.dumps(
            {
                "id": "kids",
                "title": "Отпрыски",
                "classes": [{"id": "wizard", "label": "Волшебник"}],
                "subclasses": [
                    {
                        "id": "evocation",
                        "classId": "wizard",
                        "label": "Школа воплощения",
                    },
                    {"id": "orphan", "classId": "no-such", "label": "Сирота"},
                    {"id": "classless", "classId": 7, "label": "Без класса"},
                ],
                "races": [{"id": "dragonborn", "label": "Драконорождённый"}],
                "subraces": [
                    {"id": "bronze", "raceId": "dragonborn", "label": "Бронзовый"}
                ],
            },
            ensure_ascii=False,
        ),
        DatasetMeta(
            source=DatasetSource.HOMEBREW,
            imported_at="2026-10-11",
            sha256="3" * 64,
        ),
    )
    # тот же слаг-омоним в srd51 («wizard» там есть в classes) — не подставляется
    await harness.connect_all()
    await harness.connections.connect("kids")
    await harness.index.entries("subclasses")  # освежает снимок под sync-дверь
    sub = harness.source.card_source("dd_subclass", "kids/evocation")
    assert sub is not None
    assert [(r.key, r.source_id, r.name) for r in sub.relations] == [
        ("dd_class", "kids/wizard", "Волшебник")
    ]
    race = harness.source.card_source("dd_subrace", "kids/bronze")
    assert race is not None
    assert [(r.key, r.source_id) for r in race.relations] == [
        ("dd_race", "kids/dragonborn")
    ]
    # родитель без поля родителя — связей нет; чужой/кривой id — тоже
    parent = harness.source.card_source("dd_class", "kids/wizard")
    assert parent is not None and parent.relations == ()
    orphan = harness.source.card_source("dd_subclass", "kids/orphan")
    assert orphan is not None and orphan.relations == ()
    classless = harness.source.card_source("dd_subclass", "kids/classless")
    assert classless is not None and classless.relations == ()


async def test_card_mechanics_block_assembled_from_fields(uow, tmp_path):
    """Карточка записи собирает «Механику» из её полей (спека
    «Карточка справочной записи печатает читаемую механику»,
    dd-reference-mechanics-text): класс — кость хитов/спасброски/трейты по
    уровням, вид — размер/скорость/языки, черта — требование и признаки;
    пустая запись остаётся без блоков (пин выше: ``srd51/cleric``),
    ``desc`` если будет — печатается раньше механики."""
    harness = _Harness(uow, tmp_path)
    await harness.connect_all()
    harness.storage.save(
        "mech",
        json.dumps(
            {
                "id": "mech",
                "title": "Механика",
                "classes": [
                    {
                        "id": "barbarian",
                        "label": "Варвар",
                        "grants": [
                            {"type": "hp-die", "die": 12},
                            {"type": "saving-throw", "stats": ["str", "con"]},
                        ],
                        "leveledGrants": [
                            {
                                "level": 2,
                                "grants": [
                                    {
                                        "type": "trait",
                                        "id": "danger-sense",
                                        "name": "Чувство опасности",
                                        "description": "С преимуществом.",
                                    }
                                ],
                            }
                        ],
                    },
                    dict(
                        {"id": "scribe", "label": "Писец",
                         "grants": [{"type": "speed", "value": 30}]},
                        desc="Сначала текст.",
                    ),
                ],
                "races": [
                    {
                        "id": "human",
                        "label": "Человек",
                        "size": "medium",
                        "grants": [
                            {"type": "speed", "value": 30},
                            {"type": "language-fixed", "languages": ["Общий"]},
                        ],
                    }
                ],
                "feats": [
                    {
                        "id": "grappler",
                        "label": "Борец",
                        "prerequisite": "Сила 13 или выше",
                        "grants": [
                            {"type": "trait", "name": "Захват", "description": "Тело."}
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        DatasetMeta(
            source=DatasetSource.HOMEBREW,
            imported_at="2026-10-14",
            sha256="9" * 64,
        ),
    )
    await harness.connections.connect("mech")
    for section in ("classes", "races", "feats"):
        await harness.index.entries(section)  # освежает снимок под sync-дверь
    klass = harness.source.card_source("dd_class", "mech/barbarian")
    assert klass is not None
    assert [b.title for b in klass.blocks] == ["Механика"]
    text = klass.blocks[0].text
    assert "Кость хитов: к12" in text
    assert "Владение спасбросками: Сила, Телосложение" in text
    assert "На уровне 2:" in text
    assert "«Чувство опасности»" in text and "С преимуществом." in text
    race = harness.source.card_source("dd_race", "mech/human")
    assert race is not None and [b.title for b in race.blocks] == ["Механика"]
    assert race.blocks[0].text.splitlines() == [
        "Размер: Средний",
        "Скорость: 30 фт.",
        "Языки: Общий",
    ]
    feat = harness.source.card_source("dd_feat", "mech/grappler")
    assert feat is not None
    assert feat.blocks[0].text.splitlines()[0] == "Требование: Сила 13 или выше"
    # desc (если пройдёт) — первым блоком, механика — следом
    scribe = harness.source.card_source("dd_class", "mech/scribe")
    assert scribe is not None
    assert [(b.title, b.text) for b in scribe.blocks] == [
        ("Текст", "Сначала текст."),
        ("Механика", "Скорость: 30 фт."),
    ]
    # SRD-заклинание по-прежнему честно без механики (постулат не тронут)
    spell = harness.source.card_source("dd_spell", "srd51/fire-ball")
    assert spell is not None and [b.title for b in spell.blocks] == ["Текст"]
