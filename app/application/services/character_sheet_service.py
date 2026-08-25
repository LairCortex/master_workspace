"""Character sheet service: CRUD + JSON project export/import.

Template = one `character_sheets` row; the whole page/field tree lives in
the `pages` JSON column (design D1). Field ids are stable uuid4-hex values
assigned once here (design D1/D3) — they become the PDF form-field names.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy.exc import IntegrityError

from app.domain.entities.character_sheet import SheetTemplate
from app.infrastructure.db.models import CharacterSheetModel
from app.infrastructure.repositories.character_sheet_repository import CharacterSheetRepository

#: Project-file format marker and version (spec «Экспорт проекта в JSON»).
CHARSHEET_FORMAT = "nri-charsheet"
CHARSHEET_FORMAT_VERSION = 1


class CharacterSheetNameConflict(Exception):
    """A template with this name already exists in the current game."""


class CharacterSheetImportError(Exception):
    """The file is not a valid character-sheet project; str() is the RU reason."""


class CharacterSheetService:
    def __init__(self, repo: CharacterSheetRepository) -> None:
        self._repo = repo

    # ── queries ───────────────────────────────────────────────────────────

    async def get_all(self) -> Sequence[CharacterSheetModel]:
        return await self._repo.get_all()

    async def load(self, sheet_id: int) -> SheetTemplate | None:
        """Load the domain template of a stored sheet (None if not found)."""
        row = await self._repo.get_by_id(sheet_id)
        if row is None:
            return None
        return SheetTemplate.from_dict({
            "name": row.name,
            "orientation": row.orientation,
            "pages": json.loads(row.pages),
        })

    # ── mutations ─────────────────────────────────────────────────────────

    async def create(self, template: SheetTemplate) -> CharacterSheetModel:
        existing = await self._repo.get_by_name(template.name)
        if existing is not None:
            raise CharacterSheetNameConflict(template.name)
        self._assign_field_ids(template)
        try:
            row = await self._repo.create(**_row_kwargs(template))
            await self._commit()
            return row
        except IntegrityError as exc:
            # Race guard: the name could have appeared between check and flush.
            await self._rollback()
            raise CharacterSheetNameConflict(template.name) from exc

    async def update(self, sheet_id: int, template: SheetTemplate) -> CharacterSheetModel | None:
        row = await self._repo.get_by_id(sheet_id)
        if row is None:
            return None
        if row.name != template.name:
            conflicting = await self._repo.get_by_name(template.name)
            if conflicting is not None and conflicting.id != sheet_id:
                raise CharacterSheetNameConflict(template.name)
        self._assign_field_ids(template)
        row.name = template.name
        row.orientation = template.orientation.value
        row.pages = _pages_json(template)
        row.updated_at = datetime.utcnow()
        await self._repo._session.flush()
        await self._commit()
        return row

    async def delete(self, sheet_id: int) -> bool:
        deleted = await self._repo.delete(sheet_id)
        if deleted:
            await self._commit()
        return deleted

    async def _commit(self) -> None:
        await self._repo._session.commit()

    async def _rollback(self) -> None:
        await self._repo._session.rollback()

    # ── JSON project export/import (spec «Экспорт/Импорт проекта») ───────

    @staticmethod
    def export_project(sheets: Sequence[SheetTemplate]) -> str:
        """Serialize templates (whole project or a single one) to project JSON."""
        return json.dumps(
            {
                "format": CHARSHEET_FORMAT,
                "version": CHARSHEET_FORMAT_VERSION,
                "sheets": [t.to_dict() for t in sheets],
            },
            ensure_ascii=False,
            indent=2,
        )

    @classmethod
    def parse_project(cls, data: str) -> list[SheetTemplate]:
        """Validate project JSON and return domain templates.

        Raises CharacterSheetImportError with the user-facing reason on any
        defect (bad JSON, unknown marker/version, wrong structure/types).
        """
        try:
            root = json.loads(data)
        except json.JSONDecodeError as exc:
            raise CharacterSheetImportError("файл не является корректным JSON") from exc
        if not isinstance(root, dict):
            raise CharacterSheetImportError("неверная структура файла")
        if root.get("format") != CHARSHEET_FORMAT:
            raise CharacterSheetImportError(
                "это не проект чар-листа (нет метки формата)"
            )
        version = root.get("version")
        if version != CHARSHEET_FORMAT_VERSION:
            raise CharacterSheetImportError(f"неподдерживаемая версия формата: {version!r}")
        raw_sheets = root.get("sheets")
        if not isinstance(raw_sheets, list):
            raise CharacterSheetImportError("раздел sheets должен быть списком")
        templates: list[SheetTemplate] = []
        for raw in raw_sheets:
            try:
                templates.append(SheetTemplate.from_dict(raw))
            except ValueError as exc:
                raise CharacterSheetImportError(str(exc)) from exc
        return templates

    async def import_project(self, data: str) -> list[CharacterSheetModel]:
        templates = self.parse_project(data)
        created: list[CharacterSheetModel] = []
        for template in templates:
            template.name = await self._resolve_name(template.name)
            self._assign_field_ids(template)
            created.append(await self._repo.create(**_row_kwargs(template)))
        await self._commit()
        return created

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _assign_field_ids(template: SheetTemplate) -> None:
        """Assign a stable uuid4-hex id to every field that has none.

        Ids are assigned once and never changed afterwards (design D3).
        """
        for page in template.pages:
            for f in page.fields:
                if not f.id:
                    f.id = uuid.uuid4().hex

    async def _resolve_name(self, name: str) -> str:
        """Free name for import: «X», «X (копия)», «X (копия 2)», …"""
        if await self._repo.get_by_name(name) is None:
            return name
        number = 1
        while True:
            candidate = f"{name} (копия)" if number == 1 else f"{name} (копия {number})"
            if await self._repo.get_by_name(candidate) is None:
                return candidate
            number += 1


def _pages_json(template: SheetTemplate) -> str:
    return json.dumps([p.to_dict() for p in template.pages], ensure_ascii=False)


def _row_kwargs(template: SheetTemplate) -> dict:
    return {
        "name": template.name,
        "orientation": template.orientation.value,
        "pages": _pages_json(template),
    }
