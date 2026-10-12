"""Единая нотация пути отчёта (fix-dnd-followups, задача 3.1; design Д3;
spec dnd-dataset-validator «Путь ведёт к месту в одной нотации»).

Guard-тест: каждая запись отчётов ТРЁХ каналов (датасеты, заклинания,
персонаж) матчат одной регулярной форме `поле.поле[индекс].поле` — от корня
документа, со списочными индексами в скобках; находки без места в документе
несут единый угловой placeholder («<файл>», …) и входят в ту же форму стартовым
сегментом. Форматирование живёт в сборке отчёта (ValidationReport.of), поэтому
проверка идёт через публичные двери каналов, а не через сырые проверки.
"""
from __future__ import annotations

import json
import re

from app.dd.application.character_channel import (
    CODE_CHAR_REF_UNRESOLVED,
    CODE_CHAR_SPELL_SLUG_UNRESOLVED,
    CharacterChannel,
    CharacterContext,
)
from app.dd.application.dataset_section_channel import (
    DatasetSectionChannel,
    DatasetSectionContext,
)
from app.dd.application.spellbook_channel import (
    CODE_SPELL_LEVEL_UNKNOWN,
    SpellbookChannel,
    SpellbookContext,
)
from app.dd.domain.validation_report import ValidationReport
from tests.dd.lss_check_fixtures import base_dataset, class_with

#: Единственная форма: сегмент = имя поля (или угловой placeholder) плюс
#: необязательный [индекс] (число, id записи, слаг или имя); сегменты склеены
#: точками. Никаких «:», скобочных штампов и « · » в собранном отчёте.
_SEGMENT = r"(?:<[^<>]+>|\$?[^\W\d]\w*)(?:\[(?:\d+|[^\W\d][\w -]*)\])?"
REPORT_PATH_FORM = re.compile(rf"{_SEGMENT}(?:\.{_SEGMENT})*")


def _assert_one_form(report: ValidationReport) -> list[str]:
    """Каждая запись отчёта указывает место ровно единой нотацией."""
    paths = [issue.path for issue in report.issues]
    bad = [path for path in paths if not REPORT_PATH_FORM.fullmatch(path)]
    assert bad == []
    return paths


# ── канал датасетов: schema-пути, траверс грантов, линки, placeholder ────────


def _dataset_channel() -> DatasetSectionChannel:
    return DatasetSectionChannel("classes", "hb-notation-guard")


def _nested_pick_one() -> dict:
    """Грант-ошибка на самой глубине вложенных pick-one — путь обязан дойти
    до места (spec сценарий «в т.ч. внутри списков»)."""
    return {
        "type": "pick-one",
        "options": [
            {
                "label": "Option",
                "grants": [
                    {
                        "type": "pick-one",
                        "options": [
                            {
                                "label": "Deeper",
                                "grants": [
                                    {
                                        "type": "bonus",
                                        "target": "не-таргет",
                                        "label": "L",
                                        "value": 1,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _guard_dataset_document() -> dict:
    bad_class = class_with(
        {"type": "bonus", "target": "не-таргет", "label": "L", "value": 1},
        _nested_pick_one(),
        {"type": "spell-fixed", "slug": "homemade-sparkles"},
        entity_id="wizard",
    )
    bad_class["likes2"] = "поле не из схемы"
    document = base_dataset(
        classes=[bad_class, class_with(entity_id="wizard")],
        subclasses=[{"id": "orphan", "classId": "nope", "label": "X", "grants": []}],
        races=[
            {
                "id": "elf",
                "label": "Elf",
                "size": "medium",
                "grants": [
                    {
                        "type": "trait",
                        "id": "darkvision",
                        "name": "Darkvision",
                        "params": {"ft": 60},
                        "description": "Видите в темноте.",
                    }
                ],
            }
        ],
    )
    del document["license"]
    return document


def test_dataset_channel_report_paths_match_the_single_form():
    report = _dataset_channel().validate(
        json.dumps(_guard_dataset_document(), ensure_ascii=False),
        DatasetSectionContext(spell_slugs=("fireball",)),
    )
    assert report.errors and report.warnings  # отчёт насыщенный, guard не пустой
    paths = _assert_one_form(report)
    # траверс грантов: двоеточие-склейка стала точкой, штамп (type) напечатан
    # прочь — индекс гранта остаётся адресом
    assert "classes[wizard].grants[0]" in paths
    assert "classes[wizard].grants[1].options[0].grants[0].options[0].grants[0]" in paths
    assert "subclasses[orphan].classId" in paths  # линк deep-путь
    assert "license" in paths and "classes[0].grants[5]" not in paths


def test_dataset_channel_placeholder_and_schema_field_paths():
    file_level = _dataset_channel().validate("{ это не json", DatasetSectionContext())
    assert _assert_one_form(file_level) == ["<файл>"]

    versioned = _guard_dataset_document()
    versioned["$schema"] = "https://longstoryshort.app/schema/v7/wizard-dataset.json"
    gate = _dataset_channel().validate(
        json.dumps(versioned, ensure_ascii=False), DatasetSectionContext()
    )
    assert _assert_one_form(gate) == ["$schema"]


# ── канал заклинаний: spells[индекс].поле и structural placeholder ────────────


def _spellbook_guard_document() -> str:
    return json.dumps(
        {
            "name": "Хоумбрю: Нотация",
            "items": [
                {
                    "name": "Fire bolt",
                    "type": "spell",
                    "flags": {"lss": {"slug": "fire-bolt"}},
                    "system": {"level": 42, "school": "pyromancy"},
                },
                {"name": "Тихий знак", "type": "spell", "system": {"level": 0}},
            ],
        },
        ensure_ascii=False,
    )


def test_spellbook_channel_report_paths_match_the_single_form():
    report = SpellbookChannel().validate(
        _spellbook_guard_document(), SpellbookContext(srd_slugs=("moon-pet",))
    )
    paths = _assert_one_form(report)
    level_path = next(p for p in paths if p.endswith(".level"))
    assert level_path == "spells[fire-bolt].level"
    assert CODE_SPELL_LEVEL_UNKNOWN in [i.code for i in report.warnings]
    # слаг-индекс и имя-наследник индекса живут в [...] одними символами
    assert any(p == "spells[Тихий знак]" for p in paths)
    assert any(p.startswith("spells[fire-bolt].") for p in paths)

    empty = SpellbookChannel().validate('{"items": []}', SpellbookContext())
    assert _assert_one_form(empty) == ["<файл>"]


# ── канал персонажа: data.…-пути валидатора и разрешения ссылок ───────────────


def _character_context() -> CharacterContext:
    return CharacterContext(
        world="Мир пепла",
        concept="страж",
        vocabulary=(),
        record_ids=("Elf", "Fighter"),
        spell_slugs=("fire-ball",),
    )


def _character_envelope(**data_over: object) -> str:
    data: dict = {
        "name": "Грог",
        "bonusesSkills": {},
        "info": {"race": {"id": "Dragonborn", "name": "Драконорождённый"}},
        "spells": {"list": ["fire-ball", "ghost-cantrip"]},
    }
    data.update(data_over)
    return json.dumps(
        {
            "jsonType": "character",
            "version": "2",
            "createdAt": "2026-10-12",
            # живой экспорт носит data JSON-строкой
            "data": json.dumps(data, ensure_ascii=False),
        },
        ensure_ascii=False,
    )


def test_character_channel_report_paths_match_the_single_form():
    channel = CharacterChannel(_character_context())
    report = channel.validate(_character_envelope())
    paths = _assert_one_form(report)
    codes = {issue.code for issue in report.issues}
    assert {CODE_CHAR_REF_UNRESOLVED, CODE_CHAR_SPELL_SLUG_UNRESOLVED} <= codes
    assert "data.info.race.id" in paths  # неразрешимая ссылка канала
    assert "data.spells.list[1]" in paths  # слаг вне словаря — по индексу
    assert "data.bonusesSkills" in paths and "createdAt" in paths

    broken = CharacterChannel(_character_context()).validate(
        json.dumps(
            {"jsonType": "character", "version": "2", "data": "не JSON"},
            ensure_ascii=False,
        )
    )
    assert _assert_one_form(broken) == ["data"]

    unreadable = CharacterChannel(_character_context()).validate("это не JSON")
    assert _assert_one_form(unreadable) == ["<файл>"]
