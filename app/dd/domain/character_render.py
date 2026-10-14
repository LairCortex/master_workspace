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

The same module is also the document's mechanics intake (dd-card-redesign
task 6.1, spec dnd-character-import «Раскладывание полное»): per family the
document either answers a value the card can store (:func:`
parse_document_mechanics` — the six scores, the boolean saving throws, the
boolean skill proficiencies, the speed, the slot grid, a known alignment,
well-formed feat references) or it does not, and a family that did not fit
keeps its readable block while a family that did is stored as structure
instead of painted as text («Механики легли структурой … читаемых блоков
пропущенных разделов это не отменяет»). Sections the format does not know
at all print under their original name — nothing silently lost.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.dd.domain.character_mechanics import (
    ALIGNMENTS,
    LSS_STAT_TO_ABILITY,
    SKILL_ABILITIES,
)

# The eight block names, in the order the import lays them out (Д7).
BLOCK_STATS = "Характеристики"
BLOCK_SAVES = "Спасброски"
BLOCK_SKILLS = "Навыки"
BLOCK_BONUSES = "Бонусы"
BLOCK_WEAPONS = "Оружие"
BLOCK_RESOURCES = "Ресурсы"
BLOCK_COINS = "Монеты"
BLOCK_SLOTS = "Ячейки заклинаний"

# The blocks the mechanics intake falls back to when a section is present
# but unreadable as structure (dd-card-redesign task 6.1). «Черты» is the
# block a malformed feat section shows its entries under — where the
# document also carries a text block of that name, the established merge
# rule joins the two halves into one block.
BLOCK_SPEED = "Скорость"
BLOCK_ALIGNMENT = "Мировоззрение"
BLOCK_FEATS = "Черты"

#: The canonical ability order (the one the character sheet prints).
STAT_ORDER: tuple[str, ...] = ("str", "dex", "con", "int", "wis", "cha")
STAT_LABELS = {
    "str": "Сила",
    "dex": "Ловкость",
    "con": "Телосложение",
    "int": "Интеллект",
    "wis": "Мудрость",
    "cha": "Харизма",
}
SKILL_LABELS = {
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
    for key in _ordered_keys(list(stats), STAT_ORDER):
        entry = stats[key]
        label = _label(STAT_LABELS, key)
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
            lines.append(f"- {_label(SKILL_LABELS, key)}")
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


def structural_blocks(
    data: dict[str, Any], *, mechanics: "DocumentMechanics | None" = None
) -> list[tuple[str, str]]:
    """The named blocks rendered from the document's structured halves, in
    the fixed order; an empty family contributes no block.

    With ``mechanics`` (the import's door, dd-card-redesign task 6.1) the
    render answers the laid-out state instead of the raw one: a family whose
    value the card now stores prints no block, a family that was present but
    unreadable as structure falls back to its block (the four legacy names
    plus «Скорость»/«Мировоззрение»/«Черты»), and every section the format
    does not know at all arrives under its original name. Without it the
    render is the add-dnd-game-face eight-family output, byte for byte."""
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
    if mechanics is not None:
        skip = mechanics.fitted_blocks
        families = [entry for entry in families if entry[0] not in skip]
        if mechanics.speed_text:
            families.append((BLOCK_SPEED, [mechanics.speed_text]))
        if mechanics.alignment_text:
            families.append((BLOCK_ALIGNMENT, [mechanics.alignment_text]))
        if mechanics.feat_garbage:
            families.append((BLOCK_FEATS, _feat_leftover_lines(mechanics.feat_garbage)))
    for name, lines in families:
        if lines:
            blocks.append((name, "\n".join(lines)))
    if mechanics is not None:
        blocks.extend(_unknown_section_blocks(data))
    return blocks


# ── the document → mechanics intake (dd-card-redesign task 6.1; spec
# dnd-character-import «Раскладывание полное», dnd-character-mechanics
# «Механики ездят туда-обратно через LSS») ───────────────────────────────────

#: The document keys the intake or the render already speaks — a section
#: outside this set is unknown and prints under its own name. The service
#: keys of a live export (``wizardStep``, ``choices``, ``createdAt``) and the
#: deprecated bonus channels are NOT here on purpose: the validator already
#: warns about them, they are not content the reader lost.
_KNOWN_SECTIONS: frozenset[str] = frozenset(
    (
        "name",
        "avatar",
        "level",
        "info",
        "stats",
        "skills",
        "bonuses",
        "bonusesSkills",
        "bonusesStats",
        "weaponsList",
        "resources",
        "coins",
        "spells",
        "blocks",
        "speed",
        "alignment",
        "feats",
    )
)


def _is_whole(value: object) -> bool:
    """A whole number without a bool posing as one (the module's standing
    integer norm, shared by the render and the intake)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _section_value_lines(data: dict[str, Any]) -> dict[str, str]:
    """Unknown top-level sections → block text under the original name: a
    string is content as it stands, anything else arrives as its JSON — the
    honest mirror of what the card could not store (spec «нераспознанные
    разделы получают блок с исходным именем»)."""
    texts: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key or key in _KNOWN_SECTIONS:
            continue
        if isinstance(value, str):
            text = value.strip()
        else:
            text = json.dumps(value, ensure_ascii=False)
        if text:
            texts[key] = text
    return texts


def _unknown_section_blocks(data: dict[str, Any]) -> list[tuple[str, str]]:
    """The fallback blocks in document order (a json-parsed dict preserves
    the file order, so the render is deterministic for the same bytes)."""
    return list(_section_value_lines(data).items())


# The nine alignments as LSS spells them in English (a live wizard answers
# «chaotic good», a hand-edited file may hyphenate) → the domain's fixed
# Russian nine. The Russian spellings need no table: they ARE the domain
# values. «neutral» alone lands on истинно нейтральный — the only canonical
# value that word can honestly mean.
_ALIGNMENT_EN_ALIASES: dict[str, str] = {
    "lawful good": ALIGNMENTS[0],
    "neutral good": ALIGNMENTS[1],
    "chaotic good": ALIGNMENTS[2],
    "lawful neutral": ALIGNMENTS[3],
    "true neutral": ALIGNMENTS[4],
    "neutral": ALIGNMENTS[4],
    "chaotic neutral": ALIGNMENTS[5],
    "lawful evil": ALIGNMENTS[6],
    "neutral evil": ALIGNMENTS[7],
    "chaotic evil": ALIGNMENTS[8],
}


def _normalize_alignment(raw: object) -> str | None:
    """The stored nine from a document spelling, or ``None`` (the caller
    keeps a readable block). Russian spellings are the canonical values and
    match verbatim; English ones go through the alias table after case,
    hyphen/underscore and spacing are folded."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text in ALIGNMENTS:
        return text
    folded = " ".join(text.lower().replace("-", " ").replace("_", " ").split())
    return _ALIGNMENT_EN_ALIASES.get(folded)


def _feat_leftover_lines(garbage: tuple[object, ...]) -> list[str]:
    """One readable line per feat entry the intake refused (a string, a
    number, a dict without a usable id) — the block posture of every other
    refused family."""
    lines: list[str] = []
    for entry in garbage:
        if isinstance(entry, str):
            text = entry.strip()
        else:
            text = json.dumps(entry, ensure_ascii=False)
        if text:
            lines.append(f"- {text}")
    return lines


@dataclass(frozen=True)
class DocumentMechanics:
    """One document read through the mechanics intake. ``None`` answers a
    family the card cannot store (unreadable or absent) — the import then
    clears that stored field, exactly as it clears an absent level or an
    absent reference (the file replaces the card); a fitted family answers
    its value, keyed by the DOMAIN's spellings (ability keys, skill keys).

    The ``*_text`` halves and ``feat_garbage`` are the fallback content:
    empty when nothing needs a block, the readable mirror of a present-but-
    unreadable section when it does — so nothing is silently lost even
    though the stored field stays empty («Черты» keeps its entries under
    the block name the document's own text blocks already merge into)."""

    #: The six scores keyed by ability, or None («не легло»: a partial set,
    #: a non-whole or out-of-band value, a stat key outside the six).
    scores: dict[str, int] | None = None
    #: The saving-throw proficiencies read from boolean ``save`` flags, or
    #: None when any flag was unreadable (a numeric modifier is the LSS
    #: sheet's own account — «Спасброски» keeps its block then).
    saving_throws: frozenset[str] | None = None
    #: The proficient skill keys, or None when a key outside the штатный
    #: list or a non-boolean ``proficient`` made the family unreadable.
    skill_proficiencies: frozenset[str] | None = None
    #: The slot grid «level → count», or None when an entry was outside the
    #: 1…9 levels / 0…99 counts or carried no whole count at all.
    spell_slots: dict[int, int] | None = None
    #: Speed in feet as the document spells it (a whole 0…1000), or None.
    speed: int | None = None
    #: Fallback block text for an unreadable speed («Скорость»).
    speed_text: str = ""
    #: The stored alignment, or None.
    alignment: str | None = None
    #: Fallback block text for an unreadable alignment («Мировоззрение»).
    alignment_text: str = ""
    #: The feat references in file order — ``(id, name)`` pairs; the import
    #: resolves them through the connected index like the five face links.
    feats: tuple[tuple[str, str], ...] = ()
    #: Feat entries the entry-level tolerance refused (their block lines).
    feat_garbage: tuple[object, ...] = ()

    @property
    def fitted_blocks(self) -> frozenset[str]:
        """The legacy block names the stored structure replaces — the render
        skips exactly these («не легшее — читаемые блоки как прежде» and
        never both halves of one family)."""
        names: set[str] = set()
        if self.scores is not None:
            names.add(BLOCK_STATS)
        if self.saving_throws is not None:
            names.add(BLOCK_SAVES)
        if self.skill_proficiencies is not None:
            names.add(BLOCK_SKILLS)
        if self.spell_slots is not None:
            names.add(BLOCK_SLOTS)
        return frozenset(names)


def parse_document_mechanics(data: dict[str, Any]) -> DocumentMechanics:
    """Read the storeable mechanics families out of a parsed character
    document (module docstring for the per-family rules). Pure and total:
    every shape answers a DocumentMechanics, garbage reads as «не легло»."""
    return DocumentMechanics(
        scores=_parse_scores(data),
        saving_throws=_parse_saving_throws(data),
        skill_proficiencies=_parse_skill_proficiencies(data),
        spell_slots=_parse_spell_slots(data),
        **_parse_speed(data),
        **_parse_alignment(data),
        **_parse_feats(data),
    )


def _parse_scores(data: dict[str, Any]) -> dict[str, int] | None:
    """All six canonical values or nothing — the storage gate is
    all-or-nothing («частичный набор не показывает полусчитанных строк»),
    and an extra stat key the card has no column for keeps the whole
    «Характеристики» block (an invented seventh score is not ours)."""
    raw = _document_dict(data, "stats")
    if not raw or set(raw) != set(LSS_STAT_TO_ABILITY):
        return None
    scores: dict[str, int] = {}
    for stat, ability in LSS_STAT_TO_ABILITY.items():
        entry = raw[stat]
        if not isinstance(entry, dict):
            return None
        value = entry.get("value")
        if not _is_whole(value) or not 1 <= value <= 30:
            return None
        scores[ability] = value
    return scores


def _parse_saving_throws(data: dict[str, Any]) -> frozenset[str] | None:
    """The boolean flags of the six canonical stats. Absent flags read as a
    fitted empty set (nothing proficient IS a fact the card stores); a
    numeric modifier or a foreign stat key is the sheet's own arithmetic —
    the family does not fit and its block survives."""
    raw = _document_dict(data, "stats")
    if any(key not in LSS_STAT_TO_ABILITY for key in raw):
        return None
    saves: set[str] = set()
    for stat, ability in LSS_STAT_TO_ABILITY.items():
        entry = raw.get(stat)
        if not isinstance(entry, dict) or "save" not in entry:
            continue
        flag = entry["save"]
        if not isinstance(flag, bool):
            return None
        if flag:
            saves.add(ability)
    return frozenset(saves)


def _parse_skill_proficiencies(data: dict[str, Any]) -> frozenset[str] | None:
    """The штатный skill keys with boolean ``proficient`` flags. A foreign
    slug or a non-boolean flag keeps the «Навыки» block (the render already
    prints what it can, invented translations stay invented)."""
    raw = _document_dict(data, "skills")
    if not raw:
        return frozenset()
    proficiencies: set[str] = set()
    for key, entry in raw.items():
        if key not in SKILL_ABILITIES or not isinstance(entry, dict):
            return None
        flag = entry.get("proficient")
        if flag is not None and not isinstance(flag, bool):
            return None
        if flag:
            proficiencies.add(key)
    return frozenset(proficiencies)


def _parse_spell_slots(data: dict[str, Any]) -> dict[int, int] | None:
    """The grid the «Заклинания» tab edits: ``max`` is the whole count the
    grid stores (``value`` rides the sheet's spent-half), the honest
    fallback being ``value`` alone. Outside 1…9 levels, 0…99 counts or a
    duplicated level the family does not fit — the block prints it as
    before."""
    spells = _document_dict(data, "spells")
    raw = spells.get("slots")
    if raw is None:
        return {}
    if not isinstance(raw, list):
        return None
    slots: dict[int, int] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            return None
        level = entry.get("level")
        if not _is_whole(level) or not 1 <= level <= 9 or level in slots:
            return None
        count = entry.get("max")
        if not _is_whole(count):
            count = entry.get("value")
        if not _is_whole(count) or not 0 <= count <= 99:
            return None
        slots[level] = count
    return slots


def _parse_speed(data: dict[str, Any]) -> dict[str, Any]:
    if "speed" not in data:
        return {"speed": None, "speed_text": ""}
    raw = data["speed"]
    if _is_whole(raw) and 0 <= raw <= 1000:
        return {"speed": raw, "speed_text": ""}
    if isinstance(raw, str) and not raw.strip():
        return {"speed": None, "speed_text": ""}
    text = raw.strip() if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    return {"speed": None, "speed_text": text}


def _parse_alignment(data: dict[str, Any]) -> dict[str, Any]:
    if "alignment" not in data:
        return {"alignment": None, "alignment_text": ""}
    raw = data["alignment"]
    known = _normalize_alignment(raw)
    if known is not None:
        return {"alignment": known, "alignment_text": ""}
    if isinstance(raw, str) and not raw.strip():
        return {"alignment": None, "alignment_text": ""}
    text = raw.strip() if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    return {"alignment": None, "alignment_text": text}


def _parse_feats(data: dict[str, Any]) -> dict[str, Any]:
    """Per-entry tolerance like the face links: a well-formed ``{"id": …}``
    reference rides the feat list, anything else falls back to a «Черты»
    block line. An absent section answers the empty list — the file replaces
    the card, so chosen feats the file does not name are un-chosen."""
    if "feats" not in data:
        return {"feats": (), "feat_garbage": ()}
    raw = data["feats"]
    if not isinstance(raw, list):
        return {"feats": (), "feat_garbage": (raw,)}
    feats: list[tuple[str, str]] = []
    garbage: list[object] = []
    for entry in raw:
        if not isinstance(entry, dict):
            garbage.append(entry)
            continue
        ref_id = entry.get("id")
        if not isinstance(ref_id, str) or not ref_id.strip():
            garbage.append(entry)
            continue
        name = entry.get("name")
        feats.append((ref_id.strip(), name.strip() if isinstance(name, str) else ""))
    return {"feats": tuple(feats), "feat_garbage": tuple(garbage)}
