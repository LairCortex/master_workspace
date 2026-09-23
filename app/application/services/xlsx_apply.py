"""Apply half of the xlsx import (audit B6, design D6): the two writing
passes that materialize an analyzed :class:`~app.application.services.
xlsx_analyze.ImportPlan` through the session/ORM and the image pipeline.

The code moved byte-for-byte from the former ``xlsx_import_service``
monolith. ``XlsxImportService.apply_plan`` keeps the transaction contract
(one commit / one rollback, ``progress_callback`` ticks) and calls the two
passes here; the link-target resolution stays an instance seam of the
service because tests drive their failure injection through it, so the
link pass receives it as a parameter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services import xlsx_schema as schema
from app.application.services.event_service import COLOR_INDEX_MAX, COLOR_INDEX_MIN
from app.application.services.xlsx_analyze import (
    DateShiftRow,
    ImportPlan,
    PlannedLink,
    PlannedRow,
    RowIssue,
    coord_text,
)
from app.application.services.xlsx_report_text import vanished_after_analysis
from app.domain import entity_registry
from app.domain.allowed_image_extensions import ALLOWED_IMAGE_EXTENSIONS
from app.domain.enums.entity_type import EntityType
from app.infrastructure.db.models import (
    DescriptionModel,
    EventTypeModel,
    ImageModel,
)
from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories import ORM_MODEL_BY_ENTITY_TYPE
from app.infrastructure.repositories.coord_mapping import (
    DATE_PAYLOAD_KEYS,
    route_insert_dates,
)


def orm_model(entity_type_key: str) -> type:
    """Storage model for a registry type key; the type↔ORM association is
    owned by the repository package (design D2), not by these modules."""
    return ORM_MODEL_BY_ENTITY_TYPE[EntityType(entity_type_key)]


# ── Apply / report (rework-xlsx-import, task group 3, designs D4–D6) ─────
# ``apply_plan`` consumes a finished ImportPlan: pass 1 materializes every
# planned entity (updates by unique name, creates, ghost link targets, auto
# event types, image ingestion), pass 2 adds links through the ORM
# relationships. Neither pass ever unlinks an existing relation (design D4),
# and the whole run is one transaction: exactly one commit on success,
# rollback + re-raise on any failure (spec "Транзакционность импорта").

# The ORM relationship attribute carrying links to entities of one target
# type is the registry's plural collection name (wave 3, A4): all M2M
# relations are bidirectional with back_populates, so an edge added from
# either side is visible from both and gets deduplicated.

#: PlannedRow.fields keys consumed by dedicated rules (name / description
#: row / event-type resolution / image pipeline) instead of plain setattr.
_NON_SCALAR_KEYS = frozenset({"name", "characteristics", "backstory", "event_type", "image"})


@dataclass
class ImportReport:
    """Final import report (spec "Итоговый отчёт импорта"): created/updated
    entity counts, newly installed links, the planned skipped rows carried
    over from the analysis (sheet/row/reason), warnings (unknown sheets of
    the plan plus unreadable images), the dates moved into the game calendar
    during import (C3a: sheet/row/field/old → new, empty section under the
    standard calendar) and every automatic decision taken (auto-created link
    targets and event types)."""

    created: int = 0
    updated: int = 0
    links: int = 0
    skipped: list[RowIssue] = field(default_factory=list)
    date_shifts: list[DateShiftRow] = field(default_factory=list)
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


def ordered_rows(plan: ImportPlan) -> list[PlannedRow]:
    """Non-skipped planned rows in registry-sheet order (deterministic
    ids and decision lists regardless of the workbook's tab order)."""
    order = {spec.entity_type: pos for pos, spec in enumerate(schema.all_sheets())}
    return sorted(
        (row for row in plan.entities.values() if not row.skipped),
        key=lambda row: (order[row.entity_type], row.first_row_number),
    )


async def apply_entities_pass(
    plan: ImportPlan,
    session: AsyncSession,
    report: ImportReport,
    tick: Callable[[], None],
    image_store: ImageStore | None,
) -> tuple[dict[tuple[str, str], Any], list[int]]:
    """Pass 1: every planned row upserts, every ghost materializes
    (design D5). Returns the (type, lower(name)) → model map used by
    pass 2, plus image ids replaced by updates (post-commit GC list)."""
    instances: dict[tuple[str, str], Any] = {}
    replaced_images: list[int] = []
    event_types = await _load_event_types(session)

    for row in ordered_rows(plan):
        instances[row.key] = await _upsert_row(
            row, plan.path.parent, session, report, event_types, replaced_images,
            image_store,
        )
        tick()

    sheet_order = {spec.entity_type: pos for pos, spec in enumerate(schema.all_sheets())}
    for key in sorted(plan.ghosts, key=lambda k: (sheet_order[k[0]], k[1])):
        ghost = plan.ghosts[key]
        model = orm_model(ghost.entity_type)
        obj = model(
            name=ghost.name,
            start_bc=ghost.min_start_bc,
            end_bc=ghost.max_end_bc,
            description=DescriptionModel(characteristics="", backstory=""),
        )
        # Coordinates reach the storage only through the routed resolver
        # (C3a D3): date columns under the preset, coordinate columns
        # under a custom calendar — the same route the upserted rows use.
        route_insert_dates(obj, {"start_date": ghost.min_start, "end_date": ghost.max_end})
        session.add(obj)
        await session.flush()
        instances[key] = obj
        report.created += 1
        sheet_name = schema.sheet_for(ghost.entity_type).sheet_name
        refs = ", ".join(f"лист «{s}», строка {n}" for s, n in ghost.referenced_by)
        report.decisions.append(
            f"Автосоздание: цель связи «{ghost.name}» не найдена ни в файле, ни в базе — "
            f"создана как сущность листа «{sheet_name}» с датами "
            f"{coord_text(ghost.min_start, ghost.min_start_bc)}—"
            f"{coord_text(ghost.max_end, ghost.max_end_bc)} "
            f"по ссылающимся строкам: {refs}"
        )
        tick()
    return instances, replaced_images


async def _upsert_row(
    row: PlannedRow,
    xlsx_dir: Path,
    session: AsyncSession,
    report: ImportReport,
    event_types: dict[str, Any],
    replaced_images: list[int],
    image_store: ImageStore | None,
) -> Any:
    """One planned row → created or updated ORM entity (spec "upsert").

    Only non-empty fields are applied (the plan dropped the empty ones),
    so an empty cell never erases a stored value; ``name`` of an update
    target stays as is (the lower(name) match IS the upsert key —
    design D7: no renames, no mention rewriting)."""
    model = orm_model(row.entity_type)
    if row.is_update:
        obj = await session.get(model, row.existing_id)
        if obj is None:
            raise ValueError(vanished_after_analysis(row.name, row.sheet))
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
        if key not in _NON_SCALAR_KEYS and key not in DATE_PAYLOAD_KEYS and key in columns:
            setattr(obj, key, value)
    # C3a D3: date slots are coordinates, never raw dates — they go to
    # the routed resolver (date columns under the preset, coordinate
    # columns plus a schema placeholder for the NOT NULL slot under a
    # custom calendar), not to setattr.
    route_insert_dates(obj, row.fields)

    if row.entity_type == "event" and row.fields.get("event_type"):
        # The relationship (not the raw FK) is assigned: the entity may
        # already sit in this session's identity map from the analysis,
        # and an expired-but-loaded ``event_type`` would stay stale there.
        obj.event_type = await _resolve_event_type(
            row.fields["event_type"], row, session, report, event_types,
        )

    if "image_id" in columns and row.fields.get("image"):
        image_id = await load_image_from_path(image_store, xlsx_dir, row.fields["image"])
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


async def _load_event_types(session: AsyncSession) -> dict[str, Any]:
    """World's event types by lower(name) + color/sort allocation state."""
    types = (await session.execute(select(EventTypeModel))).scalars().all()
    return {
        "by_name": {t.name.lower(): t for t in types},
        "used_colors": {t.color_index for t in types},
        "next_sort": max((t.sort_order for t in types), default=-1) + 1,
    }


async def _resolve_event_type(
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


async def apply_links_pass(
    plan: ImportPlan,
    session: AsyncSession,
    instances: dict[tuple[str, str], Any],
    report: ImportReport,
    tick: Callable[[], None],
    resolve_link_target: Callable[
        [PlannedLink, dict[tuple[str, str], Any], AsyncSession], Awaitable[Any]
    ],
) -> None:
    """Pass 2 (design D4): every planned link is ADDED through the ORM
    relationship of the source entity; existing edges are deduplicated,
    nothing is ever removed by an import (spec "Связи не отвязываются").

    Sources are entities that may have been flushed only seconds earlier,
    so their ``lazy="selectin"`` collections are not necessarily loaded —
    they are refreshed through an awaited load (``session.refresh``)
    before any synchronous mutation of them.

    ``resolve_link_target`` is the service's instance-bound seam (its
    failure is the test-driven way to exercise the all-or-nothing rollback),
    hence a parameter rather than a call into this module.
    """
    for row in ordered_rows(plan):
        attrs: list[str] = []
        pending: list[PlannedLink] = []
        for target_type, refs in row.links.items():
            if refs:
                attrs.append(entity_registry.collection(target_type))
                pending.extend(refs)
        if not pending:
            continue
        source = instances[row.key]
        await session.refresh(source, attribute_names=sorted(set(attrs)))

        collections: dict[str, list[Any]] = {}
        for ref in pending:
            tick()
            target = await resolve_link_target(ref, instances, session)
            if target is None:
                report.warnings.append(
                    f"Лист «{row.sheet}», строка {ref.source_row_number}: цель связи "
                    f"«{ref.name}» не найдена в базе — связь не установлена"
                )
                continue
            target_attr = entity_registry.collection(ref.target_type)
            collection = collections.setdefault(
                target_attr, getattr(source, target_attr),
            )
            if target.id in {obj.id for obj in collection}:
                continue  # already linked (existing or added via backref)
            collection.append(target)
            report.links += 1
    await session.flush()


async def load_image_from_path(image_store: ImageStore | None, base_dir: Path, cell_value: str) -> int | None:
    """Resolve path (relative to base_dir or absolute), ingest via ``ImageStore``.

    Returns the new ``image_id``, or None on any failure (missing file,
    unsupported extension, undecodable content, no store configured) —
    the caller turns that into a per-row warning (design D11).
    """
    if image_store is None:
        return None
    p = Path(cell_value.strip())
    if not p.is_absolute():
        p = (base_dir / p).resolve()
    if not p.exists() or not p.is_file():
        return None
    suffix = p.suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        return None
    try:
        data = p.read_bytes()
        return await image_store.store(data)
    except (OSError, ValueError):
        return None
