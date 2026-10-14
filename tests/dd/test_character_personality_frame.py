"""The «Личность» tab of a character card, offscreen (dd-card-redesign task
5.3; spec dnd-character-mechanics «Вкладка „Личность“ — набор полей»).

Three families of fields, two storages (design Д6):

* **Предыстория** — the dataset LINK, the class link's mechanism restated:
  UNSET item, «имя · датасет» captions, the dead triple re-shown annotated
  with the fixed mark and carried verbatim in the item data;
* **Мировоззрение** — the fixed nine of the domain table plus «не задано»;
  the combo is the gate (manual input is structurally impossible), the
  service validates again;
* six short + eight long texts stored under the Russian captions in the
  existing ``text_blocks`` — the long ones commit on focus-out (Enter in a
  multi-line field writes a line break, not a save), the short ones on
  editingFinished; an untouched field losing focus is no transaction.

The frame does NOT reload after a write (the old tab's discipline: a reload
would trample in-flight typing); it remembers what it saved. Failure is one
modeless Russian box, a released tab answers nothing.
"""
from __future__ import annotations

import asyncio

from PySide6.QtCore import QEvent
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import (
    QComboBox,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QWidget,
)

from app.dd.application.dataset_index_service import DatasetEntry, IndexSnapshot
from app.dd.domain.character import (
    LINK_SLOTS,
    DdCharacterExt,
    ReferenceLink,
    empty_ext,
)
from app.dd.domain.character_mechanics import (
    ALIGNMENTS,
    PERSONALITY_LONG_FIELDS,
    PERSONALITY_SHORT_FIELDS,
    CharacterMechanics,
)
from app.dd.presentation.character_personality_frame import (
    ALIGNMENT_UNSET_ITEM,
    DndPersonalityTabFrame,
)
from app.dd.presentation.character_tab_frames import (
    SOURCE_UNAVAILABLE_NOTE,
    UNSET_ITEM,
)

RECORD_LABELS = {"dd_background": "Предыстория"}


async def _drain(times: int = 8) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


class _StubService:
    def __init__(
        self,
        ext=None,
        alignment: str | None = None,
        blocks: dict[str, str] | None = None,
        fail_load: bool = False,
        fail_write: bool = False,
    ) -> None:
        self.ext = ext if ext is not None else empty_ext()
        self.mechanics = CharacterMechanics(alignment=alignment)
        self.blocks = dict(blocks or {})
        self.fail_load = fail_load
        self.fail_write = fail_write
        self.asks: list[tuple] = []

    async def get_ext(self, character_id):
        self.asks.append(("get_ext", character_id))
        if self.fail_load:
            raise RuntimeError("диск отказал")
        return self.ext

    async def get_mechanics(self, character_id):
        if self.fail_load:
            raise RuntimeError("диск отказал")
        return self.mechanics

    async def get_text_blocks(self, character_id):
        if self.fail_load:
            raise RuntimeError("диск отказал")
        return dict(self.blocks)

    async def set_reference_link(self, character_id, slot, link):
        self.asks.append(("link", slot, link))
        if self.fail_write:
            raise RuntimeError("запись не прошла")

    async def set_alignment(self, character_id, alignment):
        self.asks.append(("alignment", alignment))
        if self.fail_write:
            raise RuntimeError("запись не прошла")

    async def set_text_block(self, character_id, key, text):
        self.asks.append(("block", key, text))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.blocks[key] = text


class _StubIndex:
    def __init__(self, snap: IndexSnapshot) -> None:
        self._snap = snap

    async def snapshot(self):
        return self._snap


def _backgrounds_snapshot() -> IndexSnapshot:
    return IndexSnapshot(
        ids=("srd",),
        titles={"srd": "SRD-5.1"},
        sections={
            "backgrounds": {
                "srd": (
                    DatasetEntry("srd", "acolyte", "Аколит", {}),
                    DatasetEntry("srd", "criminal", "Преступник", {}),
                )
            }
        },
        slugs={},
    )


def _ext_with_background(link: ReferenceLink) -> DdCharacterExt:
    links = {slot: ReferenceLink("", "", "") for slot, _s, _t in LINK_SLOTS}
    links["background"] = link
    return DdCharacterExt(links=links)


def _run_locked(coro):
    return asyncio.ensure_future(coro)


def _boxes(frame) -> list[QMessageBox]:
    return [box for box in frame.findChildren(QMessageBox) if not box.isHidden()]


async def _open(qtbot, service, snap=None) -> DndPersonalityTabFrame:
    frame = DndPersonalityTabFrame(
        character_id=7,
        service=service,
        dataset_index=_StubIndex(snap or _backgrounds_snapshot()),
        record_labels=RECORD_LABELS,
        run_locked=_run_locked,
    )
    qtbot.addWidget(frame)
    await _drain()
    return frame


# ── the field set the spec names ─────────────────────────────────────────────


async def test_the_tab_prints_the_named_field_family(qtbot):
    frame = await _open(qtbot, _StubService())
    background = frame.findChild(QComboBox, "ddPersonalityBackground")
    assert background.accessibleName() == "Предыстория"
    assert [
        background.itemText(i) for i in range(background.count())
    ] == [UNSET_ITEM, "Аколит · SRD-5.1", "Преступник · SRD-5.1"]
    alignment = frame.findChild(QComboBox, "ddPersonalityAlignment")
    assert alignment.accessibleName() == "Мировоззрение"
    # spec «Девять мировоззрений и „не задано“»: ровно 10 позиций, «не
    # задано» — отсутствие, не десятое мировоззрение; неотредактируемый
    # комбо = «ручного ввода нет».
    assert [alignment.itemText(i) for i in range(alignment.count())] == [
        ALIGNMENT_UNSET_ITEM, *ALIGNMENTS
    ]
    assert len(ALIGNMENTS) == 9
    assert not alignment.isEditable()
    for key, caption in PERSONALITY_SHORT_FIELDS:
        field = frame.findChild(QLineEdit, f"ddPersonalityShort_{key}")
        assert field is not None and field.accessibleName() == caption
    assert len(PERSONALITY_SHORT_FIELDS) == 6
    assert len(PERSONALITY_LONG_FIELDS) == 8


# ── the background LINK (the class link's mechanism restated) ───────────────


async def test_stored_background_is_selected_live(qtbot):
    service = _StubService(
        ext=_ext_with_background(ReferenceLink("srd", "acolyte", "Аколит"))
    )
    frame = await _open(qtbot, service)
    background = frame.findChild(QComboBox, "ddPersonalityBackground")
    assert background.currentData() == ("srd", "acolyte", "Аколит")
    assert background.currentText() == "Аколит · SRD-5.1"


async def test_dead_background_returns_annotated_and_verbatim(qtbot):
    # spec «Снял датасет — карточка не немеет» (link half): the stored triple
    # comes back under its snapshot + the mark, selected, its data intact.
    dead = ReferenceLink("removed-set", "x-9", "Забытая предыстория")
    service = _StubService(ext=_ext_with_background(dead))
    frame = await _open(qtbot, service)
    background = frame.findChild(QComboBox, "ddPersonalityBackground")
    assert background.currentData() == ("removed-set", "x-9", "Забытая предыстория")
    assert background.currentText() == f"Забытая предыстория — {SOURCE_UNAVAILABLE_NOTE}"
    assert service.asks == [("get_ext", 7)]  # loading never rewrites


async def test_background_choice_writes_the_link_and_unset_clears_it(qtbot):
    service = _StubService()
    frame = await _open(qtbot, service)
    background = frame.findChild(QComboBox, "ddPersonalityBackground")
    background.setCurrentIndex(2)  # «Преступник · SRD-5.1»
    await _drain()
    assert service.asks[-1] == (
        "link", "background", ReferenceLink("srd", "criminal", "Преступник"),
    )
    background.setCurrentIndex(0)  # «— не выбрано» clears the triple
    await _drain()
    assert service.asks[-1] == ("link", "background", ReferenceLink("", "", ""))


# ── alignment ────────────────────────────────────────────────────────────────


async def test_alignment_selection_writes_the_nine_or_the_absence(qtbot):
    service = _StubService(alignment="хаотично-добрый")
    frame = await _open(qtbot, service)
    alignment = frame.findChild(QComboBox, "ddPersonalityAlignment")
    assert alignment.currentIndex() == ALIGNMENTS.index("хаотично-добрый") + 1
    alignment.setCurrentIndex(0)  # «— не задано» writes the absence
    await _drain()
    assert service.asks[-1] == ("alignment", None)
    alignment.setCurrentIndex(1)  # «законно-добрый»
    await _drain()
    assert service.asks[-1] == ("alignment", "законно-добрый")


async def test_stored_garbage_alignment_reads_as_unset(qtbot):
    # a value the domain no longer recognises never paints a phantom item:
    # the combo falls back to the absence without rewriting anything.
    service = _StubService(alignment="демонический")
    frame = await _open(qtbot, service)
    assert frame.findChild(
        QComboBox, "ddPersonalityAlignment"
    ).currentIndex() == 0
    assert not any(ask[0] == "alignment" for ask in service.asks)


# ── the text fields (short on editingFinished, long on focus-out) ───────────


async def test_stored_blocks_print_into_their_fields(qtbot):
    service = _StubService(
        blocks={"Рост": "180 см", "Предыстория персонажа": "Сирота с улицы."}
    )
    frame = await _open(qtbot, service)
    assert frame.findChild(
        QLineEdit, "ddPersonalityShort_height"
    ).text() == "180 см"
    assert frame.findChild(
        QWidget, "ddPersonalityLong_backstory"
    ).toPlainText() == "Сирота с улицы."
    # ordinary text without value gates: nothing normalised away
    assert service.asks == [("get_ext", 7)]


async def test_short_field_commits_on_editing_finished_once(qtbot):
    service = _StubService()
    frame = await _open(qtbot, service)
    height = frame.findChild(QLineEdit, "ddPersonalityShort_height")
    height.setText("180 см")
    height.editingFinished.emit()
    await _drain()
    assert service.asks[-1] == ("block", "Рост", "180 см")
    height.editingFinished.emit()  # focus left an untouched field → no write
    await _drain()
    assert len([a for a in service.asks if a[0] == "block"]) == 1


async def test_long_field_commits_on_focus_out(qtbot):
    service = _StubService()
    frame = await _open(qtbot, service)
    editor = frame.findChild(QWidget, "ddPersonalityLong_traits")
    editor.setPlainText("Подозрителен ко всем.")
    # the multi-line commit trigger: focus leaving the field (Enter there
    # writes a line break, never a save)
    editor.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    await _drain()
    assert service.asks[-1] == ("block", "Черты характера", "Подозрителен ко всем.")
    editor.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))  # untouched → nothing
    await _drain()
    assert len([a for a in service.asks if a[0] == "block"]) == 1


async def test_fill_does_not_write(qtbot):
    # the guard under the fill: a commit landing while the frame publishes
    # stored values costs no transaction.
    service = _StubService(blocks={"Рост": "180 см"})
    frame = await _open(qtbot, service)
    frame._loading = True
    try:
        frame._commit("height", "другое")
    finally:
        frame._loading = False
    await _drain()
    assert not any(a[0] == "block" for a in service.asks)


# ── failure and release posture ──────────────────────────────────────────────


async def test_load_failure_is_one_modeless_box(qtbot):
    frame = await _open(qtbot, _StubService(fail_load=True))
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "Не удалось загрузить поля «Личности»" in boxes[0].text()
    boxes[0].button(QMessageBox.StandardButton.Ok).click()
    assert frame._notice_box is None


async def test_write_failure_keeps_the_field_and_tells_once(qtbot):
    service = _StubService(fail_write=True)
    frame = await _open(qtbot, service)
    assert _boxes(frame) == []
    height = frame.findChild(QLineEdit, "ddPersonalityShort_height")
    height.setText("180 см")
    height.editingFinished.emit()
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "Не удалось сохранить поле «Рост»" in boxes[0].text()
    # the value stays in the field (the reader repeats the change)
    assert height.text() == "180 см"


async def test_release_tab_cancels_in_flight_load_in_silence(qtbot):
    gate = asyncio.Event()

    class _SlowService(_StubService):
        async def get_ext(self, character_id):
            await gate.wait()
            return empty_ext()

    service = _SlowService()
    frame = await _open(qtbot, service)
    frame.release_tab()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert _boxes(frame) == []  # cancellation is silent
    gate.set()


# ── the fresh card (checkpoint-2 audit; spec «Новая карточка с пустыми
#    разделами») ─────────────────────────────────────────────────────────────


async def test_fresh_card_reads_nothing_and_refuses_every_write(qtbot):
    service = _StubService()
    frame = DndPersonalityTabFrame(
        character_id=None,
        service=service,
        dataset_index=_StubIndex(_backgrounds_snapshot()),
        record_labels=RECORD_LABELS,
        run_locked=_run_locked,
    )
    qtbot.addWidget(frame)
    await _drain()
    assert service.asks == []  # the unsaved face is painted, never read
    # The background combo stands with its «—» head; choosing a candidate
    # names the save and the widget goes back to the stored empty face.
    background = frame.findChild(QComboBox, "ddPersonalityBackground")
    background.setCurrentIndex(1)
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "не сохранён" in boxes[0].text()
    boxes[0].button(QMessageBox.StandardButton.Ok).click()
    assert background.currentIndex() == 0
    # The alignment gate refuses the same way and rolls back.
    alignment = frame.findChild(QComboBox, "ddPersonalityAlignment")
    alignment.setCurrentIndex(3)
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert alignment.currentIndex() == 0
    boxes[0].button(QMessageBox.StandardButton.Ok).click()
    # A typed short text is honestly refused, not silently swallowed: the
    # notice names the save and the field goes back to empty.
    height_key = PERSONALITY_SHORT_FIELDS[0][0]
    height = frame.findChild(QLineEdit, f"ddPersonalityShort_{height_key}")
    height.setText("180 см")
    height.editingFinished.emit()
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "не сохранён" in boxes[0].text()
    boxes[0].button(QMessageBox.StandardButton.Ok).click()
    assert height.text() == ""
    # The multi-line field commits through the focus-out half of the same
    # door: the typed paragraph is honestly refused and rolled back.
    bio_key = PERSONALITY_LONG_FIELDS[0][0]
    bio = frame.findChild(QPlainTextEdit, f"ddPersonalityLong_{bio_key}")
    bio.setPlainText("Спокойный практик")
    bio.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "не сохранён" in boxes[0].text()
    boxes[0].button(QMessageBox.StandardButton.Ok).click()
    assert bio.toPlainText() == ""
    assert service.asks == []  # four refusals, zero writes
