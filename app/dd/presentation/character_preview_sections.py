"""The module's read-only mirror sections for the preview column
(dd-card-redesign task 7.1, design Д5; spec entity-preview «Секции модуля
зеркалят карточку в предпросмотре»).

A source's ``module_sections`` door hands the kernel a tuple of
:class:`~app.presentation.modules.protocol.ModuleSection` records — «title +
plain lines», painted under the kernel fields as one scrolling list. This
module is the one seat that composes those lines; it is a pure function over
already-read values, so the door behind it stays one locked read and the
wording lives in exactly one place.

The character set mirrors the card (design Д5, verbatim bullets):

* «Происхождение» — the four «Основное» link slots (вид/подвид/класс/
  подкласс) and the level; a link whose dataset went away rides the card's
  «источник не подключён» annotation (the card's reading rule, not a stored
  mark);
* «Характеристики» — one line per ability in the sheet order, in the
  design's shape «Сила 16: проверка +3, спасбросок +5» (saving-throw
  proficiency resolved per design Д8 exactly as the card's table does);
* «Навыки» — only the skills the character is proficient in, each with its
  derived value and its ability;
* «Пассивные чувства» — the штатный trio on one line, the card's join;
* «Прыжки, вес и скорость» — the strength-fed numbers plus the stored
  speed (the speed stays the master's own figure, never a derivation);
* «Черты» — one line per feat link, the dead-source annotation as in the
  feats tab;
* «Личность» — the alignment plus the «Личность» text-block fields, in the
  personality frame's field order (blocks are keyed by their captions);
* «Заклинания» — one line per spell link plus the slot grid on one line.

An empty half prints no section (the preview's standing absence posture,
«Поля, отсутствующие у типа сущности SHALL не выводиться»): a character with
nothing filled shows no module sections, while the hidden kernel texts are
the door's separate, sync ``module_blocks`` answer.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from app.dd.domain.character import FEATS_SECTION, LINK_SLOTS
from app.dd.domain.character_mechanics import (
    ABILITY_KEYS,
    PASSIVE_SENSE_SKILLS,
    PERSONALITY_LONG_FIELDS,
    PERSONALITY_SHORT_FIELDS,
    SKILL_ABILITIES,
    check_value,
    class_record_saving_throws,
    jumps_and_carry,
    passive_sense_value,
    proficiency_bonus,
    resolve_saving_throw_profs,
    saving_throw_value,
    skill_value,
)
from app.dd.domain.character_render import SKILL_LABELS
from app.dd.presentation.character_main_blocks import (
    ABILITY_LABELS,
    MAIN_LINK_SLOTS,
)
from app.dd.presentation.character_tab_frames import SOURCE_UNAVAILABLE_NOTE

if TYPE_CHECKING:
    from app.dd.application.dataset_index_service import IndexSnapshot
    from app.dd.domain.character import DdCharacterExt, DdFeatLink, DdSpellLink
    from app.dd.domain.character_mechanics import CharacterMechanics
    from app.presentation.modules.protocol import ModuleSection

# ── the fixed section captions (spec «набор секций SHALL зеркалить
# карточку»; the tests and the roadmap read these words) ─────────────────────

ORIGIN_SECTION_TITLE = "Происхождение"
ABILITIES_SECTION_TITLE = "Характеристики"
SKILLS_SECTION_TITLE = "Навыки"
PASSIVES_SECTION_TITLE = "Пассивные чувства"
PHYSICAL_SECTION_TITLE = "Прыжки, вес и скорость"
FEATS_SECTION_TITLE = "Черты"
PERSONALITY_SECTION_TITLE = "Личность"
SPELLS_SECTION_TITLE = "Заклинания"

#: The event mirror's one section — the spec dnd-encounters word, the tab
#: caption (the character builder never prints it; the encounter door does).
ENCOUNTER_SECTION_TITLE = "Встреча"

#: Line prefixes inside the sections (one seat, the tests read them here).
LEVEL_LINE_PREFIX = "Уровень"
SPEED_LINE_PREFIX = "Скорость"
CARRY_LINE_PREFIX = "Переносимый максимум"
JUMPS_LINE_PREFIX = "Прыжки"
ALIGNMENT_LINE_PREFIX = "Мировоззрение"
SLOTS_LINE_PREFIX = "Ячейки"
NOTE_LINE_PREFIX = "Заметка"
CHECK_PART_PREFIX = "проверка"
SAVE_PART_PREFIX = "спасбросок"

#: The dataset section a link slot reads (the card's dead-link rule: the
#: record must answer in the current snapshot, coding principle 2 rides
#: LINK_SLOTS — the same table the picker walks).
_SLOT_SECTIONS: dict[str, str] = {slot: section for slot, section, _t in LINK_SLOTS}


def _section(title: str, lines: Sequence[str]):
    """One section, or ``None`` when it would print nothing — an empty
    titled block never reaches the column (the absence posture)."""
    if not lines:
        return None
    from app.presentation.modules.protocol import ModuleSection

    return ModuleSection(title=title, lines=tuple(lines))


def _dead(section: str, snap: "IndexSnapshot", source_key: str, ref_id: str) -> bool:
    """Whether a stored link's record is unreachable now (its set
    disconnected or its record gone) — the card's annotation rule."""
    return snap.entry(section, source_key, ref_id) is None


def build_character_sections(
    *,
    ext: "DdCharacterExt",
    mech: "CharacterMechanics",
    feats: Sequence["DdFeatLink"],
    spells: Sequence["DdSpellLink"],
    blocks: Mapping[str, str],
    snap: "IndexSnapshot",
    record_labels: Mapping[str, str],
) -> "tuple[ModuleSection, ...]":
    """The whole mirror of one character, in the card's reading order. Every
    argument is a value the door already read under the session lock;
    nothing here touches storage."""
    sections: list = []

    origin: list[str] = []
    for slot, _section_key, type_key in MAIN_LINK_SLOTS:
        link = ext.links[slot]
        if not link.is_set:
            continue
        label = record_labels.get(type_key, type_key)
        line = f"{label}: {link.snapshot_name}"
        if _dead(_SLOT_SECTIONS[slot], snap, link.source_key, link.ref_id):
            line += f" — {SOURCE_UNAVAILABLE_NOTE}"
        origin.append(line)
    if ext.level is not None:
        origin.append(f"{LEVEL_LINE_PREFIX}: {ext.level}")
    sections.append(_section(ORIGIN_SECTION_TITLE, origin))

    if mech.scores is not None:
        scores = mech.scores
        bonus = proficiency_bonus(ext.level)
        saves = resolve_saving_throw_profs(
            class_record_saving_throws(ext, snap), mech.manual_saving_throws
        )
        sections.append(
            _section(
                ABILITIES_SECTION_TITLE,
                [
                    f"{ABILITY_LABELS[ability]} {scores[ability]}: "
                    f"{CHECK_PART_PREFIX} {check_value(scores[ability]):+d}, "
                    f"{SAVE_PART_PREFIX} "
                    f"{saving_throw_value(scores[ability], bonus, ability in saves):+d}"
                    for ability in ABILITY_KEYS
                ],
            )
        )
        sections.append(
            _section(
                SKILLS_SECTION_TITLE,
                [
                    f"{SKILL_LABELS[skill]}: "
                    f"{skill_value(scores[SKILL_ABILITIES[skill]], bonus, True):+d} "
                    f"({ABILITY_LABELS[SKILL_ABILITIES[skill]]})"
                    for skill in sorted(
                        mech.skill_proficiencies, key=list(SKILL_ABILITIES).index
                    )
                ],
            )
        )
        prof = mech.skill_proficiencies
        sections.append(
            _section(
                PASSIVES_SECTION_TITLE,
                [
                    " · ".join(
                        f"{SKILL_LABELS[skill]} "
                        f"{passive_sense_value(scores[SKILL_ABILITIES[skill]], bonus, skill in prof)}"
                        for skill in PASSIVE_SENSE_SKILLS
                    )
                ],
            )
        )
        jumps = jumps_and_carry(scores["strength"])
        physical = [
            f"{CARRY_LINE_PREFIX}: {jumps.carry_limit_pounds} фн",
            f"{JUMPS_LINE_PREFIX}: с разбега {jumps.long_jump_feet} фт · "
            f"с места {jumps.standing_long_jump_feet} фт · "
            f"в высоту {jumps.high_jump_feet} фт",
        ]
    else:
        # No score set: the derived halves stay silent (the card prints the
        # empty table, the mirror prints nothing — Д6 «полусчитанных строк
        # нет»), only the master's own speed can still speak.
        physical = []
    if mech.speed is not None:
        physical.append(f"{SPEED_LINE_PREFIX}: {mech.speed} фт")
    sections.append(_section(PHYSICAL_SECTION_TITLE, physical))

    feat_lines = []
    for feat in feats:
        line = feat.snapshot_name
        if _dead(FEATS_SECTION, snap, feat.source_key, feat.ref_id):
            line += f" — {SOURCE_UNAVAILABLE_NOTE}"
        feat_lines.append(line)
    sections.append(_section(FEATS_SECTION_TITLE, feat_lines))

    personality = []
    if mech.alignment:
        personality.append(f"{ALIGNMENT_LINE_PREFIX}: {mech.alignment}")
    for _key, caption in (*PERSONALITY_SHORT_FIELDS, *PERSONALITY_LONG_FIELDS):
        text = (blocks.get(caption) or "").strip()
        if text:
            personality.append(f"{caption}: {text}")
    sections.append(_section(PERSONALITY_SECTION_TITLE, personality))

    spell_lines = [spell.snapshot_name for spell in spells]
    if mech.spell_slots:
        spell_lines.append(
            f"{SLOTS_LINE_PREFIX}: "
            + " · ".join(
                f"{level} — {count}"
                for level, count in sorted(mech.spell_slots.items())
            )
        )
    sections.append(_section(SPELLS_SECTION_TITLE, spell_lines))

    return tuple(section for section in sections if section is not None)


def build_encounter_sections(encounter) -> "tuple[ModuleSection, ...]":
    """The event's one «Встреча» section (spec «видна секция „Встреча" с
    перечнем „монстр × количество" и заметкой»); a ``None`` encounter —
    «встречи нет» — prints nothing (the module's honest absence, the same
    posture as an unmarked ladder)."""
    if encounter is None:
        return ()
    lines = [f"{entry.name_snapshot} × {entry.count}" for entry in encounter.entries]
    if encounter.note:
        lines.append(f"{NOTE_LINE_PREFIX}: {encounter.note}")
    section = _section(ENCOUNTER_SECTION_TITLE, lines)
    return (section,) if section is not None else ()
