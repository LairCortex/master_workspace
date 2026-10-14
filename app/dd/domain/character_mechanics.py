"""Structured D&D mechanics — Qt-free formulas and gates (dd-card-redesign
task 2.1, design Д7; spec dnd-character-mechanics).

Design Д7: the presentation and the export call ONLY this module for every
derived number — the stored columns (dd_models) hold the manual facts, the
derived values are never persisted (design Д6 «Производные значения НЕ
хранятся — чистая функция»). The formulas are the spec's, verbatim:

* modifier = (value − 10) / 2 rounded DOWN (spec «модификатор = (значение −
  10) / 2 с округлением вниз» — Python's floor division is exactly that,
  including the negative half: Сила 8 → −1, Сила 1 → −5);
* proficiency bonus by level: 1–4 → +2, 5–8 → +3, 9–12 → +4, 13–16 → +5,
  17–20 → +6, no level → +2 (spec «без уровня → +2», scenario «Без уровня
  бонус мастерства минимальный»);
* check = modifier; save = modifier + proficiency bonus when proficient;
  skill = same with the skill's own proficiency; passive sense = 10 + skill;
* jumps and carry (spec scenario «Сила 16 кормит и прыгает»): carry = 15 ×
  the VALUE (not the modifier — design risk «вес от значения, а не
  модификатора» fixed by the owner), long jump = the value, standing = half
  the value (whole feet: floor), high jump = 3 + the modifier.

The skill list and the passive-sense trio are the штатный D&D sets the spec
names; the Russian captions live in the module's presentation, this table is
the ONE knowledge of which skill rides which ability (coding principle 2).
Saving-throw proficiency resolves per design Д8: a class record that names
its saves owns them (recomputed at every read, so a dataset swap breaks no
stored data), otherwise the stored manual set answers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

from app.dd.domain.character import LEVEL_MAX, LEVEL_MIN

if TYPE_CHECKING:
    from app.dd.domain.character import DdCharacterExt

# ── the six abilities (spec «шесть значений характеристик») ─────────────────

#: LSS document/dataset spellings of the six abilities → the mechanics keys
#: this module addresses them by (dd-card-redesign task 6.1/6.2). The dataset
#: records spell saving-throw grants with the LSS keys, the import reads
#: ``stats`` with them and the export writes them back; the Russian captions
#: of both spellings ride :mod:`app.dd.domain.character_render` (one
#: knowledge, one place — moved out of the presentation so the document
#: builder reaches it without touching the UI layer).
LSS_STAT_TO_ABILITY: dict[str, str] = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}

#: The inverse — the export's one door from a stored score to the document's
#: stat key (derived from the table above, so the spellings cannot drift).
ABILITY_TO_LSS_STAT: dict[str, str] = {
    ability: stat for stat, ability in LSS_STAT_TO_ABILITY.items()
}

#: Storage/domain keys of the six abilities, in the order the table prints.
ABILITY_KEYS: tuple[str, ...] = (
    "strength",
    "dexterity",
    "constitution",
    "intelligence",
    "wisdom",
    "charisma",
)

#: The value band the spec fixes for every characteristic: «в полосе 1…30
#: каждое». The UI gate, the service gate and the tests all read this pair.
ABILITY_MIN = 1
ABILITY_MAX = 30

# ── the штатный skill list (spec «штатный список навыков D&D») ─────────────

#: skill key → ability key, grouped by ability in the order the card prints
#: each ability's skills under it (spec «Под каждой характеристикой SHALL
#: печататься штатный список навыков D&D»).
SKILL_ABILITIES: dict[str, str] = {
    "athletics": "strength",
    "acrobatics": "dexterity",
    "sleight_of_hand": "dexterity",
    "stealth": "dexterity",
    "arcana": "intelligence",
    "history": "intelligence",
    "investigation": "intelligence",
    "nature": "intelligence",
    "religion": "intelligence",
    "animal_handling": "wisdom",
    "insight": "wisdom",
    "medicine": "wisdom",
    "perception": "wisdom",
    "survival": "wisdom",
    "deception": "charisma",
    "intimidation": "charisma",
    "performance": "charisma",
    "persuasion": "charisma",
}

#: The «Пассивные чувства» trio the spec names (right-hand block, no input
#: fields): each = 10 + the named skill's value (proficiency included).
PASSIVE_SENSE_SKILLS: tuple[str, ...] = ("perception", "insight", "investigation")

# ── alignment (spec «Вкладка „Личность“», fixed nine + unset) ──────────────

#: The nine D&D alignments in the spec's wording; «не задано» is the absence
#: of the stored value (None), never a tenth entry (scenario «Девять
#: мировоззрений и „не задано“»).
ALIGNMENTS: tuple[str, ...] = (
    "законно-добрый",
    "нейтрально-добрый",
    "хаотично-добрый",
    "законно-нейтральный",
    "истинно нейтральный",
    "хаотично-нейтральный",
    "законно-злой",
    "нейтрально-злой",
    "хаотично-злой",
)

# ── spell slots (spec «сетка ячеек… 0…99», «не задано») ────────────────────

SLOT_LEVEL_MIN = 1
SLOT_LEVEL_MAX = 9
SLOT_COUNT_MIN = 0
SLOT_COUNT_MAX = 99

# ── refusals (the module's message posture: the reader reads what is wrong) ─

SCORES_REFUSAL = "значения шести характеристик — полный набор, целое от 1 до 30"
SLOTS_REFUSAL = "ячейки заклинаний — целое от 0 до 99 на уровнях от 1 до 9"
ALIGNMENT_REFUSAL = "мировоззрение — одно из девяти или не задано"
SKILLS_REFUSAL = "навык для владения берётся из штатного списка навыков"
SAVING_THROWS_REFUSAL = "спасбросок для владения — одна из шести характеристик"
PROFICIENCY_LEVEL_REFUSAL = "уровень для бонуса мастерства — целое от 1 до 20 или не задан"


# ── formulas (design Д7 «чистая функция») ──────────────────────────────────


def ability_modifier(score: int) -> int:
    """(value − 10) / 2 rounded DOWN — floor division is spec's rounding for
    both signs: 16 → +3, 10 and 11 → 0, 8 → −1, 1 → −5, 30 → +10."""
    return (score - 10) // 2


def proficiency_bonus(level: int | None) -> int:
    """The level bands of the spec (+2 … +6 over 1…20); an unset level rides
    the minimal +2 (scenario «Без уровня бонус мастерства минимальный»)."""
    if level is None:
        return 2
    if isinstance(level, bool) or not isinstance(level, int):
        raise ValueError(PROFICIENCY_LEVEL_REFUSAL)
    if not LEVEL_MIN <= level <= LEVEL_MAX:
        raise ValueError(PROFICIENCY_LEVEL_REFUSAL)
    # 1–4 → 2, 5–8 → 3, 9–12 → 4, 13–16 → 5, 17–20 → 6 — one arithmetic
    # form of the five spec bands, no per-band table to drift from it.
    return 2 + (level - 1) // 4


def check_value(score: int) -> int:
    """«Проверка» = the modifier (spec: «проверка» = модификатор)."""
    return ability_modifier(score)


def _proficiency_part(proficiency_bonus_value: int, proficient: bool) -> int:
    """The whole proficiency bonus rides only a proficient line — the one
    arithmetic seat shared by saves, skills and passive senses."""
    return proficiency_bonus_value if proficient else 0


def saving_throw_value(
    score: int, proficiency_bonus_value: int, proficient: bool
) -> int:
    """«Спасбросок» = modifier + proficiency bonus when proficient."""
    return ability_modifier(score) + _proficiency_part(
        proficiency_bonus_value, proficient
    )


def skill_value(
    score: int, proficiency_bonus_value: int, proficient: bool
) -> int:
    """A skill value = the ability modifier + proficiency bonus when the
    skill's circle is switched on."""
    return ability_modifier(score) + _proficiency_part(
        proficiency_bonus_value, proficient
    )


def passive_sense_value(
    score: int, proficiency_bonus_value: int, proficient: bool
) -> int:
    """Passive sense = 10 + the skill value (spec scenario: switching the
    skill moves the passive sense by exactly the same bonus)."""
    return 10 + skill_value(score, proficiency_bonus_value, proficient)


# ── jumps and carry (spec «Скорость вводится, прыжки и вес считаются») ────


@dataclass(frozen=True)
class JumpsAndCarry:
    """The four computed numbers printed under the abilities. Speed is NOT
    one of them: it is the master's own stored figure, shown next to these
    for reference only (spec «от скорости НЕ SHALL зависеть»)."""

    carry_limit_pounds: int
    long_jump_feet: int
    standing_long_jump_feet: int
    high_jump_feet: int


def jumps_and_carry(strength: int) -> JumpsAndCarry:
    """The spec's four formulas on the STRENGTH VALUE: carry = 15 × value,
    long jump = value feet, standing jump = half the value (whole feet —
    half of an odd value rounds down), high jump = 3 + modifier. Scenario
    «Сила 16 кормит и прыгает»: 240 / 16 / 8 / 4 is reproduced exactly."""
    return JumpsAndCarry(
        carry_limit_pounds=15 * strength,
        long_jump_feet=strength,
        standing_long_jump_feet=strength // 2,
        high_jump_feet=3 + ability_modifier(strength),
    )


# ── saving-throw ownership (design Д8) ─────────────────────────────────────


def resolve_saving_throw_profs(
    class_saves: Sequence[str] | None, manual: Iterable[str]
) -> frozenset[str]:
    """Design Д8 / spec «Владение спасбросками — от класса, без класса
    свободно»: a class record that names its saves owns them (the caller
    hands what the connected dataset's class record says, so a class switch
    or a dataset removal is re-resolved at every read and no stored data is
    ever rewritten); an unnamed/absent class falls back to the manual set
    the master switched by hand."""
    if class_saves:
        return frozenset(class_saves)
    return frozenset(manual)


def class_record_saving_throws(
    ext: "DdCharacterExt", snap: Any
) -> tuple[str, ...] | None:
    """Design Д8's read of the connected dataset: the saves the chosen
    class's record names, or ``None`` when no class is linked, its source is
    disconnected or its record names none (the manual switches' domain).

    The traversal follows the schema's grant homes (the ``grants`` list and
    the leveled ``leveledGrants`` blocks, recursing through ``pick-one``
    options — the :mod:`app.dd.domain.lss_checks` walk, restated read-only
    for this one question); ``saving-throw`` grants spell their stats with
    the LSS keys, translated through :data:`LSS_STAT_TO_ABILITY`, unknown
    keys dropped rather than guessed. Moved out of the presentation in
    dd-card-redesign task 6.2: the document builder resolves the same answer
    the card paints, and the application layer never reaches into its UI."""
    link = ext.links.get("class")
    if link is None or not link.is_set:
        return None
    entry = snap.entry("classes", link.source_key, link.ref_id)
    if entry is None:
        return None
    found: list[str] = []

    def walk(items: object) -> None:
        if not isinstance(items, list):
            return
        for grant in items:
            if not isinstance(grant, dict):
                continue
            if grant.get("type") == "saving-throw":
                stats = grant.get("stats")
                if isinstance(stats, list):
                    for stat in stats:
                        ability = LSS_STAT_TO_ABILITY.get(stat)
                        if ability is not None and ability not in found:
                            found.append(ability)
            elif grant.get("type") == "pick-one":
                options = grant.get("options")
                if isinstance(options, list):
                    for option in options:
                        if isinstance(option, dict):
                            walk(option.get("grants"))

    record = entry.record
    walk(record.get("grants"))
    leveled = record.get("leveledGrants")
    if isinstance(leveled, list):
        for block in leveled:
            if isinstance(block, dict):
                walk(block.get("grants"))
    return tuple(found) if found else None


# ── write gates (the service validates through these before any row) ───────


def validate_ability_scores(
    scores: Mapping[str, int] | None,
) -> dict[str, int] | None:
    """The all-or-nothing gate (spec «Непустой набор шести значений SHALL
    храниться целиком или не храниться вовсе»): ``None``/empty clears the
    set; a non-empty mapping must carry all six keys with whole 1…30
    values — a partial set is refused, never half-stored."""
    if not scores:
        return None
    result: dict[str, int] = {}
    for key in ABILITY_KEYS:
        value = scores.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(SCORES_REFUSAL)
        if not ABILITY_MIN <= value <= ABILITY_MAX:
            raise ValueError(SCORES_REFUSAL)
        result[key] = value
    return result


def validate_spell_slots(slots: Mapping[int, int] | None) -> dict[int, int]:
    """The slots grid gate: whole counts 0…99 on levels 1…9; empty reads as
    «не задано» (the stored column goes NULL). Returned in level order so
    the stored JSON is deterministic."""
    result: dict[int, int] = {}
    if not slots:
        return result
    for level, count in slots.items():
        for value in (level, count):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(SLOTS_REFUSAL)
        if not SLOT_LEVEL_MIN <= level <= SLOT_LEVEL_MAX:
            raise ValueError(SLOTS_REFUSAL)
        if not SLOT_COUNT_MIN <= count <= SLOT_COUNT_MAX:
            raise ValueError(SLOTS_REFUSAL)
        result[level] = count
    return {level: result[level] for level in sorted(result)}


def validate_alignment(alignment: str | None) -> str | None:
    """The fixed nine or unset — «ручного ввода нет» reaches storage as a
    refusal of anything outside the list."""
    if alignment is None or alignment == "":
        return None
    if alignment not in ALIGNMENTS:
        raise ValueError(ALIGNMENT_REFUSAL)
    return alignment


def validate_skill_keys(skills: Iterable[str]) -> frozenset[str]:
    """Only the штатный list is ownable; an unknown key is a caller bug and
    is refused rather than silently dropped."""
    validated = frozenset(skills)
    unknown = validated - SKILL_ABILITIES.keys()
    if unknown:
        raise ValueError(SKILLS_REFUSAL)
    return validated


def validate_saving_throw_keys(saves: Iterable[str]) -> frozenset[str]:
    """Only the six abilities own a saving throw."""
    validated = frozenset(saves)
    if not validated <= set(ABILITY_KEYS):
        raise ValueError(SAVING_THROWS_REFUSAL)
    return validated


# ── the read value of the mechanics block (character_mechanics storage face) ─


@dataclass(frozen=True)
class CharacterMechanics:
    """The mechanics block as read: the stored manual facts only (derived
    numbers are computed by the formulas above at every render).

    ``scores`` is the all-or-nothing set (design Д6 posture: a row whose
    six columns are not all present reads as ``None`` — «частичный набор не
    показывает полусчитанных строк»); ``spell_slots`` is empty while no
    level was ever set («не задано»); ``manual_saving_throws`` is the
    master's own switch set, used when the class does not own the saves."""

    scores: dict[str, int] | None = None
    speed: int | None = None
    alignment: str | None = None
    spell_slots: dict[int, int] = field(default_factory=dict)
    skill_proficiencies: frozenset[str] = frozenset()
    manual_saving_throws: frozenset[str] = frozenset()


def empty_mechanics() -> CharacterMechanics:
    """The value an absent (or never-mechanicked) row reads as."""
    return CharacterMechanics()


# ── «Личность» (dd-card-redesign task 5.3, design Д6; spec dnd-character-
# mechanics «Вкладка „Личность“ — набор полей») ──────────────────────────────

#: The «Личность» one-line fields as (stable ASCII key, Russian caption).
#: The caption is the storage key in the existing ``text_blocks`` column
#: (design Д6: «стабильные ключи в существующем text_blocks») — «Личность»
#: grows no second store; the importer/exporter (group 6) speak the very
#: same block names. The ASCII half names the offscreen tests' widgets.
PERSONALITY_SHORT_FIELDS: tuple[tuple[str, str], ...] = (
    ("height", "Рост"),
    ("weight", "Вес"),
    ("age", "Возраст"),
    ("eyes", "Глаза"),
    ("skin", "Кожа"),
    ("hair", "Волосы"),
)

#: The «Личность» multi-line fields, same shape. «Предыстория персонажа» is
#: the free-text block and shares nothing with the «Предыстория» dataset
#: LINK of the same tab (spec: «тот же механизм ссылки, что у класса»).
PERSONALITY_LONG_FIELDS: tuple[tuple[str, str], ...] = (
    ("appearance", "Внешность"),
    ("backstory", "Предыстория персонажа"),
    ("allies", "Союзники и организации"),
    ("traits", "Черты характера"),
    ("ideals", "Идеалы"),
    ("bonds", "Привязанности"),
    ("flaws", "Слабости"),
    ("goals", "Цели"),
)
