"""The connector's module-tab save hooks on the live wiring
(add-dnd-game-face task 11.1, design Д10, spec entity-card-tabs
«Сохранение карточки сохраняет и модульные табы»).

The kernel event half and the module tab half of one Save are one user
operation but two writers: the connector, INSIDE its locked edit-save task,
awaits the staged writes the dialog forwards (``EventDialog
.external_tab_saves`` ← ``CardTabHost.save_hooks``) after the kernel fields
were written and before the timeline reloads. This file pins the connector
side end to end on the real app (the host-side collection is pinned in
test_card_group_tabs, the frame's own door in tests/dd/test_encounter_frame):

* both hooks run, in tab order, before the ladder reload — the save is one
  operation and the ladder repaints once, after every writer finished;
* a hook that refuses does NOT erase the kernel half: the event row keeps
  its new values, the ladder already reloaded under the modal (the
  consistent-state posture of every other save handler), exactly one
  ``QMessageBox.critical`` carries the tab's reason, the saving state lifts
  and the dialog stays open for the fix;
* the CREATE flow never touches the hooks — a brand-new event has no
  module record to write, and the tabs (with their ids) only exist on the
  edit card (spec «у нового события модульного таба нет»).

The hooks are injected at the dialog's public forwarding door — that door
is exactly what the connector consumes, so the injection IS the contract
under test; the real encounter frame runs its own offscreen suite.
"""
from __future__ import annotations

from datetime import date

from app.domain.game_calendar import MonthDay
from app.presentation.views.event_dialog import EventDialog

from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db

REASON = "bestiary is gone"
TITLE = "Ошибка"
PREFIX = "Не удалось сохранить раздел модуля: "


def _visible_event_dialog(window) -> EventDialog:
    return next(
        d for d in window.findChildren(EventDialog) if d.isVisible()
    )


def _critical_boxes(message_boxes):
    return [b for b in message_boxes if b[0] == "critical"]


async def _open_editor(app, wait_for, monkeypatch, name: str, log: list):
    """Create the event, open its edit card, and instrument the connector:
    the returned dialog answers the forwarding door with staged hooks
    appending to ``log``; the ladder reload rides the same log."""
    application, window = app
    await helpers.create_event_via_ui(
        window, wait_for, name,
        start_date=date(1200, 6, 1), end_date=date(1200, 6, 3),
    )
    helpers.double_click_timeline_event(window, name)
    await wait_for(lambda: [d for d in window.findChildren(EventDialog)
                            if d.isVisible()])
    dialog = _visible_event_dialog(window)
    await helpers.wait_until_settled()

    wiring = application._wiring
    real_reload = wiring._reload_timeline

    async def spy_reload(*args, **kwargs):
        log.append("reload")
        return await real_reload(*args, **kwargs)

    monkeypatch.setattr(wiring, "_reload_timeline", spy_reload)
    return application, window, dialog


async def test_edit_save_runs_the_tab_hooks_in_order_before_the_reload(
    app, wait_for, monkeypatch, message_boxes,
):
    application, window, dialog = await _open_editor(
        app, wait_for, monkeypatch, "Hook Order", log := []
    )

    async def hook_first():
        log.append("tab:first")

    async def hook_second():
        log.append("tab:second")

    monkeypatch.setattr(dialog, "external_tab_saves", lambda: (hook_first, hook_second))
    dialog.name_input.setText("Hook Order Renamed")
    dialog.save_button.click()
    await helpers.wait_until_settled()

    assert log == ["tab:first", "tab:second", "reload"]
    assert _critical_boxes(message_boxes) == []
    rows = query_db(
        application._db_path, "SELECT name FROM events WHERE name LIKE 'Hook Order%'",
    )
    assert [r[0] for r in rows] == ["Hook Order Renamed"]
    assert helpers.has_event_named(window, "Hook Order Renamed")


async def test_a_refusing_tab_reports_one_critical_and_keeps_the_kernel_half(
    app, wait_for, monkeypatch, message_boxes,
):
    """The kernel field IS saved (the reload ran before the modal), the tab's
    Russian reason reaches the reader verbatim, the saving lock lifts and the
    dialog stays open — the event stays fixable without losing either half."""
    application, window, dialog = await _open_editor(
        app, wait_for, monkeypatch, "Hook Refusal", log := []
    )

    async def hook_ok():
        log.append("tab:ok")

    async def hook_boom():
        log.append("tab:boom")
        raise RuntimeError(REASON)

    monkeypatch.setattr(dialog, "external_tab_saves", lambda: (hook_ok, hook_boom))
    dialog.name_input.setText("Hook Refusal Renamed")
    dialog.save_button.click()
    await helpers.wait_until_settled()

    assert log == ["tab:ok", "tab:boom", "reload"]  # reload precedes the modal
    crit = _critical_boxes(message_boxes)
    assert len(crit) == 1, message_boxes
    _kind, title, text = crit[0]
    assert title == TITLE
    assert text.startswith(PREFIX) and REASON in text
    # The kernel half survived the tab's refusal; the ladder shows it.
    rows = query_db(
        application._db_path,
        "SELECT name FROM events WHERE name LIKE 'Hook Refusal%'",
    )
    assert [r[0] for r in rows] == ["Hook Refusal Renamed"]
    assert helpers.has_event_named(window, "Hook Refusal Renamed")
    # finish_saving(False): the saving state lifted, the card stays open.
    assert dialog.isVisible()
    assert not dialog._saving


async def test_the_create_flow_never_touches_the_hooks(
    app, wait_for, monkeypatch, message_boxes,
):
    """A new event has no module record: the tab strip (and with it every
    staged writer) only exists once the row has an id — the create branch of
    the save must not ask for the hooks at all."""
    _application, window = app
    timeline_probe.click_object(window, "addButton")
    await wait_for(lambda: [d for d in window.findChildren(EventDialog)
                            if d.isVisible()])
    dialog = _visible_event_dialog(window)
    loaded = helpers.watch_available_entity_load(dialog)
    await wait_for(lambda: len(loaded) == 4)
    calls: list[int] = []
    monkeypatch.setattr(
        dialog, "external_tab_saves",
        lambda: calls.append(1) or (),
    )
    dialog.name_input.setText("Created Plain")
    dialog.characteristics_input.setContent("обычное")
    dialog.vm.set_dates(start=MonthDay(1200, 6, 1), end=MonthDay(1200, 6, 3))
    assert dialog.save_button.isEnabled()
    dialog.save_button.click()
    # The helper's own posture: the ladder row arrives asynchronously.
    await wait_for(lambda: helpers.has_event_named(window, "Created Plain"))
    await helpers.wait_until_settled()
    assert calls == []
    assert _critical_boxes(message_boxes) == []
