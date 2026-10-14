"""The «Способности» tab of a character card, offscreen (dd-card-redesign
task 5.2; spec dnd-character-mechanics «Черты — ссылки на записи датасетов»).

A feat choice is a REFERENCE — the pair «source + id» plus the name
snapshot — never a text copy. What is pinned here:

* the chosen list prints each pair with its dataset origin, and a pair whose
  dataset went away keeps its stored snapshot under the дословная mark
  (spec «Датасет сняли — имена целы»);
* the candidate wall reads the ``feats`` section of the connected datasets,
  excludes the chosen pairs, filters by name and id, and is capped like the
  spells tab's;
* add and remove ride the module posture: one locked write + reload, a
  failed load or write is a single modeless Russian box, a released tab
  answers nothing.

The service/index doors are stubs — the storage floor belongs to the service
tests; what matters is which triple the frame hands out.
"""
from __future__ import annotations

import asyncio

from PySide6.QtWidgets import QLabel, QLineEdit, QMessageBox, QPushButton

from app.dd.application.dataset_index_service import DatasetEntry, IndexSnapshot
from app.dd.domain.character import DdFeatLink
from app.dd.presentation.character_feats_frame import DndFeatsTabFrame
from app.dd.presentation.character_tab_frames import SOURCE_UNAVAILABLE_NOTE


async def _drain(times: int = 8) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


class _StubService:
    def __init__(
        self,
        links: list[DdFeatLink] | None = None,
        fail_load: bool = False,
        fail_write: bool = False,
    ) -> None:
        self.links = list(links or [])
        self.fail_load = fail_load
        self.fail_write = fail_write
        self.asks: list[tuple] = []

    async def get_feat_links(self, character_id):
        self.asks.append(("get_feats", character_id))
        if self.fail_load:
            raise RuntimeError("диск отказал")
        return list(self.links)

    async def add_feat_link(self, character_id, link):
        self.asks.append(("add", link))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.links.append(link)

    async def remove_feat_link(self, character_id, source_key, ref_id):
        self.asks.append(("remove", source_key, ref_id))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.links = [
            link
            for link in self.links
            if (link.source_key, link.ref_id) != (source_key, ref_id)
        ]


class _StubIndex:
    def __init__(self, snap: IndexSnapshot) -> None:
        self._snap = snap

    async def snapshot(self):
        return self._snap


def _feats_snapshot() -> IndexSnapshot:
    return IndexSnapshot(
        ids=("srd",),
        titles={"srd": "SRD-5.1"},
        sections={
            "feats": {
                "srd": (
                    DatasetEntry("srd", "alert", "Alert", {}),
                    DatasetEntry("srd", "grappler", "Grappler", {}),
                )
            }
        },
        slugs={},
    )


def _run_locked(coro):
    return asyncio.ensure_future(coro)


def _boxes(frame) -> list[QMessageBox]:
    return [box for box in frame.findChildren(QMessageBox) if not box.isHidden()]


def _candidate_buttons(frame) -> list[QPushButton]:
    return frame.findChildren(QPushButton, "ddFeatsCandidate")


def _row_captions(frame) -> list[str]:
    return [label.text() for label in frame.findChildren(QLabel, "ddFeatsRowName")]


async def _open(qtbot, service, snap=None) -> DndFeatsTabFrame:
    frame = DndFeatsTabFrame(
        character_id=7,
        service=service,
        dataset_index=_StubIndex(snap or _feats_snapshot()),
        run_locked=_run_locked,
    )
    qtbot.addWidget(frame)
    await _drain()
    return frame


async def test_empty_tab_prints_the_hint_and_the_candidate_wall(qtbot):
    service = _StubService()
    frame = await _open(qtbot, service)
    assert frame.findChild(QLabel, "ddFeatsEmpty").text().startswith("Пока нет")
    assert [b.text() for b in _candidate_buttons(frame)] == [
        "Добавить: Alert · SRD-5.1",
        "Добавить: Grappler · SRD-5.1",
    ]
    # loading alone never writes: the read pair is the whole ledger
    assert service.asks == [("get_feats", 7)]


async def test_chosen_feats_print_with_origin_and_the_dead_pair_keeps_its_name(qtbot):
    # spec «Датасет сняли — имена целы»: the stored snapshot survives
    # verbatim, only the origin label dies into the fixed mark.
    service = _StubService(
        links=[
            DdFeatLink("srd", "alert", "Alert"),
            DdFeatLink("gone-set", "x-7", "Забытая черта"),
        ]
    )
    frame = await _open(qtbot, service)
    assert _row_captions(frame) == [
        "Alert · SRD-5.1",
        f"Забытая черта — {SOURCE_UNAVAILABLE_NOTE}",
    ]
    assert len(frame.findChildren(QPushButton, "ddFeatsRemove")) == 2
    # the chosen pair is gone from the wall (already-chosen exclusion)
    assert [b.text() for b in _candidate_buttons(frame)] == [
        "Добавить: Grappler · SRD-5.1",
    ]


async def test_candidate_wall_filters_by_name_and_id(qtbot):
    service = _StubService()
    frame = await _open(qtbot, service)
    frame.findChild(QLineEdit, "ddFeatsFilter").setText("GRAP")  # name, case-folded
    assert len(_candidate_buttons(frame)) == 1
    frame.findChild(QLineEdit, "ddFeatsFilter").setText("alert")  # id half
    assert [b.text() for b in _candidate_buttons(frame)] == [
        "Добавить: Alert · SRD-5.1",
    ]
    frame.findChild(QLineEdit, "ddFeatsFilter").setText("нет-такого")
    assert _candidate_buttons(frame) == []
    assert frame.findChild(QLabel, "ddFeatsNoCandidates") is not None


async def test_render_before_the_snapshot_lands_is_honest(qtbot):
    # The belt for the pre-read state: links and the dataset snapshot arrive
    # together in one locked read, but rendering can run while the snapshot
    # door has not answered (``_snap is None``). The honest answer is pinned
    # here: nobody can confirm a stored pair's origin, so every row prints
    # under the дословная mark, and the wall admits it has nothing to offer.
    service = _StubService(links=[DdFeatLink("srd", "alert", "Alert")])
    frame = await _open(qtbot, service)
    frame._snap = None
    frame._render()
    assert _row_captions(frame) == [f"Alert — {SOURCE_UNAVAILABLE_NOTE}"]
    assert _candidate_buttons(frame) == []
    assert frame.findChild(QLabel, "ddFeatsNoCandidates") is not None


async def test_candidate_wall_is_capped(qtbot):
    service = _StubService()
    frame = await _open(qtbot, service)
    big = IndexSnapshot(
        ids=("srd",),
        titles={"srd": "SRD"},
        sections={
            "feats": {
                "srd": tuple(
                    DatasetEntry("srd", f"feat-{i:03d}", f"Feat {i}", {})
                    for i in range(60)
                )
            }
        },
        slugs={},
    )
    frame._snap = big
    frame._render_candidates()
    assert len(_candidate_buttons(frame)) == 50
    cap = frame.findChild(QLabel, "ddFeatsCandidateCap")
    assert "Показаны первые 50" in cap.text() and "ещё 10" in cap.text()


async def test_add_click_stores_the_reference_and_reloads_in_one_wave(qtbot):
    service = _StubService()
    frame = await _open(qtbot, service)
    _candidate_buttons(frame)[0].click()  # «Alert · SRD-5.1»
    await _drain()
    # the frame hands out the full triple — source, id and the NAME SNAPSHOT
    # (spec: a reference, not a live query: the name is stored with it)
    assert service.asks == [
        ("get_feats", 7),
        ("add", DdFeatLink("srd", "alert", "Alert")),
        ("get_feats", 7),
    ]
    assert _row_captions(frame) == ["Alert · SRD-5.1"]


async def test_remove_click_unbinds_and_reloads(qtbot):
    service = _StubService(links=[DdFeatLink("srd", "alert", "Alert")])
    frame = await _open(qtbot, service)
    frame.findChildren(QPushButton, "ddFeatsRemove")[0].click()
    await _drain()
    assert service.asks == [
        ("get_feats", 7),
        ("remove", "srd", "alert"),
        ("get_feats", 7),
    ]
    assert frame.findChild(QLabel, "ddFeatsEmpty") is not None


async def test_load_failure_is_one_modeless_box(qtbot):
    frame = await _open(qtbot, _StubService(fail_load=True))
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "Не удалось загрузить выбранные черты" in boxes[0].text()
    boxes[0].button(QMessageBox.StandardButton.Ok).click()
    assert frame._notice_box is None


async def test_write_failure_is_one_modeless_box_and_the_tab_lives(qtbot):
    service = _StubService(fail_write=True)
    frame = await _open(qtbot, service)
    _candidate_buttons(frame)[0].click()
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "Не удалось выполнить действие" in boxes[0].text()
    assert "выбор черты" in boxes[0].text()


async def test_fresh_card_reads_nothing_and_refuses_writes(qtbot):
    # Checkpoint-2 audit (spec «Новая карточка с пустыми разделами»): the
    # empty id is the frame's None — the tab opens honestly empty, opens no
    # read task, and every write names the save instead of pretending.
    service = _StubService()
    frame = DndFeatsTabFrame(
        character_id=None,
        service=service,
        dataset_index=_StubIndex(_feats_snapshot()),
        run_locked=_run_locked,
    )
    qtbot.addWidget(frame)
    await _drain()
    assert service.asks == []  # nothing to read on an unsaved character
    assert frame.findChild(QLabel, "ddFeatsEmpty") is not None
    # the candidate wall still stands — but choosing one refuses
    buttons = _candidate_buttons(frame)
    assert buttons
    buttons[0].click()
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "не сохранён" in boxes[0].text()
    boxes[0].button(QMessageBox.StandardButton.Ok).click()
    assert service.asks == []  # the refusal cost no write


async def test_release_tab_cancels_in_flight_load_in_silence(qtbot):
    gate = asyncio.Event()

    class _SlowService(_StubService):
        async def get_feat_links(self, character_id):
            await gate.wait()
            return []

    service = _SlowService()
    frame = await _open(qtbot, service)
    frame.release_tab()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert _boxes(frame) == []  # cancellation is silent
    gate.set()


async def test_fresh_card_refuses_the_removal_of_a_link(qtbot):
    # The removal gate mirrors the add gate on the unsaved face: a link the
    # reader somehow reaches on a fresh card names the save instead of
    # reaching for a record that does not exist (checkpoint-2 lineage, spec
    # «Новая карточка с пустыми разделами»).
    service = _StubService()
    frame = DndFeatsTabFrame(
        character_id=None,
        service=service,
        dataset_index=_StubIndex(_feats_snapshot()),
        run_locked=_run_locked,
    )
    qtbot.addWidget(frame)
    await _drain()
    assert service.asks == []

    frame._on_remove(DdFeatLink("srd", "alert", "Alert"))
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "не сохранён" in boxes[0].text()
    boxes[0].button(QMessageBox.StandardButton.Ok).click()
    assert service.asks == []  # the refusal cost no write
