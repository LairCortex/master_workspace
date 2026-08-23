"""E2E scenario 5: case-insensitive search across entities and events."""
from __future__ import annotations

from datetime import date



def _result_texts(bar) -> list[str]:
    return [bar.results_list.item(i).text() for i in range(bar.results_list.count())]


async def test_search_is_case_insensitive(app, wait_for):
    application, window = app

    # Seed: a character and an event with distinctive names.
    await application._entity_services["character"].create_entity(
        name="Архимаг Вельзариан",
        characteristics="Повелитель тайн",
        backstory="",
        start_date=date(1199, 1, 1),
        end_date=date(1199, 12, 31),
    )
    await application._session.commit()
    await application._entity_services["item"].create_entity(
        name="Меч Судьбы",
        characteristics="Клинок",
        backstory="",
        start_date=date(1199, 2, 1),
        end_date=date(1199, 12, 31),
    )
    await application._session.commit()

    bar = window.search_bar

    # Uppercase query finds the lowercase-stored character name.
    bar.search_input.setText("ВЕЛЬЗАРИАН")
    bar.search_button.click()
    await wait_for(lambda: any("Архимаг Вельзариан" in t for t in _result_texts(bar)))
    assert any("Персонажи" in t for t in _result_texts(bar))  # section header present

    # Mixed-case query finds an item.
    bar.search_input.setText("меч суд")
    bar.search_button.click()
    await wait_for(lambda: any("Меч Судьбы" in t for t in _result_texts(bar)))
