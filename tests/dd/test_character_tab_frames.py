"""The two module tabs of a character card, offscreen (add-dnd-game-face
tasks 8.2/8.3).

The frames are the module's half of the card; the kernel host (task 7.2) is
tested apart. What is pinned here is the contract the reader gets:

* the «D&D» tab: five pickers built from the connected index with the stored
  triple selected — a stored link whose source was disconnected comes back
  as its snapshot under the «источник не подключён» mark, visible and
  re-savable verbatim (spec «Снял чекбокs — карточка не немеет»);
* every field writes on its own change through the injected ``run_locked``,
  the level is the combo's own 1…20 shape, the «Открыть в браузере» button
  follows the id's keystrokes and hands the digital LSS address out;
* the «Заклинания» tab: bindings print their origin through the two read
  doors (SRD slugs, then grimoires), add and remove reload inside the one
  locked coroutine, the candidate list is filterable and capped;
* failure posture: a failed load or write is one modeless Russian box, the
* release posture: ``release_tab`` cancels the in-flight work in silence.

The service/index/grimoire doors are stubs — the storage floor belongs to
``test_character_extension.py``; what matters here is which triple the frame
hands out and what the reader can see.
"""
from __future__ import annotations

import asyncio

from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QMessageBox, QPushButton

from app.dd.application.dataset_index_service import DatasetEntry, IndexSnapshot
from app.dd.application.grimoire_index_service import GrimoireIndexSnapshot
from app.dd.domain.character import (
    LINK_SLOTS,
    DdCharacterExt,
    DdSpellLink,
    ReferenceLink,
    empty_ext,
)
from app.dd.presentation import character_tab_frames as frames
from app.dd.presentation.character_tab_frames import (
    SOURCE_UNAVAILABLE_NOTE,
    UNSET_ITEM,
    DndCharacterTabFrame,
    DndSpellsTabFrame,
    lss_sheet_url,
)


async def _drain(times: int = 8) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


class _StubService:
    """The service door as the frames see it: canned answers, recorded asks."""

    def __init__(
        self,
        ext: DdCharacterExt | None = None,
        links: list[DdSpellLink] | None = None,
        fail_load: bool = False,
        fail_write: bool = False,
    ) -> None:
        self.ext = ext if ext is not None else empty_ext()
        self.links = list(links or [])
        self.fail_load = fail_load
        self.fail_write = fail_write
        self.asks: list[tuple] = []

    async def get_ext(self, character_id):
        self.asks.append(("get_ext", character_id))
        if self.fail_load:
            raise RuntimeError("диск отказал")
        return self.ext

    async def set_reference_link(self, character_id, slot, link):
        self.asks.append(("link", slot, link))
        if self.fail_write:
            raise RuntimeError("запись не прошла")

    async def set_level(self, character_id, level):
        self.asks.append(("level", level))
        if self.fail_write:
            raise RuntimeError("запись не прошла")

    async def set_lss_sheet_id(self, character_id, sheet_id):
        self.asks.append(("sheet", sheet_id))
        if self.fail_write:
            raise RuntimeError("запись не прошла")

    async def get_spell_links(self, character_id):
        self.asks.append(("get_links", character_id))
        if self.fail_load:
            raise RuntimeError("диск отказал")
        return list(self.links)

    async def add_spell_link(self, character_id, link):
        self.asks.append(("add", link))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.links.append(link)

    async def remove_spell_link(self, character_id, source_key, slug):
        self.asks.append(("remove", source_key, slug))
        if self.fail_write:
            raise RuntimeError("запись не прошла")
        self.links = [
            link
            for link in self.links
            if (link.source_key, link.slug) != (source_key, slug)
        ]


class _StubIndex:
    def __init__(self, snap: IndexSnapshot) -> None:
        self._snap = snap

    async def snapshot(self):
        return self._snap


def _snapshot_with_entries() -> IndexSnapshot:
    """One connected set with two races; the spell-slug half is populated
    for the spells tab's SRD door."""
    return IndexSnapshot(
        ids=("srd",),
        titles={"srd": "SRD-5.1"},
        sections={
            "races": {
                "srd": (
                    DatasetEntry("srd", "dwarf", "Дворф", {}),
                    DatasetEntry("srd", "elf", "Эльф", {}),
                )
            }
        },
        slugs={"srd": ("fire-bolt", "mage-hand")},
    )


def _grimoire_snapshot() -> GrimoireIndexSnapshot:
    from app.dd.domain.grimoire import GrimoireSpell

    return GrimoireIndexSnapshot(
        ids=("grim",),
        titles={"grim": "Гримуар А"},
        spells={
            "grim": {"witch-sight": GrimoireSpell("witch-sight", "Ведьмин глаз", "…")}
        },
    )


def _run_locked(coro):
    return asyncio.ensure_future(coro)


def _boxes(frame) -> list[QMessageBox]:
    # The frame itself stays hidden offscreen; ``isHidden`` reads the box's
    # own explicit hide — a shown modeless box answers False.
    return [box for box in frame.findChildren(QMessageBox) if not box.isHidden()]


# ── the LSS door ──────────────────────────────────────────────────────────


def test_lss_sheet_url_trims_and_fills_the_digital_page():
    assert (
        lss_sheet_url(" abc123 ")
        == "https://longstoryshort.app/iframe/characters/digital/abc123/"
    )


def test_source_unavailable_note_is_the_single_fixed_wording():
    """fix-dnd-followups 4.2 (spec dnd-character-extension «Снятый датасет не
    калечит карточку» / dnd-reference-records): пометка недоступного источника
    — дословно «источник не подключён». Ровно одно сравнение с литералом;
    обе поверхности модуля, печатающие запись с недоступным источником (пики
    таба «D&D» и строки таба «Заклинаний» — остальные справочные поверхности
    по построению недоступных записей не показывают), несут ЭТУ константу:
    их пины ниже сравнивают текст строки с константой, цепочка
    «поверхность = константа = литерал» замкнута."""
    assert SOURCE_UNAVAILABLE_NOTE == "источник не подключён"


# ── the «D&D» tab ─────────────────────────────────────────────────────────


async def _open_dnd_tab(qtbot, service, snap=None) -> DndCharacterTabFrame:
    frame = DndCharacterTabFrame(
        character_id=7,
        service=service,
        dataset_index=_StubIndex(snap or _snapshot_with_entries()),
        record_labels={key: key for key, _s, _t in LINK_SLOTS} | {
            "dd_race": "Вид", "dd_subrace": "Подвид", "dd_class": "Класс",
            "dd_subclass": "Подкласс", "dd_background": "Предыстория",
        },
        run_locked=_run_locked,
    )
    qtbot.addWidget(frame)
    await _drain()
    return frame


async def test_dnd_tab_opens_empty_and_builds_pickers_from_the_index(qtbot):
    service = _StubService()
    frame = await _open_dnd_tab(qtbot, service)
    race = frame.findChild(QComboBox, "ddDndSlot_race")
    captions = [race.itemText(i) for i in range(race.count())]
    assert captions == [UNSET_ITEM, "Дворф · SRD-5.1", "Эльф · SRD-5.1"]
    assert race.currentIndex() == 0
    assert race.currentData() is None
    # Пять пиков + уровень + лист — captions via accessibleName (штатно).
    for slot in ("subrace", "class", "subclass", "background"):
        assert frame.findChild(QComboBox, f"ddDndSlot_{slot}") is not None
    assert race.accessibleName() == "Вид"
    level = frame.findChild(QComboBox, "ddDndLevel")
    # fix-dnd-followups 4.1 (spec dnd-character-extension «Уровень вне полосы
    # недоступен»): выбор состоит ровно из «не задан» и целых 1…20 — список
    # запинен целиков (0, 21 и дробное в нём отсутствуют), неотредактируемый
    # комбо не даёт и ввести что-то мимо списка.
    assert [level.itemText(i) for i in range(level.count())] == [
        UNSET_ITEM, *[str(value) for value in range(1, 21)]
    ]
    assert not level.isEditable()
    assert frame.findChild(QLineEdit, "ddDndSheetId").text() == ""
    # loading alone never writes: the single ask is the read.
    assert service.asks == [("get_ext", 7)]


async def test_dnd_tab_selects_a_live_link_and_the_stored_level(qtbot):
    ext = DdCharacterExt(
        links={
            slot: ReferenceLink("", "", "") for slot, _s, _t in LINK_SLOTS
        }
        | {"race": ReferenceLink("srd", "elf", "Эльф")},
        level=7,
        lss_sheet_id="abc",
    )
    service = _StubService(ext=ext)
    frame = await _open_dnd_tab(qtbot, service)
    race = frame.findChild(QComboBox, "ddDndSlot_race")
    assert race.currentData() == ("srd", "elf", "Эльф")
    assert race.currentText() == "Эльф · SRD-5.1"
    assert frame.findChild(QComboBox, "ddDndLevel").currentIndex() == 7
    sheet = frame.findChild(QLineEdit, "ddDndSheetId")
    assert sheet.text() == "abc"
    # isHidden reads the frame's own show/hide decision; isVisible would also
    # answer False just because the offscreen frame itself is never shown.
    assert not frame.findChild(QPushButton, "ddDndSheetOpen").isHidden()


async def test_dead_source_link_returns_annotated_and_re_savable(qtbot):
    # spec «Снял чекбокс — карточка не немеет»: the stored triple comes back
    # under its snapshot + the mark, selected — and touching ANOTHER field
    # rewrites nothing.
    dead = ReferenceLink("removed-set", "x-42", "Забытая раса")
    ext = DdCharacterExt(
        links={slot: ReferenceLink("", "", "") for slot, _s, _t in LINK_SLOTS}
        | {"race": dead},
    )
    service = _StubService(ext=ext)
    frame = await _open_dnd_tab(qtbot, service)
    race = frame.findChild(QComboBox, "ddDndSlot_race")
    assert race.currentData() == ("removed-set", "x-42", "Забытая раса")
    assert race.currentText() == f"Забытая раса — {SOURCE_UNAVAILABLE_NOTE}"
    assert service.asks == [("get_ext", 7)]  # loading never rewrites

    # The annotated item is re-savable verbatim: re-choosing it (via the
    # other slots' shape — here by direct data) hands the same triple out.
    level = frame.findChild(QComboBox, "ddDndLevel")
    level.setCurrentIndex(3)
    await _drain()
    assert service.asks == [("get_ext", 7), ("level", 3)]


async def test_dnd_tab_writes_each_field_on_its_own_change(qtbot):
    service = _StubService()
    frame = await _open_dnd_tab(qtbot, service)
    race = frame.findChild(QComboBox, "ddDndSlot_race")
    race.setCurrentIndex(1)  # «Дворф · SRD-5.1»
    await _drain()
    assert service.asks[-1] == ("link", "race", ReferenceLink("srd", "dwarf", "Дворф"))
    race.setCurrentIndex(0)  # «— не выбрано» clears the triple
    await _drain()
    assert service.asks[-1] == ("link", "race", ReferenceLink("", "", ""))

    frame.findChild(QComboBox, "ddDndLevel").setCurrentIndex(20)
    await _drain()
    assert service.asks[-1] == ("level", 20)
    frame.findChild(QComboBox, "ddDndLevel").setCurrentIndex(0)
    await _drain()
    assert service.asks[-1] == ("level", None)


async def test_dnd_tab_sheet_field_writes_once_on_editing_finished(qtbot):
    service = _StubService()
    frame = await _open_dnd_tab(qtbot, service)
    sheet = frame.findChild(QLineEdit, "ddDndSheetId")
    open_button = frame.findChild(QPushButton, "ddDndSheetOpen")
    assert open_button.isHidden()  # spec: empty id hides the button

    sheet.setText("abc")  # keystrokes drive the visibility, not the write
    assert not open_button.isHidden()
    assert not any(ask[0] == "sheet" for ask in service.asks)

    sheet.editingFinished.emit()  # focus leaves a changed field → one write
    await _drain()
    assert [ask for ask in service.asks if ask[0] == "sheet"] == [("sheet", "abc")]

    sheet.editingFinished.emit()  # an untouched field costs no transaction
    await _drain()
    assert len([ask for ask in service.asks if ask[0] == "sheet"]) == 1

    sheet.setText("")
    assert open_button.isHidden()
    sheet.editingFinished.emit()
    await _drain()
    assert [ask for ask in service.asks if ask[0] == "sheet"][-1] == ("sheet", "")


async def test_dnd_tab_open_button_hands_the_digital_address_out(qtbot, monkeypatch):
    seen: list[str] = []

    class _Desktop:
        @staticmethod
        def openUrl(url):
            seen.append(url.toString())
            return True

    monkeypatch.setattr(frames, "QDesktopServices", _Desktop)
    service = _StubService(ext=DdCharacterExt(
        links={slot: ReferenceLink("", "", "") for slot, _s, _t in LINK_SLOTS},
        lss_sheet_id="abc",
    ))
    frame = await _open_dnd_tab(qtbot, service)
    frame.findChild(QPushButton, "ddDndSheetOpen").click()
    assert seen == [
        "https://longstoryshort.app/iframe/characters/digital/abc/"
    ]


async def test_dnd_tab_load_failure_is_one_modeless_box(qtbot):
    service = _StubService(fail_load=True)
    frame = await _open_dnd_tab(qtbot, service)
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "Не удалось загрузить D&D-поля" in boxes[0].text()
    boxes[0].button(QMessageBox.StandardButton.Ok).click()
    assert frame._notice_box is None


async def test_dnd_tab_write_failure_keeps_the_field_and_tells_once(qtbot):
    service = _StubService(fail_write=True)
    frame = await _open_dnd_tab(qtbot, service)
    assert _boxes(frame) == []  # the load itself succeeded

    frame.findChild(QComboBox, "ddDndLevel").setCurrentIndex(5)
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "Не удалось сохранить поле «уровень»" in boxes[0].text()
    # the value stays in the field (the reader repeats the change)
    assert frame.findChild(QComboBox, "ddDndLevel").currentIndex() == 5


async def test_release_tab_cancels_in_flight_load_in_silence(qtbot):
    gate = asyncio.Event()

    class _SlowService(_StubService):
        async def get_ext(self, character_id):
            await gate.wait()
            return empty_ext()

        async def get_spell_links(self, character_id):
            await gate.wait()
            return []

    for factory in (DndCharacterTabFrame, DndSpellsTabFrame):
        service = _SlowService()
        kwargs = {
            "character_id": 7,
            "service": service,
            "dataset_index": _StubIndex(_snapshot_with_entries()),
            "run_locked": _run_locked,
        }
        if factory is DndCharacterTabFrame:
            kwargs["record_labels"] = {
                "dd_race": "Вид", "dd_subrace": "Подвид", "dd_class": "Класс",
                "dd_subclass": "Подкласс", "dd_background": "Предыстория",
            }
        else:
            kwargs["grimoire_index"] = None
        frame = factory(**kwargs)
        qtbot.addWidget(frame)
        await asyncio.sleep(0)
        frame.release_tab()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert _boxes(frame) == []  # cancellation is silent


async def test_sheet_guard_ignores_focus_leaves_during_fill(qtbot):
    # The defensive half of «loading never rewrites»: the guard itself —
    # editingFinished cannot fire through signals while _fill runs, so the
    # guard is pinned directly: an edit landing mid-fill costs no transaction.
    service = _StubService()
    frame = await _open_dnd_tab(qtbot, service)
    frame._sheet.setText("abc")
    frame._loading = True
    try:
        frame._on_sheet_edited()
    finally:
        frame._loading = False
    await _drain()
    assert not any(ask[0] == "sheet" for ask in service.asks)
    assert frame._saved_sheet == ""


# ── the «Заклинания» tab ──────────────────────────────────────────────────


def _spells_links() -> list[DdSpellLink]:
    return [
        DdSpellLink("srd", "fire-bolt", "Fire bolt"),
        DdSpellLink("grim", "witch-sight", "Ведьмин глаз"),
        DdSpellLink("gone", "x", "Мёртвый"),
    ]


async def _open_spells_tab(qtbot, service, *, grimoire="default") -> DndSpellsTabFrame:
    class _StubGrimoire:
        def __init__(self, snap):
            self._snap = snap

        async def snapshot(self):
            return self._snap

    frame = DndSpellsTabFrame(
        character_id=7,
        service=service,
        dataset_index=_StubIndex(_snapshot_with_entries()),
        grimoire_index=(
            _StubGrimoire(_grimoire_snapshot())
            if grimoire == "default"
            else None
        ),
        run_locked=_run_locked,
    )
    qtbot.addWidget(frame)
    await _drain()
    return frame


async def test_spells_tab_prints_bindings_with_their_origins(qtbot):
    service = _StubService(links=_spells_links())
    frame = await _open_spells_tab(qtbot, service)
    captions = [
        label.text() for label in frame.findChildren(QLabel, "ddSpellsRowName")
    ]
    assert captions == [
        "Fire bolt · SRD-5.1",
        "Ведьмин глаз · Гримуар А",
        f"Мёртвый — {SOURCE_UNAVAILABLE_NOTE}",
    ]
    assert len(frame.findChildren(QPushButton, "ddSpellsRemove")) == 3


async def test_spells_tab_empty_states(qtbot):
    from app.dd.application.grimoire_index_service import GrimoireIndexSnapshot

    service = _StubService(links=[])
    frame = await _open_spells_tab(qtbot, service)
    assert frame.findChild(QLabel, "ddSpellsEmpty").text().startswith("Пока нет")
    # candidates exist (fire-bolt/mage-hand + the grimoire spell)
    assert frame.findChildren(QPushButton, "ddSpellsCandidate")
    # nothing connected at all → the explanation replaces the list
    empty_index = IndexSnapshot(ids=(), titles={}, sections={}, slugs={})
    frame._snap = empty_index
    frame._gsnap = GrimoireIndexSnapshot(ids=(), titles={}, spells={})
    frame._render_candidates()
    assert frame.findChild(QLabel, "ddSpellsNoCandidates") is not None


async def test_spells_tab_candidates_exclude_bound_and_filter(qtbot):
    service = _StubService(links=_spells_links())
    frame = await _open_spells_tab(qtbot, service)
    captions = [
        button.text()
        for button in frame.findChildren(QPushButton, "ddSpellsCandidate")
    ]
    # all three bindings live, only the unbound SRD slug can be added;
    # its name rides the humanization
    assert captions == ["Добавить: Mage hand · SRD-5.1"]
    frame.findChild(QLineEdit, "ddSpellsFilter").setText("mage")
    assert len(frame.findChildren(QPushButton, "ddSpellsCandidate")) == 1
    # a needle that hits nothing replaces the wall with the explanation
    frame.findChild(QLineEdit, "ddSpellsFilter").setText("глаз")
    assert frame.findChildren(QPushButton, "ddSpellsCandidate") == []
    assert frame.findChild(QLabel, "ddSpellsNoCandidates") is not None
    # the filter runs through the grimoire half too (its spell neither
    # matches by name nor by slug here)
    frame.findChild(QLineEdit, "ddSpellsFilter").setText("fire")
    assert frame.findChildren(QPushButton, "ddSpellsCandidate") == []


async def test_spells_tab_add_click_binds_and_reloads_in_one_wave(qtbot):
    # fire-bolt stays bound, the grimoire spell is last — «Mage hand» is the
    # first candidate button the click can reach.
    links = [_spells_links()[0], _spells_links()[2]]
    service = _StubService(links=links)
    frame = await _open_spells_tab(qtbot, service)
    add_buttons = frame.findChildren(QPushButton, "ddSpellsCandidate")
    add_buttons[0].click()  # «Mage hand · SRD-5.1»
    await _drain()
    mage = DdSpellLink("srd", "mage-hand", "Mage hand")
    # the write and the reload are ONE coroutine: exactly one get_links
    # followed the add — no second refresh rides the done-callback.
    assert service.asks == [("get_links", 7), ("add", mage), ("get_links", 7)]
    names = [label.text() for label in frame.findChildren(QLabel, "ddSpellsRowName")]
    assert "Mage hand · SRD-5.1" in names
    # the filter also crosses the grimoire half: «hand» matches neither the
    # unbound grimoire spell's name nor its slug
    frame.findChild(QLineEdit, "ddSpellsFilter").setText("hand")
    assert frame.findChildren(QPushButton, "ddSpellsCandidate") == []


async def test_spells_tab_remove_click_unbinds_and_reloads(qtbot):
    service = _StubService(links=_spells_links())
    frame = await _open_spells_tab(qtbot, service)
    frame.findChildren(QPushButton, "ddSpellsRemove")[1].click()  # Ведьмин глаз
    await _drain()
    assert ("remove", "grim", "witch-sight") in service.asks
    assert service.asks[-1] == ("get_links", 7)  # reload rode the same wave
    names = [label.text() for label in frame.findChildren(QLabel, "ddSpellsRowName")]
    assert "Ведьмин глаз · Гримуар А" not in names


async def test_spells_tab_caps_the_candidate_wall(qtbot):
    service = _StubService(links=[])
    frame = await _open_spells_tab(qtbot, service)
    big = IndexSnapshot(
        ids=("srd",),
        titles={"srd": "SRD"},
        sections={},
        slugs={"srd": tuple(f"spell-{i:03d}" for i in range(60))},
    )
    frame._snap = big
    # the grimoire spell is out of this reading — the cap math is the point
    from app.dd.application.grimoire_index_service import GrimoireIndexSnapshot

    frame._gsnap = GrimoireIndexSnapshot(ids=(), titles={}, spells={})
    frame._render_candidates()
    assert len(frame.findChildren(QPushButton, "ddSpellsCandidate")) == 50
    cap = frame.findChild(QLabel, "ddSpellsCandidateCap")
    assert "Показаны первые 50" in cap.text() and "ещё 10" in cap.text()


async def test_spells_tab_without_the_grimoire_door_reads_an_empty_shelf(qtbot):
    service = _StubService(links=[])
    frame = await _open_spells_tab(qtbot, service, grimoire=None)
    captions = [
        button.text()
        for button in frame.findChildren(QPushButton, "ddSpellsCandidate")
    ]
    assert captions == [
        "Добавить: Fire bolt · SRD-5.1",
        "Добавить: Mage hand · SRD-5.1",
    ]


async def test_spells_tab_failures_are_modeless_boxes(qtbot):
    service = _StubService(fail_load=True)
    frame = await _open_spells_tab(qtbot, service)
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "Не удалось загрузить привязки заклинаний" in boxes[0].text()
    boxes[0].button(QMessageBox.StandardButton.Ok).click()
    assert frame._notice_box is None

    # the tab recovers by itself: a successful refresh paints the surface…
    service.fail_load = False
    service.fail_write = True
    frame.request_refresh()
    await _drain()
    add_buttons = frame.findChildren(QPushButton, "ddSpellsCandidate")
    assert add_buttons
    # …and a failed write is its own single modeless box
    add_buttons[0].click()
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "Не удалось выполнить действие" in boxes[0].text()
