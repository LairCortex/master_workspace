"""Readable Russian mechanics text assembled from a dataset record (task 1).

The LSS dataset files carry their human-readable content structurally:
grants, leveled grants, prerequisites, sizes, info blocks — the SRD files
hold no prose field and their schema forbids one (``desc`` is rejected at
import). The card of a reference record used to print identity only; this
module is the single, Qt-free door that turns those fields into plain
Russian lines (change ``dd-reference-mechanics-text``, design Д1–Д3).

Honesty rule (Д4): every printed line is a consequence of a concrete field
of the record — nothing is invented. An unknown grant type (a future format
revision) prints as an honest stub instead of vanishing; an unknown enum
key prints as itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.dd.domain.character_render import SKILL_LABELS, STAT_LABELS

#: Card block caption this text is wrapped into by the presentation door.
MECHANICS_BLOCK_TITLE = "Механика"

#: Honest stub for a grant type the app does not know (spec scenario
#: «Неизвестный грант честен, а не потерян»).
UNKNOWN_GRANT_LINE = "Признак без перевода"

_SIZE_LABELS = {"tiny": "Крохотный", "small": "Маленький", "medium": "Средний",
                "large": "Большой", "huge": "Огромный", "gargantuan": "Громадный"}
_ARMOR_LABELS = {"armor-light": "лёгкие", "armor-medium": "средние",
                 "armor-heavy": "тяжёлые", "armor-label": "указанные особые"}
_WEAPON_LABELS = {"weapon-simple": "простое", "weapon-martial": "воинское",
                  "weapon-other": "указанное особое"}
_CASTER_LABELS = {"memory": "подготовка", "list": "известные", "book": "книга"}
_BONUS_TARGET_LABELS = {
    "ac": "КД",
    "hp.max": "максимум хитов",
    "initiative": "инициатива",
    "shield": "щит",
    "speed.walk": "скорость",
    "spellAttack": "бросок атаки заклинанием",
    "spellDC": "Сл заклинаний",
}


def _label(labels: Mapping[str, str], key: str) -> str:
    """The Russian name of a slug, or the slug itself (never invented).

    Skill slugs arrive in the dataset spelling («animal handling»); the
    shared sheet map keys them with underscores — the same key, two faces.
    """
    if " " in key and key.replace(" ", "_") in labels:
        return labels[key.replace(" ", "_")]
    return labels.get(key, key)


def _joined(labels: Mapping[str, str], keys: Any) -> str:
    """Known-or-raw labels of a key list, joined for one line."""
    if not isinstance(keys, list):
        return ""
    return ", ".join(_label(labels, key) for key in keys if isinstance(key, str))


def _numbers(grant: Mapping[str, Any], *names: str) -> str:
    """The first present number of the grant rendered as text, or ``''``."""
    for name in names:
        value = grant.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"{value:g}" if isinstance(value, float) else str(value)
    return ""


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _stat_boosts(values: Any) -> str:
    """``{'str': 2}`` → «Сила +2, …» in the canonical ability order."""
    if not isinstance(values, dict):
        return ""
    parts = [
        f"{_label(STAT_LABELS, stat)} +{amount:g}"
        for stat, amount in values.items()
        if isinstance(stat, str) and isinstance(amount, (int, float))
        and not isinstance(amount, bool)
    ]
    return ", ".join(parts)


def _hp_die(grant: Mapping[str, Any], prefix: str) -> list[str]:
    die = _numbers(grant, "die")
    return [f"{prefix}Кость хитов: к{die}"] if die else []


def _saving_throw(grant: Mapping[str, Any], prefix: str) -> list[str]:
    stats = _joined(STAT_LABELS, grant.get("stats"))
    return [f"{prefix}Владение спасбросками: {stats}"] if stats else []


def _armor_prof(grant: Mapping[str, Any], prefix: str) -> list[str]:
    armors = _joined(_ARMOR_LABELS, grant.get("armors"))
    return [f"{prefix}Владение доспехами: {armors}"] if armors else []


def _weapon_prof(grant: Mapping[str, Any], prefix: str) -> list[str]:
    weapons = _joined(_WEAPON_LABELS, grant.get("weapons"))
    specific = _joined({}, grant.get("specific"))
    if weapons and specific:
        weapons = f"{weapons}; особое: {specific}"
    elif specific:
        weapons = f"особое: {specific}"
    return [f"{prefix}Владение оружием: {weapons}"] if weapons else []


def _skill_fixed(grant: Mapping[str, Any], prefix: str) -> list[str]:
    skills = _joined(SKILL_LABELS, grant.get("skills"))
    return [f"{prefix}Навыки: {skills}"] if skills else []


def _skill_choice(grant: Mapping[str, Any], prefix: str) -> list[str]:
    count = _numbers(grant, "count")
    options = grant.get("options")
    if options == "any":
        return [f"{prefix}Выбор {count} навыка(ов) из любых"]
    skills = _joined(SKILL_LABELS, options)
    if skills:
        return [f"{prefix}Выбор {count} навыка(ов) из: {skills}"]
    return [f"{prefix}Выбор {count} навыка(ов)"]


def _expertise_choice(grant: Mapping[str, Any], prefix: str) -> list[str]:
    count = _numbers(grant, "count")
    options = _joined(SKILL_LABELS, grant.get("options"))
    tail = f" из: {options}" if options else ""
    return [f"{prefix}Мастерство навыка: выбор {count} навыка(ов){tail}"]


def _tool_fixed(grant: Mapping[str, Any], prefix: str) -> list[str]:
    tools = _joined({}, grant.get("tools"))
    return [f"{prefix}Владение инструментами: {tools}"] if tools else []


def _tool_choice(grant: Mapping[str, Any], prefix: str) -> list[str]:
    count = _numbers(grant, "count")
    options = _joined({}, grant.get("options"))
    tail = f" из: {options}" if options else ""
    return [f"{prefix}Выбор {count} инструмент. набора(ов){tail}"]


def _language_fixed(grant: Mapping[str, Any], prefix: str) -> list[str]:
    languages = _joined({}, grant.get("languages"))
    return [f"{prefix}Языки: {languages}"] if languages else []


def _language_choice(grant: Mapping[str, Any], prefix: str) -> list[str]:
    count = _numbers(grant, "count")
    options = _joined({}, grant.get("options"))
    tail = f" из: {options}" if options else ""
    return [f"{prefix}Выбор {count} языка(ов){tail}"]


def _speed(grant: Mapping[str, Any], prefix: str) -> list[str]:
    value = _numbers(grant, "value")
    return [f"{prefix}Скорость: {value} фт."] if value else []


def _size(grant: Mapping[str, Any], prefix: str) -> list[str]:
    value = _text(grant.get("value"))
    return [f"{prefix}Размер: {_label(_SIZE_LABELS, value)}"] if value else []


def _asi_fixed(grant: Mapping[str, Any], prefix: str) -> list[str]:
    boosts = _stat_boosts(grant.get("values"))
    return [f"{prefix}Улучшения характеристик: {boosts}"] if boosts else []


def _asi_flexible(grant: Mapping[str, Any], prefix: str) -> list[str]:
    sets = grant.get("sets")
    if not isinstance(sets, list):
        return []
    parts: list[str] = []
    for entry in sets:
        if not isinstance(entry, dict):
            continue
        count = _numbers(entry, "count")
        amount = _numbers(entry, "amount")
        options = _joined(STAT_LABELS, entry.get("options"))
        chunk = f"{count} раз(а) по {amount}"
        if options:
            chunk = f"{chunk} очк. из: {options}"
        parts.append(chunk)
    return [f"{prefix}Улучшения характеристик: {'; '.join(parts)}"] if parts else []


def _asi_pool(grant: Mapping[str, Any], prefix: str) -> list[str]:
    total = _numbers(grant, "total")
    cap = _numbers(grant, "max")
    options = _joined(STAT_LABELS, grant.get("options"))
    line = f"Очки улучшений: {total} очк., не более {cap} в характеристику"
    if options:
        line = f"{line}, из: {options}"
    return [f"{prefix}{line}"]


def _resource(grant: Mapping[str, Any], prefix: str) -> list[str]:
    name = _text(grant.get("name")) or _text(grant.get("id"))
    if not name:
        return []
    maximum = _numbers(grant, "max")
    expr = _text(grant.get("maxExpr"))
    tail = ""
    if maximum:
        tail = f": макс. {maximum}"
    elif expr:
        tail = f": максимум по формуле {expr}"
    rests = []
    if grant.get("isShortRest") is True:
        rests.append("короткий отдых")
    if grant.get("isLongRest") is True:
        rests.append("долгий отдых")
    if rests:
        tail = f"{tail} (восстановление: {', '.join(rests)})"
    regain = _numbers(grant, "shortRestRegain")
    if regain:
        tail = f"{tail}; восстановление за короткий отдых: {regain}"
    notes = _text(grant.get("notes"))
    if notes:
        tail = f"{tail}; {notes}" if tail else f": {notes}"
    return [f"{prefix}Ресурс «{name}»{tail}"]


def _bonus(grant: Mapping[str, Any], prefix: str) -> list[str]:
    label = _text(grant.get("label"))
    target = _text(grant.get("target"))
    amount = _numbers(grant, "value") or _text(grant.get("expr"))
    mode = _text(grant.get("mode"))
    bits: list[str] = []
    if amount:
        bits.append(f"+{amount}" if mode in ("", "add") else f"{mode} {amount}")
    if target:
        bits.append(_label(_BONUS_TARGET_LABELS, target))
    joined = " к ".join(bits) if len(bits) == 2 else (bits[0] if bits else "")
    head = f"Бонус «{label}»" if label else "Бонус"
    return [f"{prefix}{head}: {joined}"] if joined else [f"{prefix}{head}"]


def _feat(grant: Mapping[str, Any], prefix: str) -> list[str]:
    feat_id = _text(grant.get("featId"))
    return [f"{prefix}Получает черту: {feat_id}"] if feat_id else []


def _equipment_fixed(grant: Mapping[str, Any], prefix: str) -> list[str]:
    items = _joined({}, grant.get("items"))
    return [f"{prefix}Снаряжение: {items}"] if items else []


def _equipment_choice(grant: Mapping[str, Any], prefix: str) -> list[str]:
    options = grant.get("options")
    if not isinstance(options, list):
        return []
    lines = [f"{prefix}Выбор снаряжения:"]
    for bundle in options:
        if isinstance(bundle, list):
            joined = " + ".join(
                item.strip() for item in bundle
                if isinstance(item, str) and item.strip()
            )
            if joined:
                lines.append(f"{prefix}  — {joined}")
    return lines if len(lines) > 1 else []


def _gold(grant: Mapping[str, Any], prefix: str) -> list[str]:
    amount = _numbers(grant, "amount")
    return [f"{prefix}Золото: {amount}"] if amount else []


def _gold_dice(grant: Mapping[str, Any], prefix: str) -> list[str]:
    dice = _text(grant.get("dice"))
    return [f"{prefix}Золото: бросок {dice}"] if dice else []


def _pick_one(grant: Mapping[str, Any], prefix: str) -> list[str]:
    label = _text(grant.get("label"))
    lines = [f"{prefix}Выбор: {label}"] if label else []
    options = grant.get("options")
    if not isinstance(options, list):
        return lines
    for option in options:
        if not isinstance(option, dict):
            continue
        option_label = _text(option.get("label"))
        if option_label:
            lines.append(f"{prefix}  — {option_label}")
        nested = option.get("grants")
        if isinstance(nested, list):
            lines.extend(_render_grants(nested, f"{prefix}    "))
    return lines


def _spellcasting(grant: Mapping[str, Any], prefix: str) -> list[str]:
    ability = _label(STAT_LABELS, _text(grant.get("ability")))
    caster = _label(_CASTER_LABELS, _text(grant.get("casterType")))
    progression = _text(grant.get("progression"))
    bits = [bit for bit in (ability and f"характеристика {ability}",
                            caster and f"тип {caster}", progression) if bit]
    return [f"{prefix}Заклинательность: {', '.join(bits)}"] if bits else []


def _spell_fixed(grant: Mapping[str, Any], prefix: str) -> list[str]:
    slug = _text(grant.get("slug"))
    return [f"{prefix}Заклинание: {slug}"] if slug else []


def _spell_choice(grant: Mapping[str, Any], prefix: str) -> list[str]:
    count = _numbers(grant, "count")
    bits = [f"Выбор {count} заклинаний"] if count else ["Выбор заклинаний"]
    circle = _numbers(grant, "circle")
    if circle:
        bits.append(f"круг {circle}")
    spell_list = _text(grant.get("spellList"))
    if spell_list:
        bits.append(f"список {spell_list}")
    return [f"{prefix}{', '.join(bits)}"]


def _trait(grant: Mapping[str, Any], prefix: str) -> list[str]:
    name = _text(grant.get("name")) or _text(grant.get("id"))
    description = _text(grant.get("description"))
    lines = []
    if name:
        lines.append(f"{prefix}«{name}»")
    if description:
        lines.append(f"{prefix}  {description}")
    return lines


def _unknown(grant: Mapping[str, Any], prefix: str) -> list[str]:
    grant_type = _text(grant.get("type")) or "<без типа>"
    return [f"{prefix}{UNKNOWN_GRANT_LINE}: {grant_type}"]


#: The closed vocabulary: one branch per grant type declared in the bundled
#: ``grant.json`` schema. A test pins this key set against the schema, so a
#: format revision that adds a type fails loudly instead of going silent.
GRANT_RENDERERS: dict[str, Callable[[Mapping[str, Any], str], list[str]]] = {
    "hp-die": _hp_die,
    "saving-throw": _saving_throw,
    "armor-prof": _armor_prof,
    "weapon-prof": _weapon_prof,
    "skill-fixed": _skill_fixed,
    "skill-choice": _skill_choice,
    "expertise-choice": _expertise_choice,
    "tool-fixed": _tool_fixed,
    "tool-choice": _tool_choice,
    "language-fixed": _language_fixed,
    "language-choice": _language_choice,
    "speed": _speed,
    "size": _size,
    "asi-fixed": _asi_fixed,
    "asi-flexible": _asi_flexible,
    "asi-pool": _asi_pool,
    "resource": _resource,
    "bonus": _bonus,
    "feat": _feat,
    "equipment-fixed": _equipment_fixed,
    "equipment-choice": _equipment_choice,
    "gold": _gold,
    "gold-dice": _gold_dice,
    "pick-one": _pick_one,
    "spellcasting": _spellcasting,
    "spell-fixed": _spell_fixed,
    "spell-choice": _spell_choice,
    "trait": _trait,
}


def _render_grants(grants: Any, prefix: str) -> list[str]:
    """Lines for one grant list; a non-grant item is skipped as noise."""
    if not isinstance(grants, list):
        return []
    lines: list[str] = []
    for grant in grants:
        if not isinstance(grant, dict):
            continue
        renderer = GRANT_RENDERERS.get(_text(grant.get("type")), _unknown)
        lines.extend(renderer(grant, prefix))
    return lines


def _level_order(entry: Any) -> float:
    if isinstance(entry, dict):
        level = entry.get("level")
        if isinstance(level, (int, float)) and not isinstance(level, bool):
            return float(level)
    return float("inf")


def _info_lines(info: Any) -> list[str]:
    if not isinstance(info, dict):
        return []
    lines: list[str] = []
    tagline = _text(info.get("tagline"))
    if tagline:
        lines.append(tagline)
    tags = _joined({}, info.get("tags"))
    if tags:
        lines.append(f"Теги: {tags}")
    primary = info.get("primaryStats")
    if isinstance(primary, list):
        stats = _joined(
            STAT_LABELS, [stat for group in primary if isinstance(group, list)
                          for stat in group if isinstance(stat, str)]
        )
        if stats:
            lines.append(f"Ключевая характеристика: {stats}")
    complexity = _numbers(info, "complexity")
    if complexity:
        lines.append(f"Сложность: {complexity}")
    return lines


def render_record_mechanics(record: Any) -> str:
    """The readable mechanics of one dataset record; ``''`` when it has none.

    Order (design Д3): the record-level fields first (требование, размер,
    уровень подкласса, info), then the flat grants, then the leveled grants
    in ascending level. The output is plain text: block titles belong to
    the presentation door, this module knows only lines.
    """
    if not isinstance(record, dict):
        return ""
    lines: list[str] = []
    prerequisite = _text(record.get("prerequisite"))
    if prerequisite:
        lines.append(f"Требование: {prerequisite}")
    size = _text(record.get("size"))
    if size:
        lines.append(f"Размер: {_label(_SIZE_LABELS, size)}")
    subclass_level = _numbers(record, "subclassLevel")
    if subclass_level:
        lines.append(f"Подкласс выбирается с {subclass_level} уровня")
    lines.extend(_info_lines(record.get("info")))
    lines.extend(_render_grants(record.get("grants"), ""))
    leveled = record.get("leveledGrants")
    if isinstance(leveled, list):
        for entry in sorted(leveled, key=_level_order):
            if not isinstance(entry, dict):
                continue
            level = _numbers(entry, "level") or "?"
            body = _render_grants(entry.get("grants"), "  ")
            if not body:
                continue
            lines.append(f"На уровне {level}:")
            lines.extend(body)
    return "\n".join(lines)
