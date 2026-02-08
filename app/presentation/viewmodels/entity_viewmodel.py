"""Entity ViewModel — generic CRUD for any entity card."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal


class EntityViewModel(QObject):
    entity_changed = Signal()

    def __init__(self, entity_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entity_service = entity_service
        self.entity: Any | None = None

    async def load(self, entity_id: int) -> None:
        self.entity = await self._entity_service.get_entity(entity_id)
        self.entity_changed.emit()

    async def save(self, **kwargs: Any) -> Any | None:
        if self.entity is None:
            return None
        result = await self._entity_service.update_entity(self.entity.id, **kwargs)
        self.entity = result
        self.entity_changed.emit()
        return result

    async def delete(self) -> bool:
        if self.entity is None:
            return False
        result = await self._entity_service.delete_entity(self.entity.id)
        if result:
            self.entity = None
            self.entity_changed.emit()
        return result
