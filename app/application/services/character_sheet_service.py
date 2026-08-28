"""Character-sheet template service: CRUD, name uniqueness, layout round-trip.

Runs on the shared ``AsyncSession`` through the repository (same convention as
``EntityService``). The ORM row <-> domain ``SheetTemplate`` conversion happens
here, so presentation never parses ``pages`` JSON. Failures surface as
``CharacterSheetError`` subclasses the UI can map to user-facing messages.

Design D5:
- create: empty single-page layout, uniqueness checked before insert and
  again at the DB level (IntegrityError backstop -> NameConflictError).
- rename: commits immediately, touches only ``name`` (never ``pages``), so a
  rename is never treated as an unsaved layout edit.
- load: corrupt JSON -> CorruptSheetError, the row is never handed out as a
  template.

A-playable (design D3): create writes ``schema_version 2`` with one page
«Страница 1»; v1 rows load without loss and the next save writes v2; a field
type outside the closed catalog -> UnknownFieldTypeError (the sheet does not
open, the database is left untouched).

C (design D2/D4): ``create_from_preset`` inserts a bundled preset as a
snapshot — the same INSERT as ``create`` but with the preset's ready ``pages``
JSON copied as-is (stable field ids). After the copy the template is fully
independent: the bundle file is only ever read, and app updates never rewrite
an already-copied layout.
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy.exc import IntegrityError

from app.domain.entities.character_sheet import (
    EMPTY_PAGES_JSON,
    ORIENTATION_PORTRAIT,
    SCHEMA_VERSION,
    SheetTemplate,
    UnknownFieldTypeError as DomainUnknownFieldTypeError,
    iter_sheet_image_ids,
)
from app.infrastructure.db.models import CharacterSheetModel
from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.views.character_sheet.presets.catalog import PresetCatalog


class CharacterSheetError(Exception):
    """Base error for character-sheet operations."""


# User-facing error messages are Russian: ``str(exc)`` is shown as-is in the
# QMessageBoxes of the list dialog and the application wiring.

class SheetNotFoundError(CharacterSheetError):
    def __init__(self, sheet_id: int) -> None:
        super().__init__(f"Шаблон чар-листа {sheet_id} не найден")
        self.sheet_id = sheet_id


class NameConflictError(CharacterSheetError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Шаблон с именем «{name}» уже существует")
        self.name = name


class CorruptSheetError(CharacterSheetError):
    def __init__(self, sheet_id: int) -> None:
        super().__init__(f"Шаблон чар-листа {sheet_id} повреждён и не может быть открыт")
        self.sheet_id = sheet_id


class UnknownFieldTypeError(CharacterSheetError):
    """A stored field type is outside the catalog: the sheet must not open."""

    def __init__(self, sheet_id: int, type_value: object) -> None:
        super().__init__(
            f"Шаблон чар-листа {sheet_id} содержит неизвестный тип поля "
            f"«{type_value}» и не может быть открыт"
        )
        self.sheet_id = sheet_id
        self.type_value = type_value


EMPTY_NAME_ERROR: str = "Имя шаблона не может быть пустым"


class TemplateHasInstancesError(CharacterSheetError):
    def __init__(self, sheet_id: int) -> None:
        super().__init__(
            f"Шаблон чар-листа {sheet_id} нельзя удалить: на него ссылаются заполненные листы"
        )
        self.sheet_id = sheet_id


class PresetNotFoundError(CharacterSheetError):
    def __init__(self, preset_id: str) -> None:
        super().__init__(f"Пресет «{preset_id}» не найден")
        self.preset_id = preset_id


class PresetCorruptError(CharacterSheetError):
    def __init__(self, preset_id: str) -> None:
        super().__init__(
            f"Макет пресета «{preset_id}» повреждён и не может быть скопирован"
        )
        self.preset_id = preset_id


class PresetBundleError(CharacterSheetError):
    """A bundled preset file is missing from the installed application."""

    def __init__(self, preset_id: str) -> None:
        super().__init__(f"Файл пресета «{preset_id}» отсутствует в приложении")
        self.preset_id = preset_id


class CharacterSheetService:
    def __init__(
        self,
        repo: CharacterSheetRepository,
        image_store: ImageStore | None = None,
        instance_repo=None,
        preset_catalog: PresetCatalog | None = None,
    ) -> None:
        self._repo = repo
        self._session = repo._session
        self._image_store = image_store
        self._instance_repo = instance_repo
        self._preset_catalog = preset_catalog or PresetCatalog()

    # -- listing -----------------------------------------------------------

    async def list_sheets(self) -> Sequence[CharacterSheetModel]:
        """Rows (id, name, ...) of the sheets of the current game, name-sorted."""
        rows = await self._repo.get_all()
        return sorted(rows, key=lambda r: r.name)

    # -- create ------------------------------------------------------------

    async def create(self, name: str) -> CharacterSheetModel:
        """Create a sheet with one empty «Страница 1» page (schema_version 2)."""
        name = name.strip()
        if not name:
            raise ValueError(EMPTY_NAME_ERROR)
        if await self._repo.get_by_name(name) is not None:
            raise NameConflictError(name)
        try:
            row = await self._repo.create(
                name=name,
                schema_version=SCHEMA_VERSION,
                orientation=ORIENTATION_PORTRAIT,
                pages=EMPTY_PAGES_JSON,
            )
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise NameConflictError(name) from None
        return row

    async def create_from_preset(
        self, preset_id: str, name: str
    ) -> CharacterSheetModel:
        """Insert a bundle preset as a regular template snapshot (design D2/D4).

        Same name rules as ``create``: blank name -> ValueError, a taken name
        -> NameConflictError. The preset's ``pages`` JSON is copied as-is
        (stable field ids, no regeneration) with portrait orientation. After
        the INSERT the template is fully independent of the bundle: the
        bundle file is only ever read here, and later saves/deletes behave
        exactly like for any other template.
        """
        name = name.strip()
        if not name:
            raise ValueError(EMPTY_NAME_ERROR)
        try:
            preset = self._preset_catalog.get(preset_id)
        except KeyError:
            raise PresetNotFoundError(preset_id) from None
        try:
            pages_json = self._preset_catalog.load_pages(preset.id)
        except OSError:
            # A broken bundle (missing file) must not surface as a raw
            # FileNotFoundError to the user.
            raise PresetBundleError(preset.id) from None
        # A corrupt bundle layout must never reach the DB as a template.
        try:
            SheetTemplate.from_pages_json(
                pages_json,
                name=name,
                orientation=ORIENTATION_PORTRAIT,
                schema_version=SCHEMA_VERSION,
            )
        except ValueError as exc:
            raise PresetCorruptError(preset.id) from exc
        if await self._repo.get_by_name(name) is not None:
            raise NameConflictError(name)
        try:
            row = await self._repo.create(
                name=name,
                schema_version=SCHEMA_VERSION,
                orientation=ORIENTATION_PORTRAIT,
                pages=pages_json,
            )
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise NameConflictError(name) from None
        return row

    # -- load --------------------------------------------------------------

    async def load(self, sheet_id: int) -> SheetTemplate:
        """Load a template from the DB. Raises, never returns a corrupt layout.

        v1 rows load without loss; a field type outside the closed catalog
        raises ``UnknownFieldTypeError`` so the sheet is not opened (design D3).
        """
        row = await self._repo.get_by_id(sheet_id)
        if row is None:
            raise SheetNotFoundError(sheet_id)
        try:
            return SheetTemplate.from_pages_json(
                row.pages,
                name=row.name,
                orientation=row.orientation,
                schema_version=row.schema_version,
                id=row.id,
            )
        except DomainUnknownFieldTypeError as exc:
            raise UnknownFieldTypeError(sheet_id, exc.type_value) from exc
        except ValueError as exc:
            raise CorruptSheetError(sheet_id) from exc

    # -- layout ------------------------------------------------------------

    async def update_pages(self, sheet_id: int, template: SheetTemplate) -> CharacterSheetModel:
        """Persist the in-memory layout (always v2) and bump ``updated_at``.

        ``to_pages_json`` always emits the v2 shape, so saving an opened v1
        sheet promotes the stored ``schema_version`` to 2 (design D3). Image
        fields that lost their reference in the new layout are GC'd only
        after the reference change is committed (design D6).
        """
        row = await self._repo.get_by_id(sheet_id)
        if row is None:
            raise SheetNotFoundError(sheet_id)
        old_image_ids = set(iter_sheet_image_ids(row.pages))
        row.pages = template.to_pages_json()
        row.schema_version = SCHEMA_VERSION
        template.schema_version = SCHEMA_VERSION
        row.updated_at = datetime.utcnow()
        await self._session.commit()
        if self._image_store is not None:
            new_image_ids = set(iter_sheet_image_ids(row.pages))
            for image_id in old_image_ids - new_image_ids:
                await self._image_store.gc_after_commit(image_id)
        return row

    # -- rename -------------------------------------------------------------

    async def rename(self, sheet_id: int, new_name: str) -> CharacterSheetModel:
        """Rename immediately (name only; ``pages`` is untouched)."""
        new_name = new_name.strip()
        if not new_name:
            raise ValueError(EMPTY_NAME_ERROR)
        row = await self._repo.get_by_id(sheet_id)
        if row is None:
            raise SheetNotFoundError(sheet_id)
        existing = await self._repo.get_by_name(new_name)
        if existing is not None and existing.id != sheet_id:
            raise NameConflictError(new_name)
        row.name = new_name
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise NameConflictError(new_name) from None
        return row

    # -- delete ------------------------------------------------------------

    async def delete(self, sheet_id: int) -> bool:
        """Delete a template, then GC its image fields (design D6).

        A template with filled instances cannot be deleted (RESTRICT + explicit
        count check). The row deletion commits first; files are removed only
        after that and only if no other referrer still holds them.
        """
        row = await self._repo.get_by_id(sheet_id)
        if row is None:
            return False
        if self._instance_repo is not None:
            if await self._instance_repo.count_by_template(sheet_id) > 0:
                raise TemplateHasInstancesError(sheet_id)
        image_ids = iter_sheet_image_ids(row.pages)
        try:
            deleted = await self._repo.delete(sheet_id)
        except IntegrityError:
            await self._session.rollback()
            raise TemplateHasInstancesError(sheet_id) from None
        if deleted:
            await self._session.commit()
            if self._image_store is not None:
                for image_id in set(image_ids):
                    await self._image_store.gc_after_commit(image_id)
        return deleted
