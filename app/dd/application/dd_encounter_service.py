"""Встреча: сервис надстройки события (add-dnd-game-face task 11.1; spec
dnd-encounters).

Одна дверь над ``dd_encounter``. Доменные ворота (монстр выбран, количество
в полосе) работают до открытия транзакции; каждая запись — одна транзакция
общего юнита игры (coding principle 3). «Пустой состав = нет встречи» —
правило этого сервиса: сохранение без строк состава удаляет строку надстройки
(если она была) и честно отвечает ``None`` — полувстречи в хранилище не
живёт. Удаления события каскадом убирают надстройку самой таблицей (FK
``ON DELETE CASCADE``).

Чтение — обычный select без транзакции, как у остальных сервисов модуля.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.dd.domain.encounter import (
    DdEncounter,
    EncounterEntry,
    normalize_entries,
    normalize_note,
)
from app.dd.infrastructure.db.dd_models import decode_composition, encode_composition
from app.dd.infrastructure.repositories.dd_encounter_repository import (
    DdEncounterRepository,
    encounter_to_domain,
)

if TYPE_CHECKING:
    from app.infrastructure.db.uow import GameSessionUoW


class DdEncounterService:
    """Read/write face of ``dd_encounter``."""

    def __init__(self, uow: "GameSessionUoW") -> None:
        self._uow = uow

    # ── reads (plain, no transaction) ────────────────────────────────────────

    async def get_encounter(self, event_id: int) -> DdEncounter | None:
        """Надстройка одного события; ``None`` — «встречи нет» (строки нет
        или её состав пуст: полувстречи не показываем)."""
        row = await DdEncounterRepository(self._uow.session).get_row(event_id)
        if row is None:
            return None
        encounter = encounter_to_domain(row)
        return encounter if encounter.entries else None

    async def encountered_event_ids(self) -> list[int]:
        """События с непустым составом — источник пометок лестницы читает
        эту выборку в свой кэш (``event_marks`` отвечает синхронно). Критерий
        — тот же, что у ``get_encounter``: строка считается встречей только
        с хоть одной читаемой строкой состава (пустой или неразбираемый
        состав — не встреча, «пустой состав = нет встречи»)."""
        repo = DdEncounterRepository(self._uow.session)
        return [
            row.event_id
            for row in await repo.list_rows()
            if decode_composition(row.composition)
        ]

    # ── writes (each one transaction) ────────────────────────────────────────

    async def save_encounter(
        self,
        event_id: int,
        entries: list[EncounterEntry],
        note: str,
    ) -> DdEncounter | None:
        """Записать состав и заметку — одна транзакция, один ответ. Пустой
        состав означает отсутствие встречи: строка надстройки удаляется (если
        была), ответ — ``None``. Непустой состав проходит ворота до
        транзакции; событие-владелец обязан существовать (FK, каскад
        убирает надстройку вместе с событием)."""
        clean_entries = normalize_entries(entries)
        clean_note = normalize_note(note)
        async with self._uow.transaction():
            repo = DdEncounterRepository(self._uow.session)
            row = await repo.get_row(event_id)
            if not clean_entries:
                if row is not None:
                    await repo.delete_row(row)
                return None
            if row is None:
                row = await repo.insert_row(event_id)
            row.composition = encode_composition(
                [
                    {
                        "monster_id": entry.monster_id,
                        "count": entry.count,
                        "name": entry.name_snapshot,
                    }
                    for entry in clean_entries
                ]
            )
            row.note = clean_note
            return encounter_to_domain(row)
