"""Unit pins for the entity-preview view model (NRI-0022, tasks 4.1–4.5).

The VM is the whole read-only composition rule: the one headline line titled
by the shown entity's type («Карточка» / «Карточка: Персонаж»), the full-card
field set with the per-type absences, the dates row
with «Бессрочно», the age line under its documented absence postures, the
image slot through the shared pipeline, the registry-ordered relation sections
without the empty blocks, and the two outgoing gestures (selection bus, image
open). The QML half is pinned in ``test_entity_preview_island.py``.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt, Signal

from app.domain.game_calendar import InvalidGameDateError
from app.presentation.viewmodels import entity_preview_view_model as vm_module
from app.presentation.viewmodels.entity_preview_view_model import (
    EntityPreviewViewModel,
)


class _NowStub(QObject):
    """The game-«now» broadcast carrier the wiring hands in (duck of
    NowDateViewModel: coord / is_bc reads + the nowChanged channel)."""

    nowChanged = Signal()

    def __init__(self, coord, is_bc: bool = False) -> None:
        super().__init__()
        self.coord = coord
        self.is_bc = is_bc


def _desc(characteristics: str = "", backstory: str = ""):
    return SimpleNamespace(characteristics=characteristics, backstory=backstory)


def _entity(entity_type: str = "character", **overrides):
    base = dict(
        id=4,
        name="Банн",
        rating=8,
        start_date=date(1200, 1, 1),
        end_date=None,
        start_bc=False,
        end_bc=False,
        description=_desc("Крепкий", "Долгая история"),
        music_url="https://example.com/song",
        image_ref=None,
        items=[],
        locations=[],
        organizations=[],
    )
    if entity_type == "character":
        base["personality"] = "Упрямый"
        base["tasks"] = "Найти брата"
    if entity_type == "item":
        # The item dataclass carries neither personality nor tasks at all —
        # the same shape the repository hands presentation.
        base["locations"] = []
    if entity_type == "organization":
        base["tasks"] = "Собрать войско"
    if entity_type == "location":
        base["tasks"] = "Держать оборону"
    base.update(overrides)
    return SimpleNamespace(**base)


# ── the empty state (task 4.1, spec «Пустой предпросмотр объясняет себя») ───


class TestEmptyState:
    def test_a_fresh_view_model_answers_the_empty_display_set(self):
        vm = EntityPreviewViewModel()
        assert bool(vm.hasEntity) is False
        assert (vm.title, vm.nameText, vm.ratingText, vm.dateText) == ("Карточка", "", "", "")
        assert (vm.ageText, vm.musicUrl, vm.imageSource) == ("", "", "")
        assert vm.sections == []
        assert vm.relatedSections == []
        assert vm.shown_entity is None

    def test_clear_returns_a_shown_entity_to_the_empty_state(self):
        vm = EntityPreviewViewModel()
        vm.show_entity("character", _entity())
        vm.clear()
        assert bool(vm.hasEntity) is False
        assert vm.title == "Карточка"
        assert vm.shown_entity is None

    def test_clear_without_anything_shown_reannounces_the_empty_set(self):
        vm = EntityPreviewViewModel()
        changed = []
        vm.contentChanged.connect(lambda: changed.append(1))
        vm.clear()
        assert changed == [1]


# ── the one headline: «Карточка» / «Карточка: <тип из реестра>» (fix 4.8) ───


@pytest.mark.parametrize(
    "type_key, label",
    [
        ("organization", "Организация"),
        ("character", "Персонаж"),
        ("item", "Предмет"),
        ("location", "Локация"),
    ],
)
def test_the_band_title_names_the_type_in_russian_from_the_registry(
    type_key, label
):
    # The band is titled by the TYPE (the reader's clarification 2026-09-28):
    # the name is a field inside the card, it never rides the headline —
    # hence the deliberately loud name below must not reach the title.
    vm = EntityPreviewViewModel()
    vm.show_entity(type_key, _entity(type_key, name="Гром-Громович"))
    assert vm.title == f"Карточка: {label}"


# ── the read-only composition (task 4.2, spec «Состав читаемого» ) ──────────


class TestComposition:
    def test_character_shows_the_full_card_field_set(self):
        vm = EntityPreviewViewModel()
        vm.show_entity("character", _entity())
        assert vm.nameText == "Банн"
        assert vm.ratingText == "Рейтинг: 8/20"
        assert vm.dateText == "01 Январь 1200 — Бессрочно"
        assert vm.musicUrl == "https://example.com/song"
        keys = [section["key"] for section in vm.sections]
        labels = [section["label"] for section in vm.sections]
        assert keys == ["characteristics", "backstory", "personality", "tasks"]
        assert labels == ["Характеристики", "Предыстория", "Личность", "Задачи"]

    def test_item_has_no_foreign_fields(self):
        # Spec scenario «У предмета нет чужих полей»: the section set follows
        # the attributes the type carries — no «Личность», no «Задачи».
        vm = EntityPreviewViewModel()
        vm.show_entity("item", _entity("item", name="Меч"))
        keys = [section["key"] for section in vm.sections]
        assert keys == ["characteristics", "backstory"]

    @pytest.mark.parametrize(
        "type_key, expect_personality",
        [("character", True), ("organization", False), ("item", False), ("location", False)],
    )
    def test_personality_belongs_to_the_character_only(self, type_key, expect_personality):
        vm = EntityPreviewViewModel()
        vm.show_entity(type_key, _entity(type_key))
        keys = [section["key"] for section in vm.sections]
        assert ("personality" in keys) is expect_personality

    def test_blank_and_absent_values_leave_their_sections_out(self):
        vm = EntityPreviewViewModel()
        entity = _entity()
        entity.description = _desc("   ", "")
        entity.personality = None
        vm.show_entity("character", entity)
        assert [section["key"] for section in vm.sections] == ["tasks"]

    def test_a_missing_description_contributes_no_text_sections(self):
        vm = EntityPreviewViewModel()
        entity = _entity("item")
        entity.description = None
        vm.show_entity("item", entity)
        assert vm.sections == []

    def test_a_missing_music_link_leaves_the_music_row_empty(self):
        vm = EntityPreviewViewModel()
        entity = _entity()
        entity.music_url = None
        vm.show_entity("character", entity)
        assert vm.musicUrl == ""

    def test_rating_defaults_and_survives_a_foreign_value(self):
        vm = EntityPreviewViewModel()
        entity = _entity()
        entity.rating = "восемь"  # a duck payload the summary posture floors to 1
        vm.show_entity("character", entity)
        assert vm.ratingText == "Рейтинг: 1/20"

    def test_named_dates_and_the_era_flags_ride_the_shared_formatter(self):
        vm = EntityPreviewViewModel()
        entity = _entity()
        entity.end_date = date(1205, 6, 7)
        entity.start_bc = True
        vm.show_entity("character", entity)
        assert vm.dateText == "01 Январь 1200 г. до н.э. — 07 Июнь 1205"

    def test_text_field_values_carry_the_mention_anchor_html(self):
        vm = EntityPreviewViewModel()
        entity = _entity()
        entity.description = _desc("", "Сражались с @[Волк](organization:2)!")
        vm.show_entity("character", entity)
        [backstory] = [s for s in vm.sections if s["key"] == "backstory"]
        assert 'href="nri://organization/2"' in backstory["html"]
        assert "Волк</a>" in backstory["html"]


# ── the age line (task 4.2 «даты/„Бессрочно“ + возраст», NRI-0021 rule) ─────


class TestAgeLine:
    def test_character_ages_to_the_game_now(self):
        vm = EntityPreviewViewModel(now_vm=_NowStub(date(1203, 1, 1)))
        vm.show_entity("character", _entity())
        assert vm.ageText == "Возраст: 3 года"

    def test_item_ages_too_and_a_closed_entity_counts_to_its_end(self):
        vm = EntityPreviewViewModel(now_vm=_NowStub(date(1210, 1, 1)))
        entity = _entity("item", end_date=date(1202, 1, 1))
        vm.show_entity("item", entity)
        assert vm.ageText == "Возраст: 2 года"

    @pytest.mark.parametrize("type_key", ["organization", "location"])
    def test_age_free_types_never_carry_the_line(self, type_key):
        vm = EntityPreviewViewModel(now_vm=_NowStub(date(1203, 1, 1)))
        vm.show_entity(type_key, _entity(type_key))
        assert vm.ageText == ""

    def test_without_a_game_now_the_line_stays_absent(self):
        vm = EntityPreviewViewModel()
        vm.show_entity("character", _entity())
        assert vm.ageText == ""

    def test_an_entity_without_a_start_date_skips_the_line(self):
        vm = EntityPreviewViewModel(now_vm=_NowStub(date(1203, 1, 1)))
        entity = _entity()
        entity.start_date = None
        vm.show_entity("character", entity)
        assert vm.ageText == ""

    def test_a_coordinate_the_calendar_refuses_hides_the_line(self, monkeypatch):
        # The Д1 damaged-value posture reused: a derived text that cannot be
        # counted leaves, it never breaks the preview.
        monkeypatch.setattr(
            vm_module, "format_age_words", lambda *args: (_ for _ in ()).throw(
                InvalidGameDateError("нет такого дня")
            )
        )
        vm = EntityPreviewViewModel(now_vm=_NowStub(date(1203, 1, 1)))
        vm.show_entity("character", _entity())
        assert vm.ageText == ""
        # The rest of the composition survives next to the missing line.
        assert vm.nameText == "Банн"

    def test_now_broadcast_re_renders_the_shown_entity_only(self):
        now = _NowStub(date(1203, 1, 1))
        vm = EntityPreviewViewModel(now_vm=now)
        changed = []
        vm.contentChanged.connect(lambda: changed.append(1))
        vm.show_entity("character", _entity())
        assert vm.ageText == "Возраст: 3 года"
        changed.clear()

        now.coord = date(1205, 1, 1)
        now.nowChanged.emit()
        assert vm.ageText == "Возраст: 5 лет"
        assert changed == [1]

        # Nothing shown -> the broadcast has nothing to re-render.
        vm.clear()
        changed.clear()
        now.nowChanged.emit()
        assert changed == []

    def test_detach_stops_following_the_now(self):
        now = _NowStub(date(1203, 1, 1))
        vm = EntityPreviewViewModel(now_vm=now)
        vm.show_entity("character", _entity())
        vm.detach_now_listener()
        now.coord = date(1299, 1, 1)
        now.nowChanged.emit()
        assert vm.ageText == "Возраст: 3 года"  # the stale value stays, no rebuild
        vm.detach_now_listener()  # idempotent (the teardown may double-call)


# ── the picture slot (task 4.3, spec «Картинка в предпросмотре») ────────────


class TestImageSlot:
    def test_a_loaded_preview_paints_and_a_null_one_degrades(self, monkeypatch, tmp_path):
        from PySide6.QtGui import QImage, QPixmap

        real = QImage(20, 20, QImage.Format.Format_RGB32)
        real.fill(Qt.GlobalColor.red)
        ok = QPixmap.fromImage(real)
        sources = iter([ok, QPixmap()])  # first show: loadable; re-show: gone
        monkeypatch.setattr(
            vm_module, "load_entity_preview", lambda entity, slot_size: next(sources)
        )
        monkeypatch.setattr(
            vm_module, "resolve_preview_path", lambda entity: tmp_path / "preview.webp"
        )
        vm = EntityPreviewViewModel()
        vm.show_entity("character", _entity())
        assert vm.imageSource.startswith("file://")
        vm.show_entity("character", _entity())
        assert vm.imageSource == ""


# ── the relation sections (task 4.4, spec «Связи показаны компактным списком») ──


class TestRelatedSections:
    def _linked(self):
        character = _entity("character")
        character.items = [SimpleNamespace(id=11, name="Кинжал")]
        character.locations = [
            SimpleNamespace(id=12, name="Пещера"),
            SimpleNamespace(id=13, name="Замок"),
        ]
        character.organizations = []
        return character

    def test_sections_follow_the_registry_order_and_drop_the_empty_ones(self):
        vm = EntityPreviewViewModel()
        vm.show_entity("character", self._linked())
        sections = vm.relatedSections
        # The character's RELATED_CONFIG order: items, locations, organizations
        # — the empty organizations section is not built at all.
        assert [section["key"] for section in sections] == ["items", "locations"]
        assert [section["label"] for section in sections] == ["Предметы", "Локации"]
        assert [row["name"] for row in sections[0]["rows"]] == ["Кинжал"]
        assert [row["type"] for row in sections[1]["rows"]] == ["location", "location"]
        assert [row["id"] for row in sections[1]["rows"]] == [12, 13]

    def test_an_entity_without_links_gets_no_sections(self):
        vm = EntityPreviewViewModel()
        vm.show_entity("character", _entity())
        assert vm.relatedSections == []

    def test_a_missing_collection_attribute_reads_as_no_rows(self):
        vm = EntityPreviewViewModel()
        entity = _entity("item")  # the duck carries no locations attribute
        delattr(entity, "locations")
        vm.show_entity("item", entity)
        assert vm.relatedSections == []

    def test_relation_rows_without_names_read_empty(self):
        vm = EntityPreviewViewModel()
        character = _entity("character")
        character.locations = [SimpleNamespace(name=None, id=0)]
        vm.show_entity("character", character)
        [[row]] = [section["rows"] for section in vm.relatedSections]
        assert row["name"] == "" and row["id"] == 0


# ── the two outgoing gestures (tasks 4.4/4.5) ───────────────────────────────


class TestGestures:
    def test_requestEntity_feeds_the_selection_bus(self):
        vm = EntityPreviewViewModel()
        vm.show_entity("character", _entity())
        emits = []
        vm.entityRequested.connect(lambda *args: emits.append(args))
        vm.requestEntity("location", 12)
        assert emits == [("location", 12)]

    def test_a_generated_mention_link_navigates(self):
        vm = EntityPreviewViewModel()
        vm.show_entity("character", _entity())
        emits = []
        vm.entityRequested.connect(lambda *args: emits.append(args))
        vm.requestLink("nri://organization/2")
        assert emits == [("organization", 2)]

    def test_a_foreign_or_broken_href_navigates_nothing(self):
        vm = EntityPreviewViewModel()
        vm.show_entity("character", _entity())
        emits = []
        vm.entityRequested.connect(lambda *args: emits.append(args))
        vm.requestLink("https://example.com")
        vm.requestLink("nri://character/abc")
        assert emits == []
        # The shown content is untouched by a dead href (task 4.5 posture;
        # the wiring resolves the deleted-target half in group 5).
        assert vm.nameText == "Банн"

    def test_requestImage_announces_only_over_a_shown_entity(self):
        vm = EntityPreviewViewModel()
        opens = []
        vm.imageRequested.connect(lambda: opens.append(1))
        vm.requestImage()
        assert opens == []
        vm.show_entity("character", _entity())
        vm.requestImage()
        assert opens == [1]
