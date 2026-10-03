"""Render-ready state of ONE card of the entity-preview column (NRI-0025 task 2.1).

NRI-0025 design Д2 splits the old single-entity preview VM in two: this class
owns the whole per-card render that ``EntityPreviewViewModel`` used to hold
field-for-field (the «Карточка: <тип> · <имя>» band caption, the short fields,
the age line counted against the game's «now», the picture slot through the
shared ``image_utils`` pipeline, the mention-anchored text sections and the
compact relation sections from the registry), while the column VM owns only
the LIST of cards, the one «now» subscription and the gestures out.

The card is a plain Python object, not a QObject: the column VM is the single
notify source (``contentChanged`` on any change) and QML receives each card as
its ``pane()`` dict — the contract the island's pane delegates bind to. The
render rules themselves are UNCHANGED from NRI-0022/NRI-0023 (the zero-pins
column stays bit-for-bit the old single card — pinned in the slot tests).

No session, no ORM, no async here either: the wiring feeds loaded entities and
the card only formats them.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QUrl

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
from app.presentation.utils.mention_html import build_mention_html

#: End-of-dates caption of an open-ended entity (the card's checkbox word).
INFINITE_LABEL = "Бессрочно"

#: The card's headline word (the reader's fix 2026-09-28, extended by the
#: reader's fix 2026-10-03): the header band is the card's only headline —
#: «Карточка» while the column is empty, «Карточка: <русское имя типа из
#: реестра> · <имя сущности>» while one is shown (the name rides the caption
#: so each of the up-to-four cards is identifiable by its headline); no
#: second «Карточка…» line lives inside the content anymore.
CARD_TITLE_LABEL = "Карточка"

#: Preview copy fit into the image slot (px). The viewer half of the click
#: re-loads through the same pipeline at its own 4096 slot (NRI-0022 task 4.3).
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


def content_fingerprint(entity_type: str, entity: Any) -> tuple:
    """The cheap content stamp behind the column VM's frame reuse (the
    2026-10-03 scroll-reset fix): every value the card renders from, minus
    the expensive halves (no image decode, no HTML build — the sha/ext pair
    and the raw texts stand in for them; equal sha means equal bytes by the
    store's own naming). The card is built once and reused across frames, so
    a frame must notice a row that moved underneath it — and object identity
    cannot be that stamp: the service updates the session's
    identity-mapped row IN PLACE mid-save (pinned by the e2e save tests), so
    the very same object arrives in the next frame carrying new values.
    Equal fingerprints ⇒ equal render; the age line is the single
    «now»-dependent field and lives outside the stamp by design
    (``recount_age`` owns it)."""
    description = getattr(entity, "description", None)
    rating = getattr(entity, "rating", 1)
    music_url = getattr(entity, "music_url", "")
    image_ref = getattr(entity, "image_ref", None)
    relations = tuple(
        (
            ref.attr,
            tuple(
                (
                    getattr(related, "id", 0) or 0,
                    str(getattr(related, "name", "") or ""),
                )
                for related in (getattr(entity, ref.attr, None) or [])
            ),
        )
        for ref in entity_registry.related_refs_for_key(entity_type)
    )
    return (
        str(getattr(entity, "name", "") or ""),
        rating if isinstance(rating, int) else 1,
        era_flag(getattr(entity, "start_bc", False)),
        era_flag(getattr(entity, "end_bc", False)),
        getattr(entity, "start_date", None),
        getattr(entity, "end_date", None),
        event_start_time(entity),
        music_url if isinstance(music_url, str) else "",
        None
        if image_ref is None
        else (getattr(image_ref, "sha256", None), getattr(image_ref, "ext", None)),
        (getattr(description, "characteristics", "") if description else "") or "",
        (getattr(description, "backstory", "") if description else "") or "",
        getattr(entity, "personality", "") or "",
        getattr(entity, "tasks", "") or "",
        relations,
    )


class EntityCardViewModel:
    """One card's display set plus its slot flags (design Д2).

    Built fully rendered; the column VM hands it out across frames as long
    as its ``content_fingerprint`` says the row behind it still paints the
    same, and only :meth:`recount_age` runs later (the «now» broadcast must
    refresh the derived line, never re-read the picture file)."""

    def __init__(
        self,
        entity_type: str,
        entity: Any,
        now_vm: Any = None,
        *,
        pinned: bool = False,
        slot_index: int = 0,
        pin_state: str,
        rev: int = 0,
    ) -> None:
        self.entity_type = entity_type
        self.entity = entity
        self.entity_id = int(getattr(entity, "id", 0) or 0)
        self.pinned = pinned
        self.slot_index = slot_index
        # The slot identity the island carries a pane's scroll across frame
        # rebuilds with (bug docs/qa/2026-10-03-preview-scroll-reset.md):
        # ``slotKey`` names the slot (the pair plus the half — a pinned card
        # and its live duplicate are two slots), ``rev`` is the column VM's
        # construction stamp for THIS card: a card rebuilt because its row
        # really changed (a save, a pin transition) arrives with a new rev,
        # so the remembered offset belongs to the old content only. The
        # column VM owns the counter; a card never invents its own rev.
        self.slot_key = f"{entity_type}/{self.entity_id}#{'pinned' if pinned else 'live'}"
        self.rev = rev
        # The content half of the reuse decision (see ``content_fingerprint``):
        # the column VM compares it against a freshly computed stamp before
        # letting this construction ride the next frame.
        self.content_fingerprint = content_fingerprint(entity_type, entity)
        # The pane's pin state word (checkpoint п.5: the column VM is its ONLY
        # author — "unpin" / "duplicate" / "limit"); the island maps the word
        # to the four fixed name/tooltip formulations and never counts.
        self.pin_state = pin_state
        self._now_vm = now_vm
        self.name_text = str(getattr(entity, "name", "") or "")
        # The band never dangles empty off the bat: the type-titled caption is
        # built right away; the plain «Карточка» word belongs to the column's
        # empty state, which has no card at all. Since the reader's fix of
        # 2026-10-03 the shown entity's name rides the caption too (up to
        # four cards share the column — the headline must say WHICH card it
        # is; the duplicate with the name field inside is the point), glued
        # by the same middle dot the timeline's search row uses since
        # NRI-0023. A name-less duck (never a stored entity) keeps the
        # type-only caption.
        type_caption = f"{CARD_TITLE_LABEL}: {entity_registry.display_label(entity_type)}"
        self.title = (
            f"{type_caption} · {self.name_text}" if self.name_text else type_caption
        )
        rating = getattr(entity, "rating", 1)
        if not isinstance(rating, int):
            rating = 1
        self.rating_text = f"Рейтинг: {rating}/20"

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
        self.date_text = f"{start} — {end}"
        self._start_bc = start_bc
        self._end_bc = end_bc
        self.age_text = self._age_line()

        music_url = getattr(entity, "music_url", "")
        self.music_url = music_url if isinstance(music_url, str) else ""

        self.image_source = self._image_source_text()
        self.sections = self._text_sections()
        self.related_sections = self._related()

    # ── the pane contract for the island (design Д2/Д6) ─────────────────────

    def pane(self) -> dict[str, Any]:
        """The card as one pane entry of the column VM's ``panes`` list. The
        identity pair rides along so a pane delegate can raise the pin and
        picture gestures by pair, never by a prunable index (design Д2);
        ``pinned``/``slotIndex`` tell the usage site which face it paints and
        ``pinState`` carries the authored pin state word (checkpoint п.5) —
        the island maps it to the four fixed formulations, the counting and
        the capacity rule never leave the column VM. ``slotKey``/``rev`` are
        the slot identity behind the island's scroll memory (2026-10-03 fix):
        the key names the slot across frame rebuilds, the rev says whether
        the card behind it is still the same construction."""
        return {
            "slotIndex": self.slot_index,
            "pinned": self.pinned,
            "pinState": self.pin_state,
            "slotKey": self.slot_key,
            "rev": self.rev,
            "entityType": self.entity_type,
            "entityId": self.entity_id,
            "title": self.title,
            "nameText": self.name_text,
            "ratingText": self.rating_text,
            "dateText": self.date_text,
            "ageText": self.age_text,
            "musicUrl": self.music_url,
            "imageSource": self.image_source,
            "sections": self.sections,
            "relatedSections": self.related_sections,
        }

    # ── the «now»-derived half ───────────────────────────────────────────────

    def recount_age(self) -> None:
        """Re-count the age line against the game's «now» (the column VM's
        single subscription fans out here; every other field is «now»-free)."""
        self.age_text = self._age_line()

    def _age_line(self) -> str:
        """The «Возраст: <формула>» row — the one age rule (``format_age_words``,
        NRI-0021 Д5) served under the same absence postures as the summary:
        age-free types and a panel built without a «now» simply show no row,
        and a coordinate the active calendar refuses hides it (never a crash)."""
        if self._now_vm is None or self.entity_type not in AGE_ENTITY_TYPES:
            return ""
        start = getattr(self.entity, "start_date", None)
        if start is None:
            return ""
        try:
            age_words = format_age_words(
                start,
                self._start_bc,
                getattr(self.entity, "end_date", None),
                self._end_bc,
                self._now_vm.coord,
                self._now_vm.is_bc,
            )
        except InvalidGameDateError:
            return ""
        return f"{AGE_LABEL}: {age_words}"

    # ── the unchanged NRI-0022 render halves ─────────────────────────────────

    def _image_source_text(self) -> str:
        """The preview file's URL, or the empty string the island paints as the
        «Нет изображения» placeholder. Decided through the shared pipeline: a
        null pixmap (no link, no directory, a missing or corrupt file) degrades
        to the placeholder exactly like the card's slot (spec image-display)."""
        pixmap = load_entity_preview(self.entity, slot_size=IMAGE_SLOT_SIZE)
        if pixmap.isNull():
            return ""
        return QUrl.fromLocalFile(str(resolve_preview_path(self.entity))).toString()

    def _text_sections(self) -> list[dict[str, str]]:
        description = getattr(self.entity, "description", None)
        sections: list[dict[str, str]] = []
        for key, label, attr in _TEXT_FIELDS:
            if key in ("characteristics", "backstory"):
                value = getattr(description, attr, "") if description else ""
            else:
                value = getattr(self.entity, attr, "") or ""
            if value and value.strip():
                sections.append({"key": key, "label": label, "html": build_mention_html(value)})
        return sections

    def _related(self) -> list[dict[str, Any]]:
        """Compact sections per the registry's relation config, in its order;
        a section without rows is not built at all (spec «Нет связей — нет
        блока»), so the island paints no empty block to hide."""
        sections: list[dict[str, Any]] = []
        for ref in entity_registry.related_refs_for_key(self.entity_type):
            rows = [
                {
                    "name": str(getattr(related, "name", "") or ""),
                    "type": ref.entity_type.value,
                    "id": getattr(related, "id", 0) or 0,
                }
                for related in (getattr(self.entity, ref.attr, None) or [])
            ]
            if rows:
                sections.append({"key": ref.attr, "label": ref.label, "rows": rows})
        return sections
