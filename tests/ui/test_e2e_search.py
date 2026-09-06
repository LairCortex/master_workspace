"""E2E scenario 5: case-insensitive search across entities and events."""
from __future__ import annotations

from datetime import date

from tests.presentation.qml_helpers import click_item, find_item


def _result_texts(bar) -> list[str]:
    return [row["text"] for row in bar._vm.rows]


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
    find_item(bar.quick, "searchInput").setProperty("text", "ВЕЛЬЗАРИАН")
    click_item(bar.quick, find_item(bar.quick, "searchButton"))
    await wait_for(lambda: any("Архимаг Вельзариан" in t for t in _result_texts(bar)))
    assert any("Персонажи" in t for t in _result_texts(bar))  # section header present

    # Mixed-case query finds an item.
    find_item(bar.quick, "searchInput").setProperty("text", "меч суд")
    click_item(bar.quick, find_item(bar.quick, "searchButton"))
    await wait_for(lambda: any("Меч Судьбы" in t for t in _result_texts(bar)))
