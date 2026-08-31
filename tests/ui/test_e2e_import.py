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
    canvas = window.timeline_widget.rows_view
    await wait_for(lambda: len(canvas.events) == 2)
    names = [e.name for e in canvas.events]
    assert any("Взятие Штурмграда" in t for t in names)
    assert any("Поход каравана на восток" in t for t in names)

    # Imported records are found by search (results list)
    bar = window.search_bar
    bar.search_input.setText("караван")
    bar.search_button.click()
    await wait_for(lambda: any(
        "Поход каравана на восток" in bar.results_list.item(i).text()
        for i in range(bar.results_list.count())
    ))


async def test_xlsx_import_partial_errors_in_message(app, file_dialogs, wait_for, message_boxes, tmp_path):
    """Rows that fail validation are skipped and listed in the summary box."""
    import openpyxl

    application, window = app
    xlsx = tmp_path / "partial.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(("name", "start_date", "end_date", "characteristics", "backstory"))
    ws.append(("Событие", "1200-05-01", None, None, None))
    ws.append(("БезДаты", None, None, None, None))   # no start date → skip
    ws.append((None, None, None, None, None))        # empty name → skip
    wb.save(xlsx)

    file_dialogs["open"] = str(xlsx)
    window.import_events_action.trigger()
    await wait_for(lambda: bool(window.findChildren(XlsxImportDialog)))
    dialog = window.findChildren(XlsxImportDialog)[0]
    browse = next(b for b in dialog.findChildren(QPushButton) if "Обзор" in b.text())
    browse.click()
    dialog.import_btn.click()

    await wait_for(lambda: any(
        kind == "information" and "Импорт завершён" in title
        for kind, title, _ in message_boxes
    ))
    _title, text = next(
        (title, t) for kind, title, t in message_boxes
        if kind == "information" and "Импорт завершён" in title
    )
    assert "Создано записей: 1" in text
    assert "Некоторые строки пропущены" in text
    assert "пустое имя" in text
    assert "не задана дата начала" in text

    # Only the valid row made it to the timeline
    canvas = window.timeline_widget.rows_view
    await wait_for(lambda: len(canvas.events) == 1)

    # Dialog closed by the wiring's finally
    await wait_for(lambda: not dialog.isVisible())


async def test_xlsx_import_missing_file_shows_critical(app, file_dialogs, wait_for, message_boxes, tmp_path):
    """An unreadable path raises inside the service → the critical box."""
    application, window = app
    file_dialogs["open"] = str(tmp_path / "no-such-file.xlsx")
    window.import_events_action.trigger()
    await wait_for(lambda: bool(window.findChildren(XlsxImportDialog)))
    dialog = window.findChildren(XlsxImportDialog)[0]
    browse = next(b for b in dialog.findChildren(QPushButton) if "Обзор" in b.text())
    browse.click()
    dialog.import_btn.click()

    await wait_for(lambda: any(
        kind == "critical" and "Ошибка импорта" in title
        for kind, title, _ in message_boxes
    ))
    # Nothing imported, dialog closed by the wiring's finally
    await wait_for(lambda: not dialog.isVisible())
    assert len(window.timeline_widget.rows_view.events) == 0
