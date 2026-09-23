"""Wave Q14 (nri-0011, design D4): sheet dialogs run their flows as managed
tasks and finish the image ingest through the game's unit of work.

Pinned here:
* 4.1 — the image row lands in the DB the moment the ingest commits (a fresh
  session on the same engine sees it before any save), and a failed ingest
  rolls the row back through the unit (a flush without the surrounding
  transaction would stay visible on the shared session);
* 4.2 — a task still running when the dialog closes is cancelled, and an
  uncaught task error reaches the user as a visible message box.
"""
from __future__ import annotations

import asyncio

import pytest
from PySide6.QtWidgets import QMessageBox
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.enums.field_type import FieldType
from app.infrastructure.db.models import ImageModel
from app.infrastructure.images.store import ImageStore
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.views.character_sheet.editor_dialog import (
    CharacterSheetEditorDialog,
)
from app.presentation.views.character_sheet.fill_dialog import (
    CharacterSheetFillDialog,
)
from tests.application.test_table_host_service import _PNG_1PX


async def _image_count(session) -> int:
    return (
        await session.execute(select(func.count()).select_from(ImageModel))
    ).scalar()


async def _image_count_in_fresh_session(async_engine) -> int:
    """A real commit is only visible through a session nobody fed."""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as other:
        return (
            await other.execute(select(func.count()).select_from(ImageModel))
        ).scalar()


def _png_file(tmp_path) -> str:
    path = tmp_path / "ingest.png"
    path.write_bytes(_PNG_1PX)
    return str(path)


async def _make_editor(async_session, uow, tmp_path):
    store = ImageStore(async_session, tmp_path / "images")
    service = CharacterSheetService(
        CharacterSheetRepository(async_session), image_store=store
    )
    row = await service.create("Макет")
    dlg = CharacterSheetEditorDialog(service, row.id, image_store=store, uow=uow)
    await dlg.load()
    return dlg


async def _make_fill(async_session, uow, tmp_path):
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    image = template.add_field(FieldType.IMAGE, (10.0, 10.0))
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист", row.id)
    store = ImageStore(async_session, tmp_path / "images")
    dlg = CharacterSheetFillDialog(
        inst_svc, sheet_svc, inst.id, image_store=store, uow=uow
    )
    await dlg.load()
    return dlg, image.id


class _RowThenBoomStore:
    """Writes an ImageModel row through the shared session and then dies.

    Without the dialog's transaction the flushed row would stay pending on
    the session (the old "waits for someone else's commit" bug); with it the
    unit must retract the flush.
    """

    def __init__(self, session) -> None:
        self._session = session

    async def store(self, data: bytes) -> int:
        row = ImageModel(
            sha256="0" * 64, ext="png", width=1, height=1, size_bytes=len(data)
        )
        self._session.add(row)
        await self._session.flush()
        raise RuntimeError("ingest died mid-write")


# ── 4.1 — the ingest finishes through the unit of work ───────────────────────


async def test_editor_ingest_commits_the_image_row_immediately(
    qtbot, async_session, async_engine, uow, tmp_path, monkeypatch
):
    dlg = await _make_editor(async_session, uow, tmp_path)
    commits: list[int] = []
    real_commit = async_session.commit

    async def counting_commit():
        commits.append(1)
        return await real_commit()

    monkeypatch.setattr(async_session, "commit", counting_commit)
    try:
        fid = dlg.view_model.place(FieldType.IMAGE, 10.0, 10.0)
        await dlg._store_and_set_image(fid, _png_file(tmp_path))
        assert dlg.view_model.template.get_field(fid).image_id is not None
        # The ingest transaction itself finalized the row: exactly one commit,
        # issued by the store call (previously the row waited for some later,
        # unrelated commit of the shared session).
        assert len(commits) == 1
        # The sheet was NOT saved — yet a fresh session already sees the row.
        assert dlg.view_model.dirty is True
        assert await _image_count_in_fresh_session(async_engine) == 1
        # The field vanished behind the dialog (id absent from the template):
        # the ingest still finalizes through the unit (the dedup-hit returns
        # the same row id), only the sheet-side write is skipped.
        await dlg._store_and_set_image("ghost-field", _png_file(tmp_path))
        assert len(commits) == 2
        assert await _image_count_in_fresh_session(async_engine) == 1
    finally:
        dlg.force_close()
        dlg.deleteLater()
        qtbot.wait(1)


async def test_editor_ingest_failure_rolls_back_the_image_row(
    qtbot, async_session, uow, tmp_path
):
    dlg = await _make_editor(async_session, uow, tmp_path)
    dlg._image_store = _RowThenBoomStore(async_session)
    try:
        fid = dlg.view_model.place(FieldType.IMAGE, 10.0, 10.0)
        with pytest.raises(RuntimeError, match="ingest died mid-write"):
            await dlg._store_and_set_image(fid, _png_file(tmp_path))
        # The unit rolled the flushed row back; the session stayed usable and
        # the field kept no dangling id.
        assert await _image_count(async_session) == 0
        assert dlg.view_model.template.get_field(fid).image_id is None
    finally:
        dlg.force_close()
        dlg.deleteLater()
        qtbot.wait(1)


async def test_fill_ingest_commits_the_image_row_immediately(
    qtbot, async_session, async_engine, uow, tmp_path, monkeypatch
):
    dlg, image_fid = await _make_fill(async_session, uow, tmp_path)
    commits: list[int] = []
    real_commit = async_session.commit

    async def counting_commit():
        commits.append(1)
        return await real_commit()

    monkeypatch.setattr(async_session, "commit", counting_commit)
    try:
        await dlg._store_and_set_image(image_fid, _png_file(tmp_path))
        assert dlg.view_model.display_value(image_fid) is not None
        # The instance was never saved — the ingest transaction still
        # finalized the row on the spot (one commit, then durable).
        assert len(commits) == 1
        assert await _image_count_in_fresh_session(async_engine) == 1
    finally:
        dlg.force_close()
        dlg.deleteLater()
        qtbot.wait(1)


async def test_fill_ingest_failure_rolls_back_the_image_row(
    qtbot, async_session, uow, tmp_path
):
    dlg, image_fid = await _make_fill(async_session, uow, tmp_path)
    dlg._image_store = _RowThenBoomStore(async_session)
    try:
        with pytest.raises(RuntimeError, match="ingest died mid-write"):
            await dlg._store_and_set_image(image_fid, _png_file(tmp_path))
        assert await _image_count(async_session) == 0
        assert dlg.view_model.display_value(image_fid) is None
    finally:
        dlg.force_close()
        dlg.deleteLater()
        qtbot.wait(1)


# ── 4.2 — managed tasks: cancel on close, visible errors ─────────────────────


async def _await_settled(task: asyncio.Task) -> None:
    for _ in range(100):
        await asyncio.sleep(0.01)
        if task.done():
            return
    pytest.fail("the task never settled")


async def _explode_task(qtbot, monkeypatch, dlg, message: str) -> None:
    shown: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox, "critical",
        staticmethod(lambda *args, **k: shown.append(args)),
    )
    task = dlg._run_task(_boom(message))
    await _await_settled(task)
    assert task.done() and not task.cancelled()
    assert dlg._tasks == set()  # the done-callback released its bookkeeping
    assert len(shown) == 1, "the failure reached the user exactly once"
    assert any(message in str(arg) for arg in shown[0][1:])  # args past parent
    dlg.force_close()
    dlg.deleteLater()
    qtbot.wait(1)


async def _boom(message: str) -> None:
    raise RuntimeError(message)


async def test_editor_close_cancels_the_inflight_task(
    qtbot, async_session, uow, tmp_path
):
    dlg = await _make_editor(async_session, uow, tmp_path)
    started = asyncio.Event()

    async def never_finishes() -> None:
        started.set()
        await asyncio.sleep(30)

    task = dlg._run_task(never_finishes())
    await started.wait()
    assert task in dlg._tasks
    dlg.close()  # not dirty → the close goes through, cancelling the task
    await _await_settled(task)
    assert task.cancelled()
    assert dlg._tasks == set()
    dlg.deleteLater()
    qtbot.wait(1)


async def test_editor_task_error_is_surfaced_visibly(
    qtbot, async_session, uow, tmp_path, monkeypatch
):
    dlg = await _make_editor(async_session, uow, tmp_path)
    clean = dlg._run_task(asyncio.sleep(0))  # a clean task reports nothing
    await _await_settled(clean)
    assert dlg._tasks == set()
    await _explode_task(qtbot, monkeypatch, dlg, "задача упала")


async def test_fill_close_cancels_the_inflight_task(
    qtbot, async_session, uow, tmp_path
):
    dlg, _fid = await _make_fill(async_session, uow, tmp_path)
    started = asyncio.Event()

    async def never_finishes() -> None:
        started.set()
        await asyncio.sleep(30)

    task = dlg._run_task(never_finishes())
    await started.wait()
    assert task in dlg._tasks
    dlg.close()
    await _await_settled(task)
    assert task.cancelled()
    assert dlg._tasks == set()
    dlg.deleteLater()
    qtbot.wait(1)


async def test_fill_task_error_is_surfaced_visibly(
    qtbot, async_session, uow, tmp_path, monkeypatch
):
    dlg, _fid = await _make_fill(async_session, uow, tmp_path)
    await _explode_task(qtbot, monkeypatch, dlg, "задача листа упала")
