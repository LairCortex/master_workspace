"""Tests for the bundled character-sheet preset catalog (add-character-sheet-c).

TDD. Catalog (design D1/D4): exactly two presets — Fate Core and Mörk Borg,
fixed order — whose layouts are bundle JSONs (SheetTemplate v2, one portrait
A4 page). Each layout has one image field «портрет» without a file, and the
bundle carries NO image files at all (no publisher logos, no art).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from app.domain.entities.character_sheet import (
    FieldType,
    PAGE_HEIGHT_PT,
    PAGE_WIDTH_PT,
    SheetTemplate,
)
from app.presentation.views.character_sheet.presets.catalog import (
    FATE_LICENSE_TEXT,
    MORK_BORG_LICENSE_TEXT,
    PRESETS_DIR,
    PresetCatalog,
)


def _loaded(preset_id: str) -> SheetTemplate:
    catalog = PresetCatalog()
    return catalog.load_template(preset_id)


def _fields(template: SheetTemplate) -> list:
    assert len(template.pages) == 1
    return template.pages[0].fields


# ── 1.1: catalog — two presets, order, license texts ────────────────────────


class TestCatalog:
    def test_exactly_two_presets_in_order(self):
        presets = PresetCatalog().list()
        assert [p.id for p in presets] == ["fate_core", "mork_borg"]
        assert [p.title for p in presets] == ["Fate Core", "Mörk Borg"]

    def test_fate_license_text(self):
        # CC BY 3.0 Evil Hat + faterpg.com (spec: the full paragraph)
        assert "Creative Commons Attribution 3.0" in FATE_LICENSE_TEXT
        assert "faterpg.com" in FATE_LICENSE_TEXT

    def test_mork_borg_license_text(self):
        # 3PP: both paragraphs — the independent-production sentence and the © line
        assert "Third Party License" in MORK_BORG_LICENSE_TEXT
        assert "©2019" in MORK_BORG_LICENSE_TEXT
        assert "Ockult Örtmästare Games" in MORK_BORG_LICENSE_TEXT
        assert "Stockholm Kartell" in MORK_BORG_LICENSE_TEXT

    def test_catalog_independent_of_game(self):
        # the catalog is a bundle property: the same two presets always
        a = PresetCatalog().list()
        b = PresetCatalog().list()
        assert [p.id for p in a] == [p.id for p in b]

    def test_get_unknown_preset_raises(self):
        with pytest.raises(KeyError):
            PresetCatalog().get("dnd5e")


# ── 1.1: layouts — schema 2, one portrait page, clamped, no bundle art ───────


class TestPresetLayouts:
    @pytest.mark.parametrize("preset_id", ["fate_core", "mork_borg"])
    def test_single_portrait_page_schema_2(self, preset_id):
        t = _loaded(preset_id)
        assert t.schema_version == 2
        assert t.orientation == "portrait"
        assert len(t.pages) == 1
        assert t.pages[0].name == "Страница 1"
        assert t.page_size == (PAGE_WIDTH_PT, PAGE_HEIGHT_PT)

    @pytest.mark.parametrize("preset_id", ["fate_core", "mork_borg"])
    def test_portrait_image_field_without_file(self, preset_id):
        images = [f for f in _fields(_loaded(preset_id)) if f.type == FieldType.IMAGE]
        assert len(images) == 1
        assert images[0].image_id is None

    @pytest.mark.parametrize("preset_id", ["fate_core", "mork_borg"])
    def test_all_fields_clamped_into_page(self, preset_id):
        t = _loaded(preset_id)
        page_w, page_h = t.page_size
        for f in t.page.fields:
            assert f.x >= 0 and f.y >= 0
            assert f.x + f.w <= page_w, f
            assert f.y + f.h <= page_h, f

    def test_stable_field_ids(self):
        ids1 = [f.id for f in _fields(_loaded("fate_core"))]
        ids2 = [f.id for f in _fields(_loaded("fate_core"))]
        assert ids1 == ids2
        assert all(i for i in ids1)  # ids are fixed in the file, not generated

    def test_bundle_has_no_image_files(self):
        # bundle = catalog + the two JSON layouts only (no logos, no art)
        entries = sorted(
            p.name for p in PRESETS_DIR.iterdir() if p.name != "__pycache__"
        )
        assert entries == [
            "__init__.py",
            "catalog.py",
            "fate_core.json",
            "mork_borg.json",
        ]

    def test_presets_dir_resolves_to_the_module_directory(self):
        # review #10: the ONLY supported layout is "layouts next to the
        # module" — true for the dev tree and for the PyInstaller onedir
        # bundle (verified against a real bundle: __file__ resolves inside
        # it, _MEIPASS adds nothing). If someone reintroduces a bundle layout
        # where the JSONs are not next to catalog.py, this fails and the
        # resolution logic must be revisited.
        from app.presentation.views.character_sheet.presets import catalog

        assert PRESETS_DIR == Path(catalog.__file__).resolve().parent
        for preset in PresetCatalog().list():
            assert (PRESETS_DIR / preset.json_name).is_file(), preset.json_name

    @pytest.mark.parametrize("preset_id", ["fate_core", "mork_borg"])
    def test_no_tables_or_radios(self, preset_id):
        # table / radio / repeating are not in the A-playable catalog at all
        types = Counter(f.type for f in _fields(_loaded(preset_id)))
        for absent in (FieldType.DROPDOWN, FieldType.RECT, FieldType.LINE):
            assert absent not in types


# ── 2.1: Fate Core composition ────────────────────────────────────────────────

FATE_SKILLS = [
    "Атлетика", "Взлом", "Связи", "Ремесло", "Обман", "Вождение", "Эмпатия",
    "Бой", "Расследование", "Знания", "Внимание", "Телосложение", "Провокация",
    "Общение", "Ресурсы", "Стрельба", "Скрытность", "Воля",
]


class TestFateCoreComposition:
    def test_name_concept_refit(self):
        fields = _fields(_loaded("fate_core"))
        labels = {f.content for f in fields if f.type == FieldType.LABEL}
        assert "Имя" in labels
        assert "Описание" in labels
        assert "Обновление" in labels
        # один числовой «обновление» (отдельно от 18 навыка)
        numbers = [f for f in fields if f.type == FieldType.NUMBER]
        assert len(numbers) == 19

    def test_five_aspects(self):
        fields = _fields(_loaded("fate_core"))
        labels = {f.content for f in fields if f.type == FieldType.LABEL}
        for name in ("Высокая концепция", "Проблема", "Аспект 1", "Аспект 2", "Аспект 3"):
            assert name in labels
        text_fields = [f for f in fields if f.type == FieldType.TEXT]
        # имя + 5 аспектов + 3 последствия
        assert len(text_fields) == 9

    def test_eighteen_skills_as_numbers_with_labels(self):
        fields = _fields(_loaded("fate_core"))
        labels = {f.content for f in fields if f.type == FieldType.LABEL}
        for skill in FATE_SKILLS:
            assert skill in labels, skill
        # 18 навыков — отдельные number (default "")
        skills = [f for f in fields
                  if f.type == FieldType.NUMBER and f.content == ""]
        assert len(skills) == 19  # 18 навыка + обновление

    def test_tricks_textarea(self):
        fields = _fields(_loaded("fate_core"))
        labels = {f.content for f in fields if f.type == FieldType.LABEL}
        assert "Трюки" in labels
        assert sum(1 for f in fields if f.type == FieldType.TEXTAREA) == 2  # описание + трюки

    def test_stress_4_plus_4_checkboxes(self):
        fields = _fields(_loaded("fate_core"))
        labels = {f.content for f in fields if f.type == FieldType.LABEL}
        assert "Физический стресс" in labels
        assert "Ментальный стресс" in labels
        checkboxes = [f for f in fields if f.type == FieldType.CHECKBOX]
        assert len(checkboxes) == 8
        assert all(f.content == "false" for f in checkboxes)

    def test_three_consequences(self):
        fields = _fields(_loaded("fate_core"))
        labels = {f.content for f in fields if f.type == FieldType.LABEL}
        assert "Последствия" in labels
        for name in ("Лёгкое", "Умеренное", "Тяжёлое"):
            assert name in labels

    def test_license_label_with_full_cc_by(self):
        fields = _fields(_loaded("fate_core"))
        license_labels = [
            f for f in fields
            if f.type == FieldType.LABEL and f.content == FATE_LICENSE_TEXT
        ]
        assert len(license_labels) == 1


# ── 2.3: Mörk Borg composition ───────────────────────────────────────────────


class TestMorkBorgComposition:
    def test_name_and_class(self):
        fields = _fields(_loaded("mork_borg"))
        labels = {f.content for f in fields if f.type == FieldType.LABEL}
        assert "Имя" in labels
        assert "Класс / Предыстория" in labels

    def test_silver_hp_and_skills_as_numbers(self):
        fields = _fields(_loaded("mork_borg"))
        labels = {f.content for f in fields if f.type == FieldType.LABEL}
        for name in (
            "Серебро", "HP (текущие)", "HP (максимум)",
            "Сила", "Ловкость", "Присутствие", "Стойкость",
        ):
            assert name in labels, name
        # серебро + 2 HP + 4 характеристики = 7 numbers
        numbers = [f for f in fields if f.type == FieldType.NUMBER]
        assert len(numbers) == 7

    def test_skill_numbers_without_min_max(self):
        # отрицательные значения в Mörk Borg допустимы: min/max не задаются
        fields = _fields(_loaded("mork_borg"))
        numbers = [f for f in fields if f.type == FieldType.NUMBER]
        assert numbers
        assert all(f.min_value is None and f.max_value is None for f in numbers)

    def test_two_omen_checkboxes(self):
        fields = _fields(_loaded("mork_borg"))
        labels = {f.content for f in fields if f.type == FieldType.LABEL}
        assert "Знамения" in labels
        checkboxes = [f for f in fields if f.type == FieldType.CHECKBOX]
        assert len(checkboxes) == 2
        assert all(f.content == "false" for f in checkboxes)

    def test_weapon_armor_texts(self):
        fields = _fields(_loaded("mork_borg"))
        labels = {f.content for f in fields if f.type == FieldType.LABEL}
        assert "Оружие" in labels
        assert "Броня" in labels
        # имя + класс + оружие + броня
        assert sum(1 for f in fields if f.type == FieldType.TEXT) == 4

    def test_equipment_abilities_textareas(self):
        fields = _fields(_loaded("mork_borg"))
        labels = {f.content for f in fields if f.type == FieldType.LABEL}
        assert "Снаряжение" in labels
        assert "Способности" in labels
        assert sum(1 for f in fields if f.type == FieldType.TEXTAREA) == 2

    def test_3pp_license_label_with_both_paragraphs(self):
        fields = _fields(_loaded("mork_borg"))
        license_labels = [
            f for f in fields
            if f.type == FieldType.LABEL and f.content == MORK_BORG_LICENSE_TEXT
        ]
        assert len(license_labels) == 1
        assert "Third Party License" in MORK_BORG_LICENSE_TEXT
        assert "©2019" in MORK_BORG_LICENSE_TEXT
