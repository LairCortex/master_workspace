"""Golden-фикстуры Foundry-экспортов заклинаний (add-dnd-game-face, task 4.1).

Живого экспорта в репозитории нет (ни ``games/``, ни ``~/.nri_manager`` его не
содержат), поэтому формат фиксирует парсер — как и велит design Д8 («У LSS нет
публичной схемы Foundry-файла заклинаний — проверка доменная») и Open Questions
изменения («формат зафиксирован парсером, не вопрос спецификации»). Фикстуры
ниже — представительные документы ровно той формы, которую выгрузки Foundry VTT
и носят:

* ``foundry_item_list_export`` — массив предметов выгрузки мира (вперемешку с
  не-заклинаниями, с дублем слага, со слагом из SRD и с записью без имени);
* ``foundry_compendium_export`` — объект-обёртка со своим ``id``/``name`` и
  списком в ``items`` (выгрузка компендиума);
* ``foundry_single_item_export`` — ОДИН предмет (штатная выгрузка предмета из
  вкладки World Items);
* ``foundry_spells_key_export`` — обёртка, прячущая список в ``spells``.

HTML описаний — живой Foundry-разметчик: ``<p>``/``<ul><li>``, ``&nbsp;``,
инлайн-бросок ``@Damage[…]`` в ссылке-якоре и служебный ``<script>``, который
в текст не попадает никогда.
"""
from __future__ import annotations

import json
from typing import Any

#: HTML описания гримуарного заклинания: абзацы, список, неразрывный пробел,
#: инлайн-бросок Foundry и служебный скрипт.
MOON_PET_HTML = (
    "<p>Вы призываете&nbsp;лунного питомца. Он <em>тихий</em> спутник.</p>"
    "<ul><li>  Броня  11  </li><li>Хиты: @Damage[4d8]</li></ul>"
    "<script>trackAnalytics()</script>"
    "<p>Существо исчезает, когда его хиты падают до 0.</p>"
)

#: Эталонный plain-text того же описания (task 4.1: HTML → plain text).
MOON_PET_TEXT = (
    "Вы призываете лунного питомца. Он тихий спутник.\n"
    "Броня 11\n"
    "Хиты: @Damage[4d8]\n"
    "Существо исчезает, когда его хиты падают до 0."
)


def foundry_item_list_export() -> dict[str, Any]:
    """Массив предметов выгрузки мира: три заклинания + один подвиг (не
    заклинание — фильтруется), дубль слага, слаг из SRD, запись без имени."""
    return [
        {
            "_id": "Kn3v7dQm1xT0aBcD",
            "name": "Лунный питомец",
            "type": "spell",
            "system": {
                "description": {"value": MOON_PET_HTML, "chat": ""},
                "level": 3,
                "school": 2,
            },
            "flags": {"lss": {"slug": "moon-pet"}},
        },
        {
            "_id": "Feat000000000001",
            "name": "Бдительность",
            "type": "feat",
            "system": {"description": {"value": "<p>Вы не можете быть удивлены.</p>"}},
        },
        {
            # Второе заклинание того же слага — GRIMOIRE_DUP_SLUG.
            "_id": "Zx9qW2eR5tY7uI8o",
            "name": "Лунный питомец (лунная копия)",
            "type": "spell",
            "flags": {"lss": {"slug": "moon pet"}},
            "system": {"description": {"value": "<p>Та же луна, тень гуще.</p>"}},
        },
        {
            # Слаг из публичного SRD — GRIMOIRE_SLUG_IN_SRD (легально, но
            # избыточно: текст SRD нам не принадлежит).
            "_id": "Fb2l1B4a11000000",
            "name": "Fireball (авторский комментарий)",
            "type": "spell",
            "slug": "fire-ball",
            "system": {"description": {"value": "<p>Только комментарий мастера.</p>"}},
        },
        {
            # Не заклинание, а запись без имени — в продукт ей места нет.
            "_id": "NoName0000000001",
            "type": "spell",
            "system": {"description": {"value": "<p>Безымянный фрагмент.</p>"}},
        },
        {
            "name": "Тихий знак",
            "type": "spell",
            "system": {"description": {"value": "<p>Жест без звука.</p>"}},
        },
    ]


def foundry_compendium_export() -> dict[str, Any]:
    """Объект-обёртка компендиума: собственные ``id``/``name`` + ``items``."""
    return {
        "id": "tina-grimoire",
        "name": "Гримуар Тины",
        "encoding": "utf8",
        "label": "Grimoire",
        "items": [
            {
                "_id": "Kn3v7dQm1xT0aBcD",
                "name": "Лунный питомец",
                "type": "spell",
                "system": {"description": {"value": MOON_PET_HTML}},
                "flags": {"lss": {"slug": "Moon-Pet"}},
            }
        ],
    }


def foundry_single_item_export() -> dict[str, Any]:
    """Один предмет вместо списка — выгрузка из вкладки World Items."""
    return {
        "_id": "Kn3v7dQm1xT0aBcD",
        "name": "Лунный питомец",
        "type": "spell",
        "system": {"description": {"value": MOON_PET_HTML}},
    }


def foundry_spells_key_export() -> dict[str, Any]:
    """Обёртка, прячущая список в ``spells`` (без типа у записей)."""
    return {
        "name": "Заметки о заклинаниях",
        "spells": [
            {
                "name": "Тихий знак",
                "id": "Quiet Sign",
                "description": "<p>Жест без звука.</p>",
            }
        ],
    }


def content_of(document: Any) -> str:
    """Текст файла так, как его принёс бы импорт: UTF-8 JSON без экранирования
    кириллицы (реальная выгрузка Foundry пишет символы как есть)."""
    return json.dumps(document, ensure_ascii=False, indent=2)
