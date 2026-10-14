"""Module-block channel — the declarative blocks of the kernel card scroll
(dd-card-redesign task 4.2, design Д2, spec entity-card-tabs «Модульные
блоки»).

Three layers, all offscreen:

* the ``ModuleBlockHost`` mechanics: tolerant collection (a hidden source,
  a source without the door, a raising door, a broken or non-duck handler —
  none of them disturbs the kernel), merge in source order with first-wins
  on a duplicated id, the per-source ``republish`` door, write routing by
  block id, and the teardown contract (handlers released, late republish and
  late writes answer nothing);
* the dialog facades: ``populate`` collects the frame for the record being
  edited (and for a fresh card — the empty id is how a module hides its
  kernel texts before the record exists), closing the window releases the
  handlers with the island;
* the QML render through ``ModuleBlockDelegate``: blocks paint at both
  anchors with штатные controls, the hidden kernel texts disappear while
  every other kernel row survives, an empty channel leaves the 0.19.1 card
  untouched, and the write-back rides the real triggers — the accessibility
  Press of a switch (Д15: the flipped MODEL value), of a button, and the
  Enter-commit of a number cell (never per keystroke).
"""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.presentation.module_block_host import ModuleBlockHost
from app.presentation.modules.protocol import (
    ModuleBlock,
    ModuleBlockCell,
    ModuleBlockFrame,
    ModuleBlockOption,
    ModuleBlockRow,
)
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from tests.presentation.qml_helpers import find_item
from tests.ui.test_theme_grab import make_runtime


class _Handler:
    """Duck handler the host collects (handle_write + release)."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, str, object]] = []
        self.released = 0

    def handle_write(self, block_id: str, field: str, value: object) -> None:
        self.writes.append((block_id, field, value))

    def release(self) -> None:
        self.released += 1


class _RaisingHandler(_Handler):
    def handle_write(self, block_id: str, field: str, value: object) -> None:
        raise RuntimeError("отказ модуля")

    def release(self) -> None:
        raise RuntimeError("не отпускает")


def _frame(
    blocks: tuple[ModuleBlock, ...] = (),
    hidden: tuple[str, ...] = (),
    factory=None,
) -> ModuleBlockFrame:
    return ModuleBlockFrame(blocks=blocks, hidden_fields=hidden, handler_factory=factory)


def _combo(block_id: str = "cls", anchor: str = "after_short_fields", **kw) -> ModuleBlock:
    return ModuleBlock(
        kind="combo",
        id=block_id,
        label="Класс",
        anchor=anchor,
        value=kw.pop("value", "wizard"),
        options=(
            ModuleBlockOption("wizard", "Чародей"),
            ModuleBlockOption("cleric", "Жрец"),
        ),
        **kw,
    )


def _press(item) -> None:
    iface = QAccessible.queryAccessibleInterface(item)
    actions = iface.actionInterface()
    assert actions is not None
    # PySide returns None from doAction whatever happened; the caller checks
    # the effect (the action names live in the tree — Press for a button,
    # Toggle for a CheckBox role under Qt 6.10's translation).
    actions.doAction("Press")


# ── host mechanics (Python face, dialog carries the VM) ─────────────────────


def test_host_merges_first_wins_publishes_and_routes_writes(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    first_handler, second_handler = _Handler(), _Handler()

    def factory_of(handler):
        def factory(wiring, card_dialog, republish):
            assert card_dialog is dialog
            return handler
        return factory

    source_a = SimpleNamespace(
        visible=True,
        module_blocks=lambda target: _frame(
            (_combo("dup"), ModuleBlock(kind="text", id="solo", label="Ок",
                                        anchor="after_music", value="+3")),
            ("characteristics",),
            factory_of(first_handler),
        ),
    )
    source_b = SimpleNamespace(
        visible=True,
        module_blocks=lambda target: _frame(
            (_combo("dup"), _combo("own", anchor="after_music")),
            ("characteristics", "backstory"),
            factory_of(second_handler),
        ),
    )
    host = ModuleBlockHost(dialog, dialog.vm, [source_a, source_b],
                           wiring=object(), target_key="character")
    host.refresh("7")

    published = dialog.vm.moduleBlocks
    ids = [entry["id"] for entry in published]
    assert ids == ["dup", "solo", "own"]  # first source wins the duplicate
    assert dialog.vm.hiddenFields == ["characteristics", "backstory"]  # union

    # A write lands on the entry that owns the block id and nowhere else.
    dialog.vm.writeModuleBlock("dup", "value", "cleric")
    dialog.vm.writeModuleBlock("own", "value", "wizard")
    assert first_handler.writes == [("dup", "value", "cleric")]
    assert second_handler.writes == [("own", "value", "wizard")]
    # A write for an unknown block is dropped without raising.
    dialog.vm.writeModuleBlock("нет-такого", "value", 1)

    # refresh() retires the previous handlers before rebuilding.
    host.refresh("8")
    assert first_handler.released == 1 and second_handler.released == 1

    # The republish door replaces only its own source's frame.
    republished: list = []

    def capturing_factory(wiring, card_dialog, republish):
        republished.append(republish)
        return _Handler()

    src = SimpleNamespace(
        visible=True,
        module_blocks=lambda target: _frame((_combo("rep"),), (), capturing_factory),
    )
    host2 = ModuleBlockHost(dialog, dialog.vm, [src], target_key="character")
    host2.refresh("1")
    assert [e["id"] for e in dialog.vm.moduleBlocks] == ["rep"]
    republished[0]([ModuleBlock(kind="text", id="rep2", label="", anchor="after_music",
                                value="x")],
                   ("backstory",))
    assert [e["id"] for e in dialog.vm.moduleBlocks] == ["rep2"]
    assert dialog.vm.hiddenFields == ["backstory"]

    host.release()
    host2.release()
    host.release()  # idempotent
    # After release the write channel is silent (the signal is detached).
    host2.release()
    dialog.vm.writeModuleBlock("rep2", "value", "y")


def test_host_tolerates_broken_sources_and_handlers(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    before = list(dialog.vm.moduleBlocks)

    broken = SimpleNamespace(visible=True,
                             module_blocks=lambda target: (_ for _ in ()).throw(
                                 RuntimeError("сбой источника")))
    hidden = SimpleNamespace(visible=False,
                             module_blocks=lambda target: _frame((_combo(),)))
    quiet = SimpleNamespace(visible=True, module_blocks=lambda target: None)
    mute = SimpleNamespace(visible=True)  # no door at all

    host = ModuleBlockHost(dialog, dialog.vm, [broken, hidden, quiet, mute],
                           target_key="event")
    host.refresh("1")
    assert dialog.vm.moduleBlocks == before == []  # kernel untouched

    # A factory that raises, and a handler that does not speak the duck
    # contract: the blocks still paint, only their writes are dropped.
    def raising_factory(wiring, card_dialog, republish):
        raise RuntimeError("нет обработчика")

    src_raise = SimpleNamespace(visible=True, module_blocks=lambda target: _frame(
        (_combo("r"),), (), raising_factory))
    src_duck = SimpleNamespace(visible=True, module_blocks=lambda target: _frame(
        (_combo("d"),), (), lambda w, dl, rp: object()))
    src_bad_write = SimpleNamespace(visible=True, module_blocks=lambda target: _frame(
        (_combo("w"),), (), lambda w, dl, rp: _RaisingHandler()))
    host2 = ModuleBlockHost(dialog, dialog.vm, [src_raise, src_duck, src_bad_write],
                            target_key="event")
    host2.refresh("1")
    assert {e["id"] for e in dialog.vm.moduleBlocks} == {"r", "d", "w"}
    for block_id in ("r", "d", "w"):
        dialog.vm.writeModuleBlock(block_id, "value", "x")  # none of them raises
    host.release()
    host2.release()


def test_republish_survives_the_doorless_sources_before_it(qtbot):
    # The live defect (checkpoint 2 audit): the real composition leads with
    # the reference source, which carries NO module_blocks door. Collected
    # entries are compact, so a handler built for the SECOND source slot had
    # its republish aimed one entry past its own — every async block frame
    # was silently dropped and «Основное» stayed empty while the sync hidden
    # fields landed. The door must follow the ENTRY, not the source index.
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    republish_doors: list = []

    def factory(wiring, card_dialog, republish):
        republish_doors.append(republish)
        return _Handler()

    doorless = SimpleNamespace(visible=True)  # the reference source's shape
    framed = SimpleNamespace(
        visible=True,
        module_blocks=lambda target: _frame((), ("characteristics",), factory),
    )
    host = ModuleBlockHost(dialog, dialog.vm, [doorless, framed],
                           wiring=object(), target_key="character")
    host.refresh("1")
    assert dialog.vm.moduleBlocks == []
    assert dialog.vm.hiddenFields == ["characteristics"]
    # The handler's async first frame lands through the door.
    republish_doors[0]([_combo("cls")], ("characteristics",))
    assert [e["id"] for e in dialog.vm.moduleBlocks] == ["cls"]

    # A re-collection retires the old entry: its late republish answers
    # nothing (identity, not index, is the door's leash).
    host.refresh("2")
    assert dialog.vm.moduleBlocks == []  # the fresh frame asks empty again
    republish_doors[0]([_combo("ghost")], ())
    assert dialog.vm.moduleBlocks == []
    # while the NEW handler's door is live again (second entry, same shape).
    republish_doors[1]([_combo("cls")], ("characteristics",))
    assert [e["id"] for e in dialog.vm.moduleBlocks] == ["cls"]
    host.release()


def test_host_release_after_the_vm_died_still_quietens(qtbot):
    import shiboken6

    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    handler = _Handler()
    src = SimpleNamespace(visible=True, module_blocks=lambda target: _frame(
        (_combo(),), (), lambda w, dl, rp: handler))
    host = ModuleBlockHost(dialog, dialog.vm, [src], target_key="event")
    host.refresh("1")
    shiboken6.delete(dialog.vm)
    host.release()  # the disconnect leg hits a dead VM — must not raise
    assert handler.released == 1


def test_host_after_release_answers_nothing(qtbot):
    # The belt of «a released island answers NOTHING» on the host's two late
    # doors: a collection that raced the close never reads the sources again
    # (the dialog re-populating a card that is already gone stays quiet), and
    # a module callback firing after the teardown leaves the published
    # channel exactly as the release left it.
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    asks: list = []
    republish_box: dict = {}

    def factory(wiring, event_dialog, republish):
        republish_box["fn"] = republish
        return _Handler()

    def door(target):
        asks.append(target.source_id)
        return _frame((_combo("late"),), (), factory)

    source = SimpleNamespace(visible=True, module_blocks=door)
    host = ModuleBlockHost(dialog, dialog.vm, [source], target_key="event")
    host.refresh("1")
    assert asks == ["1"]
    published = list(dialog.vm.moduleBlocks)
    assert [entry["id"] for entry in published] == ["late"]

    host.release()
    asks.clear()
    host.refresh("2")  # the late collection raced the teardown
    assert asks == []  # a released host never reads the sources again
    assert list(dialog.vm.moduleBlocks) == published
    republish_box["fn"]((_combo("after"),), ())  # a late module callback
    assert list(dialog.vm.moduleBlocks) == published


# ── the dialog facades: populate collects, close releases ───────────────────


def _card_with_source(frame_factory, qtbot, tmp_path, entity_type="character"):
    handler = _Handler()
    republish_box: dict = {}

    def factory(wiring, card_dialog, republish):
        republish_box["fn"] = republish
        return handler

    source = SimpleNamespace(
        visible=True,
        module_blocks=lambda target: frame_factory(target, factory),
    )
    dialog = EntityCardDialog(
        None, entity_type, theme=make_runtime(tmp_path, "dark"),
        external_sources=[source],
    )
    qtbot.addWidget(dialog)
    return dialog, handler, republish_box


def test_card_populate_collects_and_close_releases(qtbot, tmp_path):
    def frame_factory(target, factory):
        if target.source_id == "":
            return _frame((), ("characteristics", "backstory"))  # fresh card
        return _frame((_combo(),), ("characteristics", "backstory"), factory)

    dialog, handler, _ = _card_with_source(frame_factory, qtbot, tmp_path)
    # A fresh card collects at construction (it never sees populate): the
    # hidden texts are the module's honest answer before the record exists
    # (spec «Пустой новый персонаж»).
    assert dialog.vm.moduleBlocks == []
    assert dialog.vm.hiddenFields == ["characteristics", "backstory"]
    dialog.populate(SimpleNamespace(id=9, name="Морфеус"))
    assert [e["id"] for e in dialog.vm.moduleBlocks] == ["cls"]
    assert "characteristics" in dialog.vm.hiddenFields
    dialog.close()
    QApplication.processEvents()
    assert handler.released == 1


def test_empty_channel_leaves_the_kernel_untouched(qtbot, tmp_path):
    source = SimpleNamespace(visible=True,
                             module_blocks=lambda target: ModuleBlockFrame())
    dialog = EntityCardDialog(None, "character",
                              theme=make_runtime(tmp_path, "dark"),
                              external_sources=[source])
    qtbot.addWidget(dialog)
    dialog.populate(SimpleNamespace(id=1, name="c"))
    QApplication.processEvents()
    assert dialog.vm.moduleBlocks == []
    assert dialog.vm.hiddenFields == []
    for name in ("entityCharacteristicsLabel", "entityCharacteristicsField",
                 "entityBackstoryField", "entityNameField", "entityMusicField"):
        assert find_item(dialog.quick, name).property("visible") is True


# ── the QML render at the two anchors ────────────────────────────────────────


def _table_block() -> ModuleBlock:
    return ModuleBlock(
        kind="table", id="abil", label="Характеристики",
        anchor="after_short_fields",
        columns=("Характеристика", "Значение", "Владение"),
        rows=(
            ModuleBlockRow(id="str", cells=(
                ModuleBlockCell(field="name", kind="text", label="Сила"),
                ModuleBlockCell(field="value", kind="number", label="Сила",
                                min_value=1, max_value=30),
                ModuleBlockCell(field="prof", kind="switch",
                                name="Владение спасброском: Сила"),
            )),
        ),
    )


def _rich_frame(target, factory):
    return _frame(
        (
            _combo("cls"),
            _table_block(),
            ModuleBlock(kind="number", id="speed", label="Скорость",
                        anchor="after_music", value="", min_value=0,
                        max_value=999),
            ModuleBlock(kind="textline", id="sheet", label="Лист LSS",
                        anchor="after_music", value="",
                        placeholder="id цифрового листа Long Story Short"),
            ModuleBlock(kind="switch", id="profsw", label="Владение",
                        anchor="after_music"),
            ModuleBlock(kind="text", id="passive", label="Пассивная Внимательность",
                        anchor="after_music", value="12"),
            ModuleBlock(kind="buttons", id="doors", label="Лист LSS",
                        anchor="after_music",
                        actions=(ModuleBlockOption("lss", "Импорт из LSS"),
                                 ModuleBlockOption("fill", "Дозаполнить ИИ",
                                                   enabled=False))),
        ),
        ("characteristics", "backstory"),
        factory,
    )


def test_qml_paints_both_anchor_regions_with_stock_controls(qtbot, tmp_path):
    dialog, handler, republish_box = _card_with_source(_rich_frame, qtbot, tmp_path)
    dialog.populate(SimpleNamespace(id=9, name="Морфеус"))
    QApplication.processEvents()

    # The short-fields anchor: combo + table.
    assert find_item(dialog.quick, "entityModuleBlock_cls") is not None
    combo = find_item(dialog.quick, "moduleBlockCombo_cls")
    assert combo.property("model") == ["Чародей", "Жрец"]
    assert combo.property("currentIndex") == 0
    assert find_item(dialog.quick, "entityModuleBlock_abil") is not None
    assert find_item(dialog.quick, "moduleBlockRow_abil_str") is not None
    assert find_item(
        dialog.quick, "moduleBlockCellText_abil_str_name").property("text") == "Сила"
    assert find_item(dialog.quick, "moduleBlockCellNumber_abil_str_value") is not None

    # The after-music anchor: number, textline, switch, text, buttons.
    speed = find_item(dialog.quick, "moduleBlockNumber_speed")
    assert speed.property("text") == ""  # empty value prints the placeholder
    assert speed.property("placeholderText") == "не задано"
    sheet = find_item(dialog.quick, "moduleBlockTextline_sheet")
    assert sheet.property("text") == ""
    assert sheet.property("placeholderText") == "id цифрового листа Long Story Short"
    assert find_item(dialog.quick, "moduleBlockSwitch_profsw").property("checked") is False
    assert find_item(
        dialog.quick, "moduleBlockText_passive").property("text") == "12"
    assert find_item(
        dialog.quick, "moduleBlockAction_doors_lss").property("text") == "Импорт из LSS"
    assert find_item(dialog.quick, "moduleBlockAction_doors_fill").property(
        "enabled") is False  # a disabled option paints disabled

    # The hidden kernel rows left the grid; every other kernel row survived.
    for hidden in ("entityCharacteristicsLabel", "entityCharacteristicsField",
                   "entityCharacteristicsAiButton", "entityBackstoryField",
                   "entityBackstoryAiButton"):
        assert find_item(dialog.quick, hidden).property("visible") is False
    for kept in ("entityNameField", "entityMusicField", "entityStartDateField"):
        assert find_item(dialog.quick, kept).property("visible") is True


def test_qml_write_back_rides_the_real_triggers(qtbot, tmp_path):
    dialog, handler, republish_box = _card_with_source(_rich_frame, qtbot, tmp_path)
    dialog.populate(SimpleNamespace(id=9, name="Морфеус"))
    QApplication.processEvents()

    # The accessibility Press of a switch writes the FLIPPED MODEL value (Д15).
    _press(find_item(dialog.quick, "moduleBlockSwitch_profsw"))
    assert handler.writes[-1] == ("profsw", "value", True)

    # The Press of a block button commits its action id.
    _press(find_item(dialog.quick, "moduleBlockAction_doors_lss"))
    assert handler.writes[-1] == ("doors", "lss", True)

    # A number field commits on Enter, never per keystroke.
    speed = find_item(dialog.quick, "moduleBlockNumber_speed")
    speed.forceActiveFocus()
    QApplication.processEvents()
    QTest.keyClick(dialog.quick, Qt.Key.Key_3)
    QTest.keyClick(dialog.quick, Qt.Key.Key_0)
    QApplication.processEvents()
    assert ("speed", "value", "30") not in handler.writes  # still uncommitted
    QTest.keyClick(dialog.quick, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert handler.writes[-1] == ("speed", "value", "30")

    # The textline commits the same way — on Enter, never per keystroke.
    sheet = find_item(dialog.quick, "moduleBlockTextline_sheet")
    sheet.forceActiveFocus()
    QApplication.processEvents()
    QTest.keyClick(dialog.quick, Qt.Key.Key_7)
    QApplication.processEvents()
    assert ("sheet", "value", "7") not in handler.writes
    QTest.keyClick(dialog.quick, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert handler.writes[-1] == ("sheet", "value", "7")

    # A table cell writes under "<row id>.<field>".
    _press(find_item(dialog.quick, "moduleBlockCellSwitch_abil_str_prof"))
    assert handler.writes[-1] == ("abil", "str.prof", True)

    # The handler's republish moves the painted state (the tick follows the
    # frame, not the click).
    republish_box["fn"](
        tuple(
            ModuleBlock(kind="switch", id="profsw", label="Владение",
                        anchor="after_music", checked=True)
            if b.id == "profsw" else b
            for b in _rich_frame(None, lambda *a: handler).blocks
        ),
        ("characteristics", "backstory"),
    )
    QApplication.processEvents()
    assert find_item(
        dialog.quick, "moduleBlockSwitch_profsw").property("checked") is True


def test_event_dialog_carries_the_same_channel(qtbot, tmp_path):
    source = SimpleNamespace(
        visible=True,
        module_blocks=lambda target: _frame(
            (_combo("tag"), ModuleBlock(kind="text", id="tail", label="Хвост",
                                        anchor="after_music", value="х")),
        ),
    )
    dialog = EventDialog(None, theme=make_runtime(tmp_path, "dark"),
                         external_sources=[source])
    qtbot.addWidget(dialog)
    dialog.populate(SimpleNamespace(id=1, name="е"))
    QApplication.processEvents()
    assert find_item(dialog.quick, "eventModuleBlock_tag") is not None
    assert find_item(dialog.quick, "eventModuleBlockTail_tail") is not None
    # The event texts are NOT hidden (the frame hides nothing): the event's
    # own «Характеристики» stay exactly as they were.
    assert find_item(dialog.quick, "eventCharacteristicsField").property(
        "visible") is True


def test_plain_profile_has_an_empty_channel(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    dialog.populate(SimpleNamespace(id=2, name="c"))
    assert dialog.vm.moduleBlocks == []
    assert dialog.vm.hiddenFields == []
    # The write slot survives without a listener (the debug leg, no raise).
    dialog.vm.writeModuleBlock("nope", "value", 1)
