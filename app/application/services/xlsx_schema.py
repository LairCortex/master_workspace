"""Declarative registry of the unified .xlsx import file format (design D1).

One source of truth for the parser, the dialog hint and the template: five
named sheets, their RU column headers (with the old English headers accepted
as aliases), required/optional flags, special columns (``Тип`` / ``Изображение``
/ ``Рейтинг``) and the per-type link columns with their M2M association tables
(13 association tables minus the three ``*_rating`` ones, which import does
not support — see spec "Колонки связей").

Header lookup is case- and whitespace-insensitive ("Дата  начала" ==
"датаначала"); link-cell values, dates and ratings are parsed here so all
consumers share identical edge-case behavior.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Iterator

# Separator inside a link cell (spec: "список имён целей через `;`").
LINK_SEPARATOR = ";"

# Scalar "Рейтинг" column bounds (spec: range 1–5; out-of-range is a row
# problem, never a silent clamp — design D7).
RATING_MIN = 1
RATING_MAX = 5

LINK_COLUMN_DESCRIPTION = "Имена целевых сущностей через `;`"


# ── Column model ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ColumnSpec:
    """A scalar / special column of a sheet.

    ``key`` is the internal field key consumed by the parser (and matching the
    ORM field where one exists). ``label`` is the canonical Russian header;
    ``aliases`` are the additional accepted headers (legacy English names of
    the previous single-sheet import format). ``special`` marks the three
    special columns named in the design (``Тип`` / ``Изображение`` /
    ``Рейтинг``).
    """

    key: str
    label: str
    aliases: tuple[str, ...] = ()
    required: bool = False
    special: bool = False
    description: str = ""

    @property
    def accepted_headers(self) -> tuple[str, ...]:
        return (self.label,) + self.aliases


@dataclass(frozen=True)
class LinkColumnSpec:
    """A per-target link column ("Связь персонажами" etc.) of a sheet."""

    target_type: str
    label: str
    description: str = LINK_COLUMN_DESCRIPTION


@dataclass(frozen=True)
class SheetSpec:
    """Registry entry for one of the five sheets."""

    entity_type: str
    sheet_name: str
    columns: tuple[ColumnSpec, ...]
    link_targets: tuple[str, ...]

    @property
    def link_columns(self) -> tuple[LinkColumnSpec, ...]:
        return tuple(LINK_COLUMNS_BY_TARGET[t] for t in self.link_targets)

    @property
    def required_columns(self) -> tuple[ColumnSpec, ...]:
        return tuple(c for c in self.columns if c.required)

    def column(self, key: str) -> ColumnSpec | None:
        return next((c for c in self.columns if c.key == key), None)


# ── Columns ───────────────────────────────────────────────────────────────
# Russian labels are the primary headers of the new format; the English names
# are the column headers of the old single-sheet import format and stay valid
# as aliases (spec "Колонки листа").
#
# ``personality`` / ``tasks`` / ``music_url`` have no Russian counterpart in
# the spec's column list: only their legacy English headers are accepted
# (the old parser read exactly these fields; the hint texts keep the old
# descriptions for continuity).

COL_NAME = ColumnSpec(
    key="name", label="Имя", aliases=("name",), required=True,
    description="Имя / название сущности",
)
COL_START_DATE = ColumnSpec(
    key="start_date", label="Дата начала", aliases=("start_date",), required=True,
    description="Начало: YYYY-MM-DD, дата Excel (наша эра), «5 марта 44 г. до н.э.» "
                "или -0044-03-05",
)
COL_END_DATE = ColumnSpec(
    key="end_date", label="Дата конца", aliases=("end_date",),
    description="Конец: форматы те же, что у даты начала",
)
COL_CHARACTERISTICS = ColumnSpec(
    key="characteristics", label="Характеристики", aliases=("characteristics",),
    description="Описание / характеристики",
)
COL_BACKSTORY = ColumnSpec(
    key="backstory", label="Предыстория", aliases=("backstory",),
    description="Предыстория",
)
COL_RATING = ColumnSpec(
    key="rating", label="Рейтинг", special=True,
    description=f"Целое число {RATING_MIN}..{RATING_MAX}",
)
COL_IMAGE = ColumnSpec(
    key="image", label="Изображение", aliases=("image",), special=True,
    description="Путь к файлу картинки (относительно каталога .xlsx или абсолютный)",
)
COL_EVENT_TYPE = ColumnSpec(
    key="event_type", label="Тип", special=True,
    description="Тип события (отсутствующий тип создаётся автоматически)",
)
COL_PERSONALITY = ColumnSpec(
    key="personality", label="personality",
    description="Личность",
)
COL_TASKS = ColumnSpec(
    key="tasks", label="tasks",
    description="Задачи",
)
COL_MUSIC_URL = ColumnSpec(
    key="music_url", label="music_url",
    description="Ссылка на музыкальную тему",
)

_ALL_ENTITY_TYPES: tuple[str, ...] = ("event", "character", "location", "organization", "item")

# Link column per *target* type (spec "Колонки связей"). The association table
# for a (source, target) pair lives in LINK_TABLES below.
LINK_COLUMNS_BY_TARGET: dict[str, LinkColumnSpec] = {
    "event": LinkColumnSpec(target_type="event", label="Связь событиями"),
    "character": LinkColumnSpec(target_type="character", label="Связь персонажами"),
    "organization": LinkColumnSpec(target_type="organization", label="Связь организациями"),
    "item": LinkColumnSpec(target_type="item", label="Связь предметами"),
    "location": LinkColumnSpec(target_type="location", label="Связь локациями"),
}

# (source entity type, target entity type) → M2M association table, as defined
# in app/infrastructure/db/models.py. Covers all 13 M2M tables except the
# three ``*_rating`` ones (ratings are out of import scope).
_LINK_TABLE_FACTS: tuple[tuple[str, str, str], ...] = (
    ("event", "organization", "event_organization"),
    ("event", "character", "event_character"),
    ("event", "item", "event_item"),
    ("event", "location", "event_location"),
    ("organization", "character", "organization_character"),
    ("organization", "item", "organization_item"),
    ("organization", "location", "organization_location"),
    ("character", "item", "character_item"),
    ("character", "location", "character_location"),
    ("item", "location", "item_location"),
)

LINK_TABLES: dict[tuple[str, str], str] = {}
for _src, _dst, _table in _LINK_TABLE_FACTS:
    LINK_TABLES[(_src, _dst)] = _table
    LINK_TABLES[(_dst, _src)] = _table


# ── Sheet registry ────────────────────────────────────────────────────────

def _common_columns() -> tuple[ColumnSpec, ...]:
    # Required + optional columns present on every sheet (spec "Колонки листа").
    return (COL_NAME, COL_START_DATE, COL_END_DATE, COL_CHARACTERISTICS, COL_BACKSTORY, COL_RATING)


SHEETS: dict[str, SheetSpec] = {
    spec.entity_type: spec
    for spec in (
        SheetSpec(
            entity_type="event",
            sheet_name="События",
            columns=_common_columns() + (COL_EVENT_TYPE,),
            link_targets=("character", "organization", "item", "location"),
        ),
        SheetSpec(
            entity_type="character",
            sheet_name="Персонажи",
            columns=_common_columns() + (COL_PERSONALITY, COL_TASKS, COL_MUSIC_URL, COL_IMAGE),
            link_targets=("event", "organization", "item", "location"),
        ),
        SheetSpec(
            entity_type="location",
            sheet_name="Локации",
            columns=_common_columns() + (COL_TASKS, COL_MUSIC_URL, COL_IMAGE),
            link_targets=("event", "character", "organization", "item"),
        ),
        SheetSpec(
            entity_type="organization",
            sheet_name="Организации",
            columns=_common_columns() + (COL_TASKS, COL_MUSIC_URL, COL_IMAGE),
            link_targets=("event", "character", "item", "location"),
        ),
        SheetSpec(
            entity_type="item",
            sheet_name="Предметы",
            columns=_common_columns() + (COL_MUSIC_URL,),
            link_targets=("event", "character", "organization", "location"),
        ),
    )
}


def all_sheets() -> tuple[SheetSpec, ...]:
    return tuple(SHEETS[t] for t in _ALL_ENTITY_TYPES)


def sheet_for(entity_type: str) -> SheetSpec:
    try:
        return SHEETS[entity_type.lower()]
    except KeyError:
        raise ValueError(f"Неизвестный тип сущности: {entity_type}") from None


def find_sheet_by_name(name: object) -> SheetSpec | None:
    """Match a workbook sheet title to a registry entry (case/space-insensitive)."""
    normalized = normalize_header(name)
    return next((s for s in SHEETS.values() if normalize_header(s.sheet_name) == normalized), None)


# ── Header resolution ─────────────────────────────────────────────────────

def normalize_header(raw: object) -> str:
    """Case- and whitespace-insensitive form of a header/sheet name."""
    if raw is None:
        return ""
    return "".join(str(raw).split()).casefold()


@dataclass(frozen=True)
class ResolvedHeaders:
    """Header row of a sheet mapped onto registry columns.

    ``scalars`` / ``links`` map a column position in the header row to the
    matched column; on duplicate headers the first occurrence wins. Every
    header that matches neither a scalar nor an allowed link column of the
    sheet lands in ``unknown`` and is ignored (spec "дополнительные
    неизвестные колонки SHALL игнорироваться").
    """

    scalars: dict[int, ColumnSpec]
    links: dict[int, LinkColumnSpec]
    unknown: list[str]

    def position(self, key: str) -> int | None:
        for pos, col in self.scalars.items():
            if col.key == key:
                return pos
        return None


def match_header(sheet: SheetSpec, raw: object) -> ColumnSpec | LinkColumnSpec | None:
    """Resolve a single header cell against the sheet's columns (or None)."""
    normalized = normalize_header(raw)
    if not normalized:
        return None
    for col in sheet.columns:
        if normalized in (normalize_header(h) for h in col.accepted_headers):
            return col
    for target in sheet.link_targets:
        link = LINK_COLUMNS_BY_TARGET[target]
        if normalized == normalize_header(link.label):
            return link
    return None


def resolve_headers(sheet: SheetSpec, headers: Iterable[object]) -> ResolvedHeaders:
    scalars: dict[int, ColumnSpec] = {}
    links: dict[int, LinkColumnSpec] = {}
    unknown: list[str] = []
    seen: set[str] = set()
    for pos, raw in enumerate(headers):
        matched = match_header(sheet, raw)
        if matched is None:
            text = str(raw).strip() if raw is not None else ""
            if text:
                unknown.append(text)
            continue
        marker = normalize_header(matched.label)
        if marker in seen:
            continue  # duplicate header: first occurrence wins
        seen.add(marker)
        if isinstance(matched, LinkColumnSpec):
            links[pos] = matched
        else:
            scalars[pos] = matched
    return ResolvedHeaders(scalars=scalars, links=links, unknown=unknown)


def missing_required_headers(sheet: SheetSpec, headers: Iterable[object]) -> list[str]:
    """Labels of required columns absent from the header row (empty ⇒ OK)."""
    resolved = resolve_headers(sheet, headers)
    present = {col.key for col in resolved.scalars.values()}
    return [col.label for col in sheet.required_columns if col.key not in present]


def link_table(source_type: str, target_type: str) -> str:
    """Association M2M table for a (source, target) pair (order-insensitive)."""
    try:
        return LINK_TABLES[(source_type, target_type)]
    except KeyError:
        raise ValueError(
            f"Связь {source_type} ↔ {target_type} не поддерживается импортом"
        ) from None


# ── Value parsing (shared edge-case semantics) ────────────────────────────

def parse_cell_date(value: object) -> tuple[date, bool] | None:
    """Native Excel cell or text date → ``(date, is_bc)``; else None.

    Era vocabulary of add-era-aware-dates (design D7): native Excel cells and
    bare ISO ``YYYY-MM-DD`` are our era exactly as before; the added BC text
    forms are the game-style «N г. до н.э.» with a mandatory month
    («5 марта 44 г. до н.э.») and the signed ISO ``-YYYY-MM-DD`` with years
    1…9999 (no year zero). Empty cells, blanks and unparsable text (e.g.
    "31.12.2025" or a month-less "44 г. до н.э.") all yield None — callers
    treat None start_date as a row problem (spec "Битая дата начала").
    """
    if isinstance(value, datetime):
        return value.date(), False
    if isinstance(value, date):
        return value, False
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.startswith("-"):
            return _parse_bc_iso(text)
        try:
            return date.fromisoformat(text), False
        except ValueError:
            pass
        return _parse_bc_text(text)
    return None


# «N г. до н.э.» — the Russian/game game-display wording with the mandatory
# era suffix; month and day are required (spec: «месяц при этом обязателен»).
# Both the genitive scenario spelling («5 марта …») and the nominative form
# the display prints («05 Март …») are accepted, as well as the optional
# punctuation dots of the era suffix.
_BC_TEXT_RE = re.compile(
    r"^(?P<day>\d{1,2})\s+(?P<month>[a-zа-яё]+)\s+(?P<year>\d{1,4})\s*"
    r"г\.?\s*до\s*н\.?\s*э\.?$",
    re.IGNORECASE,
)

# Signed ISO form of the BC era: -YYYY-MM-DD, years 1…9999.
_BC_ISO_RE = re.compile(r"^-(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$")

# Default Russian month names in nominative + genitive (mirrors the game
# display vocabulary; custom per-game month names are out of parse scope).
_BC_MONTHS: dict[str, int] = {
    name: number
    for number, forms in (
        (1, ("январь", "января")), (2, ("февраль", "февраля")),
        (3, ("март", "марта")), (4, ("апрель", "апреля")),
        (5, ("май", "мая")), (6, ("июнь", "июня")),
        (7, ("июль", "июля")), (8, ("август", "августа")),
        (9, ("сентябрь", "сентября")), (10, ("октябрь", "октября")),
        (11, ("ноябрь", "ноября")), (12, ("декабрь", "декабря")),
    )
    for name in forms
}


def _parse_bc_iso(text: str) -> tuple[date, bool] | None:
    match = _BC_ISO_RE.match(text)
    if match is None:
        return None
    year, month, day = (int(match.group(name)) for name in ("year", "month", "day"))
    try:
        # date() enforces the shared 1…9999 year bounds of both eras.
        return date(year, month, day), True
    except ValueError:
        return None  # year 0 / impossible month-day


def _parse_bc_text(text: str) -> tuple[date, bool] | None:
    match = _BC_TEXT_RE.match(text)
    if match is None:
        return None
    month = _BC_MONTHS.get(match.group("month").lower())
    if month is None:
        return None  # month must be given in the Russian/game wording
    try:
        return date(int(match.group("year")), month, int(match.group("day"))), True
    except ValueError:
        return None


def parse_cell_rating(value: object) -> int | None:
    """Integer rating 1..5; None for empty cells; ValueError for garbage.

    Out-of-range or non-integer content raises ValueError so the pre-analysis
    can mark the row as a problem instead of silently clamping (design D7).
    Booleans are rejected explicitly (an Excel TRUE is not a rating).
    """
    if value is None:
        return None
    candidate: int
    if isinstance(value, bool):
        raise ValueError(f"рейтинг «{value}» — не число")
    if isinstance(value, int):
        candidate = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"рейтинг «{value}» — не целое число")
        candidate = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            candidate = int(text)
        except ValueError:
            raise ValueError(f"рейтинг «{text}» — не целое число") from None
    else:
        raise ValueError(f"рейтинг «{value!r}» — недопустимое значение")
    if not RATING_MIN <= candidate <= RATING_MAX:
        raise ValueError(
            f"рейтинг {candidate} вне диапазона {RATING_MIN}..{RATING_MAX}"
        )
    return candidate


def parse_link_cell(value: object) -> list[str]:
    """Split a link cell on ``;``; segments are stripped, blanks skipped.

    Order and duplicates are preserved — deduplication of the final link set
    belongs to the apply pass (design D4).
    """
    if value is None:
        return []
    return [seg.strip() for seg in str(value).split(LINK_SEPARATOR) if seg.strip()]


def all_headers(sheet: SheetSpec) -> Iterator[ColumnSpec | LinkColumnSpec]:
    """Scalar/special columns followed by the sheet's link columns."""
    yield from sheet.columns
    yield from sheet.link_columns


__all__ = [
    "LINK_SEPARATOR",
    "LINK_TABLES",
    "LINK_COLUMNS_BY_TARGET",
    "ColumnSpec",
    "LinkColumnSpec",
    "ResolvedHeaders",
    "SheetSpec",
    "SHEETS",
    "all_headers",
    "all_sheets",
    "find_sheet_by_name",
    "link_table",
    "match_header",
    "missing_required_headers",
    "normalize_header",
    "parse_cell_date",
    "parse_cell_rating",
    "parse_link_cell",
    "resolve_headers",
    "sheet_for",
]
