"""Game-calendar settings service (roadmap piece C2, design D2–D6).

Turns the per-game ``game_settings`` key ``game_calendar`` into the process's
active calendar and back:

* :meth:`CalendarSettingsService.load_and_apply` reads the key, migrates the
  legacy ``custom_months`` setting exactly once (design D3 — the deletion of
  the old key is itself the "already migrated" marker), activates the decoded
  calendar through ``set_current_calendar`` and reports corruption reasons
  without ever rewriting a damaged row (design D4 — showing the warning is
  the caller's business, keeping this service free of Qt).
* :meth:`CalendarSettingsService.reconcile_era_keys` re-derives every stored
  ``start_key``/``end_key`` of the six dated tables from the *active* calendar
  — one formula, one commit, writes only on mismatch (design D5; it fully
  replaces the deleted Gregorian SQL backfill, NULL keys included).
* :meth:`CalendarSettingsService.apply_to_records` wraps the domain's pure
  :func:`build_shift_report` over the same six tables: preview mode changes
  nothing, apply mode shifts every reported invalid coordinate and recomputes
  its key inside a single transaction that rolls back whole on any error
  (design D6).  No production call site before the C4 master.

The ``save(calendar)`` half of design D2 belongs to that C4 wizard and is
deliberately absent here.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.date_era import era_key
from app.domain.game_calendar import (
    DEFAULT_MONTH_NAMES,
    CalendarCorrupted,
    CalendarDecoded,
    DateField,
    GameCalendar,
    MonthDay,
    ShiftCheck,
    ShiftReport,
    SpecProblem,
    StandardCalendar,
    build_shift_report,
    decode_calendar,
    encode_calendar,
    set_current_calendar,
)
from app.infrastructure.db.models import (
    CharacterModel,
    EventModel,
    GameSettingsModel,
    ItemModel,
    LocationModel,
    OrganizationModel,
    RatingModel,
)

_LOGGER = logging.getLogger(__name__)

#: Key under which the game's calendar lives in ``game_settings`` (design D1).
CALENDAR_SETTINGS_KEY = "game_calendar"

#: Deprecated month-names key written by app versions before C2;
#: ``date_utils``'s own ``SETTINGS_KEY`` disappears with the process global.
LEGACY_MONTHS_KEY = "custom_months"

#: The six dated tables C2 traverses, in the deterministic order the C1
#: traversal (and hence every report) preserves (design D5/D6).
_ERA_MODELS: dict[str, type] = {
    "events": EventModel,
    "organizations": OrganizationModel,
    "characters": CharacterModel,
    "items": ItemModel,
    "locations": LocationModel,
    "ratings": RatingModel,
}


@dataclass(frozen=True)
class LoadOutcome:
    """Result of one game-open calendar load.

    ``calendar`` is what the service made active; ``reasons`` carries the
    machine-readable :class:`SpecProblem` causes when the stored key could not
    be decoded — exactly the codes the presentation maps to its Russian
    warning phrases (design D4).  An empty ``reasons`` tuple means the open
    had nothing to warn about.
    """

    calendar: GameCalendar
    reasons: tuple[SpecProblem, ...] = ()


def _decode_legacy_months(raw: str) -> dict[int, str] | None:
    """Read the pre-C2 ``custom_months`` JSON ``{"<month number>": name}``.

    ``None`` means unreadable — not JSON, not an object, a non-integer key or
    a non-string name — the D3 corruption branch then drops the key without
    creating a new one.  An empty object decodes to ``{}`` (no customization,
    not corruption).
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    months: dict[int, str] = {}
    for key, name in data.items():
        if not isinstance(name, str):
            return None
        try:
            months[int(key)] = name
        except ValueError:
            return None
    return months


class CalendarSettingsService:
    """Calendar load/migrate/reconcile/apply operations over a game session.

    Stateless by design (D2): the session arrives per call, so one instance
    safely serves every game the process opens in sequence.
    """

    async def load_and_apply(self, session: AsyncSession) -> LoadOutcome:
        """Read ``game_calendar``, migrate ``custom_months``, activate (D3/D4).

        Order of design D3: a readable legacy key with no new key becomes a
        ``standard`` ``month_names`` override and the old key dies; names
        equivalent to the Gregorian defaults write no new key at all; an
        unreadable old key is dropped without a new one (logged); both keys
        present means the new key wins and the old one is still deleted.  A
        damaged ``game_calendar`` value decodes to reasons — the game opens on
        the «Стандартный» preset, the row is left byte-identical for the C4
        master to repair, and the caller shows the warning from
        :attr:`LoadOutcome.reasons` (the row's own data must survive a manual
        DB edit, so the service never fixes it here).
        """
        game_row = await self._get_setting(session, CALENDAR_SETTINGS_KEY)
        legacy_row = await self._get_setting(session, LEGACY_MONTHS_KEY)

        reasons: tuple[SpecProblem, ...] = ()
        if game_row is not None:
            if legacy_row is not None:
                # D3: the new key wins; the deprecated one goes either way.
                await session.delete(legacy_row)
                await session.commit()
            decoded = decode_calendar(game_row.value)
            if isinstance(decoded, CalendarCorrupted):
                reasons = decoded.reasons
                _LOGGER.warning(
                    "Ignoring corrupted %s setting (%s): %s",
                    CALENDAR_SETTINGS_KEY,
                    "; ".join(f"{p.code}: {p.message}" for p in reasons),
                    game_row.value,
                )
                calendar: GameCalendar = StandardCalendar()
            else:
                assert isinstance(decoded, CalendarDecoded)
                calendar = decoded.calendar
        elif legacy_row is not None:
            calendar = await self._migrate_legacy_months(session, legacy_row)
        else:
            # Old game without either key: preset, and no key is written
            # "just in case" (spec «Старая игра без ключа»).
            calendar = StandardCalendar()

        set_current_calendar(calendar)
        return LoadOutcome(calendar=calendar, reasons=reasons)

    async def _migrate_legacy_months(
        self, session: AsyncSession, legacy_row: GameSettingsModel
    ) -> StandardCalendar:
        """One-shot ``custom_months`` → ``game_calendar`` transfer (design D3)."""
        months = _decode_legacy_months(legacy_row.value)
        if months is None:
            _LOGGER.warning(
                "Dropping unreadable %s setting: %r", LEGACY_MONTHS_KEY, legacy_row.value
            )
        else:
            overrides = {
                number: name
                for number, name in months.items()
                if DEFAULT_MONTH_NAMES.get(number) != name
            }
            if overrides:
                session.add(
                    GameSettingsModel(
                        key=CALENDAR_SETTINGS_KEY,
                        value=encode_calendar(
                            StandardCalendar(month_names=overrides)
                        ),
                    )
                )
        await session.delete(legacy_row)
        await session.commit()
        return StandardCalendar(month_names=months)

    @staticmethod
    async def _get_setting(
        session: AsyncSession, key: str
    ) -> GameSettingsModel | None:
        result = await session.execute(
            select(GameSettingsModel).where(GameSettingsModel.key == key)
        )
        return result.scalars().first()

    async def reconcile_era_keys(self, session: AsyncSession) -> int:
        """Re-derive every stored key from the active calendar (design D5).

        Selects all dated rows of the six tables, recomputes ``start_key`` /
        ``end_key`` with ``era_key`` (the dispatcher on the one active
        calendar — the single formula, with the «Стандартный» preset giving
        the exact pre-C2 numbers) and mutates only the rows that disagree;
        a missing (NULL) key of a stored date simply recomputes too, which is
        what closed old-version rows under the deleted SQL backfill.  Exactly
        one commit covers every difference; ``session.commit()`` over a clean
        session writes nothing, so an idempotent second pass leaves the
        database byte-identical.  Returns the number of corrected rows.
        """
        changed_rows = 0
        for model in _ERA_MODELS.values():
            rows = (await session.execute(select(model))).scalars().all()
            for row in rows:
                row_changed = False
                if row.start_date is not None:
                    start_key = era_key(row.start_date, bool(row.start_bc))
                    if row.start_key != start_key:
                        row.start_key = start_key
                        row_changed = True
                if row.end_date is not None:
                    end_key = era_key(row.end_date, bool(row.end_bc))
                    if row.end_key != end_key:
                        row.end_key = end_key
                        row_changed = True
                elif row.end_key is not None:
                    row.end_key = None
                    row_changed = True
                if row_changed:
                    changed_rows += 1
        await session.commit()
        return changed_rows

    async def apply_to_records(
        self,
        session: AsyncSession,
        calendar: GameCalendar,
        dry_run: bool = True,
    ) -> ShiftReport:
        """Check or apply ``calendar`` to all dated records (design D6).

        Both modes traverse the six tables in the fixed :data:`_ERA_MODELS`
        order, turn every stored ``(date, era)`` pair into a domain
        :data:`ShiftCheck` (only :class:`MonthDay` is expressible in the date
        columns until C3) and hand the checks to the pure
        :func:`build_shift_report`.  Preview returns that report having read
        only; apply rewrites each reported coordinate together with the key
        of ``calendar`` through the same transaction — any error anywhere
        rolls the whole run back, leaving no half-shifted record — and then
        the very same report is returned, so a preview stays valid for the
        application it predicted.
        """
        checks = await self._collect_checks(session)
        report = build_shift_report(checks, calendar)
        if dry_run:
            return report
        try:
            for entry in report.records:
                new_coord, is_bc = entry.new
                assert isinstance(new_coord, MonthDay)
                model = _ERA_MODELS[entry.table]
                field = entry.field.value
                await session.execute(
                    update(model)
                    .where(model.id == entry.row_id)
                    .values(
                        **{
                            f"{field}_date": date(new_coord.year, new_coord.month, new_coord.day),
                            f"{field}_bc": int(is_bc),
                            f"{field}_key": calendar.to_key(new_coord, is_bc),
                        }
                    )
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return report

    @staticmethod
    async def _collect_checks(session: AsyncSession) -> list[ShiftCheck]:
        """Every stored dated coordinate of the six tables as ``ShiftCheck``."""
        checks: list[ShiftCheck] = []
        for table, model in _ERA_MODELS.items():
            rows = (await session.execute(select(model))).scalars().all()
            for row in rows:
                if row.start_date is not None:
                    checks.append((
                        table,
                        row.id,
                        DateField.START,
                        MonthDay(row.start_date.year, row.start_date.month, row.start_date.day),
                        bool(row.start_bc),
                    ))
                if row.end_date is not None:
                    checks.append((
                        table,
                        row.id,
                        DateField.END,
                        MonthDay(row.end_date.year, row.end_date.month, row.end_date.day),
                        bool(row.end_bc),
                    ))
        return checks
