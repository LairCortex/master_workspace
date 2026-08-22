from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Description:
    characteristics: str = ""
    backstory: str = ""
    id: int | None = None
