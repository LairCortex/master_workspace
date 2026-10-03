"""NRI-0025 task 6.2 grep-pin: ``EventService.get_last_event_for_entity`` is
dead code and stays dead (design Д7 — its only consumer was the search's
full path, abolished by task 6.1; the delta of spec `global-search` leaves no
gesture that could ever want «the entity's latest-by-start event» again).

The law: no ``app/`` source mentions the identifier at all — neither the
method's definition (its tests were deleted together with it) nor any call.
A revived need must go through a fresh change, not a silent paste. Scan and
planted-violation self-check follow the repo's grep-pin law (precedent
``tests/presentation/test_entity_icons.py``: the scanner must bite on a
hypothetical violation, not pass vacuously)."""
from __future__ import annotations

from pathlib import Path

import app

APP_DIR = Path(app.__file__).resolve().parent
FORBIDDEN = "get_last_event_for_entity"


def _offenders(source: str) -> list[int]:
    """Line numbers of the source lines quoting the forbidden identifier."""
    return [
        lineno
        for lineno, line in enumerate(source.splitlines(), start=1)
        if FORBIDDEN in line
    ]


def test_scanner_bites_on_a_planted_call():
    # Self-check: a call OR a re-definition must both be reported.
    assert _offenders(
        "target = await self._event_service.get_last_event_for_entity(t, i)"
    ) == [1]
    assert _offenders(f"    async def {FORBIDDEN}(self, entity_type):") == [1]


def test_no_app_source_mentions_the_dead_lookup():
    files = sorted(p for p in APP_DIR.rglob("*.py") if "__pycache__" not in p.parts)
    assert files, f"scan root is broken: {APP_DIR}"
    offenders = []
    for path in files:
        for lineno in _offenders(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(APP_DIR.parent)}:{lineno}")
    assert offenders == [], (
        "полный путь поиска через событие упразднён (nri-0025, design Д7): "
        "get_last_event_for_entity удалён и не должен возвращаться — "
        "обращения найдены в " + ", ".join(offenders)
    )
