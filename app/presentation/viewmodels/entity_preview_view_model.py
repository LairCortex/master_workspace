"""Synchronous, render-ready state for the entity-preview QML island.

NRI-0022 (tasks 4.1–4.5, design D1/D2): the right column shows the last entity
selected in the middle column, READ-ONLY — this view model turns one entity
(the domain/duck-typed row the wiring loaded through the entity service) into
display texts: the one header line titled by the shown entity's type
(«Карточка» / «Карточка: Персонаж», the reader's fix 2026-09-28), the
full-card field set, the image slot
through the shared ``image_utils`` pipeline, the compact relation sections from
the registry's ``RELATED_CONFIG``, and the mention-anchor HTML of every text
field (``utils.mention_html``, the single generator). The island emits back
only two things: a selection request (relation row / mention link — the same
``(type, id)`` bus the panel's single click feeds, design D2) and an image
open request; the facade turns the latter into the viewer dialog.

No session, no ORM, no async here: the wiring feeds entities in and reads the
request signals out. The derived age line follows the game's «now» (NRI-0021
Д2/Д5 posture): the VM subscribes to the «now» VM, re-renders the shown entity
on the broadcast, and the island's release detaches the subscription.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot

from app.domain import entity_registry
from app.domain.game_calendar import InvalidGameDateError
from app.presentation.utils.date_utils import (
    AGE_ENTITY_TYPES,
    AGE_LABEL,
    era_flag,
    event_start_time,
    format_age_words,
    format_event_start,
    format_game_date,
)
from app.presentation.utils.image_utils import load_entity_preview, resolve_preview_path
from app.presentation.utils.mention_html import build_mention_html, parse_mention_link

#: End-of-dates caption of an open-ended entity (the card's checkbox word).
INFINITE_LABEL = "Бессрочно"

#: The column's one title (the reader's fix 2026-09-28): the header band is
#: the only headline — «Карточка» while the column is empty, «Карточка:
#: <русское имя типа из реестра>» while one is shown; no second «Карточка…»
#: line lives inside the content anymore.
CARD_TITLE_LABEL = "Карточка"

#: Preview copy fit into the image slot (px). The viewer half of the click
#: re-loads through the same pipeline at its own 4096 slot (task 4.3).
IMAGE_SLOT_SIZE = 240

#: Text fields of the read-only composition, render order: (key, section
#: caption, value reader). Absent or blank values leave the section out (spec
#: «Поля, отсутствующие у типа сущности, SHALL не выводиться») — so «Личность»
#: only ever reaches a character and «Задачи» never an item, with no per-type
#: branch beyond the attributes the type actually carries.
_TEXT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("characteristics", "Характеристики", "characteristics"),
    ("backstory", "Предыстория", "backstory"),
    ("personality", "Личность", "personality"),
    ("tasks", "Задачи", "tasks"),
)


class EntityPreviewViewModel(QObject):
    """The shown entity's display set; all presentation rules live here."""

    contentChanged = Signal()
    #: The preview's half of the one selection bus (design D2): a relation row
    #: or a mention link was activated — the wiring loads and shows that entity
    #: and tries the middle-column highlight; the preview never loads itself.
    entityRequested = Signal(str, int)
    #: The picture was activated; the facade opens the viewer dialog.
    imageRequested = Signal()

    def __init__(self, now_vm=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._now_vm = now_vm
        self._entity_type: str | None = None
        self._entity: Any = None
        # The band never dangles empty off the bat: the plain word stands
        # until a type-titled rebuild replaces it.
        self._title = CARD_TITLE_LABEL
        self._name_text = ""
        self._rating_text = ""
        self._date_text = ""
        self._age_text = ""
        self._music_url = ""
        self._image_source = ""
        self._sections: list[dict[str, str]] = []
        self._related_sections: list[dict[str, Any]] = []
        if now_vm is not None:
            now_vm.nowChanged.connect(self._on_now_changed)

    # ── QML-facing properties (design D1: the island only paints) ──────────

    hasEntity = Property(bool, lambda self: self._entity is not None, notify=contentChanged)
    title = Property(str, lambda self: self._title, notify=contentChanged)
    nameText = Property(str, lambda self: self._name_text, notify=contentChanged)
    ratingText = Property(str, lambda self: self._rating_text, notify=contentChanged)
    dateText = Property(str, lambda self: self._date_text, notify=contentChanged)
    ageText = Property(str, lambda self: self._age_text, notify=contentChanged)
    musicUrl = Property(str, lambda self: self._music_url, notify=contentChanged)
    imageSource = Property(str, lambda self: self._image_source, notify=contentChanged)
    sections = Property("QVariant", lambda self: self._sections, notify=contentChanged)
    relatedSections = Property(
        "QVariant", lambda self: self._related_sections, notify=contentChanged
    )

    # ── Python-side reads (the facade builds the viewer from these) ────────

    @property
    def shown_entity(self) -> Any:
        """The entity currently displayed (``None`` in the empty state)."""
        return self._entity

    # ── feeding (the wiring's only two entry points) ───────────────────────

    def show_entity(self, entity_type: str, entity: Any) -> None:
        """Display one loaded entity; re-reads replace the shown values
        (spec «Сохранение карточки обновляет предпросмотр»)."""
        self._entity_type = entity_type
        self._entity = entity
        self._rebuild()

    def clear(self) -> None:
        """Back to the self-explaining empty state (delete / new game / the
        next start all funnel through here via the wiring)."""
        self._entity_type = None
        self._entity = None
        self._rebuild()

    # ── QML-facing slots (the island's two outgoing gestures) ──────────────

    @Slot(str, int)
    def requestEntity(self, entity_type: str, entity_id: int) -> None:
        """A relation row was activated (mouse click or accessibility Press —
        the library row runs both through this one slot)."""
        self.entityRequested.emit(entity_type, entity_id)

    @Slot(str)
    def requestLink(self, link: str) -> None:
        """``onLinkActivated`` receiver: a generated mention anchor navigates;
        any other href (external URL, stale fragment) is a silent no-op, so a
        broken mention of a deleted entity can never break the preview."""
        target = parse_mention_link(link)
        if target is None:
            return
        self.entityRequested.emit(target[0], target[1])

    @Slot()
    def requestImage(self) -> None:
        if self._entity is not None:
            self.imageRequested.emit()

    # ── «now» following (NRI-0021 Д2/Д5 posture, reused for the age row) ───

    def detach_now_listener(self) -> None:
        """Stop following the game's «now» (island teardown; idempotent)."""
        if self._now_vm is not None:
            self._now_vm.nowChanged.disconnect(self._on_now_changed)
            self._now_vm = None

    def _on_now_changed(self) -> None:
        if self._entity is not None:
            self._rebuild()

    # ── the one build path ──────────────────────────────────────────────────

    def _rebuild(self) -> None:
        if self._entity is None:
            self._title = CARD_TITLE_LABEL
            self._name_text = ""
            self._rating_text = ""
            self._date_text = ""
            self._age_text = ""
            self._music_url = ""
            self._image_source = ""
            self._sections = []
            self._related_sections = []
            self.contentChanged.emit()
            return

        entity = self._entity
        self._name_text = str(getattr(entity, "name", "") or "")
        # The one headline of the column (the reader's fix 2026-09-28): the
        # band carries the registry's Russian type name — «Карточка: Персонаж»,
        # «Карточка: Предмет» — the entity's own name stays a field inside
        # the card, never a headline.
        self._title = (
            f"{CARD_TITLE_LABEL}: {entity_registry.display_label(self._entity_type)}"
        )
        rating = getattr(entity, "rating", 1)
        if not isinstance(rating, int):
            rating = 1
        self._rating_text = f"Рейтинг: {rating}/20"

        start_bc = era_flag(getattr(entity, "start_bc", False))
        end_bc = era_flag(getattr(entity, "end_bc", False))
        # NRI-0023 task 8.1 (design Д9, spec event-time «Время на поверхностях
        # события»): the start side rides the single surface helper with the
        # duck-typed time reader — an event shown here prints its «, HH:MM»
        # tail, every time-less entity keeps the caption bit-for-bit.  The end
        # stays a day (only the start carries a time).
        start = format_event_start(
            getattr(entity, "start_date", None),
            start_bc,
            event_start_time(entity),
        )
        end = format_game_date(
            getattr(entity, "end_date", None), INFINITE_LABEL, is_bc=end_bc
        )
        self._date_text = f"{start} — {end}"
        self._age_text = self._age_line(start_bc, end_bc)

        music_url = getattr(entity, "music_url", "")
        self._music_url = music_url if isinstance(music_url, str) else ""

        self._image_source = self._image_source_text()
        self._sections = self._text_sections()
        self._related_sections = self._related()
        self.contentChanged.emit()

    def _age_line(self, start_bc: bool, end_bc: bool) -> str:
        """The «Возраст: <формула>» row — the one age rule (``format_age_words``,
        NRI-0021 Д5) served under the same absence postures as the summary:
        age-free types and a panel built without a «now» simply show no row,
        and a coordinate the active calendar refuses hides it (never a crash)."""
        if self._now_vm is None or self._entity_type not in AGE_ENTITY_TYPES:
            return ""
        start = getattr(self._entity, "start_date", None)
        if start is None:
            return ""
        try:
            age_words = format_age_words(
                start,
                start_bc,
                getattr(self._entity, "end_date", None),
                end_bc,
                self._now_vm.coord,
                self._now_vm.is_bc,
            )
        except InvalidGameDateError:
            return ""
        return f"{AGE_LABEL}: {age_words}"

    def _image_source_text(self) -> str:
        """The preview file's URL, or the empty string the island paints as the
        «Нет изображения» placeholder. Decided through the shared pipeline: a
        null pixmap (no link, no directory, a missing or corrupt file) degrades
        to the placeholder exactly like the card's slot (spec image-display)."""
        pixmap = load_entity_preview(self._entity, slot_size=IMAGE_SLOT_SIZE)
        if pixmap.isNull():
            return ""
        return QUrl.fromLocalFile(str(resolve_preview_path(self._entity))).toString()

    def _text_sections(self) -> list[dict[str, str]]:
        description = getattr(self._entity, "description", None)
        sections: list[dict[str, str]] = []
        for key, label, attr in _TEXT_FIELDS:
            if key in ("characteristics", "backstory"):
                value = getattr(description, attr, "") if description else ""
            else:
                value = getattr(self._entity, attr, "") or ""
            if value and value.strip():
                sections.append({"key": key, "label": label, "html": build_mention_html(value)})
        return sections

    def _related(self) -> list[dict[str, Any]]:
        """Compact sections per the registry's relation config, in its order;
        a section without rows is not built at all (spec «Нет связей — нет
        блока»), so the island paints no empty block to hide."""
        sections: list[dict[str, Any]] = []
        for ref in entity_registry.related_refs_for_key(self._entity_type):
            rows = [
                {
                    "name": str(getattr(related, "name", "") or ""),
                    "type": ref.entity_type.value,
                    "id": getattr(related, "id", 0) or 0,
                }
                for related in (getattr(self._entity, ref.attr, None) or [])
            ]
            if rows:
                sections.append({"key": ref.attr, "label": ref.label, "rows": rows})
        return sections
