"""RED wiring tests for ``fix-silent-dialog-save-debt`` (spec save-error-reporting).

The four dialog save paths — create event, edit event, update entity card,
solo entity create from the «+» menu — must adopt the semantics the drag
path (``on_event_dates_moved``) already honors: the service rolls back, the
handler reloads what the success path would have shown, and the user sees
exactly ONE ``QMessageBox.critical`` whose text carries the failure reason.

The autouse ``message_boxes`` fixture (tests/ui/conftest.py) is the spy: it
replaces the modal-spinning ``QMessageBox`` statics with record-and-dismiss
stubs (offscreen-safe — no test here waits on a button press) and logs every
call as ``(kind, title, text)``. Fake services raise ``RuntimeError`` with a
distinct reason; each path asserts one critical, title «Ошибка», the
design-fixed prefix (D2) and the reason inside the text.

Successful-path coverage stays in the existing suites (test_e2e_events,
test_e2e_crud) — untouched here.
"""
from __future__ import annotations

from PySide6.QtCore import QDate

from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog

from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db

REASON = "disk is gone"
TITLE = "Ошибка"


def _critical_boxes(message_boxes) -> list[tuple[str, str, str]]:
    return [b for b in message_boxes if b[0] == "critical"]


def _assert_one_critical_with(message_boxes, prefix: str) -> None:
    crit = _critical_boxes(message_boxes)
    assert len(crit) == 1, f"exactly one critical expected, got {message_boxes}"
    _kind, title, text = crit[0]
    assert title == TITLE
    assert text.startswith(prefix), text
    assert REASON in text, f"the failure reason must be readable: {text}"


async def _fail(monkeypatch, owner, method_name: str):
    """Replace ``owner.method_name`` with a raiser of RuntimeError(REASON)."""

    async def boom(*args, **kwargs):
        raise RuntimeError(REASON)

    monkeypatch.setattr(owner, method_name, boom)


async def test_event_dialog_create_failure_shows_one_critical(
    app, wait_for, monkeypatch, message_boxes,
):
    """Create-event path (``on_saved``): the dialog save that never reached
    the DB must end in rollback + tape reload + exactly one modal, and must
    leave neither the timeline nor the DB with the doomed event."""
    application, window = app
    await _fail(monkeypatch, application._wiring._event_service,
                "create_event_with_relations")

    timeline_probe.click_object(window, "addButton")
    await wait_for(lambda: [d for d in window.findChildren(EventDialog) if d.isVisible()])
    dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    loaded = helpers.watch_available_entity_load(dialog)
    await wait_for(lambda: len(loaded) == 4)
    dialog.name_input.setText("Doomed Event")
    dialog.characteristics_input.setContent("обречено")
    dialog.start_date_input.setDate(QDate(1200, 1, 5))
    dialog.end_date_input.setDate(QDate(1200, 1, 6))
    assert dialog.save_button.isEnabled()
    dialog.save_button.click()
    await helpers.wait_until_settled()

    _assert_one_critical_with(message_boxes, "Не удалось сохранить событие")
    assert not helpers.has_event_named(window, "Doomed Event")
    assert query_db(
        application._db_path, "SELECT 1 FROM events WHERE name = 'Doomed Event'",
    ) == []


async def test_event_dialog_edit_failure_shows_one_critical(
    app, wait_for, monkeypatch, message_boxes,
):
    """Edit-event path (``on_event_updated``): a failed update keeps the DB
    row (and the tape) at the old values and reports exactly one modal."""
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, "Edit Fail",
        start_date=QDate(1200, 6, 1), end_date=QDate(1200, 6, 3),
    )
    helpers.double_click_timeline_event(window, "Edit Fail")
    await wait_for(lambda: [d for d in window.findChildren(EventDialog) if d.isVisible()])
    dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    await helpers.wait_until_settled()

    await _fail(monkeypatch, application._wiring._event_service,
                "update_event_with_relations")
    dialog.name_input.setText("Edit Fail Renamed")
    dialog.save_button.click()
    await helpers.wait_until_settled()

    _assert_one_critical_with(message_boxes, "Не удалось сохранить событие")
    rows = query_db(
        application._db_path, "SELECT name FROM events WHERE name LIKE 'Edit Fail%'",
    )
    assert [r[0] for r in rows] == ["Edit Fail"]  # old value survives
    assert helpers.has_event_named(window, "Edit Fail")
    assert not helpers.has_event_named(window, "Edit Fail Renamed")


async def test_entity_card_update_failure_shows_one_critical(
    app, wait_for, monkeypatch, menu_qmenu, message_boxes,
):
    """Entity-card update path (``on_entity_saved`` in ``on_entity_click``):
    a failed update keeps the DB row at the old name and reports the reason
    in exactly one modal («Не удалось сохранить сущность»)."""
    application, window = app
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "Old Name",
        characteristics="исходник",
    )
    await wait_for(lambda: query_db(
        application._db_path, "SELECT id FROM characters WHERE name = 'Old Name'",
    ))
    await helpers.wait_until_settled()
    entity_id = query_db(
        application._db_path, "SELECT id FROM characters WHERE name = 'Old Name'",
    )[0][0]

    # Detail-panel double-click seam: the panel entity_clicked signal is what
    # the wiring listens to for opening the entity card.
    window.detail_panel.entity_clicked.emit("character", entity_id)
    await wait_for(lambda: [
        d for d in window.findChildren(EntityCardDialog)
        if d.isVisible() and d.name_input.text() == "Old Name"
    ])
    card = next(
        d for d in window.findChildren(EntityCardDialog)
        if d.isVisible() and d.name_input.text() == "Old Name"
    )
    await helpers.wait_until_settled()

    await _fail(monkeypatch, application._get_entity_service("character"),
                "update_entity_with_relations")
    card.name_input.setText("New Name")
    card.save_button.click()
    await helpers.wait_until_settled()

    _assert_one_critical_with(message_boxes, "Не удалось сохранить сущность")
    assert query_db(
        application._db_path, "SELECT 1 FROM characters WHERE name = 'New Name'",
    ) == []
    assert query_db(
        application._db_path, "SELECT 1 FROM characters WHERE name = 'Old Name'",
    ) != []


async def test_solo_entity_create_failure_shows_one_critical(
    app, wait_for, monkeypatch, menu_qmenu, message_boxes,
):
    """Solo-create path (``on_entity_saved`` inside ``on_add_entity``): the
    currently silent bare ``except: rollback`` must report «Не удалось
    создать сущность» once, and the entity must not appear in the DB."""
    application, window = app
    await _fail(monkeypatch, application._get_entity_service("character"),
                "create_entity")

    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "Doomed Character",
        characteristics="не доживёт",
    )
    await helpers.wait_until_settled()

    _assert_one_critical_with(message_boxes, "Не удалось создать сущность")
    assert query_db(
        application._db_path,
        "SELECT 1 FROM characters WHERE name = 'Doomed Character'",
    ) == []
