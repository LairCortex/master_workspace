"""Accessibility pins for the module's new native controls (add-dnd-game-face
task 12.1; spec «Доступность без координат»).

The module's screens are plain Qt widgets, so their tree face is the widget
bridge's: ``QAccessible.queryAccessibleInterface`` answers the штатный role,
the name comes from the caption/buddy label/accessibleName — and every
activation the contract promises (row → card, filter → naming, checkbox →
the persisted write) must ride the accessibility action channel, not only
the mouse. This file pins exactly that, control by control, offscreen:

* «Справочник…»: the tab bar answers PageTab children named by the plural
  captions, a PageTab Press switches the browsed tab; the filter carries its
  caption as a name (a placeholder paints but never names); a row button is
  named by its visible caption and its accessibility Press seats the card in
  the preview column; the empty-state button names the screen it opens.
* The character's «D&D» tab: every reference picker is a named ComboBox
  (the slot caption — one knowledge with the descriptors), the level and the
  LSS field carry their captions; «Открыть в браузере» is named by its
  caption and its Press hands the digital sheet URL out; the LSS file
  doors (overwrite/save-raw + «Экспорт для LSS…») are named buttons, and
  an uncomposed door prints nothing at all.
* The «Заклинания» tab: the filter is named, «Снять» and «Добавить: …»
  persist through an accessibility Press.
* «Датасеты D&D…»: the reference switch and the per-row connect boxes are
  CheckBoxes named by what they do; their persistence rides the accessibility
  Toggle channel — cocoa turns a reader's AXPress on the CheckBox role into
  Toggle (the PR-001 fact), which flips ``checked`` through toggle() WITHOUT
  emitting clicked; a clicked-wired switch would show a tick that lies (the
  NRI-0023 F2 class, widget side — the reason these wires ride ``toggled``).
* «Бестиарий» + monster card: filter named, rows are named buttons whose
  Press opens the card, the card's tabs answer PageTab, its fields are named
  through buddy labels/accessibleName, its actions are caption-named Buttons.
* The «Встреча» tab: the add-row door is a named button whose Press stages a
  row, and the staged row's picker/spin/note/«Убрать» all answer the tree.

Mouse-channel behavior of these screens stays where it was pinned (the
per-screen test modules); nothing here re-pins business logic — only the
tree face and the action channel.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabBar,
    QTabWidget,
    QPlainTextEdit,
    QWidget,
)

from app.dd.application.dataset_index_service import DatasetEntry, IndexSnapshot
from app.dd.application.grimoire_index_service import GrimoireIndexSnapshot
from app.dd.domain.character import empty_ext
from app.dd.domain.dataset import DatasetSource
from app.dd.domain.grimoire import GrimoireSpell
from app.dd.domain.monster import DdMonster
from app.dd.presentation import character_tab_frames as frames
from app.dd.presentation.bestiary_sheet import (
    DD_BESTIARY_CREATE_TEXT,
    DndBestiarySheet,
    monster_row_caption,
)
from app.dd.presentation.character_tab_frames import (
    EXPORT_FOR_LSS_TEXT,
    IMPORT_OVERWRITE_TEXT,
    SAVE_RAW_TEXT,
    DndCharacterTabFrame,
    DndSpellsTabFrame,
)
from app.dd.presentation.datasets_sheet import DndDatasetsSheet
from app.dd.presentation.dd_encounter_frame import ADD_ROW_TEXT, DndEncounterTabFrame
from app.dd.presentation.monster_card_sheet import (
    DD_MONSTER_BLOCK_ADD_TEXT,
    DD_MONSTER_BLOCK_REMOVE_TEXT,
    DD_MONSTER_IMAGE_PICK_TEXT,
    DD_MONSTER_IMAGE_REMOVE_TEXT,
    DD_MONSTER_TAB_OVERVIEW,
    DD_MONSTER_TAB_TEXTS,
    DndMonsterCardSheet,
)
from app.dd.presentation.reference_sheet import (
    DD_REFERENCE_OPEN_DATASETS_TEXT,
    DndReferenceSheet,
)
from app.dd.presentation.reference_source import RECORD_TYPES
from app.presentation.modules.protocol import ExternalHit
from app.presentation.wiring import ApplicationWiring


# ── the shared probe helpers (AGENTS offscreen pattern) ──────────────────────


def iface(widget: QWidget) -> QAccessible.QAccessibleInterface:
    found = QAccessible.queryAccessibleInterface(widget)
    assert found is not None, f"no accessibility interface on {widget!r}"
    return found


def name_of(widget: QWidget) -> str:
    return iface(widget).text(QAccessible.Name)


def actions_of(widget: QWidget) -> list[str]:
    actions = iface(widget).actionInterface()
    assert actions is not None, f"no action interface on {widget!r}"
    return list(actions.actionNames())


def press(widget: QWidget, qtbot) -> None:
    """One accessibility Press — the channel a reader uses (no
    coordinates); animateClick ends its 100 ms timer through the Qt loop."""
    assert "Press" in actions_of(widget)
    iface(widget).actionInterface().doAction("Press")
    qtbot.wait(250)  # animateClick's timer releases the click signal


async def drain(times: int = 60) -> None:
    for _ in range(times):
        await asyncio.sleep(0.005)


def make_window(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    app = SimpleNamespace(_image_store=None, _theme=None)
    wiring = ApplicationWiring(
        app,
        window,
        None,
        None,
        None,
        None,
        None,
        SimpleNamespace(lock=asyncio.Lock()),
    )
    return window, wiring


# ── «Справочник…»: tabs, filter, rows, empty state ──────────────────────────


class _RefSource:
    """The protocol duck in the volume the sheet reads (test_reference_sheet's
    shape with the reference flag)."""

    def __init__(self, descriptors, rows, visible=True) -> None:
        self.type_descriptors = [
            SimpleNamespace(key=key, label=label, plural_label=plural, reference=True)
            for key, label, plural in descriptors
        ]
        self.visible = visible
        self._rows = rows

    async def search(self, query: str):
        return list(self._rows)


_REF_DESCRIPTORS = [
    ("dd_class", "Класс", "Классы"),
    ("dd_feat", "Черта", "Черты"),
    ("dd_spell", "Заклинание", "Заклинания"),
]


async def _make_reference_sheet(qtbot, rows, open_datasets=lambda: None):
    window, wiring = make_window(qtbot)
    shown: list[tuple[str, str]] = []
    sheet = DndReferenceSheet(
        sources=(_RefSource(_REF_DESCRIPTORS, rows),),
        run_locked=wiring.run_locked,
        show_card=lambda key, source_id: shown.append((key, source_id)),
        open_datasets=open_datasets,
        parent=window,
    )
    qtbot.addWidget(sheet)
    wiring.open_sheet(sheet)
    sheet.request_refresh()
    await sheet._load_task
    return sheet, shown


async def test_reference_tabs_answer_page_tabs_named_by_captions(qtbot):
    sheet, _ = await _make_reference_sheet(
        qtbot, [ExternalHit("dd_class", "srd51/cleric", "Клейрик", "SRD 5.1 (2014)")]
    )
    try:
        bar = sheet.findChild(QTabWidget).findChild(QTabBar)
        bar_iface = iface(bar)
        tabs = [
            bar_iface.child(index)
            for index in range(bar_iface.childCount())
            if bar_iface.child(index).role() == QAccessible.Role.PageTab
        ]
        assert [tab.text(QAccessible.Name) for tab in tabs] == [
            "Классы",
            "Черты",
            "Заклинания",
        ]
        # One reader Press on the last tab switches the browsed tab (the
        # widget-side counterpart of the islands' tab contract).
        assert "Press" in list(tabs[2].actionInterface().actionNames())
        tabs[2].actionInterface().doAction("Press")
        await drain()
        assert sheet.findChild(QTabWidget).currentIndex() == 2
    finally:
        sheet.close()


async def test_reference_filter_is_named_editable_text(qtbot):
    sheet, _ = await _make_reference_sheet(qtbot, [])
    try:
        box = sheet.findChild(QLineEdit, "referenceFilter")
        assert iface(box).role() == QAccessible.Role.EditableText
        # The caption at the point of application — a placeholder only paints.
        assert name_of(box) == "Фильтр по имени"
    finally:
        sheet.close()


async def test_reference_row_press_through_accessibility_opens_the_card(qtbot):
    hit = ExternalHit("dd_class", "srd51/cleric", "Клейрик", "SRD 5.1 (2014)")
    sheet, shown = await _make_reference_sheet(qtbot, [hit])
    try:
        row = next(
            b
            for b in sheet.findChildren(QPushButton)
            if b.objectName() == "referenceRow"
        )
        assert iface(row).role() == QAccessible.Role.Button
        assert name_of(row) == row.text() == "Клейрик · SRD 5.1 (2014)"
        press(row, qtbot)
        assert shown == [("dd_class", "srd51/cleric")]
        assert not sheet.isVisible()  # the sheet steps aside for the column
    finally:
        sheet.close()


async def test_reference_empty_state_button_names_the_screen_it_opens(qtbot):
    opened: list[bool] = []
    sheet, _ = await _make_reference_sheet(qtbot, [], lambda: opened.append(True))
    try:
        button = sheet.findChild(QPushButton, "referenceOpenDatasets")
        assert button.isVisible()
        assert iface(button).role() == QAccessible.Role.Button
        assert name_of(button) == DD_REFERENCE_OPEN_DATASETS_TEXT
        press(button, qtbot)
        assert opened == [True]
    finally:
        sheet.close()


# ── the character's «D&D» tab: named pickers and doors ──────────────────────


class _ExtService:
    def __init__(self) -> None:
        self.ext = empty_ext()
        self.links: list = []
        self.sheet_links: list = []

    async def get_ext(self, character_id):
        return self.ext

    async def set_reference_link(self, character_id, slot, link):
        self.ext.links[slot] = link

    async def set_level(self, character_id, level):
        self.ext.level = level

    async def set_lss_sheet_id(self, character_id, sheet_id):
        pass

    async def get_spell_links(self, character_id):
        return list(self.links)

    async def add_spell_link(self, character_id, link):
        self.links.append(link)

    async def remove_spell_link(self, character_id, source_key, slug):
        self.links = [
            link
            for link in self.links
            if (link.source_key, link.slug) != (source_key, slug)
        ]


class _Index:
    def __init__(self) -> None:
        self.snap = IndexSnapshot(
            ids=("srd51",),
            titles={"srd51": "SRD 5.1 (2014)"},
            sections={
                section: {
                    "srd51": (DatasetEntry("srd51", f"{section}-1", f"Запись {section}", {}),)
                }
                for section, _descriptor in RECORD_TYPES
                if section != "spells"
            },
            slugs={"srd51": ("fireball",)},
        )

    async def snapshot(self):
        return self.snap


def _run_locked(coro):
    return asyncio.ensure_future(coro)


async def _make_dnd_frame(qtbot, *, importer=None, builder=None):
    frame = DndCharacterTabFrame(
        character_id=1,
        service=_ExtService(),
        dataset_index=_Index(),
        record_labels={descriptor.key: descriptor.label for _, descriptor in RECORD_TYPES},
        run_locked=_run_locked,
        import_service=importer,
        document_builder=builder,
    )
    qtbot.addWidget(frame)
    frame.show()
    await drain()
    return frame


async def test_dnd_tab_pickers_are_named_comboboxes(qtbot):
    frame = await _make_dnd_frame(qtbot)
    labels = {descriptor.key: descriptor.label for _, descriptor in RECORD_TYPES}
    expected = {
        "ddDndSlot_race": labels["dd_race"],
        "ddDndSlot_subrace": labels["dd_subrace"],
        "ddDndSlot_class": labels["dd_class"],
        "ddDndSlot_subclass": labels["dd_subclass"],
        "ddDndSlot_background": labels["dd_background"],
        "ddDndLevel": "Уровень",
    }
    # The picker face (Qt's штатно, pinned as fact): role ComboBox; the Name
    # slot answers the current value (the native popup value-as-title — a
    # QAccessibleComboBox overrides accessibleName here, offscreen probe
    # 2026-10-10); the slot's caption reaches the reader through the buddy
    # LabelOf relation the form's addRow sets up — no coordinates anywhere.
    for object_name, caption in expected.items():
        combo = frame.findChild(QComboBox, object_name)
        assert combo is not None, object_name
        combo_iface = iface(combo)
        assert combo_iface.role() == QAccessible.Role.ComboBox, object_name
        for label_iface, flag in combo_iface.relations():
            if flag & QAccessible.RelationFlag.Label:
                assert label_iface.text(QAccessible.Name).startswith(caption), (
                    object_name
                )
                break
        else:
            pytest.fail(f"{object_name}: no buddy Label relation for «{caption}»")
    sheet_field = frame.findChild(QLineEdit, "ddDndSheetId")
    assert iface(sheet_field).role() == QAccessible.Role.EditableText
    assert name_of(sheet_field) == "Идентификатор листа LSS"


async def test_dnd_tab_browser_button_press_hands_the_url_out(qtbot, monkeypatch):
    frame = await _make_dnd_frame(qtbot)
    opened: list[str] = []

    class _Desk:
        @staticmethod
        def openUrl(url):
            opened.append(url.toString())

    monkeypatch.setattr(frames, "QDesktopServices", _Desk)
    sheet_field = frame.findChild(QLineEdit, "ddDndSheetId")
    sheet_field.setText("12345")  # a filled id shows the door (spec)
    button = frame.findChild(QPushButton, "ddDndSheetOpen")
    assert button.isVisible()
    assert iface(button).role() == QAccessible.Role.Button
    assert name_of(button) == "Открыть в браузере"
    press(button, qtbot)
    assert opened == ["https://longstoryshort.app/iframe/characters/digital/12345/"]


async def test_dnd_tab_file_doors_are_named_buttons(qtbot):
    frame = await _make_dnd_frame(qtbot, importer=SimpleNamespace(), builder=SimpleNamespace())
    for object_name, caption in (
        ("ddDndImportOverwrite", IMPORT_OVERWRITE_TEXT),
        ("ddDndSaveRaw", SAVE_RAW_TEXT),
        ("ddDndExportLss", EXPORT_FOR_LSS_TEXT),
    ):
        button = frame.findChild(QPushButton, object_name)
        assert iface(button).role() == QAccessible.Role.Button, object_name
        assert name_of(button) == button.text() == caption, object_name


async def test_dnd_tab_prints_no_door_without_its_service(qtbot):
    """The no-dead-action posture per door: an uncomposed service prints no
    button at all — the export half joins the row on its own (task 5.3),
    the import halves stay behind the import service."""
    only_export = await _make_dnd_frame(qtbot, builder=SimpleNamespace())
    assert only_export.findChild(QPushButton, "ddDndExportLss") is not None
    assert only_export.findChild(QPushButton, "ddDndImportOverwrite") is None
    assert only_export.findChild(QPushButton, "ddDndSaveRaw") is None
    no_doors = await _make_dnd_frame(qtbot)
    for object_name in ("ddDndExportLss", "ddDndImportOverwrite", "ddDndSaveRaw"):
        assert no_doors.findChild(QPushButton, object_name) is None


# ── the «Заклинания» tab: named filter, persisting row doors ────────────────


class _GrimoireIndex:
    def __init__(self) -> None:
        self.snap = GrimoireIndexSnapshot(
            ids=("home",),
            titles={"home": "Хоумбрю-гримуар"},
            spells={"home": {"moon-pet": GrimoireSpell("moon-pet", "Лунный питомец", "…")}},
        )

    async def snapshot(self):
        return self.snap


async def _make_spells_frame(qtbot, service):
    frame = DndSpellsTabFrame(
        character_id=1,
        service=service,
        dataset_index=_Index(),
        grimoire_index=_GrimoireIndex(),
        run_locked=_run_locked,
    )
    qtbot.addWidget(frame)
    frame.show()
    await drain()
    return frame


async def test_spells_tab_filter_and_candidate_press_persist(qtbot):
    service = _ExtService()
    frame = await _make_spells_frame(qtbot, service)
    box = frame.findChild(QLineEdit, "ddSpellsFilter")
    assert iface(box).role() == QAccessible.Role.EditableText
    assert name_of(box) == "Фильтр заклинаний"

    from app.dd.domain.character import DdSpellLink

    service.links.append(
        DdSpellLink(source_key="srd51", slug="fireball", snapshot_name="Fireball")
    )
    frame.request_refresh()
    await drain()

    candidates = [
        b
        for b in frame.findChildren(QPushButton)
        if b.objectName() == "ddSpellsCandidate"
    ]
    assert candidates, "SRD and grimoire candidates should offer additions"
    candidate = next(b for b in candidates if "Лунный питомец" in b.text())
    assert iface(candidate).role() == QAccessible.Role.Button
    assert name_of(candidate) == candidate.text() == "Добавить: Лунный питомец · Хоумбрю-гримуар"
    press(candidate, qtbot)
    await drain()
    assert any(link.slug == "moon-pet" for link in service.links)

    removes = [
        b for b in frame.findChildren(QPushButton) if b.objectName() == "ddSpellsRemove"
    ]
    assert removes
    remove = removes[0]
    assert name_of(remove) == "Снять"
    press(remove, qtbot)
    await drain()
    assert all(link.slug != "fireball" for link in service.links)


# ── «Датасеты D&D…»: the switch and the rows persist on the reader's channel ──


class _Holder:
    def __init__(self) -> None:
        self.visible = True
        self.written: list[bool] = []

    async def set_visible(self, enabled: bool) -> None:
        self.written.append(enabled)
        self.visible = enabled


def _shelf(dataset_id: str):
    return SimpleNamespace(
        dataset_id=dataset_id,
        title=f"Набор {dataset_id}",
        meta=SimpleNamespace(source=DatasetSource.SRD, check_errors=None),
    )


async def _make_datasets_sheet(qtbot, holder, disconnects, statuses=None):
    window, wiring = make_window(qtbot)
    connections = SimpleNamespace(
        statuses=statuses or (lambda: _statuses()),
        disconnect=disconnects,
    )

    async def _statuses():
        return [SimpleNamespace(dataset_id="srd51", present=True)]

    sheet = DndDatasetsSheet(
        library=SimpleNamespace(list_storage=lambda: [_shelf("srd51")]),
        connections=connections,  # type: ignore[arg-type]
        importer=SimpleNamespace(),  # type: ignore[arg-type]
        run_locked=wiring.run_locked,
        parent=window,
        theme=None,
        reference_visibility=holder,
    )
    qtbot.addWidget(sheet)
    wiring.open_sheet(sheet)
    sheet.request_refresh()
    await drain()
    return window, sheet


async def test_reference_switch_is_a_named_checkbox_persisting_on_toggle(qtbot):
    holder = _Holder()
    _, sheet = await _make_datasets_sheet(qtbot, holder, _noop_async)
    try:
        box = sheet.findChild(QCheckBox, "ddReferenceSearchBox")
        assert iface(box).role() == QAccessible.Role.CheckBox
        assert name_of(box) == "Показывать справочные записи в поиске"
        # The reader's channel: cocoa turns AXPress on a CheckBox into Toggle,
        # which flips checked through toggle() without clicked — persistence
        # must ride the state (task 12.1; a lying tick returns if the wire
        # moves back to clicked).
        assert "Toggle" in actions_of(box)
        iface(box).actionInterface().doAction("Toggle")
        await drain()
        assert holder.written == [False]
        assert box.isChecked() is False
    finally:
        sheet.close()


async def _noop_async(*_args):
    return None


def _last_child(widget, type_, object_name: str):
    """The live instance of a name repeated across repaints.

    The datasets sheet repaints its whole table on every frame, and Qt
    deletes replaced cell widgets asynchronously — so findChildren can still
    list the previous frame's box. The most recently created one is the live.
    """
    matches = [
        child
        for child in widget.findChildren(type_)
        if child.objectName() == object_name
    ]
    assert matches, f"no {object_name!r} under {widget!r}"
    return matches[-1]


async def test_row_connect_box_is_named_and_persists_on_toggle(qtbot):
    # The connected set the sheet reads, as a fake the service drives: the
    # box's name and state follow what the persisted links actually say, so
    # a write that never landed can never print as connected.
    connected = {"srd51"}

    async def statuses():
        return [
            SimpleNamespace(dataset_id=dataset_id, present=True)
            for dataset_id in sorted(connected)
        ]

    async def disconnect(dataset_id: str) -> None:
        connected.discard(dataset_id)

    _, sheet = await _make_datasets_sheet(
        qtbot, _Holder(), disconnect, statuses=statuses
    )
    try:
        box = _last_child(sheet, QCheckBox, "ddDatasetConnectBox")
        assert iface(box).role() == QAccessible.Role.CheckBox
        # Named by what its press does at this row (a connected set is
        # offered removal).
        assert name_of(box) == "Отключить набор от игры"
        assert "Toggle" in actions_of(box)
        iface(box).actionInterface().doAction("Toggle")
        await drain()
        assert connected == set()
        # The repaint rebuilt the row: the live box now offers the other
        # direction, so the tree never advertises a write it no longer does.
        reloaded = _last_child(sheet, QCheckBox, "ddDatasetConnectBox")
        assert box.isChecked() is False
        assert name_of(reloaded) == "Подключить набор к игре"
    finally:
        sheet.close()


async def test_datasets_sheet_buttons_are_caption_named(qtbot):
    _, sheet = await _make_datasets_sheet(qtbot, _Holder(), _noop_async)
    try:
        for object_name, caption in (
            ("ddSrdButton", "Загрузить SRD"),
            ("ddImportButton", "Импорт файла…"),
            ("ddRecheckButton", "Повторить проверку"),
        ):
            button = sheet.findChild(QPushButton, object_name)
            assert iface(button).role() == QAccessible.Role.Button, object_name
            assert name_of(button) == caption, object_name
            assert "Press" in actions_of(button), object_name
    finally:
        sheet.close()


# ── «Бестиарий»: named filter, rows open the card through the tree ──────────


def _monster(mid: int, name: str, rating: int = 1) -> DdMonster:
    return DdMonster(id=mid, name=name, rating=rating, blocks={}, image_id=None)


async def _make_bestiary(qtbot, monsters, opened):
    service = SimpleNamespace(list_monsters=lambda: _list(monsters))

    async def _list(items):
        return list(items)

    window, wiring = make_window(qtbot)
    sheet = DndBestiarySheet(
        service=service,  # type: ignore[arg-type]
        run_locked=wiring.run_locked,
        open_card=opened,
        parent=window,
    )
    qtbot.addWidget(sheet)
    wiring.open_sheet(sheet)
    sheet.request_refresh()
    await sheet._load_task
    return window, sheet


async def test_bestiary_filter_rows_and_creation_are_named(qtbot):
    opened: list[int | None] = []
    _, sheet = await _make_bestiary(
        qtbot, [_monster(1, "Гоблин", 2)], opened.append
    )
    try:
        box = sheet.findChild(QLineEdit, "bestiaryFilter")
        assert iface(box).role() == QAccessible.Role.EditableText
        assert name_of(box) == "Фильтр по имени"
        create = sheet.findChild(QPushButton, "bestiaryCreate")
        assert name_of(create) == DD_BESTIARY_CREATE_TEXT
        row = next(
            b
            for b in sheet.findChildren(QPushButton)
            if b.objectName() == "bestiaryRow"
        )
        assert iface(row).role() == QAccessible.Role.Button
        assert name_of(row) == row.text() == monster_row_caption(_monster(1, "Гоблин", 2))
        press(row, qtbot)
        assert opened == [1]
    finally:
        sheet.close()


async def test_bestiary_empty_state_offers_a_named_creation_door(qtbot):
    opened: list[int | None] = []
    _, sheet = await _make_bestiary(qtbot, [], opened.append)
    try:
        button = sheet.findChild(QPushButton, "bestiaryEmptyCreate")
        assert button.isVisible()
        assert name_of(button) == DD_BESTIARY_CREATE_TEXT
        press(button, qtbot)
        assert opened == [None]
    finally:
        sheet.close()


# ── monster card: PageTab tabs, buddy-named fields, caption buttons ─────────


async def _make_monster_card(qtbot, monster):
    from tests.dd.test_monster_card_sheet import _Service  # duck with real gates

    service = _Service(monsters=[monster])
    window, wiring = make_window(qtbot)
    card = DndMonsterCardSheet(
        monster.id,
        service,
        wiring.run_locked,
        lambda saved: None,
        parent=window,
    )
    qtbot.addWidget(card)
    wiring.open_sheet(card)
    await drain()
    return window, card


async def test_monster_card_tabs_and_fields_are_addressable(qtbot):
    monster = _monster(1, "Гоблин", 2)
    monster = DdMonster(
        id=1, name="Гоблин", rating=2, blocks={"Атаки": "Короткий меч"}, image_id=None
    )
    _, card = await _make_monster_card(qtbot, monster)
    try:
        bar = card.findChild(QTabWidget).findChild(QTabBar)
        bar_iface = iface(bar)
        tab_names = [
            bar_iface.child(index).text(QAccessible.Name)
            for index in range(bar_iface.childCount())
            if bar_iface.child(index).role() == QAccessible.Role.PageTab
        ]
        assert tab_names == [DD_MONSTER_TAB_OVERVIEW, DD_MONSTER_TAB_TEXTS]

        # Overview tab: the name and rating are named through their buddy
        # labels (штатно), the picture doors by their captions.
        assert iface(card.findChild(QLineEdit, "ddMonsterName")).role() == (
            QAccessible.Role.EditableText
        )
        assert name_of(card.findChild(QLineEdit, "ddMonsterName")) == "Имя"
        assert iface(card.findChild(QSpinBox, "ddMonsterRating")).role() == (
            QAccessible.Role.SpinBox
        )
        assert name_of(card.findChild(QSpinBox, "ddMonsterRating")) == "Рейтинг"
        pick = card.findChild(QPushButton, "ddMonsterImagePick")
        assert name_of(pick) == DD_MONSTER_IMAGE_PICK_TEXT
        assert name_of(card.findChild(QPushButton, "ddMonsterImageRemove")) == (
            DD_MONSTER_IMAGE_REMOVE_TEXT
        )
        # The texts tab shows its block rows: the block's fields are named
        # (placeholders paint, names ride accessibleName), removal is a named
        # button, adding another block is a named door.
        assert name_of(card.findChild(QLineEdit, "ddMonsterBlockTitle")) == (
            "Заголовок блока"
        )
        assert name_of(card.findChild(QPlainTextEdit, "ddMonsterBlockText")) == (
            "Текст блока"
        )
        assert name_of(card.findChild(QPushButton, "ddMonsterBlockAdd")) == (
            DD_MONSTER_BLOCK_ADD_TEXT
        )
        assert name_of(card.findChild(QPushButton, "ddMonsterBlockRemove")) == (
            DD_MONSTER_BLOCK_REMOVE_TEXT
        )
        assert name_of(card.findChild(QPushButton, "ddMonsterSave")) == "Сохранить"
        assert name_of(card.findChild(QPushButton, "ddMonsterCancel")) == "Отмена"
    finally:
        card.close()


# ── the «Встреча» tab: the staged row is fully addressable ──────────────────


class _EncounterFrameMonsters:
    def __init__(self, names):
        self.names = list(names)

    async def list_monsters(self):
        return [
            SimpleNamespace(id=index, name=name)
            for index, name in enumerate(self.names, 1)
        ]


class _Encounters:
    def __init__(self) -> None:
        self.saved = None

    async def get_encounter(self, event_id):
        return None

    async def save_encounter(self, event_id, entries, note):
        self.saved = (event_id, entries, note)
        return None


async def _make_encounter_frame(qtbot):
    frame = DndEncounterTabFrame(
        event_id=7,
        encounter_service=_Encounters(),
        monster_service=_EncounterFrameMonsters(["Гоблин", "Огр"]),
        source=SimpleNamespace(apply_saved=lambda *a: None),
        run_locked=_run_locked,
    )
    qtbot.addWidget(frame)
    frame.show()
    await drain()
    return frame


async def test_encounter_frame_controls_answer_the_tree(qtbot):
    frame = await _make_encounter_frame(qtbot)
    add = frame.findChild(QPushButton, "ddEncounterAdd")
    assert iface(add).role() == QAccessible.Role.Button
    assert name_of(add) == add.text() == ADD_ROW_TEXT
    press(add, qtbot)
    row = next(r for r in frame.findChildren(QWidget) if r.objectName() == "ddEncounterRow")
    combo = row.findChild(QComboBox, "ddEncounterMonster")
    assert iface(combo).role() == QAccessible.Role.ComboBox
    # A popup's штатно face: the Name slot answers the selected value and
    # the accessibleName is not used for it (Qt's QAccessibleComboBox,
    # offscreen probe 2026-10-10) — the row stays addressable by the value
    # the reader is choosing, no coordinates needed.
    assert name_of(combo) == "Гоблин"
    assert combo.accessibleName() == "Монстр"
    spin = row.findChild(QSpinBox, "ddEncounterCount")
    assert iface(spin).role() == QAccessible.Role.SpinBox
    assert name_of(spin) == "Количество"
    note = frame.findChild(QPlainTextEdit, "ddEncounterNote")
    assert name_of(note) == "Заметка встречи"
    remove = row.findChild(QPushButton, "ddEncounterRemove")
    assert name_of(remove) == "Убрать"
    press(remove, qtbot)
    assert not any(
        r.objectName() == "ddEncounterRow" for r in frame.findChildren(QWidget)
    )
