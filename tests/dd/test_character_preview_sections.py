"""The preview mirror's one wording seat (dd-card-redesign task 7.1,
design Д5; spec entity-preview «Секции модуля зеркалят карточку в
предпросмотре»).

The builder is a pure function over already-read values, so these are plain
unit tests (no Qt, no DB): every spec bullet gets its line shape reproduced
verbatim — «Сила 16: проверка +3, спасбросок +5», the saving-throw ownership
of design Д8, «монстр × количество», the card's «источник не подключён»
annotation on a dead link — and the absence posture (an empty half prints no
titled section) is pinned per half. The encounter builder shares the file
because it shares the section record and the «empty prints nothing» rule.
"""
from __future__ import annotations

from app.dd.application.dataset_index_service import DatasetEntry, IndexSnapshot
from dataclasses import replace

from app.dd.domain.character import (
    DdFeatLink,
    DdSpellLink,
    ReferenceLink,
    empty_ext,
)
from app.dd.domain.character_mechanics import CharacterMechanics
from app.dd.presentation.character_preview_sections import (
    ALIGNMENT_LINE_PREFIX,
    NOTE_LINE_PREFIX,
    build_character_sections,
    build_encounter_sections,
)
from app.dd.presentation.character_tab_frames import SOURCE_UNAVAILABLE_NOTE
from app.presentation.modules.protocol import ModuleSection

_RECORD_LABELS = {
    "dd_race": "Вид",
    "dd_subrace": "Подвид",
    "dd_class": "Класс",
    "dd_subclass": "Подкласс",
    "dd_background": "Предыстория",
}


def _snap(with_class_record: bool = False, feats_alive: bool = True) -> IndexSnapshot:
    class_record: dict = {}
    if with_class_record:
        class_record["grants"] = [
            {"type": "saving-throw", "stats": ["str", "con"]}
        ]
    feats: tuple[DatasetEntry, ...] = ()
    if feats_alive:
        feats = (DatasetEntry("srd", "alert", "Бдительность", {}),)
    return IndexSnapshot(
        ids=("srd",),
        titles={"srd": "SRD-5.1"},
        sections={
            "races": {"srd": (DatasetEntry("srd", "dwarf", "Дворф", {}),)},
            "subraces": {"srd": (DatasetEntry("srd", "mountain", "Горный", {}),)},
            "classes": {"srd": (DatasetEntry("srd", "fighter", "Воин", class_record),)},
            "subclasses": {},
            "backgrounds": {},
            "feats": {"srd": feats},
        },
        slugs={},
    )


def _full_ext():
    ext = empty_ext()
    ext.links["race"] = ReferenceLink("srd", "dwarf", "Дворф")
    ext.links["class"] = ReferenceLink("srd", "fighter", "Воин")
    return replace(ext, level=3)


def _build(**overrides):
    args = dict(
        ext=_full_ext(),
        mech=CharacterMechanics(),
        feats=(),
        spells=(),
        blocks={},
        snap=_snap(),
        record_labels=_RECORD_LABELS,
    )
    args.update(overrides)
    return build_character_sections(**args)


def _titles(sections) -> list[str]:
    return [section.title for section in sections]


def test_everything_empty_prints_nothing():
    """A fresh character with no mechanics is a mirror of silence: no titled
    empty block ever reaches the column (the standing absence posture)."""
    ext = empty_ext()
    assert _build(ext=ext, mech=CharacterMechanics()) == ()


def test_origin_mirrors_the_main_slots_and_level_with_the_card_annotation():
    """The four «Основное» slots (the background belongs to «Личность», not
    here) plus the level, dead links annotated per the card's reading rule."""
    sections = _build()
    origin = sections[0]
    assert origin.title == "Происхождение"
    assert origin.lines == ("Вид: Дворф", "Класс: Воин", "Уровень: 3")
    # A link whose record died with its dataset rides the card's reading
    # rule, not a stored mark.
    ext = empty_ext()
    ext.links["background"] = ReferenceLink("gone", "soldier", "Солдат")
    assert _build(ext=ext) == ()  # the background slot alone prints nothing
    dead_class = _full_ext()
    dead_class.links["class"] = ReferenceLink("srd", "warlock", "Колдун")
    (origin2,) = [s for s in _build(ext=dead_class) if s.title == "Происхождение"]
    assert origin2.lines[1] == f"Класс: Колдун — {SOURCE_UNAVAILABLE_NOTE}"
    # No level — the level line is absent, the link lines stand.
    no_level = replace(_full_ext(), level=None)
    (origin3,) = [s for s in _build(ext=no_level) if s.title == "Происхождение"]
    assert origin3.lines == ("Вид: Дворф", "Класс: Воин")


def test_abilities_skills_passives_and_physical_follow_the_card_formulas():
    mech = CharacterMechanics(
        scores={
            "strength": 16,
            "dexterity": 14,
            "constitution": 15,
            "intelligence": 10,
            "wisdom": 12,
            "charisma": 8,
        },
        speed=30,
        skill_proficiencies=frozenset({"perception", "athletics"}),
    )
    sections = _build(mech=mech, snap=_snap(with_class_record=True))
    by_title = {section.title: section for section in sections}
    # The design's verbatim shape «Сила 16: проверка +3, спасбросок +5» —
    # the class record (Д8) owns the saves: str/con are the proficient pair.
    assert by_title["Характеристики"].lines[0] == (
        "Сила 16: проверка +3, спасбросок +5"
    )
    assert by_title["Характеристики"].lines[5] == (
        "Харизма 8: проверка -1, спасбросок -1"
    )
    # Skills: only the switched-on circles, value plus the owning ability,
    # printed in the sheet order (athletics rides its strength first).
    assert by_title["Навыки"].lines == (
        "Атлетика: +5 (Сила)",
        "Восприятие: +3 (Мудрость)",
    )
    assert by_title["Пассивные чувства"].lines == (
        "Восприятие 13 · Проницательность 11 · Расследование 10",
    )
    assert by_title["Прыжки, вес и скорость"].lines == (
        "Переносимый максимум: 240 фн",
        "Прыжки: с разбега 16 фт · с места 8 фт · в высоту 6 фт",
        "Скорость: 30 фт",
    )


def test_manual_saves_answer_without_a_class_record():
    """Д8's fallback: the class names no saves (no record here) — the
    master's own switch set decides the proficient pair."""
    mech = CharacterMechanics(
        scores=dict(
            zip(
                ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"),
                (10, 10, 10, 10, 10, 10),
            )
        ),
        manual_saving_throws=frozenset({"dexterity"}),
    )
    sections = _build(mech=mech)
    by_title = {section.title: section for section in sections}
    assert by_title["Характеристики"].lines[1] == (
        "Ловкость 10: проверка +0, спасбросок +2"
    )
    assert by_title["Характеристики"].lines[0] == (
        "Сила 10: проверка +0, спасбросок +0"
    )


def test_derived_halves_stay_silent_without_the_score_set():
    """Д6 «полусчитанных строк нет»: no six-score set — no abilities, no
    skills, no passives, no jumps; only the master's own speed still speaks."""
    sections = _build(mech=CharacterMechanics(speed=25))
    titles = _titles(sections)
    assert "Характеристики" not in titles
    assert "Навыки" not in titles
    assert "Пассивные чувства" not in titles
    physical = next(s for s in sections if s.title == "Прыжки, вес и скорость")
    assert physical.lines == ("Скорость: 25 фт",)


def test_feats_personality_and_spells_sections():
    ext = _full_ext()
    mech = CharacterMechanics(
        alignment="истинно нейтральный",
        spell_slots={1: 4, 2: 3},
    )
    sections = _build(
        ext=ext,
        mech=mech,
        feats=(
            DdFeatLink("srd", "alert", "Бдительность"),
            DdFeatLink("srd", "gone", "Снятая черта"),
        ),
        spells=(DdSpellLink("srd", "fireball", "Огненный шар"),),
        blocks={"Возраст": "47", "Глаза": "серые", "Волосы": "  "},
    )
    by_title = {section.title: section for section in sections}
    assert by_title["Черты"].lines == (
        "Бдительность",
        f"Снятая черта — {SOURCE_UNAVAILABLE_NOTE}",
    )
    assert by_title["Личность"].lines == (
        f"{ALIGNMENT_LINE_PREFIX}: истинно нейтральный",
        "Возраст: 47",
        "Глаза: серые",
    )
    assert by_title["Заклинания"].lines == (
        "Огненный шар",
        "Ячейки: 1 — 4 · 2 — 3",
    )


def test_sections_are_protocol_records():
    """The channel shape is the protocol's frozen record («title + plain
    lines»), so the kernel paints it without knowing the module."""
    sections = _build()
    assert sections  # origin alone at minimum
    assert all(isinstance(section, ModuleSection) for section in sections)


# ── the event mirror ─────────────────────────────────────────────────────────


class _Entry:
    def __init__(self, name_snapshot: str, count: int) -> None:
        self.name_snapshot = name_snapshot
        self.count = count


class _Encounter:
    def __init__(self, entries, note: str) -> None:
        self.entries = tuple(entries)
        self.note = note


def test_no_encounter_prints_no_section():
    assert build_encounter_sections(None) == ()
    # The storage posture «пустой состав = нет встречи» also lands on the
    # empty answer: an overlay row list plus no note is an empty section,
    # which is no section.
    assert build_encounter_sections(_Encounter([], "")) == ()


def test_encounter_lists_monsters_and_note():
    (section,) = build_encounter_sections(
        _Encounter(
            [_Entry("Гоблин", 4), _Entry("Трогллод", 1)],
            "Засада у брода",
        )
    )
    assert section.title == "Встреча"
    assert section.lines == (
        "Гоблин × 4",
        "Трогллод × 1",
        f"{NOTE_LINE_PREFIX}: Засада у брода",
    )


def test_encounter_without_note_omits_the_note_line():
    (section,) = build_encounter_sections(_Encounter([_Entry("Волк", 2)], ""))
    assert section.lines == ("Волк × 2",)
