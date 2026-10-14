"""Сборщик читаемой механики записи датасета (dd-reference-mechanics-text,
задачи 4.1–4.2; spec dnd-reference-records «Карточка справочной записи
печатает читаемую механику»).

Покрыты: все 28 типов грантов закрытого словаря схемы (по одной живой
формулировке и пустительным веткам), неизвестный тип — честная строка,
неизвестный ключ enum печатается как есть, поуровневые секции по возрастанию
уровня, поля записи (требование/размер/подкласс/info), пустая запись — пустая
строка, и тест-равенство: обработчики == типы ``type`` из ``grant.json``
(расширение формата падает здесь, а не молчанием в карточке).
"""
from __future__ import annotations

import json
from pathlib import Path

from app.dd.domain.grant_render import (
    GRANT_RENDERERS,
    UNKNOWN_GRANT_LINE,
    render_record_mechanics,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "app/dd/resources/schemas/grant.json"
)


def _one(record: dict) -> str:
    return render_record_mechanics(record)


def _grant(grant: dict) -> str:
    return render_record_mechanics({"grants": [grant]})


def test_scheme_parity_handlers_match_schema_types() -> None:
    definitions = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["definitions"]
    types = {
        entry["properties"]["type"]["const"]
        for name, entry in definitions.items()
        if name != "Grant"
        and isinstance(entry.get("properties", {}).get("type"), dict)
        and "const" in entry["properties"]["type"]
    }
    assert set(GRANT_RENDERERS) == types


def test_record_fields_in_fixed_order() -> None:
    text = _one(
        {
            "prerequisite": "Сила 13 или выше",
            "size": "medium",
            "subclassLevel": 3,
            "info": {
                "tagline": "Ярость сметающая",
                "tags": ["Ближний бой"],
                "primaryStats": [["str"], "мусор", ["нет-такого"]],
                "complexity": 2,
            },
        }
    )
    assert text.splitlines() == [
        "Требование: Сила 13 или выше",
        "Размер: Средний",
        "Подкласс выбирается с 3 уровня",
        "Ярость сметающая",
        "Теги: Ближний бой",
        "Ключевая характеристика: Сила, нет-такого",
        "Сложность: 2",
    ]


def test_record_skeleton_garbage_is_honest() -> None:
    assert render_record_mechanics(None) == ""
    assert render_record_mechanics("текст") == ""
    assert render_record_mechanics({}) == ""
    assert render_record_mechanics({"info": "не словарь", "grants": "не список"}) == ""
    assert render_record_mechanics({"size": "custom", "info": {"tags": [7]}}) == (
        "Размер: custom"
    )


def test_leveled_grants_sections_ascending() -> None:
    text = _one(
        {
            "leveledGrants": [
                {"level": 3, "grants": [{"type": "trait", "name": "Бешенство",
                                         "description": "Описание бешенства."}]},
                {"level": 1, "grants": [{"type": "trait", "name": "Ярость"}]},
                {"grants": [{"type": "speed", "value": 30}]},
                "мусор",
                {"level": 4, "grants": []},
            ]
        }
    )
    assert text.splitlines() == [
        "На уровне 1:",
        "  «Ярость»",
        "На уровне 3:",
        "  «Бешенство»",
        "    Описание бешенства.",
        "На уровне ?:",
        "  Скорость: 30 фт.",
    ]


def test_trait_full_and_stub() -> None:
    assert _grant({"type": "trait", "id": "rage"}).splitlines() == ["«rage»"]
    assert _grant({"type": "trait", "name": "X", "description": "Тело."}) == (
        "«X»\n  Тело."
    )
    assert _grant({"type": "trait"}) == ""


def test_unknown_grant_is_an_honest_line() -> None:
    assert _grant({"type": "wings-flight"}) == f"{UNKNOWN_GRANT_LINE}: wings-flight"
    assert _grant({"label": "без типа"}) == f"{UNKNOWN_GRANT_LINE}: <без типа>"
    assert render_record_mechanics({"grants": [42, {"type": "speed", "value": 5}]}) == (
        "Скорость: 5 фт."
    )


def test_hp_die_and_saving_throws() -> None:
    assert _grant({"type": "hp-die", "die": 12}) == "Кость хитов: к12"
    assert _grant({"type": "hp-die"}) == ""
    assert _grant(
        {"type": "saving-throw", "stats": ["str", "конь"]}
    ) == "Владение спасбросками: Сила, конь"
    assert _grant({"type": "saving-throw", "stats": "не список"}) == ""


def test_armor_and_weapon_profs() -> None:
    assert _grant(
        {"type": "armor-prof", "armors": ["armor-light", "armor-heavy"]}
    ) == "Владение доспехами: лёгкие, тяжёлые"
    assert _grant({"type": "armor-prof", "armors": []}) == ""
    assert _grant(
        {
            "type": "weapon-prof",
            "weapons": ["weapon-simple"],
            "specific": ["Сет"],
        }
    ) == "Владение оружием: простое; особое: Сет"
    assert _grant({"type": "weapon-prof", "specific": ["Сет"]}) == (
        "Владение оружием: особое: Сет"
    )
    assert _grant({"type": "weapon-prof", "weapons": []}) == ""


def test_skill_grants() -> None:
    assert _grant({"type": "skill-fixed", "skills": ["athletics"]}) == (
        "Навыки: Атлетика"
    )
    assert _grant(
        {"type": "skill-choice", "count": 2, "options": "any"}
    ) == "Выбор 2 навыка(ов) из любых"
    assert _grant(
        {
            "type": "skill-choice",
            "count": 2,
            "options": ["animal handling", "athletics", 7],
        }
    ) == "Выбор 2 навыка(ов) из: Обращение с животными, Атлетика"
    assert _grant({"type": "skill-choice", "count": 2}) == "Выбор 2 навыка(ов)"
    assert _grant(
        {"type": "expertise-choice", "count": 2, "options": ["athletics"]}
    ) == "Мастерство навыка: выбор 2 навыка(ов) из: Атлетика"
    assert _grant({"type": "expertise-choice", "count": 1}) == (
        "Мастерство навыка: выбор 1 навыка(ов)"
    )


def test_tool_language_speed_size() -> None:
    assert _grant({"type": "tool-fixed", "tools": ["Набор травника"]}) == (
        "Владение инструментами: Набор травника"
    )
    assert _grant({"type": "tool-fixed", "tools": []}) == ""
    assert _grant(
        {"type": "tool-choice", "count": 3, "options": ["Набор отравителей"]}
    ) == "Выбор 3 инструмент. набора(ов) из: Набор отравителей"
    assert _grant({"type": "tool-choice", "count": 3, "options": []}) == (
        "Выбор 3 инструмент. набора(ов)"
    )
    assert _grant({"type": "language-fixed", "languages": ["Общий"]}) == (
        "Языки: Общий"
    )
    assert _grant({"type": "language-fixed", "languages": []}) == ""
    assert _grant(
        {"type": "language-choice", "count": 2, "options": ["Эльфийский"]}
    ) == "Выбор 2 языка(ов) из: Эльфийский"
    assert _grant({"type": "language-choice", "count": 1}) == "Выбор 1 языка(ов)"
    assert _grant({"type": "speed", "value": 30.5}) == "Скорость: 30.5 фт."
    assert _grant({"type": "speed"}) == ""
    assert _grant({"type": "size", "value": "small"}) == "Размер: Маленький"
    assert _grant({"type": "size", "value": "weird"}) == "Размер: weird"
    assert _grant({"type": "size"}) == ""


def test_ability_score_improvements() -> None:
    assert _grant({"type": "asi-fixed", "values": {"str": 2, "dex": "мусор"}}) == (
        "Улучшения характеристик: Сила +2"
    )
    assert _grant({"type": "asi-fixed", "values": []}) == ""
    assert _grant(
        {
            "type": "asi-flexible",
            "sets": [
                {"count": 2, "amount": 1, "options": ["str", "dex"]},
                {"count": 1, "amount": 1},
                "мусор",
            ],
        }
    ) == ("Улучшения характеристик: 2 раз(а) по 1 очк. из: Сила, Ловкость; "
          "1 раз(а) по 1")
    assert _grant({"type": "asi-flexible", "sets": "не список"}) == ""
    assert _grant({"type": "asi-flexible", "sets": []}) == ""
    assert _grant(
        {"type": "asi-pool", "total": 3, "max": 2, "options": ["int", "wis"]}
    ) == "Очки улучшений: 3 очк., не более 2 в характеристику, из: Интеллект, Мудрость"
    assert _grant({"type": "asi-pool", "total": 1, "max": 1, "options": []}) == (
        "Очки улучшений: 1 очк., не более 1 в характеристику"
    )


def test_resource_variants() -> None:
    assert _grant(
        {"type": "resource", "id": "rage", "name": "Ярость", "max": 2,
         "isLongRest": True}
    ) == "Ресурс «Ярость»: макс. 2 (восстановление: долгий отдых)"
    assert _grant(
        {"type": "resource", "name": "Ки-подрыв", "maxExpr": "[LVL]",
         "isShortRest": True, "shortRestRegain": 1, "notes": "Сжигается бонусом"}
    ) == ("Ресурс «Ки-подрыв»: максимум по формуле [LVL] "
          "(восстановление: короткий отдых); восстановление за короткий отдых: 1; "
          "Сжигается бонусом")
    assert _grant({"type": "resource", "id": "ki", "notes": "заметка"}) == (
        "Ресурс «ki»: заметка"
    )
    assert _grant({"type": "resource"}) == ""


def test_bonus_feat_gold() -> None:
    assert _grant(
        {"type": "bonus", "target": "hp.max", "expr": "[LVL]",
         "label": "Драконья устойчивость"}
    ) == "Бонус «Драконья устойчивость»: +[LVL] к максимум хитов"
    assert _grant(
        {"type": "bonus", "target": "ac", "value": 1, "mode": "set"}
    ) == "Бонус: set 1 к КД"
    assert _grant({"type": "bonus", "label": "Ловкость пальцев"}) == "Бонус «Ловкость пальцев»"
    assert _grant({"type": "feat", "featId": "any"}) == "Получает черту: any"
    assert _grant({"type": "feat"}) == ""
    assert _grant({"type": "gold", "amount": 15}) == "Золото: 15"
    assert _grant({"type": "gold"}) == ""
    assert _grant({"type": "gold-dice", "dice": "5d4*10"}) == "Золото: бросок 5d4*10"
    assert _grant({"type": "gold-dice"}) == ""


def test_equipment_fixed_and_choice() -> None:
    assert _grant({"type": "equipment-fixed", "items": ["Облачение"]}) == (
        "Снаряжение: Облачение"
    )
    assert _grant({"type": "equipment-fixed", "items": []}) == ""
    assert _grant(
        {
            "type": "equipment-choice",
            "options": [["Большой топор"], ["Топор", "Щит"], [], 7, ["   "]],
        }
    ) == ("Выбор снаряжения:\n  — Большой топор\n  — Топор + Щит")
    assert _grant({"type": "equipment-choice", "options": "не список"}) == ""
    assert _grant({"type": "equipment-choice", "options": [[]]}) == ""


def test_pick_one_nesting() -> None:
    text = _grant(
        {
            "type": "pick-one",
            "label": "Стартовое снаряжение",
            "options": [
                {
                    "label": "Вариант А",
                    "grants": [{"type": "equipment-fixed", "items": ["Рюкзак"]}],
                },
                {"label": "Вариант Б"},
                {"grants": "не список"},
                7,
            ],
        }
    )
    assert text.splitlines() == [
        "Выбор: Стартовое снаряжение",
        "  — Вариант А",
        "    Снаряжение: Рюкзак",
        "  — Вариант Б",
    ]
    assert _grant({"type": "pick-one", "options": "не список"}) == ""


def test_spell_grants() -> None:
    assert _grant(
        {"type": "spellcasting", "ability": "cha", "casterType": "memory",
         "progression": "full"}
    ) == "Заклинательность: характеристика Харизма, тип подготовка, full"
    assert _grant({"type": "spellcasting", "ability": "", "casterType": ""}) == ""
    assert _grant({"type": "spell-fixed", "slug": "bless"}) == "Заклинание: bless"
    assert _grant({"type": "spell-fixed"}) == ""
    assert _grant(
        {"type": "spell-choice", "count": 1, "circle": 6, "spellList": "warlock"}
    ) == "Выбор 1 заклинаний, круг 6, список warlock"
    assert _grant({"type": "spell-choice"}) == "Выбор заклинаний"
