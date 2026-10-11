"""Доменный парсер гримуаров (add-dnd-game-face, task 4.1; design Д8;
spec dnd-grimoire-import «Гримуарный файл проходит проверку с отчётом»).

Golden-тесты на фикстурах ``grimoire_fixtures`` (живого экспорта в репозитории
нет — формат, по указанию design Д8, фиксирует парсер, и эти тесты и есть его
запись): состав и порядок заклинаний, plain-text HTML-описаний, фильтр
не-заклинаний и безымянных записей, нормализация слогов, обе ветки
предупреждений (дубль слага, слаг из SRD) и обе ветки ошибок (пусто,
неразбираемое). Мокросетевой контур: парсер — чистая функция текста.
"""
from __future__ import annotations

import json

from app.dd.domain.grimoire import (
    CODE_GRIMOIRE_DUP_SLUG,
    CODE_GRIMOIRE_EMPTY,
    CODE_GRIMOIRE_SLUG_IN_SRD,
    CODE_GRIMOIRE_UNPARSEABLE,
    grimoire_spell_slugs,
    grimoire_title_from_document,
    html_to_plain_text,
    normalize_spell_slug,
    parse_grimoire,
)
from app.dd.domain.validation_report import Severity
from tests.dd.grimoire_fixtures import (
    MOON_PET_HTML,
    MOON_PET_TEXT,
    content_of,
    foundry_compendium_export,
    foundry_item_list_export,
    foundry_single_item_export,
    foundry_spells_key_export,
)

SRD = ("fire-ball", "mage-hand")


# ── golden: выгрузка мира (массив предметов) ─────────────────────────────────


def test_golden_world_item_export_parses_the_spells():
    """Заклинания читаются в порядке файла, не-заклинания и безымянные записи
    не попадают в продукт, HTML становится plain text."""
    parse = parse_grimoire(content_of(foundry_item_list_export()), SRD)

    assert parse.report.import_allowed
    assert parse.document_id is None  # массив не называет себя
    assert parse.title == ""
    assert [(spell.slug, spell.name, spell.description) for spell in parse.spells] == [
        ("moon-pet", "Лунный питомец", MOON_PET_TEXT),
        ("moon-pet", "Лунный питомец (лунная копия)", "Та же луна, тень гуще."),
        ("fire-ball", "Fireball (авторский комментарий)", "Только комментарий мастера."),
        ("", "Тихий знак", "Жест без звука."),
    ]


def test_golden_world_item_export_warns_about_dup_and_srd():
    """Дубль слага и слаг из SRD — предупреждения (порог импорта не меняют),
    каждый со своим путём в документе."""
    parse = parse_grimoire(content_of(foundry_item_list_export()), SRD)

    assert [(i.code, i.severity, i.path) for i in parse.report.issues] == [
        (CODE_GRIMOIRE_SLUG_IN_SRD, Severity.WARNING, "spells[fire-ball]"),
        (CODE_GRIMOIRE_DUP_SLUG, Severity.WARNING, "spells[moon-pet]"),
    ]
    messages = {i.code: i.message for i in parse.report.issues}
    assert "уже занят в файле" in messages[CODE_GRIMOIRE_DUP_SLUG]
    assert "копия гримуара избыточна" in messages[CODE_GRIMOIRE_SLUG_IN_SRD]


def test_srd_check_skipped_without_the_public_lists():
    """Без публичных списков проверка пересечения молчит ровно целиком (та же
    предписанная LSS доза tolerance, что у валидатора датасетов)."""
    parse = parse_grimoire(content_of(foundry_item_list_export()))

    assert [i.code for i in parse.report.issues] == [CODE_GRIMOIRE_DUP_SLUG]


def test_spell_slugs_are_the_deduplicated_non_empty_ones():
    """Словарь валидатора (task 4.3) получает непустые слаги в порядке файла,
    без повторов."""
    parse = parse_grimoire(content_of(foundry_item_list_export()))

    assert grimoire_spell_slugs(parse) == ("moon-pet", "fire-ball")


# ── golden: прочие формы Foundry-документа ──────────────────────────────────


def test_golden_compendium_wrapper_carries_its_own_identity():
    """Обёртка компендиума называет и идентификатор, и заголовок — импорт
    опознаёт файл по ним (spec «под своим идентификатором»)."""
    parse = parse_grimoire(content_of(foundry_compendium_export()))

    assert parse.document_id == "tina-grimoire"
    assert parse.title == "Гримуар Тины"
    assert parse.spells[0].slug == "moon-pet"  # «Moon-Pet» → слаб LSS
    assert parse.spells[0].description == MOON_PET_TEXT


def test_golden_single_item_export_is_one_spell():
    """Выгрузка одного предмета — один заклинанийский документ."""
    parse = parse_grimoire(content_of(foundry_single_item_export()))

    assert parse.report.issues == ()
    assert [(s.slug, s.name) for s in parse.spells] == [("", "Лунный питомец")]
    assert parse.spells[0].description == MOON_PET_TEXT
    # Идентичность предмета — его ``_id`` (гримуар без имени всё равно
    # опознаваем при повторном импорте тех же байт).
    assert parse.document_id == "Kn3v7dQm1xT0aBcD"
    assert parse.title == "Лунный питомец"


def test_golden_spells_key_export_reads_the_lss_style_id_as_slug():
    """Список в ``spells`` и ``id`` вместо слага — LSS-флавор записи: слаг
    нормализуется из ``id``, описание читается и без обёртки ``value``."""
    parse = parse_grimoire(content_of(foundry_spells_key_export()))

    assert parse.title == "Заметки о заклинаниях"
    assert [(s.slug, s.name, s.description) for s in parse.spells] == [
        ("quiet-sign", "Тихий знак", "Жест без звука.")
    ]


# ── ошибки: порог импорта ───────────────────────────────────────────────────


def test_unreadable_bytes_are_an_error_with_the_reason():
    parse = parse_grimoire("{ это не json")

    assert not parse.report.import_allowed
    issue = parse.report.errors[0]
    assert issue.code == CODE_GRIMOIRE_UNPARSEABLE
    assert "не является корректным JSON" in issue.message
    assert parse.spells == ()


def test_structure_outside_the_format_is_refused():
    """Спека «структура вне формата SHALL отвергаться с причиной»."""
    for content in ('{"foo": 1}', '"строка"', "5", "null"):
        parse = parse_grimoire(content)
        assert [i.code for i in parse.report.errors] == [CODE_GRIMOIRE_UNPARSEABLE]
        assert not parse.report.import_allowed


def test_structure_error_names_the_three_accepted_shapes():
    parse = parse_grimoire('{"classes": []}')

    message = parse.report.errors[0].message
    assert "items/spells" in message and "массив предметов" in message


def test_document_without_spells_is_empty_not_unreadable():
    """Пустой (или состоящий только из не-заклинаний) документ — отдельная
    ошибка «пусто»: файл разобран, просто хранить в нём нечего."""
    for document in ([], {"name": "Пустой", "items": []}, [{"type": "feat", "name": "F"}]):
        parse = parse_grimoire(json.dumps(document, ensure_ascii=False))
        assert [i.code for i in parse.report.errors] == [CODE_GRIMOIRE_EMPTY]
        assert not parse.report.import_allowed


def test_nameless_entries_leave_nothing_behind_and_earn_empty():
    """Записи без имени не печатаются; если печатать нечего — файл пуст."""
    parse = parse_grimoire(
        json.dumps(
            [{"type": "spell", "system": {"description": {"value": "<p>?</p>"}}}]
        )
    )

    assert [i.code for i in parse.report.errors] == [CODE_GRIMOIRE_EMPTY]


# ── tolerance и нормализация ────────────────────────────────────────────────


def test_non_object_entries_and_wrong_types_are_skipped_one_by_one():
    """Толерантность по образцу индекса датасетов: мусорные элементы пропускаются
    один за одним, здоровые записи того же файла импортируются."""
    parse = parse_grimoire(
        json.dumps(
            [
                None,
                "не объект",
                42,
                {"type": 7, "name": "Странный тип"},  # тип не текст — считаем заклинанием
                {"name": "Тихий знак", "slug": "quiet-sign"},
            ],
            ensure_ascii=False,
        )
    )

    assert parse.report.issues == ()
    assert [(s.name, s.slug) for s in parse.spells] == [
        ("Странный тип", ""),
        ("Тихий знак", "quiet-sign"),
    ]


def test_slug_normalization_is_mechanical():
    assert normalize_spell_slug("  Moon-Pet  ") == "moon-pet"
    assert normalize_spell_slug("Moon_Pet") == "moon-pet"
    assert normalize_spell_slug("Лунный питомец") == ""  # вне LSS-алфавита
    assert normalize_spell_slug("--Double--Dash--") == "double-dash"
    assert normalize_spell_slug("Fire!!Ball?") == "fireball"


def test_description_reading_falls_through_the_candidate_paths():
    """Порядок доверия к полям описания зафиксирован парсером: system.value →
    description.value → system → description."""
    for path in (
        ("system", "description", "value"),
        ("description", "value"),
        ("system", "description"),
        ("description",),
    ):
        entry: dict = {"name": "Тихий знак"}
        node = entry
        for step in path[:-1]:
            node[step] = {}
            node = node[step]
        node[path[-1]] = "<p>Жест без звука.</p>"
        parse = parse_grimoire(json.dumps([entry], ensure_ascii=False))
        assert parse.spells[0].description == "Жест без звука.", path


def test_spell_without_any_description_reads_empty_text():
    parse = parse_grimoire(json.dumps([{"name": "Без описания", "slug": "blank"}]))

    assert parse.spells[0].description == ""
    assert parse.report.issues == ()


def test_off_type_spell_items_are_filtered_by_type():
    """Предмет с чужим ``type`` — не заклинание; регистр и пробелы не мешают."""
    parse = parse_grimoire(
        json.dumps(
            [
                {"name": "Подвиг", "type": "Feat "},
                {"name": "Заклинание", "type": " SPELL "},
            ],
            ensure_ascii=False,
        )
    )

    assert [s.name for s in parse.spells] == ["Заклинание"]


# ── HTML → plain text ───────────────────────────────────────────────────────


def test_html_converter_keeps_prose_and_breaks_blocks():
    """Служебный скринпт не печатается, неразрывный пробел гаснет в пробеле,
    инлайн-бросок Foundry доживает до текста, блоки становятся строками."""
    assert html_to_plain_text(MOON_PET_HTML) == MOON_PET_TEXT


def test_html_converter_tolerates_broken_markup_and_entities():
    assert html_to_plain_text("<p>Открытый &amp; незакрытый") == "Открытый & незакрытый"
    assert html_to_plain_text("") == ""
    assert html_to_plain_text("<div>\n\n  \n</div>") == ""
    assert html_to_plain_text("<style>p{color:red}</style><p>Текст</p>") == "Текст"


# ── заголовок для списка хранилища ──────────────────────────────────────────


def test_title_reader_falls_back_on_any_unreadable_input():
    assert grimoire_title_from_document({"name": " Гримуар "}, "fb") == "Гримуар"
    assert grimoire_title_from_document({"title": "T"}, "fb") == "T"
    assert grimoire_title_from_document({"label": "L"}, "fb") == "L"
    assert grimoire_title_from_document({"name": "   "}, "fb") == "fb"
    assert grimoire_title_from_document([1, 2], "fb") == "fb"
    assert grimoire_title_from_document(None, "fb") == "fb"
