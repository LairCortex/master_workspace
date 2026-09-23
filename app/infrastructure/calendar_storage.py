"""Storage codecs for the game calendar settings (piece C2/C3a/C4, designs
D1/D2/D6) — the three format carriers moved verbatim out of
``app.domain.game_calendar`` (wave-6 decomposition, task 6.6) so the domain
keeps pure calendar logic while JSON/text formats live in the infrastructure.

The wire formats are unchanged: the versioned ``{"v": 1, "kind": ...}``
calendar value (design D1), the wizard draft envelope wrapping that custom-spec
body with a stage marker (design D6), and the discriminated
``M:year:month:day`` / ``I:year:index`` coordinate text (design D2).  A broken
stored value never raises: each decoder answers with machine-reason results
(``CalendarCorrupted`` / ``DraftCorrupted`` / ``CoordCorrupted``) and the caller
chooses the warning phrasing (design D4).
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from app.domain.game_calendar import (
    DEFAULT_MONTH_NAMES,
    CalendarSpec,
    CustomCalendar,
    GameCalendar,
    GameCoord,
    IntercalaryDay,
    IntercalarySpec,
    MonthDay,
    MonthSpec,
    SpecProblem,
    StandardCalendar,
    validate,
)

# ── Storage codec (roadmap piece C2, design D1) ──────────────────────────

#: JSON format version :func:`encode_calendar` writes and
#: :func:`decode_calendar` reads; a value stamped with any other version is
#: reported as ``unknown_version`` rather than silently misread (spec
#: «Календарь-настройки хранятся в базе игры»).
CALENDAR_STORAGE_VERSION = 1

#: ``kind`` discriminators of the stored value (design D1).
_KIND_STANDARD = "standard"
_KIND_CUSTOM = "custom"


@dataclass(frozen=True)
class CalendarDecoded:
    """Successful decode: the stored value describes this calendar."""

    calendar: GameCalendar


@dataclass(frozen=True)
class CalendarCorrupted:
    """Rejected decode: every reason the stored value could not be read.

    The reasons are the machine-readable :class:`SpecProblem` codes design
    D4 reserves for corruption — the codec's own ``corrupt_json``,
    ``unknown_version`` and ``corrupt_shape`` plus the spec-validation
    codes of a rejected custom spec (the full list, never just the first
    hit).  Like ``validate`` these are never localized here; the
    presentation renders the user-facing warning from these codes."""

    reasons: tuple[SpecProblem, ...]


def _corrupt_shape(detail: str) -> CalendarCorrupted:
    """One malformed-payload problem as a decode result."""
    return CalendarCorrupted((SpecProblem("corrupt_shape", detail),))


class CalendarStorageCarrier(Protocol):
    """Storage shape of one calendar implementation.

    A carrier pairs a ``kind`` discriminator with the calendar class it owns
    and the two halves of the format; registering a third calendar means
    writing one carrier and adding it to :data:`CALENDAR_STORAGE_CARRIERS`,
    never editing the codec."""

    kind: str
    calendar_type: type

    def encode(self, calendar: GameCalendar) -> dict: ...

    def decode(self, data: dict) -> CalendarDecoded | CalendarCorrupted: ...


# ── Registry of stored calendar implementations ──────────────────────────
# The former ``isinstance`` chain of ``encode_calendar`` and the
# ``_KIND_STANDARD``/``_KIND_CUSTOM`` branch chain of the payload reader moved
# into one carrier per calendar (design D1).  A third calendar now joins the
# format by implementing this carrier surface once (:attr:`kind`,
# :attr:`calendar_type`, :meth:`encode`, :meth:`decode`) and adding it to
# :data:`CALENDAR_STORAGE_CARRIERS` — no encoder or decoder branch is edited
# (audit «Открытость/закрытость» finding, target of wave-6 task 6.7).


class StandardCalendarStorageCarrier:
    """``kind: standard`` — the preset plus an optional ``month_names``
    override, whose keys are month numbers carried as JSON strings.

    The payload gains a ``month_names`` object only when the preset's names
    actually differ from ``DEFAULT_MONTH_NAMES`` — an empty (or all-default)
    override stays normalized into "no field", so a setting is never stored
    "про запас" (spec «Календарь-настройки хранятся в базе игры», design
    "Open Questions").
    """

    kind = _KIND_STANDARD
    calendar_type = StandardCalendar

    def encode(self, calendar: StandardCalendar) -> dict:
        payload: dict = {"v": CALENDAR_STORAGE_VERSION, "kind": self.kind}
        overrides = {
            str(number): name
            for number, name in calendar.month_names.items()
            if DEFAULT_MONTH_NAMES.get(number) != name
        }
        if overrides:
            payload["month_names"] = overrides
        return payload

    def decode(self, data: dict) -> CalendarDecoded | CalendarCorrupted:
        raw_names = data.get("month_names")
        if raw_names is None:
            return CalendarDecoded(StandardCalendar())
        if not isinstance(raw_names, dict):
            return _corrupt_shape("month_names must be a JSON object")
        month_names: dict[int, str] = {}
        for number, name in raw_names.items():
            if not isinstance(name, str):
                return _corrupt_shape(f"month name for key {number!r} is not a string")
            try:
                month_names[int(number)] = name
            except ValueError:
                return _corrupt_shape(
                    f"month_names key {number!r} is not an integer month number"
                )
        return CalendarDecoded(StandardCalendar(month_names=month_names))


class CustomCalendarStorageCarrier:
    """``kind: custom`` — the full spec: ``months`` (name + length),
    ``week_names`` and ``intercalary`` (name + after_month), list order
    meaningful.

    Decoding goes field-by-field after a shape pass (both ``validate`` and
    ``CustomCalendar`` assume plain ints and strings) through the core's own
    validation of the rebuilt spec.
    """

    kind = _KIND_CUSTOM
    calendar_type = CustomCalendar

    def encode(self, calendar: CustomCalendar) -> dict:
        spec = calendar.spec
        return {
            "v": CALENDAR_STORAGE_VERSION,
            "kind": self.kind,
            "months": [{"name": month.name, "length": month.length} for month in spec.months],
            "week_names": list(spec.week_names),
            "intercalary": [
                {"name": rule.name, "after_month": rule.after_month}
                for rule in spec.intercalary
            ],
        }

    def decode(self, data: dict) -> CalendarDecoded | CalendarCorrupted:
        months_raw = data.get("months")
        week_raw = data.get("week_names")
        intercalary_raw = data.get("intercalary")
        if (
            not isinstance(months_raw, list)
            or not isinstance(week_raw, list)
            or not isinstance(intercalary_raw, list)
        ):
            return _corrupt_shape(
                "custom calendar fields months/week_names/intercalary must be JSON lists"
            )
        months: list[MonthSpec] = []
        for entry in months_raw:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("name"), str)
                or not _is_stored_int(entry.get("length"))
            ):
                return _corrupt_shape(
                    f"month entry {entry!r} needs a string name and an integer length"
                )
            months.append(MonthSpec(entry["name"], entry["length"]))
        for name in week_raw:
            if not isinstance(name, str):
                return _corrupt_shape(f"week name {name!r} must be a string")
        intercalary: list[IntercalarySpec] = []
        for entry in intercalary_raw:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("name"), str)
                or not _is_stored_int(entry.get("after_month"))
            ):
                return _corrupt_shape(
                    f"intercalary entry {entry!r} needs a string name "
                    f"and an integer after_month"
                )
            intercalary.append(IntercalarySpec(entry["name"], entry["after_month"]))
        spec = CalendarSpec(
            months=tuple(months), week_names=tuple(week_raw), intercalary=tuple(intercalary)
        )
        spec_problems = validate(spec)
        if spec_problems:
            return CalendarCorrupted(tuple(spec_problems))
        return CalendarDecoded(CustomCalendar(spec))


#: ``kind`` discriminator → carrier, in write order (the error phrasings of
#: :func:`encode_calendar` and the payload reader are derived from this
#: registry, so a newly registered calendar appears in them automatically).
CALENDAR_STORAGE_CARRIERS: Mapping[str, CalendarStorageCarrier] = MappingProxyType(
    {
        _KIND_STANDARD: StandardCalendarStorageCarrier(),
        _KIND_CUSTOM: CustomCalendarStorageCarrier(),
    }
)


def _carrier_for(calendar: GameCalendar) -> CalendarStorageCarrier | None:
    """The carrier owning ``calendar``'s storage shape, or ``None``.

    Lookup stays ``isinstance``-based, exactly like the chain it replaced, so
    a subclass of a registered calendar keeps that calendar's shape."""
    for carrier in CALENDAR_STORAGE_CARRIERS.values():
        if isinstance(calendar, carrier.calendar_type):
            return carrier
    return None


def encode_calendar(calendar: GameCalendar) -> str:
    """Serialize a calendar into the stored JSON value of design D1.

    The payload shape comes from the calendar's carrier in
    :data:`CALENDAR_STORAGE_CARRIERS`; only calendars registered there have a
    storage shape — an unregistered implementer of the protocol refuses here
    with ``TypeError`` until someone gives it a carrier.
    """
    carrier = _carrier_for(calendar)
    if carrier is None:
        raise TypeError(
            "only "
            + " and ".join(
                carrier.calendar_type.__name__
                for carrier in CALENDAR_STORAGE_CARRIERS.values()
            )
            + " can be stored, not "
            f"{type(calendar).__name__}"
        )
    return json.dumps(carrier.encode(calendar), ensure_ascii=False)


def decode_calendar(raw: str) -> CalendarDecoded | CalendarCorrupted:
    """Read the stored JSON value back into a calendar (design D1).

    A broken value never raises (design D4): the result is either a
    ``CalendarDecoded`` calendar or a ``CalendarCorrupted`` carrying
    machine-readable reasons — the caller chooses its warning phrasing from
    those codes and leaves the corrupted row untouched.  A stored custom
    spec is run through the core's ``validate`` first, so the full reason
    list is reported and the ``CustomCalendar`` constructor — the same
    gate, reached only with a pre-validated spec — cannot raise here.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return CalendarCorrupted(
            (SpecProblem("corrupt_json", "the stored calendar is not parseable JSON"),)
        )
    return _decode_calendar_data(data)


def _decode_calendar_data(data: object) -> CalendarDecoded | CalendarCorrupted:
    """Decode an already-parsed calendar payload — shared by
    :func:`decode_calendar` and the wizard-draft reader below, so a draft's
    ``spec`` body really goes through the very same validation path as the
    main key (design D6: "переиспользует decode_calendar для тела спеки")."""
    if not isinstance(data, dict):
        return _corrupt_shape(
            f"stored calendar must be a JSON object, got {type(data).__name__}"
        )
    version = data.get("v")
    if version != CALENDAR_STORAGE_VERSION:
        return CalendarCorrupted(
            (
                SpecProblem(
                    "unknown_version",
                    f"calendar format version {version!r} is not supported "
                    f"(this app reads and writes version {CALENDAR_STORAGE_VERSION})",
                ),
            )
        )
    kind = data.get("kind")
    carrier = CALENDAR_STORAGE_CARRIERS.get(kind)
    if carrier is None:
        return _corrupt_shape(
            f"unknown calendar kind {kind!r}, expected "
            + " or ".join(repr(k) for k in CALENDAR_STORAGE_CARRIERS)
        )
    return carrier.decode(data)


def _is_stored_int(value: object) -> bool:
    """An integer of the JSON world — ``bool`` is ``int`` in Python but is
    never a length or a month number in this format."""
    return isinstance(value, int) and not isinstance(value, bool)

# ── Wizard draft codec (roadmap piece C4, design D6) ──────────────────────

#: JSON format version :func:`encode_draft` writes and :func:`decode_draft`
#: reads; a draft stamped with any other version reads as corruption rather
#: than being silently misread — mirroring :data:`CALENDAR_STORAGE_VERSION`.
CALENDAR_DRAFT_VERSION = 1

#: Machine codes of the wizard's build stages.  The stage stored in a draft is
#: the first screen the assembly has NOT closed yet (design D6: "stage =
#: следующая незакрытая"); the completed part of the form is already inside
#: ``spec`` with defaults standing in for the unclosed stages.
DRAFT_STAGE_WEEK = "week"
DRAFT_STAGE_MONTHS = "months"
DRAFT_STAGE_INTERCALARY = "intercalary"
DRAFT_STAGE_PREVIEW = "preview"

#: All stage codes a stored draft may carry.
DRAFT_STAGES: tuple[str, ...] = (
    DRAFT_STAGE_WEEK,
    DRAFT_STAGE_MONTHS,
    DRAFT_STAGE_INTERCALARY,
    DRAFT_STAGE_PREVIEW,
)


@dataclass(frozen=True)
class CalendarDraft:
    """The wizard's half-built custom calendar: the spec assembled so far
    (unclosed stages keep their defaults) plus the next open ``stage`` — the
    two fields of design D6, with no behavior of its own.  A draft is data
    only: it never touches the active calendar, captions or keys until
    :meth:`CalendarSettingsService.promote_draft` raises it to the main key."""

    spec: CalendarSpec
    stage: str


@dataclass(frozen=True)
class DraftDecoded:
    """Successful decode: the stored draft value describes this draft."""

    draft: CalendarDraft


@dataclass(frozen=True)
class DraftCorrupted:
    """Rejected decode: machine-readable reasons in the same
    :class:`SpecProblem` shape as the calendar codec — ``corrupt_json``,
    ``unknown_version``, ``corrupt_shape`` (draft envelope problems) plus the
    spec-validation codes of a rejected spec body, which the shared payload
    reader passes through verbatim.  A rejected draft simply means "no
    draft" (spec «Битой черновик — как его нет»); the caller logs and starts
    the flow fresh."""

    reasons: tuple[SpecProblem, ...]


def _draft_corrupt_shape(detail: str) -> DraftCorrupted:
    """One malformed-envelope problem as a draft decode result."""
    return DraftCorrupted((SpecProblem("corrupt_shape", detail),))


def encode_draft(draft: CalendarDraft) -> str:
    """Serialize a wizard draft into its stored JSON value (design D6).

    ``{"v": 1, "spec": <custom value of the main codec>, "stage": "months"}``
    — the spec body is produced by :func:`encode_calendar` itself, so the
    draft and the main key share one spec representation and one evolution
    rhythm.  Writing is the read's strict gate: the spec goes through the
    ``CustomCalendar`` constructor (the same gate as the main key — a draft
    half the wizard would consider validated must actually validate), and an
    unknown stage has no storage shape and refuses with ``ValueError`` —
    like ``encode_calendar``, this function never invents data.
    """
    if draft.stage not in DRAFT_STAGES:
        raise ValueError(
            f"unknown wizard draft stage {draft.stage!r}, "
            f"expected one of {', '.join(repr(s) for s in DRAFT_STAGES)}"
        )
    inner = json.loads(encode_calendar(CustomCalendar(draft.spec)))
    payload = {
        "v": CALENDAR_DRAFT_VERSION,
        "spec": inner,
        "stage": draft.stage,
    }
    return json.dumps(payload, ensure_ascii=False)


def decode_draft(raw: str) -> DraftDecoded | DraftCorrupted:
    """Read a stored draft value back — never raising, exactly like
    :func:`decode_calendar` beside it.

    Every failure shape answers with reasons, and the service then reads the
    draft as absent (spec «Битой черновик — как его нет»): an unparsable
    envelope, a foreign format version, a ``spec`` that is not an object or
    not a custom calendar value, an unknown stage, or a spec body the core
    itself rejects (full reason list from ``validate``).  The spec body is
    read through the shared payload decoder, so a draft cannot smuggle a
    spec the main key would refuse; the «Стандартный» preset is not a draft
    (the wizard assembles custom calendars only — design D6)."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return DraftCorrupted(
            (SpecProblem("corrupt_json", "the stored calendar draft is not parseable JSON"),)
        )
    if not isinstance(data, dict):
        return _draft_corrupt_shape(
            f"stored draft must be a JSON object, got {type(data).__name__}"
        )
    version = data.get("v")
    if version != CALENDAR_DRAFT_VERSION:
        return DraftCorrupted(
            (
                SpecProblem(
                    "unknown_version",
                    f"calendar draft format version {version!r} is not supported "
                    f"(this app reads and writes version {CALENDAR_DRAFT_VERSION})",
                ),
            )
        )
    spec_raw = data.get("spec")
    if not isinstance(spec_raw, dict):
        return _draft_corrupt_shape(
            f"draft spec must be a JSON object, got {type(spec_raw).__name__}"
        )
    stage = data.get("stage")
    if stage not in DRAFT_STAGES:
        return _draft_corrupt_shape(
            f"unknown wizard stage {stage!r}, expected one of "
            f"{', '.join(repr(s) for s in DRAFT_STAGES)}"
        )
    decoded = _decode_calendar_data(spec_raw)
    if isinstance(decoded, CalendarCorrupted):
        return DraftCorrupted(decoded.reasons)
    assert isinstance(decoded, CalendarDecoded)
    if not isinstance(decoded.calendar, CustomCalendar):
        return _draft_corrupt_shape(
            "a wizard draft wraps a custom calendar spec, not the standard preset"
        )
    return DraftDecoded(CalendarDraft(spec=decoded.calendar.spec, stage=stage))


# ── Coordinate storage codec (roadmap piece C3a, design D2) ───────────────

#: Kind discriminators of the stored coordinate text (design D2): the first
#: field is always the kind, so a regular day and an intercalary day never
#: share one representation and the reading is self-describing.
_COORD_KIND_MONTH = "M"
_COORD_KIND_INTERCALARY = "I"

#: Field names per kind in text order — the stored text is exactly these
#: colon-joined plain ``str()`` integers (no leading zeros written, none
#: demanded on reading; canonicalness is pinned by the round trip).
_COORD_FIELDS = MappingProxyType(
    {
        _COORD_KIND_MONTH: ("year", "month", "day"),
        _COORD_KIND_INTERCALARY: ("year", "index"),
    }
)


@dataclass(frozen=True)
class CoordDecoded:
    """Successful decode: the stored text describes this coordinate."""

    coord: GameCoord


@dataclass(frozen=True)
class CoordCorrupted:
    """Rejected decode: every machine-readable reason the text could not be
    read, in the same :class:`SpecProblem` shape the calendar codec uses —
    ``empty_coord``, ``not_a_string``, ``unknown_kind`` (missing or foreign
    discriminator), ``incomplete_coord``, ``too_many_fields`` and
    ``non_numeric_field`` (one per offending field).  Never localized; the
    caller phrases its warning from these codes."""

    reasons: tuple[SpecProblem, ...]


def encode_coord(coord: GameCoord) -> str:
    """Serialize one coordinate into its stored text (design D2).

    ``"M:year:month:day"`` for a month day, ``"I:year:index"`` for an
    intercalary day — plain ``str()`` digits, which makes the mapping
    injective (distinct kinds differ in the discriminator; same-kind
    coordinates differ in at least one colon-separated number and a number
    cannot swallow the separator) and the cycle ``decode(encode(c)) == c``
    exact.  Era is not part of a coordinate (D3), so it is not part of its
    text either — the same text serves both eras.  Existence in any calendar
    is deliberately NOT checked: the codec owns shape, while
    ``classify``/``shift_invalid`` own existence.  A value that is not one of
    the two D3 coordinate kinds has no storage shape and raises
    ``TypeError`` (same refusal stance as ``encode_calendar``).
    """
    if isinstance(coord, MonthDay):
        return f"{_COORD_KIND_MONTH}:{coord.year}:{coord.month}:{coord.day}"
    if isinstance(coord, IntercalaryDay):
        return f"{_COORD_KIND_INTERCALARY}:{coord.year}:{coord.index}"
    raise TypeError(
        "only MonthDay and IntercalaryDay coordinates can be stored, not "
        f"{type(coord).__name__}"
    )


def decode_coord(raw: str) -> CoordDecoded | CoordCorrupted:
    """Read a stored coordinate text back (design D2).

    Like :func:`decode_calendar` next to it, an unreadable value never
    raises: the answer is a :class:`CoordCorrupted` carrying the *full* list
    of machine-readable reasons, and the storage resolver/C4 caller logs and
    repairs from those codes.  The reader is deliberately more lenient than
    the writer — a hand-edited ``M:044:03:05`` parses, and re-encoding the
    result returns the canonical text — while the format itself stays an
    opaque internal representation read only by this codec.  No number is
    checked against any calendar here: an out-of-calendar coordinate decodes
    exactly, because existence is the shift policy's question, not the
    codec's.
    """
    if not isinstance(raw, str):
        return CoordCorrupted(
            (SpecProblem("not_a_string", f"stored coordinate {raw!r} is not text"),)
        )
    if not raw:
        return CoordCorrupted(
            (SpecProblem("empty_coord", "stored coordinate text is empty"),)
        )
    parts = raw.split(":")
    kind = parts[0]
    field_names = _COORD_FIELDS.get(kind)
    if field_names is None:
        return CoordCorrupted(
            (
                SpecProblem(
                    "unknown_kind",
                    f"coordinate kind {kind!r} is neither {_COORD_KIND_MONTH!r} "
                    f"(month day) nor {_COORD_KIND_INTERCALARY!r} (intercalary day)",
                ),
            )
        )
    given = parts[1:]
    problems: list[SpecProblem] = []
    if len(given) < len(field_names):
        problems.append(
            SpecProblem(
                "incomplete_coord",
                f"coordinate text {raw!r}: kind {kind!r} needs {len(field_names)} "
                f"numbers, found {len(given)}",
            )
        )
    elif len(given) > len(field_names):
        problems.append(
            SpecProblem(
                "too_many_fields",
                f"coordinate text {raw!r}: kind {kind!r} has {len(field_names)} "
                f"numbers, found {len(given)}",
            )
        )
    numbers: list[int] = []
    for name, text in zip(field_names, given):
        try:
            numbers.append(int(text))
        except ValueError:
            problems.append(
                SpecProblem(
                    "non_numeric_field",
                    f"{kind} coordinate field {name} {text!r} is not an integer",
                )
            )
    if problems:
        return CoordCorrupted(tuple(problems))
    if kind == _COORD_KIND_MONTH:
        return CoordDecoded(MonthDay(*numbers))
    return CoordDecoded(IntercalaryDay(*numbers))
