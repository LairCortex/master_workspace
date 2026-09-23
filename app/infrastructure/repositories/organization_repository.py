"""Organization repository — the dated table for OrganizationModel (factory alias, C4)."""
from __future__ import annotations

from app.infrastructure.db.models import OrganizationModel
from app.infrastructure.repositories.dated_repository import dated_repository

OrganizationRepository = dated_repository(OrganizationModel)
