"""Game export into a ``.nri`` archive (audit B2, task 6.3).

The Qt half of the flow stays in the composition root — save dialog and the
message boxes; the service owns the export mechanics: archive naming and the
call into the infrastructure packager.
"""
from __future__ import annotations

from pathlib import Path

from app.infrastructure.db.game_manager import export_game


class ExportService:
    """Export one game (a catalog directory holding its ``.db``) to ``.nri``."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    @property
    def game_name(self) -> str:
        """Catalog convention: the game name is the directory name."""
        return Path(self._db_path).parent.name

    def suggested_file_name(self) -> str:
        """Default save-dialog file name for this game."""
        return f"{self.game_name}.nri"

    def run_export(self, dest_path: str) -> None:
        """Pack the game into ``dest_path``; raises the packager's errors."""
        export_game(self._db_path, dest_path)
