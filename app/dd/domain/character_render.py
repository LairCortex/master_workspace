"""The structural render of a character document (add-dnd-game-face task 9.2,
design Д7; spec dnd-character-import «структурные данные SHALL рендериться
человекочитаемыми именованными блоками»).

The structured halves of the LSS document — ability scores, saving-throw
proficiencies, skill proficiencies, the current bonus channel, weapons,
resources, coins and the spell-slot counters — are not text blocks, and a
dump of JSON under the reader's eyes is not «читается без LSS» (spec
scenario «Структура читается без LSS»). This module turns each family into
one deterministic named block: the same document always renders the same
lines in the same order, English slugs gain their Russian labels where the
label is known (an unknown slug prints as it stands — invented translations
are worse than a foreign word), and an empty family produces NO block at all
(an empty «Монеты» section is noise, not information).

The import lays these blocks into ``text_blocks`` first; a document block
that carries the same name merges into the same block (structural lines
first, the author's text below) — neither half is ever silently lost.

Qt-free, storage-free, warning-free: best effort over tolerant shapes; the
raw snapshot stays the source of truth for anything finer than this render.
"""
from __future__ import annotations

from typing import Any

# The eight block names, in the order the import lays them out (Д7).
BLOCK_STATS = "Характеристики"
BLOCK_SAVES = "Спасброски"
BLOCK_SKILLS = "Навыки"
BLOCK_BONUSES = "Бонусы"
BLOCK_WEAPONS = "Оружие"
BLOCK_RESOURCES = "Ресурсы"
BLOCK_COINS = "Монеты"
BLOCK_SLOTS = "Ячейки заклинаний"

#: The canonical ability order (the one the character sheet prints).
_STAT_ORDER: tuple[str, ...] = ("str", "dex", "con", "int", "wis", "cha")
_STAT_LABELS = {
    "str": "Сила",
    "dex": "Ловкость",
    "con": "Телосложение",
    "int": "Интеллект",
    "wis": "Мудрость",
    "cha": "Харизма",
}
_SKILL_LABELS = {
    "acrobatics": "Акробатика",
    "animal_handling": "Обращение с животными",
    "arcana": "Магия",
    "athletics": "Атлетика",
    "deception": "Обман",
    "history": "История",
    "insight": "Проницательность",
    "intimidation": "Запугивание",
    "investigation": "Расследование",
    "medicine": "Медицина",
    "nature": "Природа",
    "perception": "Восприятие",
    "performance": "Актёрство",
    "persuasion": "Убеждение",
    "religion": "Религия",
    "sleight_of_hand": "Ловкость рук",
    "stealth": "Скрытность",
    "survival": "Выживание",
}
#: The canonical coin order (pp → cp, the order a purse prints).
_COIN_ORDER: tuple[str, ...] = ("pp", "gp", "ep", "sp", "cp")


def _label(labels: dict[str, str], key: str) -> str:
    """The Russian name of a slug, or the slug itself (never invented)."""
    return labels.get(key, key)


def _ordered_keys(keys: list[str], known_order: tuple[str, ...]) -> list[str]:
    """Known keys in their canonical order, unknown ones after, alphabetical
    — deterministic for the same document."""
    known = [key for key in known_order if key in keys]
    rest = sorted(key for key in keys if key not in known_order)
    return known + rest


def _stat_lines(stats: dict[str, Any], *, saves: bool) -> list[str]:
    lines: list[str] = []
    for key in _ordered_keys(list(stats), _STAT_ORDER):
        entry = stats[key]
        label = _label(_STAT_LABELS, key)
        if saves:
            save = entry.get("save") if isinstance(entry, dict) else None
            if isinstance(save, bool):
                if save:
                    lines.append(f"{label}: владеет")
            elif isinstance(save, int) and not isinstance(save, bool):
                sign = "+" if save >= 0 else "−"
                lines.append(f"{label}: {sign}{abs(save)}")
        else:
            value = entry.get("value") if isinstance(entry, dict) else entry
            if isinstance(value, int) and not isinstance(value, bool):
                lines.append(f"{label}: {value}")
    return lines


def _skill_lines(skills: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in sorted(skills):
        entry = skills[key]
        proficient = entry.get("proficient") if isinstance(entry, dict) else None
        if proficient:
            lines.append(f"- {_label(_SKILL_LABELS, key)}")
    return lines


def _bonus_lines(bonuses: list[Any]) -> list[str]:
    lines: list[str] = []
    for entry in bonuses:
        if not isinstance(entry, dict):
            continue
        target = entry.get("target")
        if not isinstance(target, str) or not target:
            continue
        formula = entry.get("formula")
        if not isinstance(formula, str):
            value = entry.get("value")
            formula = str(value) if value is not None else ""
        lines.append(f"- {target}: {formula}" if formula else f"- {target}")
    return lines


def _weapon_lines(weapons: list[Any]) -> list[str]:
    lines: list[str] = []
    for entry in weapons:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        line = f"- {name}"
        attack = entry.get("attackFormula")
        if isinstance(attack, str) and attack:
            line += f" · атака {attack}"
        damage = entry.get("damageFormula")
        if isinstance(damage, str) and damage:
            line += f" · урон {damage}"
        lines.append(line)
    return lines


def _resource_lines(resources: list[Any]) -> list[str]:
    lines: list[str] = []
    for entry in resources:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        value = entry.get("value")
        maximum = entry.get("max")
        both_ints = (
            isinstance(value, int)
            and not isinstance(value, bool)
            and isinstance(maximum, int)
            and not isinstance(maximum, bool)
        )
        lines.append(f"- {name}: {value}/{maximum}" if both_ints else f"- {name}")
    return lines


def _coin_lines(coins: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in _ordered_keys(list(coins), _COIN_ORDER):
        value = coins[key]
        if isinstance(value, int) and not isinstance(value, bool):
            lines.append(f"{key}: {value}")
    return lines


def _slot_lines(spells: dict[str, Any]) -> list[str]:
    slots = spells.get("slots")
    if not isinstance(slots, list):
        return []
    lines: list[str] = []
    for entry in slots:
        if not isinstance(entry, dict):
            continue
        level = entry.get("level")
        if not isinstance(level, int) or isinstance(level, bool):
            continue
        value = entry.get("value")
        maximum = entry.get("max")
        both_ints = (
            isinstance(value, int)
            and not isinstance(value, bool)
            and isinstance(maximum, int)
            and not isinstance(maximum, bool)
        )
        line = f"- {level}-й круг"
        if both_ints:
            line += f": {value} / {maximum}"
        lines.append(line)
    return lines


def _document_list(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    return value if isinstance(value, list) else []


def _document_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def structural_blocks(data: dict[str, Any]) -> list[tuple[str, str]]:
    """The named blocks rendered from the document's structured halves, in
    the fixed order; an empty family contributes no block."""
    blocks: list[tuple[str, str]] = []
    families: list[tuple[str, list[str]]] = [
        (BLOCK_STATS, _stat_lines(_document_dict(data, "stats"), saves=False)),
        (BLOCK_SAVES, _stat_lines(_document_dict(data, "stats"), saves=True)),
        (BLOCK_SKILLS, _skill_lines(_document_dict(data, "skills"))),
        (BLOCK_BONUSES, _bonus_lines(_document_list(data, "bonuses"))),
        (BLOCK_WEAPONS, _weapon_lines(_document_list(data, "weaponsList"))),
        (BLOCK_RESOURCES, _resource_lines(_document_list(data, "resources"))),
        (BLOCK_COINS, _coin_lines(_document_dict(data, "coins"))),
        (BLOCK_SLOTS, _slot_lines(_document_dict(data, "spells"))),
    ]
    for name, lines in families:
        if lines:
            blocks.append((name, "\n".join(lines)))
    return blocks
