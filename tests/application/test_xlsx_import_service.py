"""Tests for XlsxImportService."""
from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.application.services.xlsx_import_service import XlsxImportService


class DummyService:
    def __init__(self):
        self.created = []

    async def create_entity(self, **kwargs):
        self.created.append(kwargs)


class DummyEventService(DummyService):
    async def create_event(self, **kwargs):
        self.created.append(kwargs)


@pytest.mark.asyncio
async def test_import_events_tmpdir(tmp_path: Path):
    wb = Workbook()
    ws = wb.active
    ws.append(["name", "start_date", "end_date", "characteristics", "backstory"])
    ws.append(["Battle", date(1200, 1, 1), date(1200, 12, 31), "Big fight", "Ancient war"])
    path = tmp_path / "events.xlsx"
    wb.save(path)

    ev_svc = DummyEventService()
    char_svc = DummyService()
    loc_svc = DummyService()
    org_svc = DummyService()
    item_svc = DummyService()
    svc = XlsxImportService(ev_svc, char_svc, loc_svc, org_svc, item_svc)

    result = await svc.import_file("event", path)
    assert result.created == 1
    assert not result.errors
    assert len(ev_svc.created) == 1
    assert ev_svc.created[0]["name"] == "Battle"

