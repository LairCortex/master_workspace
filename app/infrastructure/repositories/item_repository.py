"""Item repository — the dated table for ItemModel (factory alias, C4)."""
from __future__ import annotations

from app.infrastructure.db.models import ItemModel
from app.infrastructure.repositories.dated_repository import dated_repository

ItemRepository = dated_repository(ItemModel)
