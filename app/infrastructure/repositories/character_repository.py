"""Character repository."""
from __future__ import annotations


from app.infrastructure.db.models import CharacterModel
from app.infrastructure.repositories.base_repository import BaseRepository


class CharacterRepository(BaseRepository[CharacterModel]):
    def __init__(self, session) -> None:
        super().__init__(session, CharacterModel)
