"""E2E scenario 7: XLSX import of events (file dialog stubbed, real import path)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QPushButton

from app.presentation.views.xlsx_import_dialog import XlsxImportDialog

FIXTURE_XLSX = Path(__file__).resolve().parent.parent / "fixtures" / "import_sample.xlsx"


async def test_xlsx_import_events_to_timeline(app, file_dialogs, wait_for):
    application, window = app

    file_dialogs["open"] = str(FIXTURE_XLSX)
    window.import_events_action.trigger()
    await wait_for(lambda: bool(window.findChildren(XlsxImportDialog)))
    dialog = window.findChildren(XlsxImportDialog)[0]

    # "Обзор…" → stubbed getOpenFileName returns the fixture path
    browse = next(b for b in dialog.findChildren(QPushButton) if "Обзор" in b.text())
    browse.click()
    assert dialog.path_edit.text() == str(FIXTURE_XLSX)

    dialog.import_btn.click()

    # Imported events appear on the timeline (async import + info box auto-accepted)
    timeline = window.timeline_widget.list_widget
    await wait_for(lambda: timeline.count() == 2)
    texts = [timeline.item(i).text() for i in range(timeline.count())]
    assert any("Взятие Штурмграда" in t for t in texts)
    assert any("Поход каравана на восток" in t for t in texts)

    # Imported records are found by search (results list)
    bar = window.search_bar
    bar.search_input.setText("караван")
    bar.search_button.click()
    await wait_for(lambda: any(
        "Поход каравана на восток" in bar.results_list.item(i).text()
        for i in range(bar.results_list.count())
    ))
