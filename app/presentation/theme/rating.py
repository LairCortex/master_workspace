"""Theme-derived presentation colors shared by rating consumers."""
from __future__ import annotations

from PySide6.QtGui import QColor


def rating_to_color(rating: int, runtime=None) -> QColor:
    """Return the clamped 1..20 rating tint, or transparent off-skin."""
    t = max(0.0, min(1.0, (rating - 1) / 19.0))
    tokens = runtime.tokens if runtime is not None else None
    if not tokens:
        return QColor(0, 0, 0, 0)

    low = QColor(tokens.get("color.rating.low", {}).get(runtime.theme, ""))
    high = QColor(tokens.get("color.rating.high", {}).get(runtime.theme, ""))
    if not (low.isValid() and high.isValid()):
        return QColor(0, 0, 0, 0)

    return QColor(
        int(low.red() + t * (high.red() - low.red())),
        int(low.green() + t * (high.green() - low.green())),
        int(low.blue() + t * (high.blue() - low.blue())),
        int(80 + t * 140),
    )
