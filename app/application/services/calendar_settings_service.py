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
  replaces the deleted Gregorian SQL backfill, NULL keys included).  Since
  C3a the keyed truth per slot is what the storage resolver reads — the
  coordinate column when filled, the date columns otherwise (design D3).
* :meth:`CalendarSettingsService.sweep_dated_records` is the C3a game-open
  traversal of design D8: unreadable coordinate texts are repaired, the
  resolved coordinates run through :func:`build_shift_report` against the
  active calendar, every invalid one is shifted through the routed
  :func:`assign_coord` with the move logged, and :meth:`reconcile_era_keys`
  closes the pass — all idempotent, a no-op on a standard game.
* :meth:`CalendarSettingsService.apply_to_records` wraps the same pure
  :func:`build_shift_report` over coordinates read through the resolver
  (intercalary ones included): preview mode changes nothing, apply mode
  shifts every reported coordinate, recomputes the keys of ``calendar`` and
  migrates the storages — a custom calendar fills the coordinate columns
  (the legacy date columns are left untouched), the «Стандартный» preset
  moves coordinates back into the date columns (shifting what it cannot
  hold) and empties the coordinate columns — inside a single transaction
  that rolls back whole on any error (designs D6/D8).  No production call
  site before the C4 master.

Since piece C4 the same service is also the wizard's storage side
(designs D6/D9): :meth:`CalendarSettingsService.load_draft` /
:meth:`~CalendarSettingsService.save_draft` /
:meth:`~CalendarSettingsService.discard_draft` keep the work-in-progress
custom spec under the ``game_calendar_draft`` key (a damaged draft reads as
"no draft", logged, the row untouched) and :meth:`load_wizard_seen` exposes
the ``calendar_wizard_seen`` flag text for the presentation's first-entry
check; :meth:`promote_draft` raises a finished assembly to the active
calendar — record transfer, settings overwrite, draft deletion and the
optional «seen» flag in one transaction, activation after the commit.
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
    CALENDAR_DRAFT_KEY,
    CALENDAR_SETTINGS_KEY,
    CALENDAR_WIZARD_SEEN_KEY,
    CALENDAR_WIZARD_SEEN_YES,
    DEFAULT_MONTH_NAMES,
    CalendarCorrupted,
    CalendarDecoded,
    CalendarDraft,
    DateField,
    DraftCorrupted,
    DraftDecoded,
    GameCalendar,
    GameCoord,
    MonthDay,
    ShiftCheck,
    ShiftReport,
    SpecProblem,
    StandardCalendar,
    build_shift_report,
    current_calendar,
    decode_calendar,
    decode_draft,
    encode_calendar,
    encode_coord,
    encode_draft,
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
    assign_coord,
    resolve_coord,
)

_LOGGER = logging.getLogger(__name__)

# ``CALENDAR_SETTINGS_KEY`` / ``CALENDAR_DRAFT_KEY`` / ``CALENDAR_WIZARD_SEEN_*``
# are owned by the domain (next to the storage codecs both keys carry) and
# re-exported here for the service's callers; C4 added them via the import.

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

#: The two date slots of every dated row, with their column-name prefix
#: (the resolver's own slot spelling, design D3).
_DATE_SLOTS = ((DateField.START, "start"), (DateField.END, "end"))


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

    async def _upsert_setting(
        self, session: AsyncSession, key: str, value: str
    ) -> None:
        """Write ``key`` through the row that may already exist (the C4
        overwrite also cures a corrupted stored value — design D9: an
        existing row simply receives the new text)."""
        row = await self._get_setting(session, key)
        if row is None:
            session.add(GameSettingsModel(key=key, value=value))
        else:
            row.value = value

    async def _delete_setting(self, session: AsyncSession, key: str) -> None:
        """Delete ``key`` when present; an absent key is a silent no-op."""
        row = await self._get_setting(session, key)
        if row is not None:
            await session.delete(row)

    # ── C4: wizard draft and wizard-seen flag (designs D6/D9) ─────────────

    async def load_draft(self, session: AsyncSession) -> CalendarDraft | None:
        """Read the wizard's draft, or ``None`` when there is none to
        continue from (spec «Черновик мастера календаря»).

        An unreadable or invalid stored draft reads exactly as an absent one
        — logged, never dialog-ed, never rewritten (spec «Битой черновик —
        как его нет»; the row stays for a manual inspection just like a
        damaged ``game_calendar``).  The draft never enters the active
        calendar: this is a plain read for the wizard flow only (task 4.5).
        """
        row = await self._get_setting(session, CALENDAR_DRAFT_KEY)
        if row is None:
            return None
        decoded = decode_draft(row.value)
        if isinstance(decoded, DraftCorrupted):
            _LOGGER.warning(
                "Ignoring corrupted %s setting (%s): %r",
                CALENDAR_DRAFT_KEY,
                "; ".join(f"{p.code}: {p.message}" for p in decoded.reasons),
                row.value,
            )
            return None
        assert isinstance(decoded, DraftDecoded)
        return decoded.draft

    async def save_draft(self, session: AsyncSession, draft: CalendarDraft) -> None:
        """Persist the wizard's draft after a passed stage (design D6): the
        assembled spec runs through the codec's gate, so only a spec that
        itself validates is ever stored; a previous draft is overwritten."""
        await self._upsert_setting(session, CALENDAR_DRAFT_KEY, encode_draft(draft))
        await session.commit()

    async def discard_draft(self, session: AsyncSession) -> None:
        """Drop the draft — the wizard finished with it (cancelled flow or,
        atomically inside :meth:`promote_draft`, a promotion)."""
        await self._delete_setting(session, CALENDAR_DRAFT_KEY)
        await session.commit()

    async def load_wizard_seen(self, session: AsyncSession) -> str | None:
        """The raw ``calendar_wizard_seen`` text, or ``None`` for an old game
        created before the wizard existed (that absence itself means "never
        auto-show" — spec «Флаг просмотра мастера календаря»).  Presentation
        compares against ``CALENDAR_WIZARD_SEEN_NO``; nothing here decides."""
        row = await self._get_setting(session, CALENDAR_WIZARD_SEEN_KEY)
        return row.value if row is not None else None

    async def promote_draft(
        self,
        session: AsyncSession,
        calendar: GameCalendar,
        mark_wizard_seen: bool = False,
    ) -> ShiftReport:
        """The wizard's atomic application (design D9): one transaction
        raising a finished assembly to the active calendar.

        In a single commit: the C2 record transfer for ``calendar`` (the very
        storage-write body :meth:`apply_to_records` uses, so keys, shifts and
        storages are computed by one code path), the settings write —
        ``game_calendar`` overwritten with ``calendar``, which also cures a
        previously corrupted row (spec «Перезапись вместо ремонта») —, the
        draft's deletion, and optionally ``calendar_wizard_seen="1"`` when the
        application closes the first-entry wizard (design D8).  Any error
        rolls ALL of it back (spec «запись нового ключа и удаление черновика
        SHALL пережить ту же атомарность, что и перенос записей»): the records,
        the settings and the draft keep their pre-promotion bytes.  Only after
        the commit the calendar becomes active and the identity map expires;
        the returned report is recomputed by the same pure builder as the
        wizard's preview, so the application matches what it listed.
        """
        checks, rows = await self._collect_checks(session)
        report = build_shift_report(checks, calendar)
        try:
            await self._write_applied_storage(session, rows, calendar, report)
            await self._upsert_setting(
                session, CALENDAR_SETTINGS_KEY, encode_calendar(calendar)
            )
            await self._delete_setting(session, CALENDAR_DRAFT_KEY)
            if mark_wizard_seen:
                await self._upsert_setting(
                    session, CALENDAR_WIZARD_SEEN_KEY, CALENDAR_WIZARD_SEEN_YES
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        set_current_calendar(calendar)
        session.expire_all()  # the straight UPDATEs skipped the identity map
        return report

    async def reconcile_era_keys(self, session: AsyncSession) -> int:
        """Re-derive every stored key from the active calendar (design D5).

        Selects all dated rows of the six tables, recomputes ``start_key`` /
        ``end_key`` from the *resolved* coordinate of each slot (design D3:
        filled coordinate column first, date columns otherwise — a plain
        standard row reads as the ``MonthDay`` of its date, so the «Стандартный»
        preset still gives the exact pre-C2 numbers) with ``era_key`` (the
        dispatcher on the one active calendar — the single formula; it fully
        replaces the deleted SQL Gregorian backfill, NULL keys included) and
        mutates only the rows that disagree.  Exactly one commit covers every
        difference; ``session.commit()`` over a clean session writes nothing,
        so an idempotent second pass leaves the database byte-identical.
        Returns the number of corrected rows.
        """
        changed_rows = 0
        for model in _ERA_MODELS.values():
            rows = (await session.execute(select(model))).scalars().all()
            for row in rows:
                row_changed = False
                start = resolve_coord(row, DateField.START)
                if start is not None:
                    start_key = era_key(start, bool(row.start_bc))
                    if row.start_key != start_key:
                        row.start_key = start_key
                        row_changed = True
                end = resolve_coord(row, DateField.END)
                if end is not None:
                    end_key = era_key(end, bool(row.end_bc))
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

    async def sweep_dated_records(self, session: AsyncSession) -> ShiftReport:
        """Game-open traversal of the six dated tables (C3a, design D8).

        Runs right after :meth:`load_and_apply`, in its fixed three steps:

        1. **repair** — the pass reads every slot through
           :func:`resolve_coord`, which clears unreadable coordinate texts
           and logs table + id (spec «Повреждённая координатная колонка»);
        2. **shift** — the resolved (coordinate, era) pairs, intercalary
           included, go through :func:`build_shift_report` against the
           *active* calendar; every reported coordinate moves to its clamp
           through the routed :func:`assign_coord` (coordinate slot under a
           custom calendar, date columns under the preset — design D3) and
           the move — old → new text plus reason code — goes to the log;
        3. **reconcile** — :meth:`reconcile_era_keys` re-keys every row from
           the now-consistent coordinates (external tampering included).

        The whole pass is idempotent — shifted clamps are valid by
        construction, repairs are one-shot, reconcile writes only mismatches
        — and on a standard game a complete no-op (its date columns hold
        valid Gregorian month-day coordinates, the coordinate columns stay
        empty).  Returns the shift report of this open.
        """
        calendar = current_calendar()
        checks, rows = await self._collect_checks(session)
        report = build_shift_report(checks, calendar)
        for entry in report.records:
            row, _ = rows[(entry.table, entry.row_id)]
            assign_coord(row, entry.field, entry.new[0])
            _LOGGER.info(
                "Startup sweep shifted %s id=%s %s: %s -> %s (%s)",
                entry.table,
                entry.row_id,
                entry.field.value,
                encode_coord(entry.old[0]),
                encode_coord(entry.new[0]),
                entry.reason.value,
            )
        await session.commit()
        await self.reconcile_era_keys(session)
        return report

    async def apply_to_records(
        self,
        session: AsyncSession,
        calendar: GameCalendar,
        dry_run: bool = True,
    ) -> ShiftReport:
        """Check or apply ``calendar`` to all dated records (designs D6/D8).

        Both modes traverse the six tables in the fixed :data:`_ERA_MODELS`
        order and read every stored slot through :func:`resolve_coord` — so
        the traversal is over the game coordinates the app actually lives
        on (intercalary included), whichever column holds them.  The checks
        go to the pure :func:`build_shift_report` against ``calendar``.

        *preview* returns that report having changed nothing: the resolver's
        in-memory repair of corrupted coordinate texts is discarded, the base
        stays byte-identical (spec «Проверка ничего не меняет»).

        *apply* rewrites the whole storage of every dated row inside one
        transaction — any error anywhere rolls the run back to exactly the
        state the preview saw (spec «Ошибка применения откатывает всё»):
        shifted coordinates, the keys of ``calendar``, and the storage
        migration the calendar switch means: a custom calendar encodes every
        coordinate into the coordinate column and never touches the legacy
        date columns; the «Стандартный» preset moves each coordinate into
        its date column (one already valid there by the shift policy of the
        very same build) and empties the coordinate column (spec «Хранилища
        переезжают вместе с календарём»).  The very same report the preview
        produced is returned, so the preview stays valid for the application
        it predicted (spec «Применение совпадает с проверкой»).

        Writes go as straight ``UPDATE``s: derived keys must be exactly
        ``calendar``'s own, independent of whichever calendar is active at
        the moment of the call (C4 activates the saved calendar afterwards).
        """
        checks, rows = await self._collect_checks(session)
        report = build_shift_report(checks, calendar)
        if dry_run:
            if session.dirty:
                # Only the resolver's repair of corrupted coordinate texts can
                # dirty a preview — the spec asks the base to stay untouched,
                # so the in-memory clearing is discarded, not persisted.
                await session.rollback()
            return report
        try:
            await self._write_applied_storage(session, rows, calendar, report)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        session.expire_all()  # the straight UPDATEs skipped the identity map
        return report

    @staticmethod
    async def _write_applied_storage(
        session: AsyncSession,
        rows: dict[tuple[str, int], tuple],
        calendar: GameCalendar,
        report: ShiftReport,
    ) -> None:
        """Shifted coordinates, keys and storages of every dated row — the
        single transaction body shared verbatim by :meth:`apply_to_records`
        and :meth:`promote_draft` (design D9: the master's promotion applies
        through the very same C2 write path, no second implementation).
        Commits nothing: the caller owns the transaction boundary."""
        shifted = {
            (entry.table, entry.row_id, entry.field): entry.new[0]
            for entry in report.records
        }
        preset = isinstance(calendar, StandardCalendar)
        for (table, row_id), (row, resolved) in rows.items():
            model = _ERA_MODELS[table]
            values: dict[str, object] = {}
            for field, slot in _DATE_SLOTS:
                coord = resolved.get(field)
                if coord is None:
                    # An open slot keys nothing and holds no coordinate —
                    # dangling key or debris text in it is cleared either
                    # way; the legacy date column is already empty there.
                    values[f"{slot}_key"] = None
                    values[f"{slot}_coord"] = None
                    continue
                is_bc = bool(getattr(row, f"{slot}_bc"))
                final = shifted.get((table, row_id, field), coord)
                values[f"{slot}_key"] = calendar.to_key(final, is_bc)
                if preset:
                    # Valid in the preset already (the shift above ran
                    # against it) ⇒ physically a Gregorian date.
                    assert isinstance(final, MonthDay)
                    values[f"{slot}_date"] = date(final.year, final.month, final.day)
                    values[f"{slot}_coord"] = None
                else:
                    values[f"{slot}_coord"] = encode_coord(final)
            await session.execute(
                # The table object (not the model) keeps the statements
                # on column names: ``start_date`` is the coord-aware
                # property since C3a, while the physical columns keep
                # their legacy names (design D1/D3).
                model.__table__.update().where(model.__table__.c.id == row_id)
                .values(**values)
            )

    @staticmethod
    async def _collect_checks(
        session: AsyncSession,
    ) -> tuple[list[ShiftCheck], dict[tuple[str, int], tuple]]:
        """Every stored dated coordinate of the six tables as ``ShiftCheck``s.

        The single reading traversal of both the startup sweep and the
        apply operation: each slot value comes from :func:`resolve_coord`
        (which doubles as the design D8 repair step: corrupted coordinate
        texts are cleared and logged while read), paired with the row's own
        era flag.  Also returns the traversal order — ``{(table, id): (row,
        {field: coordinate})}`` — so the writer applies shifts to the very
        rows this pass has seen.
        """
        checks: list[ShiftCheck] = []
        rows: dict[tuple[str, int], tuple] = {}
        for table, model in _ERA_MODELS.items():
            for row in (await session.execute(select(model))).scalars().all():
                resolved: dict[DateField, GameCoord] = {}
                for field, slot in _DATE_SLOTS:
                    coord = resolve_coord(row, field)
                    if coord is not None:
                        checks.append((
                            table,
                            row.id,
                            field,
                            coord,
                            bool(getattr(row, f"{slot}_bc")),
                        ))
                        resolved[field] = coord
                rows[(table, row.id)] = (row, resolved)
        return checks, rows
