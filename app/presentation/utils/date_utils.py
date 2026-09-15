"""Date formatting utilities with custom month names support."""
from __future__ import annotations

import json
from datetime import date
from typing import Dict

# Default Russian month names (used when no custom mapping is set)
DEFAULT_MONTHS: Dict[int, str] = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}

# Shared mutable state — set once on game load, used everywhere
_current_months: Dict[int, str] = dict(DEFAULT_MONTHS)


def set_custom_months(months: Dict[int, str] | None) -> None:
    """Set custom month names for the current game session.

    Missing months fall back to defaults.
    """
    _current_months.clear()
    _current_months.update(DEFAULT_MONTHS)
    if months:
        _current_months.update(months)


def get_custom_months() -> Dict[int, str]:
    """Return current month name mapping."""
    return dict(_current_months)


def month_name(month: int) -> str:
    """Return the display name for a month number (1-12)."""
    return _current_months.get(month, str(month))


def format_game_date(
    d: date | None, fallback: str = "?", is_bc: bool | None = False
) -> str:
    """Format a date using custom month names: 'dd MonthName yyyy'.

    A date of the BC era (add-era-aware-dates, design D6) prints its year as
    'dd MonthName yyyy г. до н.э.'; our-era dates keep the previous format.
    An empty era (``None``) reads as «н.э.» — the open-end mark ``fallback``
    never carries an era either way.
    """
    if d is None:
        return fallback
    era = " г. до н.э." if is_bc else ""
    return f"{d.day:02d} {month_name(d.month)} {d.year}{era}"


def split_date_era(value: date | tuple[date, bool] | None) -> tuple[date | None, bool | None]:
    """Coerce a date-or-(date, era) value into a ``(date | None, era)`` pair.

    The bridges between popups and dialogs pass (date, is_bc) tuples, while a
    bare ``date`` stays a legal legacy input: it comes back with era ``None``
    («era not stated — keep whatever the receiver holds»). ``None`` is
    «no date» and reads as our era.
    """
    if value is None:
        return None, False
    if isinstance(value, tuple) and len(value) == 2:
        return value[0], bool(value[1])
    return value, None


def era_flag(value: object) -> bool:
    """Read an era flag stored on a row/dataclass (int 0/1 or bool).

    Anything that is not an int/bool (e.g. an attribute-less stand-in) is
    «н.э.» — the same default as the ``DEFAULT 0`` column of design D3.
    """
    return bool(value) if isinstance(value, (bool, int)) else False


# ── Serialization for DB storage ──────────────────────────────────────────

SETTINGS_KEY = "custom_months"


def months_to_json(months: Dict[int, str]) -> str:
    """Serialize month mapping to JSON for DB storage."""
    return json.dumps({str(k): v for k, v in months.items()}, ensure_ascii=False)


def months_from_json(raw: str | None) -> Dict[int, str] | None:
    """Deserialize month mapping from JSON. Returns None if no customization."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return {int(k): v for k, v in data.items()}
    except (json.JSONDecodeError, ValueError):
        return None
