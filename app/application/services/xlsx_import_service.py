"""Service for importing entities from .xlsx files.

The unified five-sheet import (rework-xlsx-import, design D2/D3):
``analyze_file`` reads the workbook once (together with a read-only name
index over the game DB) and produces a pure :class:`ImportPlan` — fatal
file errors, merged rows per (type, lower(name)), per-row planned skips,
upsert targets and auto-created link targets (ghosts). ``apply_plan``
consumes that artifact: pass 1 creates/updates all entities (ghost
targets, auto event types, images through ``ImageStore``), pass 2 only
adds links via the ORM relationships; the whole apply runs inside the
game's :class:`GameSessionUoW` transaction — one commit on success,
rollback + re-raise on any failure (task group 3, design D4–D6; wave 5
task 5.11 moved the finish from commit/rollback callbacks to the unit).

Wave 4 (audit finding B6, design D6) cut the module by responsibility:
workbook parsing, merging and link resolution live in ``xlsx_analyze``,
the two writing passes in ``xlsx_apply``, user-facing report phrases in
``xlsx_report_text``; the name-index SQL moved to the repository layer
(``infrastructure/repositories/name_index.py``). What remains here is the
service API its callers know, the analyze/apply orchestration and the
transaction/progress contract of ``apply_plan``. Plan artifact and report
types are re-exported below so every pre-split import path still works.

The legacy single-sheet API (``validate_file`` / ``import_file``) was
removed together with the old file format (proposal: BREAKING — the
one-sheet English-header files are no longer read).
"""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.xlsx_analyze import (
    DateShiftRow,
    ImportPlan,
    LINK_TO_DB,
    LINK_TO_FILE,
    LINK_TO_GHOST,
    PlannedLink,
    RowIssue,
    analyze_workbook,
    build_name_index,
    coord_text,
    resolve_links,
)
from app.application.services.xlsx_apply import (
    ImportReport,
    apply_entities_pass,
    apply_links_pass,
    ordered_rows,
    orm_model,
)
from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.images.store import ImageStore

#: pre-split name of the coordinate renderer (tests import it as-is)
_coord_text = coord_text

__all__ = [
    "DateShiftRow",
    "ImportPlan",
    "ImportReport",
    "LINK_TO_DB",
    "LINK_TO_FILE",
    "LINK_TO_GHOST",
    "RowIssue",
    "XlsxImportService",
]


class XlsxImportService:
    """High-level service for the unified five-sheet .xlsx import.

    The analyze/apply flow writes exclusively through the session/ORM and
    the ``ImageStore`` ingest pipeline — no per-type entity/event services
    are involved (they were the plumbing of the removed single-sheet API).
    """

    def __init__(self, image_store: ImageStore | None = None) -> None:
        # Ingest pipeline for the «Изображение» column — None only in tests
        # that don't exercise that column.
        self._image_store = image_store

    async def analyze_file(
        self, path: str | Path, uow: GameSessionUoW | None = None
    ) -> ImportPlan:
        """Pre-analyze a five-sheet .xlsx into a pure :class:`ImportPlan`.

        Only reads (workbook + read-only name-index queries); writes nothing.
        ``uow`` (when given) provides the game session whose DB holds the
        upsert/link-target name index of design D3 (``uow.session`` — reads
        need no finish); the unit is never committed here. The plan is fully
        populated only when the index is available — an unresolved link
        reference to a type the file itself does not define is then a fatal
        error instead of a silently wrong ghost.
        """
        path = Path(path)
        if not path.exists():
            return ImportPlan(path=path, fatal_errors=[f"Файл не найден: {path}"])

        plan = analyze_workbook(path)
        if plan.has_fatal:
            return plan

        if uow is not None:
            await build_name_index(plan, uow.session)
        resolve_links(plan)
        return plan

    # ── Applying the plan (task group 3) ───────────────────────────────────

    async def apply_plan(
        self,
        plan: ImportPlan,
        uow: GameSessionUoW,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ImportReport:
        """Apply an analyzed plan in two passes inside one transaction.

        Pass 1 creates/updates every planned entity (``xlsx_apply``) —
        including ghost link targets (min-start/max-end dates from the
        referring rows) and missing event types, each recorded in
        ``report.decisions``; pass 2 adds every link through the ORM
        relationships with deduplication and never unlinks anything.
        A fatal plan is refused before anything is touched.

        Transaction (task 3.3, wave 5 task 5.11): ``uow`` is the explicit
        dependency from the wiring — the passes run inside its single
        transaction, which commits once on clean exit and rolls back +
        re-raises on any failure (the commit/rollback callback parameters
        are gone; the unit holds that contract). Images replaced by the
        updates are GC'd as a post-write hook of the same unit (design D6),
        so the collector runs after the import committed and its failure is
        logged there without ever failing the import (audit Q14 scenario 4).
        ``progress_callback(done, total)`` gets one tick per entity/ghost and
        per link reference.
        """
        if plan.has_fatal:
            raise ValueError("Импорт невозможен: " + " ".join(plan.fatal_errors))

        report = ImportReport(
            skipped=list(plan.skipped_rows),
            warnings=list(plan.warnings),
            # The dates the active calendar refused and the import clamped
            # (C3a, spec «Итоговый отчёт импорта»): collected from the merged
            # rows that will really be written, start slot before end slot.
            date_shifts=[
                shift
                for row in ordered_rows(plan)
                for slot in ("start_date", "end_date")
                if (shift := row.date_shifts.get(slot)) is not None
            ],
        )
        total = len(plan.planned_rows) + len(plan.ghosts) + sum(1 for _ in plan.iter_links())
        processed = 0

        def tick() -> None:
            nonlocal processed
            processed += 1
            if progress_callback is not None:
                progress_callback(processed, total)

        async with uow.transaction():
            instances, replaced_images = await apply_entities_pass(
                plan, uow.session, report, tick, self._image_store,
            )
            await apply_links_pass(
                plan, uow.session, instances, report, tick,
                resolve_link_target=self._resolve_link_target,
            )
            if replaced_images and self._image_store is not None:
                uow.after_write(
                    partial(self._image_store.gc_after_commit, *replaced_images)
                )

        if progress_callback is not None:
            progress_callback(total, total)
        return report

    @staticmethod
    async def _resolve_link_target(
        ref: PlannedLink,
        instances: dict[tuple[str, str], Any],
        session: AsyncSession,
    ) -> Any | None:
        if ref.resolution == LINK_TO_DB:
            return await session.get(orm_model(ref.target_type), ref.db_id)
        # LINK_TO_FILE and LINK_TO_GHOST both live in the pass-1 instance map.
        return instances.get(ref.target_key)
