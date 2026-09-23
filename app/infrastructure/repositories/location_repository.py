"""Location repository — the dated table for LocationModel (factory alias, C4)."""
from __future__ import annotations

from app.infrastructure.db.models import LocationModel
from app.infrastructure.repositories.dated_repository import dated_repository

LocationRepository = dated_repository(LocationModel)
