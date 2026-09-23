"""Character repository — the dated table for CharacterModel (factory alias, C4)."""
from __future__ import annotations

from app.infrastructure.db.models import CharacterModel
from app.infrastructure.repositories.dated_repository import dated_repository

CharacterRepository = dated_repository(CharacterModel)
