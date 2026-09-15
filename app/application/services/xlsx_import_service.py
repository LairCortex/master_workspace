"""Service for importing entities from .xlsx files.

The unified five-sheet import (rework-xlsx-import, design D2/D3):
``analyze_file`` reads the workbook once (together with a read-only name
index over the game DB) and produces a pure :class:`ImportPlan` — fatal
file errors, merged rows per (type, lower(name)), per-row planned skips,
upsert targets and auto-created link targets (ghosts). ``apply_plan``
consumes that artifact: pass 1 creates/updates all entities (ghost
targets, auto event types, images through ``ImageStore``), pass 2 only
adds links via the ORM relationships; the whole apply runs in one
transaction with a single commit on success and a rollback on any
failure (task group 3, design D4–D6).

The legacy single-sheet API (``validate_file`` / ``import_file``) was
removed together with the old file format (proposal: BREAKING — the
one-sheet English-header files are no longer read).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services import xlsx_schema as schema
from app.application.services.event_service import COLOR_INDEX_MAX, COLOR_INDEX_MIN
from app.domain.date_era import era_key
from app.infrastructure.db.models import (
    CharacterModel,
    DescriptionModel,
    EventModel,
    EventTypeModel,
    ImageModel,
    ItemModel,
    LocationModel,
    OrganizationModel,
)
from app.infrastructure.images.store import ImageStore

# ORM model per registry entity type (app/infrastructure/db/models.py).
_ORM_MODELS: dict[str, type] = {
    "event": EventModel,
    "character": CharacterModel,
    "location": LocationModel,
    "organization": OrganizationModel,
    "item": ItemModel,
}

# Link-reference resolution kinds (design D3): resolved to a row of the same
# file, to a uniquely named DB entity, or auto-created from the reference.
LINK_TO_FILE = "file"
LINK_TO_DB = "db"
LINK_TO_GHOST = "ghost"


# ── Import plan (rework-xlsx-import, design D2) ───────────────────────────
# The plan is a pure artifact: no DB mutation happens during analysis, and
# applying it (task group 3) consumes exactly what is stored here. Fatal file
# errors block applying; row-level problems are recorded as planned skips.

@dataclass
class RowIssue:
    """One planned-skip reason for one source row (list: sheet + row number)."""

    sheet: str
    row_number: int  # 1-based Excel row number (header row = 1)
    reason: str


@dataclass
class NameIndexEntry:
    """DB entities of one type sharing one lower(name) (design D3)."""

    models: list[Any] = field(default_factory=list)

    @property
    def is_unique(self) -> bool:
        return len(self.models) == 1

    @property
    def is_ambiguous(self) -> bool:
        return len(self.models) > 1


@dataclass
class PlannedLink:
    """One link-column reference collected during parsing/merging.

    ``resolution`` is decided by the name index (design D3): file row wins
    (determinism), else a unique DB match, else a ghost target; an ambiguous
    DB match (no file row) skips the referring row with a planned-skip.
    """

    target_type: str
    name: str  # original case as written in the cell
    target_key: tuple[str, str]  # (target_type, lower(name))
    source_row_number: int  # Excel row whose cell wrote this reference
    resolution: str = LINK_TO_GHOST
    db_id: int | None = None


@dataclass
class PlannedRow:
    """A merged planned entity (one or more file rows of one type and name).

    ``fields`` carries only non-empty values of the registry column keys
    (merge: later non-empty wins — spec "Слияние одинаковых имён"; upsert:
    an empty cell therefore never reaches the update — spec "Пустая ячейка
    не затирает"). ``existing_id`` set ⇒ update plan, else create plan.
    """

    entity_type: str
    sheet: str
    key: tuple[str, str]  # (entity_type, lower(name)) — merge key
    first_row_number: int  # Excel row of the first contributing row
    fields: dict[str, Any] = field(default_factory=dict)
    links: dict[str, list[PlannedLink]] = field(default_factory=dict)
    skipped: bool = False
    existing_id: int | None = None

    @property
    def name(self) -> str:
        return self.fields["name"]

    @property
    def is_update(self) -> bool:
        return self.existing_id is not None


@dataclass
class PlannedGhost:
    """Auto-created link target (design D5): dates are the min start /
    max end of the referring rows in the shared chronological order (design
    D2 era keys, add-era-aware-dates task 5.2 — a BC date always precedes any
    our-era one regardless of its raw ``date`` value); materialized by the
    apply pass with the matching eras."""

    entity_type: str
    key: tuple[str, str]
    name: str  # original case of the first referring cell
    min_start: date
    max_end: date
    min_start_bc: bool = False  # era of min_start (add-era-aware-dates, D7)
    max_end_bc: bool = False  # era of max_end
    referenced_by: list[tuple[str, int]] = field(default_factory=list)  # (sheet, row)


@dataclass
class ImportPlan:
    path: Path
    entities: dict[tuple[str, str], PlannedRow] = field(default_factory=dict)
    ghosts: dict[tuple[str, str], PlannedGhost] = field(default_factory=dict)
    skipped_rows: list[RowIssue] = field(default_factory=list)
    fatal_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # DB lower(name)s with more than one row per type (task 2.3 GROUP BY).
    ambiguous_names: dict[str, set[str]] = field(default_factory=dict)
    name_index: dict[tuple[str, str], NameIndexEntry] = field(default_factory=dict)
    # True once the DB name index was built (an empty index with built=True
    # legitimately means "none of the plan's names are in the DB").
    name_index_built: bool = False

    @property
    def has_fatal(self) -> bool:
        return bool(self.fatal_errors)

    @property
    def planned_rows(self) -> list[PlannedRow]:
        """Merged entities that will actually be created/updated."""
        return [row for row in self.entities.values() if not row.skipped]

    def iter_links(self) -> Iterator[PlannedLink]:
        for row in self.entities.values():
            if row.skipped:
                continue
            yield from (link for links in row.links.values() for link in links)

    def lookup_row(self, target_type: str, name: str) -> PlannedRow | None:
        """Planned row of ``target_type`` by (lowercased) name — link target."""
        return self.entities.get((target_type, name.strip().lower()))


def _empty_cell(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _era_text(d: date, is_bc: bool) -> str:
    """ISO date annotated with the era marker for BC («… до н.э.»)."""
    return f"{d.isoformat()} до н.э." if is_bc else d.isoformat()


def _row_to_draft(
    spec: schema.SheetSpec,
    sheet_title: str,
    row_number: int,
    resolved: schema.ResolvedHeaders,
    row: tuple,
) -> tuple[PlannedRow | None, RowIssue | None]:
    """Parse one data row into a merge candidate, or a planned-skip issue."""
    fields: dict[str, Any] = {}
    for pos in sorted(resolved.scalars):
        col = resolved.scalars[pos]
        value = row[pos] if pos < len(row) else None
        if col.key in ("start_date", "end_date"):
            parsed = schema.parse_cell_date(value)
            if parsed is not None:
                moment, is_bc = parsed
                fields[col.key] = moment
                # The era travels next to its date under the ORM field names
                # (start_bc/end_bc — same kwargs the entity services take):
                # the merge keeps the pair atomic, later non-empty wins both.
                era_key_field = "start_bc" if col.key == "start_date" else "end_bc"
                fields[era_key_field] = is_bc
            elif col.key == "start_date":
                shown = "пусто" if _empty_cell(value) else f"значение «{value}» не является датой"
                return None, RowIssue(sheet_title, row_number, f"дата начала: {shown}")
            # An unparsable optional end date is simply not applied (the
            # spec marks only the start date as a row problem).
            continue
        if col.key == "rating":
            try:
                rating = schema.parse_cell_rating(value)
            except ValueError as exc:
                return None, RowIssue(sheet_title, row_number, str(exc))
            if rating is not None:
                fields["rating"] = rating
            continue
        if _empty_cell(value):
            continue  # non-empty values only (merge/upsert overlap rule)
        fields[col.key] = str(value).strip()

    name = fields.get("name")
    if not name:
        return None, RowIssue(sheet_title, row_number, "пустое имя")

    links: dict[str, list[PlannedLink]] = {}
    for pos, link_col in resolved.links.items():
        value = row[pos] if pos < len(row) else None
        bucket = links.setdefault(link_col.target_type, [])
        seen = {link.target_key for link in bucket}
        for target_name in schema.parse_link_cell(value):
            key = (link_col.target_type, target_name.lower())
            if key in seen:
                continue  # duplicate target within one cell
            seen.add(key)
            bucket.append(
                PlannedLink(
                    target_type=link_col.target_type,
                    name=target_name,
                    target_key=key,
                    source_row_number=row_number,
                )
            )
    draft = PlannedRow(
        entity_type=spec.entity_type,
        sheet=sheet_title,
        key=(spec.entity_type, name.lower()),
        first_row_number=row_number,
        fields=fields,
        links=links,
    )
    return draft, None


def _parse_sheet(
    plan: ImportPlan,
    spec: schema.SheetSpec,
    sheet_title: str,
    rows: list[tuple],
) -> None:
    """Check one known sheet's header row and merge its data rows into plan."""
    if not rows or all(_empty_cell(cell) for cell in rows[0]):
        plan.fatal_errors.append(f"Лист «{sheet_title}»: нет строки заголовков.")
        return
    missing = schema.missing_required_headers(spec, rows[0])
    if missing:
        plan.fatal_errors.append(
            f"Лист «{sheet_title}»: отсутствуют обязательные колонки: {', '.join(missing)}."
        )
        return

    resolved = schema.resolve_headers(spec, rows[0])
    for row_number, raw_row in enumerate(rows[1:], start=2):
        row = tuple(None if _empty_cell(cell) else cell for cell in raw_row)
        if not any(cell is not None for cell in row):
            continue  # fully blank row (openpyxl dimension padding) — not a row
        draft, issue = _row_to_draft(spec, sheet_title, row_number, resolved, row)
        if issue is not None:
            plan.skipped_rows.append(issue)
            continue
        merged = plan.entities.get(draft.key)
        if merged is None:
            plan.entities[draft.key] = draft
            continue
        # Merge (type, lower(name)): later non-empty fields override, links
        # accumulate (order preserved, per-row dedup already applied).
        merged.fields.update(draft.fields)
        for target_type, refs in draft.links.items():
            existing = merged.links.setdefault(target_type, [])
            seen = {link.target_key for link in existing}
            existing.extend(link for link in refs if link.target_key not in seen)


def _collect_wanted_names(plan: ImportPlan) -> dict[str, set[str]]:
    """lower(name)s per type that the plan needs resolved against the DB."""
    wanted: dict[str, set[str]] = {}
    for row in plan.entities.values():
        wanted.setdefault(row.entity_type, set()).add(row.key[1])
    for row in plan.entities.values():
        for refs in row.links.values():
            for ref in refs:
                wanted.setdefault(ref.target_type, set()).add(ref.target_key[1])
    return wanted


async def _build_name_index(plan: ImportPlan, session: AsyncSession) -> None:
    """Name index of design D3 — one grouped query + one candidate query per
    type (never per row): ambiguous DB names via
    ``GROUP BY lower(name) HAVING COUNT(*) > 1``, unique candidates via a
    lower(name) IN lookup. An update target is planned only for a unique
    match; ambiguous row names stay create-plans (existing_id is None)."""
    wanted = _collect_wanted_names(plan)
    for entity_type, names in wanted.items():
        model = _ORM_MODELS[entity_type]
        lower_name = func.lower(model.name)
        grouped = (
            select(lower_name.label("lower_name"), func.count().label("row_count"))
            .group_by(lower_name)
            .having(func.count() > 1)
        )
        ambiguous = {
            r.lower_name
            for r in (await session.execute(grouped)).all()
            if r.lower_name in names
        }
        if ambiguous:
            plan.ambiguous_names.setdefault(entity_type, set()).update(ambiguous)
        candidates = (
            await session.execute(select(model).where(lower_name.in_(sorted(names))))
        ).scalars().all()
        by_lower: dict[str, list[Any]] = {}
        for obj in candidates:
            by_lower.setdefault(str(obj.name).lower(), []).append(obj)
        for lower_key in set(by_lower) | ambiguous:
            plan.name_index[(entity_type, lower_key)] = NameIndexEntry(
                models=list(by_lower.get(lower_key, []))
            )
    for row in plan.entities.values():
        entry = plan.name_index.get(row.key)
        if entry is not None and entry.is_unique:
            row.existing_id = entry.models[0].id
    plan.name_index_built = True


def _grow_ghost(plan: ImportPlan, ref: PlannedLink, row: PlannedRow) -> None:
    """Expand the ghost buffer with one reference (design D5: min start /
    max end of the referring rows; a missing end date counts as its start).
    Bounds compare through the shared era key (design D2/D7): raw ``date``
    objects would order BC years backwards and mix the eras wrongly."""
    start = row.fields["start_date"]
    start_bc = bool(row.fields.get("start_bc"))
    end = row.fields.get("end_date") or start
    end_bc = bool(row.fields.get("end_bc")) if row.fields.get("end_date") else start_bc
    start_key = era_key(start, start_bc)
    end_key = era_key(end, end_bc)
    ghost = plan.ghosts.get(ref.target_key)
    if ghost is None:
        plan.ghosts[ref.target_key] = PlannedGhost(
            entity_type=ref.target_type,
            key=ref.target_key,
            name=ref.name,  # first reference keeps its case
            min_start=start,
            max_end=end,
            min_start_bc=start_bc,
            max_end_bc=end_bc,
            referenced_by=[(row.sheet, ref.source_row_number)],
        )
        return
    if start_key < era_key(ghost.min_start, ghost.min_start_bc):
        ghost.min_start, ghost.min_start_bc = start, start_bc
    if end_key > era_key(ghost.max_end, ghost.max_end_bc):
        ghost.max_end, ghost.max_end_bc = end, end_bc
    source = (row.sheet, ref.source_row_number)
    if source not in ghost.referenced_by:
        ghost.referenced_by.append(source)


def _resolve_row_links(plan: ImportPlan, row: PlannedRow) -> RowIssue | None:
    """Classify one row's link references; None if all resolve fine.

    A reference to an ambiguous DB name that no file row defines makes the
    whole referring row a planned skip (task 2.3); a name absent from both
    file and DB becomes a ghost target.
    """
    for refs in row.links.values():
        for ref in refs:
            target = plan.entities.get(ref.target_key)
            if target is not None and not target.skipped:
                ref.resolution, ref.db_id = LINK_TO_FILE, None
                continue
            entry = plan.name_index.get(ref.target_key)
            if entry is not None and entry.is_unique:
                ref.resolution, ref.db_id = LINK_TO_DB, entry.models[0].id
                continue
            if entry is not None and entry.is_ambiguous:
                label = schema.LINK_COLUMNS_BY_TARGET[ref.target_type].label
                sheet_name = schema.sheet_for(ref.target_type).sheet_name
                return RowIssue(
                    row.sheet,
                    ref.source_row_number,
                    f"колонка «{label}»: ссылка «{ref.name}» разрешения "
                    f"не имеет — в базе несколько сущностей (лист «{sheet_name}»), "
                    "а в файле нет строки с таким именем",
                )
            # Unknown target → ghost, unless the name index was never built
            # (no session *and* the file defines no rows of the target type):
            # then membership in the DB cannot be told apart from absence.
            has_file_rows_of_type = any(
                other.entity_type == ref.target_type
                and not other.skipped
                for other in plan.entities.values()
            )
            if not plan.name_index_built and not has_file_rows_of_type:
                plan.fatal_errors.append(
                    f"Лист «{row.sheet}», строка {ref.source_row_number}: ссылка "
                    f"«{ref.name}» не может быть проверена — индекс имён не построен"
                )
            ref.resolution, ref.db_id = LINK_TO_GHOST, None
    return None


def _resolve_links(plan: ImportPlan) -> None:
    """Resolve every link reference, iterating to a fixpoint: skipping a row
    can remove it as a file-resolvable target and cascade its referrers to
    the DB/ghost/ambiguous branches (the skip set only grows, so this ends).
    Ghosts are finally grown from surviving rows only."""
    while True:
        new_skips: list[RowIssue] = []
        for row in list(plan.entities.values()):
            if row.skipped:
                continue
            issue = _resolve_row_links(plan, row)
            if issue is not None:
                row.skipped = True
                new_skips.append(issue)
        plan.skipped_rows.extend(new_skips)
        if not new_skips:
            break
    plan.ghosts = {}
    for row in plan.entities.values():
        if row.skipped:
            continue
        for refs in row.links.values():
            for ref in refs:
                if ref.resolution == LINK_TO_GHOST:
                    _grow_ghost(plan, ref, row)


# ── Apply / report (rework-xlsx-import, task group 3, designs D4–D6) ─────
# ``apply_plan`` consumes a finished ImportPlan: pass 1 materializes every
# planned entity (updates by unique name, creates, ghost link targets, auto
# event types, image ingestion), pass 2 adds links through the ORM
# relationships. Neither pass ever unlinks an existing relation (design D4),
# and the whole run is one transaction: exactly one commit on success,
# rollback + re-raise on any failure (spec "Транзакционность импорта").

#: ORM relationship attribute carrying links to entities of one target type
#: — the same collection names the models declare (all M2M relations are
#: bidirectional with back_populates, so an edge added from either side is
#: visible from both and gets deduplicated).
RELATION_ATTRS_BY_TARGET: dict[str, str] = {
    "event": "events",
    "character": "characters",
    "organization": "organizations",
    "item": "items",
    "location": "locations",
}

#: PlannedRow.fields keys consumed by dedicated rules (name / description
#: row / event-type resolution / image pipeline) instead of plain setattr.
_NON_SCALAR_KEYS = frozenset({"name", "characteristics", "backstory", "event_type", "image"})


@dataclass
class ImportReport:
    """Final import report (spec "Итоговый отчёт импорта"): created/updated
    entity counts, newly installed links, the planned skipped rows carried
    over from the analysis (sheet/row/reason), warnings (unknown sheets of
    the plan plus unreadable images) and every automatic decision taken
    (auto-created link targets and event types)."""

    created: int = 0
    updated: int = 0
    links: int = 0
    skipped: list[RowIssue] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _first_free_color_index(used: set[int]) -> int:
    """Design D5: smallest free ``color.chart.{1..8}`` index; when all eight
    are taken, rotate past the highest used one (same rule as the event
    types dialog)."""
    for index in range(COLOR_INDEX_MIN, COLOR_INDEX_MAX + 1):
        if index not in used:
            return index
    return (max(used) % COLOR_INDEX_MAX) + COLOR_INDEX_MIN


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
        self, path: str | Path, session: AsyncSession | None = None
    ) -> ImportPlan:
        """Pre-analyze a five-sheet .xlsx into a pure :class:`ImportPlan`.

        Only reads (workbook + read-only name-index queries); writes nothing.
        ``session`` (when given) provides the upsert/link-target name index of
        design D3; it is never committed here. The plan is fully populated
        only when the index is available — an unresolved link reference to a
        type the file itself does not define is then a fatal error instead of
        a silently wrong ghost.
        """
        path = Path(path)
        if not path.exists():
            return ImportPlan(path=path, fatal_errors=[f"Файл не найден: {path}"])

        plan = self._analyze_workbook(path)
        if plan.has_fatal:
            return plan

        if session is not None:
            await _build_name_index(plan, session)
        _resolve_links(plan)
        return plan

    @staticmethod
    def _analyze_workbook(path: Path) -> ImportPlan:
        """One-shot read of the workbook (task 2.1): known sheets are parsed
        and merged, unknown ones only warned about; every file-level defect
        lands in ``plan.fatal_errors`` and aborts the rest of the analysis."""
        plan = ImportPlan(path=path)
        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:  # openpyxl raises a zoo of format errors
            plan.fatal_errors.append(f"Файл повреждён или не является .xlsx: {exc}")
            return plan

        try:
            known: list[tuple[schema.SheetSpec, str]] = []
            for title in wb.sheetnames:
                spec = schema.find_sheet_by_name(title)
                if spec is None:
                    plan.warnings.append(
                        f"Неизвестный лист «{title}» не входит в набор листов "
                        "импорта и импортирован не будет."
                    )
                else:
                    known.append((spec, title))

            by_registry_name: dict[str, list[str]] = {}
            for spec, title in known:
                by_registry_name.setdefault(
                    schema.normalize_header(spec.sheet_name), []
                ).append(title)
            duplicates = [titles for titles in by_registry_name.values() if len(titles) > 1]
            if duplicates:
                for titles in duplicates:
                    plan.fatal_errors.append(
                        "Дубликаты листа в нескольких написаниях: "
                        + ", ".join(f"«{t}»" for t in titles)
                    )
                return plan

            if not known:
                expected = ", ".join(s.sheet_name for s in schema.all_sheets())
                plan.fatal_errors.append(
                    f"В файле нет ни одного знакомого листа. Ожидаемые листы: {expected}."
                )
                return plan

            for spec, title in known:
                _parse_sheet(plan, spec, title, list(wb[title].iter_rows(values_only=True)))

            if not plan.fatal_errors and not plan.entities and not plan.skipped_rows:
                plan.fatal_errors.append(
                    "Файл пустой: знакомые листы не содержат ни одной строки данных."
                )
        finally:
            wb.close()
        return plan

    # ── Applying the plan (task group 3) ───────────────────────────────────

    async def apply_plan(
        self,
        plan: ImportPlan,
        session: AsyncSession,
        progress_callback: Callable[[int, int], None] | None = None,
        commit: Callable[[], Awaitable[Any]] | None = None,
        rollback: Callable[[], Awaitable[Any]] | None = None,
    ) -> ImportReport:
        """Apply an analyzed plan in two passes inside one transaction.

        Pass 1 creates/updates every planned entity — including ghost link
        targets (min-start/max-end dates from the referring rows) and missing
        event types, each recorded in ``report.decisions``; pass 2 adds every
        link through the ORM relationships with deduplication and never
        unlinks anything. A fatal plan is refused before anything is touched.

        Transaction (task 3.3): ``session`` is the explicit dependency from
        the wiring; the success commit and the failure rollback go through
        the ``commit``/``rollback`` callbacks when provided (defaults are
        the session's own methods) — exactly one commit, and on any
        exception everything the passes did is rolled back and the exception
        re-raised for the UI.  ``progress_callback(done, total)`` gets one
        tick per entity/ghost and per link reference.
        """
        if plan.has_fatal:
            raise ValueError("Импорт невозможен: " + " ".join(plan.fatal_errors))

        do_commit = commit if commit is not None else session.commit
        do_rollback = rollback if rollback is not None else session.rollback

        report = ImportReport(
            skipped=list(plan.skipped_rows),
            warnings=list(plan.warnings),
        )
        total = len(plan.planned_rows) + len(plan.ghosts) + sum(1 for _ in plan.iter_links())
        processed = 0

        def tick() -> None:
            nonlocal processed
            processed += 1
            if progress_callback is not None:
                progress_callback(processed, total)

        try:
            instances, replaced_images = await self._apply_entities_pass(plan, session, report, tick)
            await self._apply_links_pass(plan, session, instances, report, tick)
            await do_commit()
        except Exception:
            await do_rollback()
            raise

        # Images replaced by the (now committed) updates: best-effort GC,
        # the same post-commit contract EntityService follows (design D6 of
        # image-storage — must never affect the succeeded import).
        if replaced_images and self._image_store is not None:
            await self._image_store.gc_after_commit(*replaced_images)
        if progress_callback is not None:
            progress_callback(total, total)
        return report

    @staticmethod
    def _ordered_rows(plan: ImportPlan) -> list[PlannedRow]:
        """Non-skipped planned rows in registry-sheet order (deterministic
        ids and decision lists regardless of the workbook's tab order)."""
        order = {spec.entity_type: pos for pos, spec in enumerate(schema.all_sheets())}
        return sorted(
            (row for row in plan.entities.values() if not row.skipped),
            key=lambda row: (order[row.entity_type], row.first_row_number),
        )

    async def _apply_entities_pass(
        self,
        plan: ImportPlan,
        session: AsyncSession,
        report: ImportReport,
        tick: Callable[[], None],
    ) -> tuple[dict[tuple[str, str], Any], list[int]]:
        """Pass 1: every planned row upserts, every ghost materializes
        (design D5). Returns the (type, lower(name)) → model map used by
        pass 2, plus image ids replaced by updates (post-commit GC list)."""
        instances: dict[tuple[str, str], Any] = {}
        replaced_images: list[int] = []
        event_types = await self._load_event_types(session)

        for row in self._ordered_rows(plan):
            instances[row.key] = await self._upsert_row(
                row, plan.path.parent, session, report, event_types, replaced_images,
            )
            tick()

        sheet_order = {spec.entity_type: pos for pos, spec in enumerate(schema.all_sheets())}
        for key in sorted(plan.ghosts, key=lambda k: (sheet_order[k[0]], k[1])):
            ghost = plan.ghosts[key]
            model = _ORM_MODELS[ghost.entity_type]
            obj = model(
                name=ghost.name,
                start_date=ghost.min_start,
                start_bc=ghost.min_start_bc,
                end_date=ghost.max_end,
                end_bc=ghost.max_end_bc,
                description=DescriptionModel(characteristics="", backstory=""),
            )
            session.add(obj)
            await session.flush()
            instances[key] = obj
            report.created += 1
            sheet_name = schema.sheet_for(ghost.entity_type).sheet_name
            refs = ", ".join(f"лист «{s}», строка {n}" for s, n in ghost.referenced_by)
            report.decisions.append(
                f"Автосоздание: цель связи «{ghost.name}» не найдена ни в файле, ни в базе — "
                f"создана как сущность листа «{sheet_name}» с датами "
                f"{_era_text(ghost.min_start, ghost.min_start_bc)}—"
                f"{_era_text(ghost.max_end, ghost.max_end_bc)} "
                f"по ссылающимся строкам: {refs}"
            )
            tick()
        return instances, replaced_images

    async def _upsert_row(
        self,
        row: PlannedRow,
        xlsx_dir: Path,
        session: AsyncSession,
        report: ImportReport,
        event_types: dict[str, Any],
        replaced_images: list[int],
    ) -> Any:
        """One planned row → created or updated ORM entity (spec "upsert").

        Only non-empty fields are applied (the plan dropped the empty ones),
        so an empty cell never erases a stored value; ``name`` of an update
        target stays as is (the lower(name) match IS the upsert key —
        design D7: no renames, no mention rewriting)."""
        model = _ORM_MODELS[row.entity_type]
        if row.is_update:
            obj = await session.get(model, row.existing_id)
            if obj is None:
                raise ValueError(
                    f"сущность «{row.name}» (лист «{row.sheet}») исчезла из базы "
                    "между анализом и применением"
                )
            report.updated += 1
            if "characteristics" in row.fields or "backstory" in row.fields:
                desc = obj.description
                if desc is None:
                    desc = DescriptionModel(characteristics="", backstory="")
                    obj.description = desc
                if "characteristics" in row.fields:
                    desc.characteristics = row.fields["characteristics"]
                if "backstory" in row.fields:
                    desc.backstory = row.fields["backstory"]
        else:
            obj = model(
                name=row.fields["name"],
                description=DescriptionModel(
                    characteristics=row.fields.get("characteristics", ""),
                    backstory=row.fields.get("backstory", ""),
                ),
            )
            session.add(obj)
            report.created += 1

        columns = {c.key for c in model.__table__.columns}
        for key, value in row.fields.items():
            # An event's «Рейтинг» never reaches setattr below: EventModel has
            # no rating column, so it is silently dropped (carried contract).
            if key not in _NON_SCALAR_KEYS and key in columns:
                setattr(obj, key, value)

        if row.entity_type == "event" and row.fields.get("event_type"):
            # The relationship (not the raw FK) is assigned: the entity may
            # already sit in this session's identity map from the analysis,
            # and an expired-but-loaded ``event_type`` would stay stale there.
            obj.event_type = await self._resolve_event_type(
                row.fields["event_type"], row, session, report, event_types,
            )

        if "image_id" in columns and row.fields.get("image"):
            image_id = await self._load_image_from_path(xlsx_dir, row.fields["image"])
            if image_id is None:
                # Spec "Нечитаемый файл картинки": the entity stays valid.
                report.warnings.append(
                    f"Лист «{row.sheet}», строка {row.first_row_number}: изображение "
                    f"«{row.fields['image']}» не загружено — сущность сохранена без изображения"
                )
            elif image_id != obj.image_id:
                if obj.image_id:
                    replaced_images.append(obj.image_id)
                obj.image_ref = await session.get(ImageModel, image_id)

        await session.flush()
        return obj

    @staticmethod
    async def _load_event_types(session: AsyncSession) -> dict[str, Any]:
        """World's event types by lower(name) + color/sort allocation state."""
        types = (await session.execute(select(EventTypeModel))).scalars().all()
        return {
            "by_name": {t.name.lower(): t for t in types},
            "used_colors": {t.color_index for t in types},
            "next_sort": max((t.sort_order for t in types), default=-1) + 1,
        }

    async def _resolve_event_type(
        self,
        label: str,
        row: PlannedRow,
        session: AsyncSession,
        report: ImportReport,
        event_types: dict[str, Any],
    ) -> EventTypeModel:
        """Look the «Тип» label up by lower(name); auto-create a missing type
        with the first free color_index (spec "Новый тип события", D5)."""
        type_model = event_types["by_name"].get(label.lower())
        if type_model is None:
            type_model = EventTypeModel(
                name=label,
                color_index=_first_free_color_index(event_types["used_colors"]),
                sort_order=event_types["next_sort"],
            )
            session.add(type_model)
            await session.flush()
            event_types["by_name"][label.lower()] = type_model
            event_types["used_colors"].add(type_model.color_index)
            event_types["next_sort"] += 1
            report.decisions.append(
                f"Автосоздание: тип события «{label}» отсутствует в мире — создан "
                f"(событие «{row.name}», лист «{row.sheet}», строка {row.first_row_number})"
            )
        return type_model

    async def _apply_links_pass(
        self,
        plan: ImportPlan,
        session: AsyncSession,
        instances: dict[tuple[str, str], Any],
        report: ImportReport,
        tick: Callable[[], None],
    ) -> None:
        """Pass 2 (design D4): every planned link is ADDED through the ORM
        relationship of the source entity; existing edges are deduplicated,
        nothing is ever removed by an import (spec "Связи не отвязываются").

        Sources are entities that may have been flushed only seconds earlier,
        so their ``lazy="selectin"`` collections are not necessarily loaded —
        they are refreshed through an awaited load (``session.refresh``)
        before any synchronous mutation of them."""
        for row in self._ordered_rows(plan):
            attrs: list[str] = []
            pending: list[PlannedLink] = []
            for target_type, refs in row.links.items():
                if refs:
                    attrs.append(RELATION_ATTRS_BY_TARGET[target_type])
                    pending.extend(refs)
            if not pending:
                continue
            source = instances[row.key]
            await session.refresh(source, attribute_names=sorted(set(attrs)))

            collections: dict[str, list[Any]] = {}
            for ref in pending:
                tick()
                target = await self._resolve_link_target(ref, instances, session)
                if target is None:
                    report.warnings.append(
                        f"Лист «{row.sheet}», строка {ref.source_row_number}: цель связи "
                        f"«{ref.name}» не найдена в базе — связь не установлена"
                    )
                    continue
                collection = collections.setdefault(
                    RELATION_ATTRS_BY_TARGET[ref.target_type],
                    getattr(source, RELATION_ATTRS_BY_TARGET[ref.target_type]),
                )
                if target.id in {obj.id for obj in collection}:
                    continue  # already linked (existing or added via backref)
                collection.append(target)
                report.links += 1
        await session.flush()

    @staticmethod
    async def _resolve_link_target(
        ref: PlannedLink,
        instances: dict[tuple[str, str], Any],
        session: AsyncSession,
    ) -> Any | None:
        if ref.resolution == LINK_TO_DB:
            return await session.get(_ORM_MODELS[ref.target_type], ref.db_id)
        # LINK_TO_FILE and LINK_TO_GHOST both live in the pass-1 instance map.
        return instances.get(ref.target_key)

    async def _load_image_from_path(self, base_dir: Path, cell_value: str) -> int | None:
        """Resolve path (relative to base_dir or absolute), ingest via ``ImageStore``.

        Returns the new ``image_id``, or None on any failure (missing file,
        unsupported extension, undecodable content, no store configured) —
        the caller turns that into a per-row warning (design D11).
        """
        if self._image_store is None:
            return None
        p = Path(cell_value.strip())
        if not p.is_absolute():
            p = (base_dir / p).resolve()
        if not p.exists() or not p.is_file():
            return None
        suffix = p.suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"):
            return None
        try:
            data = p.read_bytes()
            return await self._image_store.store(data)
        except (OSError, ValueError):
            return None

