"""Infrastructure access to the per-game ``game_settings`` key/value table.

Single place where this table is touched (audit B2, task 6.2): both the
calendar settings service and the LLM prompts used to hand-roll the same
``select``-then-insert/update dance — the duplication is collapsed here so
every key goes through one get/upsert/delete trio.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.game_calendar import GameCoord, current_calendar
from app.infrastructure.calendar_storage import (
    CoordCorrupted,
    decode_coord,
    encode_coord,
)
from app.infrastructure.db.models import GameSettingsModel

_LOGGER = logging.getLogger(__name__)

# ── ``game_settings`` storage keys (roadmap pieces C2/C4, designs D1/D6) ──

#: Key under which the game's active calendar setting lives in the per-game
#: ``game_settings`` key/value table.
CALENDAR_SETTINGS_KEY = "game_calendar"

#: Key under which the calendar wizard keeps its work-in-progress draft
#: (piece C4, design D6): the same versioned spec body as the main key, lined
#: with a stage marker.  Never consulted on game open — a draft warms the
#: wizard flow only, never the active calendar (spec «Черновик мастера
#: календаря»).
CALENDAR_DRAFT_KEY = "game_calendar_draft"

#: Key of the binary «wizard seen» flag (C4): a game created by this version
#: is seeded with :data:`CALENDAR_WIZARD_SEEN_NO`, a keyless game reads as an
#: old one that never sees the wizard automatically, and the flag influences
#: nothing but the wizard's auto-show (spec «Флаг просмотра мастера
#: календаря»).
CALENDAR_WIZARD_SEEN_KEY = "calendar_wizard_seen"

#: The two stored texts of the flag.
CALENDAR_WIZARD_SEEN_NO = "0"
CALENDAR_WIZARD_SEEN_YES = "1"

#: Key of the game's «now» date (NRI-0021, design Д1): the coordinate of the
#: active calendar with its era flag, stored as JSON ``{"coord": <encoded
#: coordinate>, "bc": 0|1}`` through the :mod:`app.infrastructure.calendar_storage`
#: codec.  Since NRI-0023 (task 2.3) the same JSON carries the optional hour
#: key ``"h"`` — an integer of the active calendar's day; the key is written
#: only when a hour is set, so pre-0023 values stay byte-identical and stay
#: readable ("no key = no hour").  The key is seeded nowhere — its absence is
#: the rule "real today translated into the active calendar", the first
#: explicit edit is the first write (spec «Игровая «сейчас» хранится одна на
#: игру»).
CURRENT_DATE_KEY = "current_date"

#: Key of the preview column's pinned cards (NRI-0025, design Д3): a JSON
#: array ``[{"t": <type>, "i": <id>}]`` whose order IS the pin order, read
#: and written through :class:`PreviewPinsRepository`.  The key is seeded
#: nowhere — its absence is the normal «nothing pinned yet» state, a damaged
#: value reads as the empty list with a journal entry, and an unavailable
#: pair is dropped silently at restore by the connector (spec «Закрепления
#: хранятся в настройках игры и переживают перезапуск»).
PREVIEW_PINS_KEY = "preview_pins"

#: Key of the D&D-module flag (add-dnd-module-foundation, design Д1): a JSON
#: object ``{"enabled": <bool>, "version": <int>}`` whose ``version`` is the
#: module data-format version that wrote it (a module version, not an app
#: version — it lives slower than releases). The key is seeded nowhere: its
#: absence is the ordinary game. The composition point ``app/main.py`` reads
#: it through :func:`decode_dnd_module_flag` BEFORE composing any module
#: (spec «Признак модуля определяет состав»); the module's own service (the
#: lifecycle group) writes it through this very registry, so the single
#: transaction finish point holds. The row is never rewritten on a read: a
#: damaged value reads as «module off» with the one journal entry and stays
#: byte-identical for the next explicit write.
DND_MODULE_KEY = "dnd_module"

#: Key of the D&D datasets a game connects to (add-dnd-module-foundation,
#: task 3.4, design Д4): a JSON array of dataset-id strings — ``["srd51",
#: "my-pack"]`` — the ids pointing at the GLOBAL dataset storage
#: (``~/.nri_manager/datasets/``), never at game rows: connecting a set
#: writes only this row, disconnecting removes only the link. The key is
#: seeded nowhere (its absence is «no sets connected»), and a damaged value
#: reads as the empty list with the one journal entry, the row staying
#: byte-identical for the next explicit connect/disconnect (the absent-value
#: discipline of the other typed keys). An id whose file has since left the
#: storage is NOT silently dropped here — the module shows it as missing
#: (spec «Пропавший набор помечен»).
DND_DATASETS_KEY = "dnd_datasets"

#: Key of the game's «показывать справочные записи в поиске» toggle
#: (add-dnd-game-face task 3.3, spec dnd-reference-records «Справочные
#: сущности участвуют в поиске под одним переключателем»): a JSON boolean —
#: ``true``/``false`` — seeded NOWHERE, so the key's absence is the spec's
#: default «показывать» (the reference is discovered on the module's first
#: enable). A damaged value reads as the same default WITH the one journal
#: entry the codec logs and stays byte-identical for the checkbox's next
#: explicit write; the row is never rewritten on a read (the absent-value
#: discipline of the other typed keys).
DND_SEARCH_SHOW_REFERENCE_KEY = "dnd_search_show_reference"

#: Key of the D&D grimoires a game connects to (add-dnd-game-face, task 4.2,
#: design Д6; spec dnd-grimoire-import «Игра подключает гримуары списком,
#: отключение обратимо»): a JSON array of grimoire-id strings — ``["my-spells",
#: "tina-grimoire"]`` — the ids pointing at the GLOBAL grimoire storage
#: (``~/.nri_manager/grimoires/``), never at game rows: connecting a grimoire
#: writes only this row, disconnecting removes only the link and the file
#: stays. Seeded nowhere (its absence is «no grimoires connected»); a damaged
#: value reads as the empty list with the one journal entry the codec logs and
#: stays byte-identical for the next explicit write (the absent-value
#: discipline of the other typed keys). Whether an id still has a file is the
#: module's reading rule (spec «Пропавший файл помечен» — the id is never
#: dropped silently), not the codec's.
DND_GRIMOIRES_KEY = "dnd_grimoires"

#: The module data-format version THIS application writes into the flag
#: (add-dnd-module-foundation tasks 2.1/2.6, design Д1). The number lives in
#: the kernel's key registry — not inside ``app/dd`` — because the ordinary
#: kernel reads it twice: the composition compares it with the stored version
#: (a game written by a newer module opens ordinary with a warning), and the
#: synchronous launcher seeds it when the master picks the «D&D» system at
#: creation (game_manager may not import the module package, guard
#: tests/test_dd_module_isolation.py). ``app/dd`` re-exports it under its own
#: name; bumping THIS constant is the single edit a module data-format
#: change makes in the kernel.
DND_MODULE_DATA_VERSION = 1


def encode_dnd_module_flag(enabled: bool, version: int) -> str:
    """JSON body of design Д1: ``{"enabled": <bool>, "version": <int>}`` — the
    exact shape :func:`decode_dnd_module_flag` reads back. The counterpart of
    the codec lives here so every writer (the module's settings service, the
    launcher's synchronous creation seed) shares one format; like the other
    encoders this one never re-validates invented semantics beyond types —
    callers pass booleans and positive integers by construction."""
    return json.dumps({"enabled": bool(enabled), "version": int(version)})


class GameSettingsRepository:
    """Key/value CRUD over ``game_settings`` for one bound session.

    Deliberately uncommitted: the repository never commits or rolls back —
    the caller owns the transaction (services via their own discipline or
    the game's unit of work).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> str | None:
        """Stored text for ``key``, or ``None`` when the key is absent."""
        result = await self._session.execute(
            select(GameSettingsModel).where(GameSettingsModel.key == key)
        )
        row = result.scalars().first()
        return row.value if row is not None else None

    async def upsert(self, key: str, value: str) -> None:
        """Store ``value`` under ``key``, overwriting an existing row in place."""
        result = await self._session.execute(
            select(GameSettingsModel).where(GameSettingsModel.key == key)
        )
        row = result.scalars().first()
        if row is None:
            self._session.add(GameSettingsModel(key=key, value=value))
        else:
            row.value = value

    async def delete(self, key: str) -> None:
        """Delete ``key`` when present; an absent key is a silent no-op."""
        result = await self._session.execute(
            select(GameSettingsModel).where(GameSettingsModel.key == key)
        )
        row = result.scalars().first()
        if row is not None:
            await self._session.delete(row)


# ── Typed «now» storage (NRI-0021 task 2.1, design Д1) ─────────────────────


@dataclass(frozen=True)
class CurrentDateValue:
    """The decoded stored «now»: a coordinate of the active calendar, the era
    flag and the optional hour — the value design Д2 names for the service to
    hold, the hour added by NRI-0023 (task 2.3, spec «Игровая «сейчас»
    хранится одна на игру»).  ``hour=None`` means «час не выставлен» — the
    state every pre-0023 value and every fresh seed carries.  Pure data;
    every reading rule ("absent", "corrupted", "out-of-range hour") lives in
    :class:`CurrentDateRepository`."""

    coord: GameCoord
    is_bc: bool
    hour: int | None = None


def _current_date_corrupt(reason: str, raw: str) -> None:
    """Log one corruption the way the calendar key already phrases it (design
    Д1: «поведение как у „Повреждённое значение календарь-ключа“» — a warning
    and life by the absence rule; the damaged row is left untouched)."""
    _LOGGER.warning(
        "Ignoring corrupted %s setting (%s): %r", CURRENT_DATE_KEY, reason, raw
    )


def _encode_current_date(
    coord: GameCoord, is_bc: bool, hour: int | None = None
) -> str:
    """JSON body of design Д1: ``{"coord": <encode_coord text>, "bc": 0|1}``,
    NRI-0023 extended with ``"h": <int>`` only when a hour is set — a value
    without an hour stays byte-identical to the pre-0023 format, so writing
    never strands an older app on an unreadable key (v1-compatible codec).
    The coordinate codec owns the coordinate text and refuses non-coordinates
    itself (``TypeError``) — this wrapper never invents a stored date."""
    body: dict = {"coord": encode_coord(coord), "bc": 1 if is_bc else 0}
    if hour is not None:
        body["h"] = hour
    return json.dumps(body, ensure_ascii=False)


def _decode_current_date(raw: str) -> CurrentDateValue | None:
    """Read the stored JSON back, ``None`` for anything unreadable.

    Every rejection (unparseable JSON, a foreign shape, a missing or non
    ``0|1`` ``bc``, an off-type ``h``, a coordinate text the codec itself
    refuses) logs the one warning naming the reason and answers ``None`` —
    the caller then lives by the absence rule; the row is never rewritten
    here (same discipline as :meth:`CalendarSettingsService.load_and_apply`).
    The NRI-0023 hour: an absent key means "not set"; a stored hour the
    *active* calendar no longer has (a narrowed day after a calendar switch)
    reads silently as "not set" — the signature loses its hour without any
    write (design Д5, spec «Сужение суток чистит недоступный час»), while the
    date itself keeps serving."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _current_date_corrupt("not parseable JSON", raw)
        return None
    if not isinstance(data, dict):
        _current_date_corrupt(
            f"must be a JSON object, got {type(data).__name__}", raw
        )
        return None
    bc_raw = data.get("bc")
    if isinstance(bc_raw, bool) or bc_raw not in (0, 1):
        _current_date_corrupt(f"era flag {bc_raw!r} is neither 0 nor 1", raw)
        return None
    hour: int | None = None
    if "h" in data:
        h_raw = data["h"]
        if isinstance(h_raw, bool) or not isinstance(h_raw, int):
            _current_date_corrupt(f"hour {h_raw!r} is not an integer", raw)
            return None
        if 0 <= h_raw < current_calendar().day_hours:
            hour = h_raw
    decoded = decode_coord(data.get("coord"))
    if isinstance(decoded, CoordCorrupted):
        _current_date_corrupt(
            "; ".join(f"{p.code}: {p.message}" for p in decoded.reasons), raw
        )
        return None
    return CurrentDateValue(coord=decoded.coord, is_bc=bc_raw == 1, hour=hour)


class CurrentDateRepository:
    """Typed storage access for the per-game ``current_date`` key.

    The same typed-wrapper pattern as :class:`LlmSettingsRepository`: a thin
    face over the shared :class:`GameSettingsRepository` trio, owning the
    JSON ``{"coord", "bc"}`` format on top of the coordinate codec.  Reads
    that find an unreadable value (unparsable body, malformed coordinate, or
    a coordinate the *active* calendar cannot host — a calendar switch may
    leave it out of range, design Д1/Риск) log and answer ``None``, leaving
    the row byte-identical for the first explicit edit to overwrite.  Like
    the trio below, this repository never commits — the caller owns the
    transaction (the service's unit of work).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._settings = GameSettingsRepository(session)

    async def load(self) -> CurrentDateValue | None:
        """The stored «now», or ``None`` for "absent or unreadable"."""
        raw = await self._settings.get(CURRENT_DATE_KEY)
        if raw is None:
            return None
        value = _decode_current_date(raw)
        if value is None:
            return None
        if not current_calendar().is_valid(value.coord):
            _current_date_corrupt(
                f"coordinate {encode_coord(value.coord)} does not exist in the "
                "active calendar",
                raw,
            )
            return None
        return value

    async def save(
        self, coord: GameCoord, is_bc: bool, hour: int | None = None
    ) -> None:
        """Store ``coord``/``is_bc`` (and the optional ``hour``) as the game's
        «now», overwriting any previous (even corrupted) value — «Перезапись
        вместо ремонта».          ``hour=None`` writes no ``h`` key at all, keeping
        the value in the pre-0023 shape (v1-compatible codec)."""
        await self._settings.upsert(
            CURRENT_DATE_KEY, _encode_current_date(coord, is_bc, hour)
        )


# ── Typed preview-pins storage (NRI-0025 task 1.1, design Д3) ───────────────


def _preview_pins_corrupt(reason: str, raw: str) -> None:
    """Log one corruption the way the other typed keys phrase it: a damaged
    pins list reads as empty with a journal entry and life by the absence
    rule (task 1.1); the row itself is left untouched — the next explicit
    pin/unpin rewrites a clean list (design Д3: no background repair write)."""
    _LOGGER.warning(
        "Ignoring corrupted %s setting (%s): %r", PREVIEW_PINS_KEY, reason, raw
    )


#: One stored pin id: integer for a kernel entity, non-empty text (including
#: the composite «источник/запись») for a registered external entity
#: (add-dnd-game-face task 6.2, spec preview-pins «числовой — для сущностей
#: ядра, строковый … для зарегистрированных внешних сущностей»).
PinId = int | str


def _encode_preview_pins(pins: Sequence[tuple[str, PinId]]) -> str:
    """JSON body of design Д3: ``[{"t": <type>, "i": <id>}]`` — the array
    order IS the pin order (spec «порядок сохраняется»).  The pairs arrive
    from the connector, whose types are entity strings by construction; the
    encoder never re-validates them (same division of labour as
    :func:`_encode_current_date` — no stored pair is invented here).  Since
    task 6.2 an ``i`` rides either an int (kernel row) or a str (external
    source id); JSON carries both shapes natively."""
    return json.dumps([{"t": t, "i": i} for t, i in pins], ensure_ascii=False)


def _decode_preview_pins(raw: str) -> list[tuple[str, PinId]]:
    """Read the stored array back, pair order preserved.

    All-or-nothing like the «now» codec: anything unreadable — unparsable
    JSON, a non-array body, an entry that is not an object, a ``t`` that is
    not text, or an ``i`` that is neither an integer nor non-empty text —
    logs the one warning naming the reason and answers the EMPTY list
    (task 1.1: «битый JSON читается как пустой список с записью в журнал»);
    the damaged row is never rewritten here.  Since task 6.2 the ``i`` half
    accepts BOTH id shapes (int for the kernel, str for a registered external
    source id — an empty string names no record and stays corruption).
    Whether a structurally fine pair still names an existing entity is
    the connector's restore rule (design Д3: unavailable pairs are dropped at
    read of the game open), not the codec's — a foreign type text reads back
    exactly as stored.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _preview_pins_corrupt("not parseable JSON", raw)
        return []
    if not isinstance(data, list):
        _preview_pins_corrupt(
            f"must be a JSON array, got {type(data).__name__}", raw
        )
        return []
    pins: list[tuple[str, PinId]] = []
    for entry in data:
        if not isinstance(entry, dict):
            _preview_pins_corrupt(f"entry {entry!r} is not a JSON object", raw)
            return []
        type_raw = entry.get("t")
        if not isinstance(type_raw, str):
            _preview_pins_corrupt(f"type {type_raw!r} is not text", raw)
            return []
        id_raw = entry.get("i")
        if isinstance(id_raw, bool):
            _preview_pins_corrupt(f"id {id_raw!r} is not an id", raw)
            return []
        if isinstance(id_raw, int):
            pins.append((type_raw, id_raw))
            continue
        if isinstance(id_raw, str) and id_raw:
            pins.append((type_raw, id_raw))
            continue
        _preview_pins_corrupt(f"id {id_raw!r} is neither an integer nor text", raw)
        return []
    return pins


class PreviewPinsRepository:
    """Typed storage access for the per-game ``preview_pins`` key.

    The same typed-wrapper pattern as :class:`CurrentDateRepository`: a thin
    face over the shared :class:`GameSettingsRepository` trio, owning the
    JSON ``[{"t", "i"}]`` format on top of it.  An absent key is the normal
    empty state and reads as the empty list WITHOUT a warning; a damaged
    value reads as the empty list WITH the one journal entry the codec logs,
    the row staying byte-identical for the next explicit pin/unpin to
    overwrite (design Д3: «молчаливое излечение хранилища» happens through
    the user's next write, never as a background rewrite).  Like the trio,
    this repository never commits — the caller owns the transaction (the
    service's unit of work).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._settings = GameSettingsRepository(session)

    async def load(self) -> list[tuple[str, PinId]]:
        """The stored pins in pin order — empty for "absent or unreadable"."""
        raw = await self._settings.get(PREVIEW_PINS_KEY)
        if raw is None:
            return []
        return _decode_preview_pins(raw)

    async def save(self, pins: Sequence[tuple[str, PinId]]) -> None:
        """Store the full list as the game's pins, overwriting any previous
        (even corrupted) value; the array order carries the pin order."""
        await self._settings.upsert(PREVIEW_PINS_KEY, _encode_preview_pins(pins))


# ── Typed D&D-module flag (add-dnd-module-foundation task 1.2, design Д1) ──


@dataclass(frozen=True)
class DndModuleFlag:
    """The decoded stored D&D flag: whether the module is on for this game
    and which module data-format version wrote it.  Pure data — every
    reading rule ("absent", "corrupted", "ahead of the supported version")
    lives in :func:`decode_dnd_module_flag` and the composition decision,
    never here."""

    enabled: bool
    version: int


def _dnd_module_corrupt(reason: str, raw: str) -> None:
    """Log one corruption the way the other typed keys phrase it: a damaged
    flag reads as «module off» with a journal entry and life by the absence
    rule (spec «Испорченный признак открывает игру как обычную»); the row
    itself is left byte-identical for the next explicit write."""
    _LOGGER.warning(
        "Ignoring corrupted %s setting (%s): %r", DND_MODULE_KEY, reason, raw
    )


def decode_dnd_module_flag(raw: str) -> DndModuleFlag | None:
    """Read the stored flag body, ``None`` for anything unreadable.

    All-or-nothing like the other typed codecs: anything unreadable —
    unparsable JSON, a non-object body, a missing or non-boolean
    ``enabled``, a missing/non-integer/boolean/non-positive ``version`` —
    logs the one warning naming the reason and answers ``None``; the caller
    then lives by the absence rule (design Д1: «нечитаемое значение
    трактуется как модуль выключен»), and the row is never rewritten here.
    Unknown extra keys pass untouched: the format grows additively, a newer
    writer must not turn a readable game into a corrupted one.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _dnd_module_corrupt("not parseable JSON", raw)
        return None
    if not isinstance(data, dict):
        _dnd_module_corrupt(
            f"must be a JSON object, got {type(data).__name__}", raw
        )
        return None
    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        _dnd_module_corrupt(f"enabled flag {enabled!r} is not a boolean", raw)
        return None
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        _dnd_module_corrupt(
            f"module version {version!r} is not a positive integer", raw
        )
        return None
    return DndModuleFlag(enabled=enabled, version=version)


# ── Typed D&D dataset connections (add-dnd-module-foundation task 3.4) ───────


def _dnd_datasets_corrupt(reason: str, raw: str) -> None:
    """Log one corruption the way the other typed keys phrase it: a damaged
    connection list reads as empty with a journal entry and life by the
    absence rule; the row itself stays byte-identical for the next explicit
    connect/disconnect to overwrite (no background repair)."""
    _LOGGER.warning(
        "Ignoring corrupted %s setting (%s): %r", DND_DATASETS_KEY, reason, raw
    )


def _encode_dnd_datasets(dataset_ids: Sequence[str]) -> str:
    """JSON array of dataset ids — the array order IS the connection order
    the screens show. The ids are storage names the module validated; this
    encoder, like the other ones, never re-invents them."""
    return _encode_id_list(dataset_ids)


def _encode_id_list(identifiers: Sequence[str]) -> str:
    """The one JSON-array-of-text body the id-list keys share (the dataset
    connections and, since add-dnd-game-face task 4.2, the grimoire
    connections): the array order IS the order the screens show."""
    return json.dumps(list(identifiers), ensure_ascii=False)


def _decode_dnd_datasets(raw: str) -> list[str]:
    """Read the stored array back, id order preserved, all-or-nothing like
    the preview-pins codec: anything unreadable — unparsable JSON, a
    non-array body, an entry that is not text — logs the one warning naming
    the reason and answers the EMPTY list; the damaged row is never
    rewritten here."""
    return _decode_id_list(raw, _dnd_datasets_corrupt)


def _decode_id_list(raw: str, corrupt: Callable[[str, str], None]) -> list[str]:
    """The one array-of-text reading rule the id-list keys share; every
    rejection goes to the caller's ``corrupt(reason, raw)`` logger, so each
    key keeps naming itself in the journal while the grammar lives once."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        corrupt("not parseable JSON", raw)
        return []
    if not isinstance(data, list):
        corrupt(f"must be a JSON array, got {type(data).__name__}", raw)
        return []
    ids: list[str] = []
    for entry in data:
        if not isinstance(entry, str):
            corrupt(f"entry {entry!r} is not text", raw)
            return []
        ids.append(entry)
    return ids


class DndDatasetsRepository:
    """Typed storage access for the per-game ``dnd_datasets`` key.

    The same typed-wrapper pattern as :class:`PreviewPinsRepository`: a thin
    face over the shared :class:`GameSettingsRepository` trio, owning the
    JSON ``["<dataset id>", …]`` format.  An absent key is the normal «no
    sets connected» state and reads as the empty list without a warning; a
    damaged value reads empty WITH the one journal entry the codec logs, the
    row staying byte-identical for the next explicit write.  Whether an id
    still has a file in the global storage is the module's reading rule
    (spec «Пропавший набор помечен» — it never deletes ids silently), not the
    codec's.  Like the trio, this repository never commits — the caller owns
    the transaction (the module service's unit of work).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._settings = GameSettingsRepository(session)

    async def load(self) -> list[str]:
        """The connected dataset ids in stored order — empty for «absent or
        unreadable»."""
        raw = await self._settings.get(DND_DATASETS_KEY)
        if raw is None:
            return []
        return _decode_dnd_datasets(raw)

    async def save(self, dataset_ids: Sequence[str]) -> None:
        """Store the full list as the game's connections, overwriting any
        previous (even corrupted) value; the array order is kept."""
        await self._settings.upsert(
            DND_DATASETS_KEY, _encode_dnd_datasets(dataset_ids)
        )


# ── Typed D&D reference-search toggle (add-dnd-game-face task 3.3) ───────────


def _dnd_search_show_reference_corrupt(reason: str, raw: str) -> None:
    """Log one corruption the way the other typed keys phrase it: a damaged
    value reads as the default «показывать» with a journal entry and life by
    the absence rule (the spec's default is visible, so the fallback for an
    unreadable row is the same answer as for a missing one); the row stays
    byte-identical for the checkbox's next explicit write."""
    _LOGGER.warning(
        "Ignoring corrupted %s setting (%s): %r",
        DND_SEARCH_SHOW_REFERENCE_KEY,
        reason,
        raw,
    )


def decode_dnd_search_show_reference(raw: str | None) -> bool:
    """Read the stored boolean; ``True`` for «absent, unreadable or true».

    The spec default is «показывать» (task 3.3), so both the missing key
    (``raw is None``) and anything unreadable — unparsable JSON, a non-boolean
    body — answer ``True``; only the damaged readings earn the one journal
    entry, the row is never rewritten here."""
    if raw is None:
        return True
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _dnd_search_show_reference_corrupt("not parseable JSON", raw)
        return True
    if not isinstance(data, bool):
        _dnd_search_show_reference_corrupt(
            f"must be a JSON boolean, got {type(data).__name__}", raw
        )
        return True
    return data


class DndSearchShowReferenceRepository:
    """Typed storage access for the per-game ``dnd_search_show_reference`` key.

    The same typed-wrapper pattern as :class:`DndDatasetsRepository`: a thin
    face over the shared :class:`GameSettingsRepository` trio owning the JSON
    boolean body. Absent or damaged reads as the spec default «показывать»
    (the damaged half through :func:`decode_dnd_search_show_reference`, which
    also logs the journal entry); the module's own visibility service writes
    through it. Like the trio, this repository never commits — the caller owns
    the transaction (the module service's unit of work).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._settings = GameSettingsRepository(session)

    async def load(self) -> bool:
        """The stored flag — ``True`` for «absent, damaged or true»."""
        raw = await self._settings.get(DND_SEARCH_SHOW_REFERENCE_KEY)
        return decode_dnd_search_show_reference(raw)

    async def save(self, enabled: bool) -> None:
        """Store the boolean, overwriting any previous (even corrupted) value."""
        await self._settings.upsert(
            DND_SEARCH_SHOW_REFERENCE_KEY, json.dumps(bool(enabled))
        )


# ── Typed D&D grimoire connections (add-dnd-game-face task 4.2) ─────────────


def _dnd_grimoires_corrupt(reason: str, raw: str) -> None:
    """Log one corruption the way the other typed keys phrase it: a damaged
    grimoire list reads as empty with a journal entry and life by the absence
    rule; the row itself stays byte-identical for the next explicit
    connect/disconnect to overwrite (no background repair)."""
    _LOGGER.warning(
        "Ignoring corrupted %s setting (%s): %r", DND_GRIMOIRES_KEY, reason, raw
    )


class DndGrimoiresRepository:
    """Typed storage access for the per-game ``dnd_grimoires`` key.

    The same typed-wrapper pattern as :class:`DndDatasetsRepository` (and the
    very array-of-text grammar it shares through :func:`_decode_id_list`): a
    thin face over the shared :class:`GameSettingsRepository` trio owning the
    JSON ``["<grimoire id>", …]`` format. An absent key is the normal «no
    grimoires connected» state and reads as the empty list without a warning;
    a damaged value reads empty WITH the one journal entry the codec logs, the
    row staying byte-identical for the next explicit write. Whether an id
    still has a file in the global grimoire storage is the module's reading
    rule (spec «Пропавший файл помечен» — the id is never dropped silently),
    not the codec's. Like the trio, this repository never commits — the caller
    owns the transaction (the module service's unit of work).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._settings = GameSettingsRepository(session)

    async def load(self) -> list[str]:
        """The connected grimoire ids in stored order — empty for «absent or
        unreadable»."""
        raw = await self._settings.get(DND_GRIMOIRES_KEY)
        if raw is None:
            return []
        return _decode_id_list(raw, _dnd_grimoires_corrupt)

    async def save(self, grimoire_ids: Sequence[str]) -> None:
        """Store the full list as the game's connections, overwriting any
        previous (even corrupted) value; the array order is kept."""
        await self._settings.upsert(
            DND_GRIMOIRES_KEY, _encode_id_list(grimoire_ids)
        )
