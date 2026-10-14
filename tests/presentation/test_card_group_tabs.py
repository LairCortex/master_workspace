"""Card grouping tabs — dormant in the kernel (dd-card-redesign task 3, spec
entity-card-tabs «Ядро рисует карточки одним экраном, табы приносит модуль»).

Three halves, all offscreen:

* the Qt-free strip state (``CardGroupState``): the kernel declares exactly
  one «Основное» entry — the whole 0.19.1 screen — the module tail still
  appends after it, the active-index rules and the field→group reveal hold,
  and a shortening tail falls back onto the kernel entry;
* both islands' Qt face: with the kernel alone the strip is HIDDEN and the
  card is the single screen; a guest tab wakes the strip, transfers the
  relations into the stitched bottom band (one instance in the tree, capped
  at a third of the window), and a refused save reveals (and marks) the
  kernel tab; the field itself keeps working through a switch because the
  pages are built once and only shown;
* the module-tab mechanism (``CardTabHost``): a stub source's ``CardTabSpec``
  lands after the kernel entry, the factory widget overlays the body slot the
  QML page publishes while its tab is active, ``release_tab`` + teardown
  retire it with the island, and a module that is absent / hidden / broken
  never disturbs the kernel (spec «Таб модуля живёт с модулем»);
* the late module frame and the window (live-audit 2026-10-13 blocker): when
  a controller republishes its loaded frame after the window opened, both
  tabbed windows regrow to the new ask so the stitched band and the buttons
  stay inside the window — while the single-screen kernel never refits.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from types import SimpleNamespace

import shiboken6
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtWidgets import QApplication, QWidget

from app.presentation.card_tab_groups import (
    GROUP_OVERVIEW,
    CardGroupState,
    group_key_for_field,
    kernel_card_groups,
)
from app.presentation.card_tab_host import CardTabHost
from app.presentation.modules.protocol import (
    CardTabSpec,
    ModuleBlock,
    ModuleBlockCell,
    ModuleBlockFrame,
    ModuleBlockRow,
)
from app.presentation.viewmodels.entity_card_island_view_model import (
    EntityCardIslandViewModel,
)
from app.presentation.viewmodels.event_dialog_island_view_model import (
    EventDialogIslandViewModel,
)
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from tests.presentation.qml_helpers import find_item, walk_items
from tests.ui.test_theme_grab import make_runtime


def _named(dialog, object_name: str):
    return [
        item
        for item in walk_items(dialog.quick.rootObject())
        if item.objectName() == object_name
    ]


# ── the Qt-free strip state ─────────────────────────────────────────────────


def test_kernel_declares_the_single_screen():
    kernel = kernel_card_groups()
    assert kernel == [{"key": GROUP_OVERVIEW, "title": "Основное"}]
    # Every validated kernel field lives on the one screen (the reveal rule
    # answers the single group for all of them, unknown names answer None).
    for field in ("name", "rating", "start_date", "end_date", "no_end", "image",
                  "age", "music_url", "hour", "minute", "event_type", "parent",
                  "characteristics", "backstory"):
        assert group_key_for_field(field) == GROUP_OVERVIEW
    assert group_key_for_field("nothing-like-this") is None


def test_state_module_tail_heads_after_kernel_and_shortening_falls_back():
    state = CardGroupState(kernel_card_groups())
    changed, active_changed = state.set_external_groups(
        [{"key": "dnd.sheet", "title": "Лист"}]
    )
    assert (changed, active_changed) == (True, False)
    assert [entry["key"] for entry in state.entries()] == [
        GROUP_OVERVIEW, "dnd.sheet",
    ]
    # Selecting the module tab, then the module tail empties: the reader is
    # returned to the kernel entry (the kernel never shifts).
    assert state.set_active(1)
    assert state.key_at(1) == "dnd.sheet"
    changed, active_changed = state.set_external_groups([])
    assert (changed, active_changed) == (True, True)
    assert state.active == 0
    assert [entry["key"] for entry in state.entries()] == [GROUP_OVERVIEW]
    # A no-op replacement stays silent (the populate echo must not churn).
    assert state.set_external_groups([]) == (False, False)


def test_state_absent_safe_moves_and_field_reveal():
    state = CardGroupState(kernel_card_groups())
    assert state.set_active(-1) is False
    assert state.set_active(99) is False
    assert state.key_at(99) is None
    assert state.set_active(0) is False  # already active
    # Every kernel field reveals the single screen…
    assert state.group_index_for_field("characteristics") == 0
    assert state.group_index_for_field("name") == 0
    assert state.group_index_for_field("nothing-like-this") is None
    assert state.kernel_count() == 1
    # …but the reveal is absent-safe: a mapped field on a strip that carries
    # no kernel entry at all (the defensive leg) reveals nothing.
    lone = CardGroupState([{"key": "dnd.sheet", "title": "Лист"}])
    assert lone.group_index_for_field("characteristics") is None


# ── the shared Qt face on both view models ──────────────────────────────────


def test_event_vm_strip_reveal_and_clear(qtbot):
    vm = EventDialogIslandViewModel(owner=object())
    assert vm.active_group_key() == GROUP_OVERVIEW
    assert [entry["key"] for entry in vm.groups] == [GROUP_OVERVIEW]
    assert vm.kernelCount == 1
    assert vm.moduleGroups == []
    emitted: list[str] = []
    vm.activeGroupChanged.connect(lambda: emitted.append("active"))
    vm.invalidatedFieldChanged.connect(lambda: emitted.append("invalid"))

    # On the single screen the reveal lands where the reader already is: the
    # active key never moves, only the mark is raised.
    vm.reveal_field("characteristics")
    assert vm.activeGroup == 0 and vm.activeGroupKey == GROUP_OVERVIEW
    assert vm.invalidatedField == "characteristics"
    # Re-revealing the same pair is silent (no echo at QML).
    vm.reveal_field("characteristics")
    assert emitted == ["invalid"]
    vm.clear_invalidated_field()
    assert vm.invalidatedField == ""
    assert emitted == ["invalid", "invalid"]
    # Clearing an already-clear mark is silent too.
    vm.clear_invalidated_field()
    assert emitted == ["invalid", "invalid"]

    # A guest tab joins: the module tail is visible to QML as its own list,
    # the reveal from a guest tab walks back onto the kernel screen.
    vm.set_external_groups([{"key": "dnd.sheet", "title": "Лист"}])
    assert [entry["key"] for entry in vm.moduleGroups] == ["dnd.sheet"]
    vm.selectGroup(1)
    assert vm.activeGroupKey == "dnd.sheet"
    vm.reveal_field("characteristics")
    assert vm.activeGroup == 0
    assert emitted.count("active") == 2  # guest tab + the reveal back
    # An out-of-strip selection changes nothing.
    vm.selectGroup(77)
    assert vm.activeGroup == 0
    # reportBodyRect relays AND stamps the last rect (DND-LIVE-1: the host
    # may only subscribe after the island's final publish).
    seen: list[tuple] = []
    vm.bodyRectChanged.connect(lambda *a: seen.append(a))
    vm.reportBodyRect(1.0, 2.0, 300.0, 400.0)
    assert seen == [(1.0, 2.0, 300.0, 400.0)]
    assert vm.last_body_rect() == (1.0, 2.0, 300.0, 400.0)


def test_entity_vm_strip_matches_type_relations(qtbot):
    # The single screen is every type's screen: relations or not, the kernel
    # answers the one «Основное» entry (the D1 rollback of the trio/pair).
    vm = EntityCardIslandViewModel("character", [], [], owner=object())
    assert [entry["key"] for entry in vm.groups] == [GROUP_OVERVIEW]
    rating = EntityCardIslandViewModel("rating", [], [], owner=object())
    assert [entry["key"] for entry in rating.groups] == [GROUP_OVERVIEW]
    # The reveal moves nothing on the single screen and marks the field.
    rating.reveal_field("characteristics")
    assert rating.active_group_key() == GROUP_OVERVIEW
    assert rating.invalidatedField == "characteristics"
    # An unknown field name reveals nothing, moves nothing, and does not
    # clobber the mark that is already up.
    rating.reveal_field("no-such-field")
    assert rating.invalidatedField == "characteristics"
    assert rating.active_group_key() == GROUP_OVERVIEW


# ── the islands: one screen alone, strip + band only with guest tabs ────────


def test_event_dialog_alone_is_the_single_screen(qtbot, tmp_path):
    dialog = EventDialog(None, theme=make_runtime(tmp_path, "dark"))
    qtbot.addWidget(dialog)
    strip = find_item(dialog.quick, "eventGroupTabs")
    assert strip.property("visible") is False  # the strip sleeps
    # The 0.19.1 form fills the body and the relations ride their own seat
    # under it — one instance each, no band yet.
    assert find_item(dialog.quick, "eventKernelPage") is not None
    assert len(_named(dialog, "eventRelatedTabs")) == 1
    assert len(_named(dialog, "organizationsRelatedSection")) == 1
    assert find_item(dialog.quick, "eventRelationsSingle").property("active") is True
    assert find_item(dialog.quick, "eventRelationsBand").property("active") is False

    # The body slot is published (task 7.2 dependency): a non-empty rect the
    # host can overlay onto was reported at least once.
    published: list[tuple] = []
    dialog.vm.bodyRectChanged.connect(lambda *a: published.append(a))
    body = find_item(dialog.quick, "eventGroupBody")
    body.setWidth(body.width() + 1)
    assert published and published[-1][2] > 0 and published[-1][3] > 0

    # «Ошибка указывает дорогу» on the single screen: an empty name marks the
    # name caption right where the reader stands.
    saves: list[object] = []
    dialog.saved.connect(saves.append)
    dialog.vm.requestSave()
    assert dialog.vm.active_group_key() == GROUP_OVERVIEW
    assert dialog.vm.invalidatedField == "name"
    assert saves == []  # nothing saved (valid gate)
    root = dialog.quick.rootObject()
    label = find_item(dialog.quick, "eventNameLabel")
    assert label.property("color") == root.property("accentColor")


def test_event_dialog_guest_tab_wakes_strip_and_band(qtbot, tmp_path):
    dialog = EventDialog(None, theme=make_runtime(tmp_path, "dark"))
    qtbot.addWidget(dialog)
    strip = find_item(dialog.quick, "eventGroupTabs")
    dialog.vm.set_external_groups([{"key": "dnd.sheet", "title": "Лист"}])
    QApplication.processEvents()

    assert strip.property("visible") is True
    tabs = sorted(
        (
            item
            for item in walk_items(strip)
            if item.metaObject().className().startswith("ThemeTabButton")
        ),
        key=lambda item: item.x(),
    )
    assert [tab.property("text") for tab in tabs] == ["Основное", "Лист"]
    for tab, key in zip(tabs, (GROUP_OVERVIEW, "dnd.sheet")):
        assert tab.objectName() == f"eventGroupTab_{key}"
    # Equal shares — the library bar law holds for this consumer too.
    assert tabs[0].width() > 0
    assert max(tab.width() for tab in tabs) - min(tab.width() for tab in tabs) <= 1

    # The relations transfer to the stitched band: still ONE instance in the
    # tree (the seats are mutually exclusive), the band carries it now, and
    # it is capped at a third of the window (spec «полоса… не больше трети»).
    root = dialog.quick.rootObject()
    assert len(_named(dialog, "eventRelatedTabs")) == 1
    assert len(_named(dialog, "organizationsRelatedSection")) == 1
    band = find_item(dialog.quick, "eventRelationsBand")
    assert band.property("active") is True
    assert find_item(dialog.quick, "eventRelationsSingle").property("active") is False
    assert band.height() <= root.height() / 3 + 1

    # Switching onto the guest tab never hides the band, and the sections
    # stayed alive through the transfer (built once, not rebuilt).
    dialog.vm.selectGroup(1)
    assert band.property("active") is True
    assert band.height() > 0
    guest_page = _named(dialog, "eventGroupPage_dnd.sheet")
    assert len(guest_page) == 1
    assert find_item(dialog.quick, "eventKernelPage").property("visible") is False


def test_entity_card_qml_input_survives_switch_and_save_reads_hidden_tab(qtbot, tmp_path):
    dialog = EntityCardDialog(
        None, "character", theme=make_runtime(tmp_path, "dark")
    )
    qtbot.addWidget(dialog)
    root = dialog.quick.rootObject()
    strip = find_item(dialog.quick, "entityGroupTabs")
    assert strip.property("visible") is False  # alone: no strip at all

    name_field = find_item(dialog.quick, "entityNameField")
    name_field.setProperty("text", "Морфеус")
    chars_field = find_item(dialog.quick, "entityCharacteristicsField")
    chars_field.setProperty("text", "Архитектор")
    QApplication.processEvents()
    assert dialog.vm.name == "Морфеус"

    # A guest tab wakes the strip; input entered on the single screen is
    # intact after a round trip through the guest page (the pages are built
    # once — the switch only moves the visible page, spec «Ввод переживает
    # смену таба»). The relations moved to the band and are still one.
    dialog.vm.set_external_groups([{"key": "dnd.sheet", "title": "Лист"}])
    QApplication.processEvents()
    assert strip.property("visible") is True
    band = find_item(dialog.quick, "entityRelationsBand")
    assert band.property("active") is True
    assert band.height() <= root.height() / 3 + 1
    assert len(_named(dialog, "entityRelatedTabs")) == 1
    assert find_item(dialog.quick, "entityRelationsInScroll").property("active") is False
    dialog.vm.selectGroup(1)
    dialog.vm.selectGroup(0)
    assert name_field.property("text") == "Морфеус"
    assert chars_field.property("text") == "Архитектор"

    # A save issued while the guest tab is up still reads every field into
    # the result (the field values live in the VM, not on screen).
    assert dialog.vm.saveEnabled
    assert find_item(dialog.quick, "entityCharacteristicsLabel").property(
        "color"
    ) != root.property("accentColor")
    dialog.vm.requestSave()
    data = dialog.get_data()
    assert data["name"] == "Морфеус"
    assert data["characteristics"] == "Архитектор"


def test_event_dialog_reveal_marks_the_offending_field(qtbot, tmp_path):
    dialog = EventDialog(None, theme=make_runtime(tmp_path, "dark"))
    qtbot.addWidget(dialog)
    root = dialog.quick.rootObject()
    dialog.vm.name = "Погоня"  # name whole; the empty-text pair offends
    dialog.vm.requestSave()
    assert dialog.vm.invalidatedField == "characteristics"
    assert dialog.vm.active_group_key() == GROUP_OVERVIEW
    label = find_item(dialog.quick, "eventCharacteristicsLabel")
    assert label.property("color") == root.property("accentColor")
    # Filling one of the pair restores validity and the next save clears the
    # mark (an accepted attempt leaves no highlight behind).
    dialog.vm.characteristicsHost.storage = "Догоним"
    assert dialog.vm.valid
    dialog.vm.requestSave()
    assert dialog.vm.invalidatedField == ""


def test_event_dialog_end_date_offender_and_lock_names_nothing(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.vm.name = "Осада"
    dialog.vm.characteristicsHost.storage = "Текст"
    dialog.vm.set_dates(
        start=date(2025, 5, 5), end=date(2025, 5, 1), start_bc=False, end_bc=False
    )
    dialog.vm.requestSave()
    assert dialog.vm.invalidatedField == "end_date"
    assert dialog.vm.active_group_key() == GROUP_OVERVIEW  # the dates live here
    # A refusal caused by the save lock is not a field problem: no mark
    # appears, nothing saves. (First an accepted save washes the end_date
    # mark away — the mark only ever clears on success.)
    dialog.vm.set_dates(end=date(2025, 5, 9))
    assert dialog.vm.valid
    saves: list[object] = []
    dialog.saved.connect(saves.append)
    dialog.vm.requestSave()
    assert len(saves) == 1 and dialog.vm.invalidatedField == ""
    dialog.vm.set_save_locked(True)
    dialog.vm.requestSave()
    assert len(saves) == 1  # the lock refused the attempt
    assert dialog.vm.invalidatedField == ""
    assert dialog.vm.active_group_key() == GROUP_OVERVIEW  # stayed where it was


def test_card_reveal_marks_name_and_accepted_save_clears(qtbot):
    dialog = EntityCardDialog(None, "item")
    qtbot.addWidget(dialog)
    saves: list[object] = []
    dialog.saved.connect(saves.append)
    dialog.vm.requestSave()  # empty name on the single screen
    assert dialog.vm.active_group_key() == GROUP_OVERVIEW
    assert dialog.vm.invalidatedField == "name"
    assert saves == []
    dialog.vm.name = "Кольцо"
    dialog.vm.requestSave()
    assert len(saves) == 1  # saveRequested reached the facade
    assert dialog.vm.invalidatedField == ""


def test_relations_seat_transfer_keeps_the_reader_where_they_were(qtbot):
    # Task 3.3 («сохранение скролла/фокуса»): moving the strip between the
    # scroll seat and the band seat swaps the Loader item, but the relations
    # tab the reader had opened rides the root mirror and seats again — the
    # transfer never silently drops the reader back to «Организации».
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    tabs = find_item(dialog.quick, "eventRelatedTabs")
    tabs.setProperty("currentIndex", 2)
    QApplication.processEvents()
    assert tabs.property("currentIndex") == 2
    dialog.vm.set_external_groups([{"key": "dnd.sheet", "title": "Лист"}])
    QApplication.processEvents()
    band_tabs = find_item(dialog.quick, "eventRelatedTabs")
    assert band_tabs.property("currentIndex") == 2
    assert [
        bool(t.property("checked"))
        for t in sorted(
            (
                item
                for item in walk_items(band_tabs)
                if item.metaObject().className().startswith("ThemeTabButton")
            ),
            key=lambda item: item.x(),
        )
    ] == [False, False, True, False]


# ── the seats' real geometry in the kernel profile (live audit 2026-10-13) ──
#
# The live audit found both single-screen windows broken while every flag
# above stayed green: the sleeping stitched-band Loader stays a VISIBLE
# 0-size item, so QQuickLayout kept honouring its ``Layout.preferredHeight``
# of 230 px even with the seat inactive. In the event dialog that ghost
# collapsed the live relations seat to height 0 and dropped «Сохранить»/
# «Отмена» below the pinned 620 window (they survived only as the Enter
# default); in the entity card it ate 230 px of the scroll viewport and the
# relations end hung below the fold — and the in-scroll Loader, unlike the
# 0.19.1 direct-child seat, floor-sized itself to the block's natural width
# (794 px through a 760 px card). These pins read the geometry the flags
# cannot see: visibility, height, width and the scene coordinates.


def _flickable_of(qt_view, scroll):
    return next(
        item
        for item in walk_items(scroll)
        if "Flickable" in item.metaObject().className()
    )


def test_kernel_event_screen_holds_relations_and_buttons_inside_the_window(qtbot):
    # Blocker 1: at the pinned 720×620 the single screen must contain, with
    # no scrolling, the relations seat AND the action row (the 0.19.1
    # posture — the event form never scrolled and never will).
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(50)
    root = dialog.quick.rootObject()

    # The stitched band sleeps OUT of the layout, not just out of content.
    band = find_item(dialog.quick, "eventRelationsBand")
    assert band.property("visible") is False
    assert band.height() == 0

    # The 0.19.1 seat is the live one and wears a real box.
    seat = find_item(dialog.quick, "eventRelationsSingle")
    assert seat.property("visible") is True
    assert seat.height() > 0

    tabs = find_item(dialog.quick, "eventRelatedTabs")
    tabs_bottom = tabs.mapToScene(QPointF(0, tabs.height())).y()
    assert tabs_bottom <= root.height()
    for name in ("eventSaveButton", "eventCancelButton"):
        button = find_item(dialog.quick, name)
        origin = button.mapToScene(QPointF(0, 0))
        assert origin.y() >= tabs_bottom - 1, name  # buttons under the strip
        assert origin.y() + button.height() <= root.height() + 1, name
        assert origin.x() + button.width() <= root.width() + 1, name


def test_kernel_card_scroll_end_reveals_the_whole_relations_block(qtbot):
    # Blocker 2: the strip sits at the END OF THE SCROLL with working
    # geometry — the band no longer steals viewport, the seat keeps its
    # 0.19.1 height and wears the scroll's width, never its own natural.
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(50)
    root = dialog.quick.rootObject()

    band = find_item(dialog.quick, "entityRelationsBand")
    assert band.property("visible") is False
    assert band.height() == 0

    seat = find_item(dialog.quick, "entityRelationsInScroll")
    assert seat.property("visible") is True
    assert seat.height() == root.property("relationsNatural")
    scroll = find_item(dialog.quick, "entityCardScroll")
    available = scroll.property("availableWidth")
    assert 0 < seat.width() <= available + 1
    origin = seat.mapToScene(QPointF(0, 0))
    assert origin.x() + seat.width() <= root.width() + 1

    # At the size the scene itself publishes the whole screen fits at once
    # (the 0.19.1 posture): relations included, no scroll needed; on a short
    # offscreen screen the scroll at least reveals the block completely.
    dialog.resize(int(root.implicitWidth()), int(root.implicitHeight()))
    qtbot.wait(50)
    flick = _flickable_of(dialog.quick, scroll)
    if flick.property("contentHeight") > flick.height():
        flick.setProperty(
            "contentY", flick.property("contentHeight") - flick.height()
        )
        qtbot.wait(50)
    scroll_bottom = scroll.mapToScene(QPointF(0, 0)).y() + scroll.height()
    for item in walk_items(root):
        if item.objectName().startswith("entityRelatedSection_") and item.property(
            "visible"
        ):
            bottom = item.mapToScene(QPointF(0, item.height())).y()
            assert bottom <= scroll_bottom + 1
            for button in (i for i in walk_items(item) if i.property("visible")):
                if button.objectName().endswith(("LinkButton", "UnlinkButton")):
                    button_bottom = button.mapToScene(
                        QPointF(0, button.height())
                    ).y()
                    assert button_bottom <= root.height() + 1


def test_kernel_card_without_sections_keeps_the_seat_out_of_the_scroll(qtbot):
    # The same ghost class, the type without sections: an inactive scroll
    # seat must not stretch the content with its preferred 230 px either.
    dialog = EntityCardDialog(None, "rating")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(50)
    seat = find_item(dialog.quick, "entityRelationsInScroll")
    assert seat.property("active") is False
    assert seat.property("visible") is False
    assert seat.height() == 0


# ── the module-tab mechanism ────────────────────────────────────────────────


class _TabWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.released = 0

    def release_tab(self) -> None:
        self.released += 1


class _Source:
    visible = True

    def __init__(self, keys=(), *, raises=False):
        self.specs = [
            CardTabSpec(key=key, title=f"Таб {key}", factory=None) for key in keys
        ]
        self._raises = raises
        self.built: list[tuple[object, str]] = []

    def card_tabs(self, target):
        if self._raises:
            raise RuntimeError("источник сломан")
        self.last_target = target

        def factory(wiring, source_id):
            self.built.append((wiring, source_id))
            return _TabWidget()

        return tuple(dataclasses.replace(spec, factory=factory) for spec in self.specs)


def _host(dialog, sources, key="event"):
    return CardTabHost(dialog, dialog.vm, sources, "WIRING", target_key=key)


def test_host_appends_after_kernel_overlays_and_releases(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    kernel = [entry["key"] for entry in dialog.vm.groups]
    assert kernel == [GROUP_OVERVIEW]
    source = _Source(["dnd.sheet"])
    host = _host(dialog, [source])
    # A card that edits nothing IS collected: the empty id is a target the
    # source answers (spec «Пустое событие тоже с двумя табами» / «Новая
    # карточка с пустыми разделами») — the tab stands with its widget
    # built on the empty id and hidden.
    host.refresh(None)
    assert source.last_target.source_id == ""
    assert [entry["key"] for entry in dialog.vm.groups] == kernel + ["dnd.sheet"]
    fresh = next(iter(dialog.findChildren(_TabWidget)))
    assert source.built == [("WIRING", "")]
    # The record is known: the fresh widget retires, the tab rebuilds on
    # (wiring, source_id), parented to the dialog and hidden.
    host.refresh("42")
    assert fresh.released == 1
    assert source.last_target.key == "event" and source.last_target.source_id == "42"
    assert [entry["key"] for entry in dialog.vm.groups] == kernel + ["dnd.sheet"]
    widget = next(iter(dialog.findChildren(_TabWidget)))
    assert widget is not fresh
    assert widget.parent() is dialog
    assert widget.isVisible() is False
    assert source.built == [("WIRING", ""), ("WIRING", "42")]

    # The QML page publishes its body slot when the scene lays out; while
    # the module tab is active the widget overlays that slot, hidden away
    # otherwise, and the card itself keeps working.
    dialog.show()
    QApplication.processEvents()
    dialog.vm.selectGroup(1)
    assert widget.isVisible() is True
    assert widget.width() > 0 and widget.height() > 0
    dialog.vm.selectGroup(0)
    assert widget.isVisible() is False

    # Teardown: release_tab ran once, the widget left the window, and the
    # release is idempotent (the close routes may schedule it twice).
    host.release()
    assert widget.released == 1
    assert widget.parent() is None
    host.release()
    assert widget.released == 1


def test_host_seeds_the_body_rect_published_before_it_subscribed(qtbot):
    # DND-LIVE-1 (live cocoa defect, strip fixed but overlay dead): the QML
    # page publishes its body slot during the island load, while the dialog
    # builds this host only after setup_island. A sheet opening at its final
    # size never republishes, so the host must replay the VM's last stamp —
    # the overlay knows its slot with no later emit and no show.
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    published = dialog.vm.last_body_rect()  # filled by the island's load
    assert published is not None and published[2] > 0 and published[3] > 0
    host = _host(dialog, [_Source(["dnd.sheet"])])
    host.refresh("42")
    widget = next(iter(dialog.findChildren(_TabWidget)))
    dialog.vm.selectGroup(1)
    assert widget.isVisibleTo(dialog)  # placed from the cache, not a new emit
    assert not widget.geometry().isEmpty()
    host.release()


def test_host_without_a_published_rect_waits_for_the_next_one(qtbot):
    # The mirror leg: a page that has not published yet leaves the module
    # tab hidden, and the first live publish places it. The stub dialog maps
    # to itself (quick is the dialog), so the rect lands unchanged.
    vm = EventDialogIslandViewModel(owner=object())
    dialog = QWidget()
    dialog.quick = dialog
    qtbot.addWidget(dialog)
    host = CardTabHost(
        dialog, vm, [_Source(["dnd.sheet"])], "WIRING", target_key="event"
    )
    host.refresh("42")
    widget = next(iter(dialog.findChildren(_TabWidget)))
    vm.selectGroup(1)
    assert not widget.isVisibleTo(dialog)
    vm.reportBodyRect(10.0, 20.0, 300.0, 400.0)
    assert widget.isVisibleTo(dialog)
    assert widget.geometry() == QRect(10, 20, 300, 400)
    host.release()


def test_host_module_off_returns_the_single_screen(qtbot):
    # A module switched off mid-life: its source goes not-visible (the
    # detach the façade propagates), the tab leaves the strip, its widget
    # releases and departs, the card returns to the single screen with the
    # strip asleep (spec entity-card-tabs «Таб модуля живёт с модулем»).
    # The off switch is the SOURCE's answer, never the empty target — a
    # fresh card under a LIVE module collects its tabs (checkpoint-2 audit).
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    source = _Source(["dnd.sheet"])
    host = _host(dialog, [source])
    host.refresh("42")
    widget = next(iter(dialog.findChildren(_TabWidget)))
    dialog.vm.selectGroup(1)  # active on the tab about to disappear
    source.visible = False  # the detach
    host.refresh("42")
    QApplication.processEvents()
    assert widget.released == 1
    assert widget.parent() is None
    assert [entry["key"] for entry in dialog.vm.groups] == [GROUP_OVERVIEW]
    assert dialog.vm.active_group_key() == GROUP_OVERVIEW
    strip = find_item(dialog.quick, "eventGroupTabs")
    assert strip.property("visible") is False
    # The relations ride back into their 0.19.1 seat with the strip asleep.
    assert find_item(dialog.quick, "eventRelationsBand").property("active") is False
    assert find_item(dialog.quick, "eventRelationsSingle").property("active") is True
    assert len(_named(dialog, "eventRelatedTabs")) == 1
    host.release()


def test_host_broken_and_hidden_sources_never_move_the_kernel(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    kernel = [entry["key"] for entry in dialog.vm.groups]

    broken = _Source(["bad"], raises=True)
    host = _host(dialog, [broken], key="character")
    host.refresh("7")
    assert [entry["key"] for entry in dialog.vm.groups] == kernel  # survived

    hidden = _Source(["gone"])
    hidden.visible = False
    host2 = _host(dialog, [hidden], key="character")
    host2.refresh("7")
    assert [entry["key"] for entry in dialog.vm.groups] == kernel

    # A factory that answers a non-widget (or raises) drops its tab only;
    # the first source wins a duplicated key.
    def bad_factory(wiring, source_id):
        return "не виджет"

    def raising_factory(wiring, source_id):
        raise RuntimeError("нет виджета")

    class _FixedSource:
        visible = True

        def card_tabs(self, target):
            return (
                CardTabSpec(key="bad.one", title="ошибка типа", factory=bad_factory),
                CardTabSpec(key="bad.two", title="ошибка сборки", factory=raising_factory),
            )

    host3 = _host(dialog, [_FixedSource()], key="character")
    host3.refresh("7")
    assert [entry["key"] for entry in dialog.vm.groups] == kernel
    # A source that answers None (not every source speaks tabs).
    quiet = SimpleNamespace(visible=True, card_tabs=lambda target: None)
    host4 = _host(dialog, [quiet], key="character")
    host4.refresh("7")
    assert [entry["key"] for entry in dialog.vm.groups] == kernel
    for h in (host, host2, host3, host4):
        h.release()


def test_plain_profile_cards_are_single_screen(qtbot):
    # The kernel profile passes no external sources at all (the module-off
    # route): both dialogs populate/refresh with an empty tuple, every type
    # keeps the one «Основное» entry and the strip stays asleep —
    # «табы dd не видны в ядре/без модуля», «карточки неотличимы от 0.19.1».
    event = EventDialog(None)
    qtbot.addWidget(event)
    event.populate(SimpleNamespace(id=1, name="e"))
    assert [entry["key"] for entry in event.vm.groups] == [GROUP_OVERVIEW]
    assert find_item(event.quick, "eventGroupTabs").property("visible") is False
    assert find_item(event.quick, "eventRelationsBand").property("active") is False
    card = EntityCardDialog(None, "character")
    qtbot.addWidget(card)
    card.populate(SimpleNamespace(id=2, name="c"))
    assert [entry["key"] for entry in card.vm.groups] == [GROUP_OVERVIEW]
    assert find_item(card.quick, "entityGroupTabs").property("visible") is False
    assert find_item(card.quick, "entityRelationsBand").property("active") is False
    rating = EntityCardDialog(None, "rating")
    qtbot.addWidget(rating)
    rating.populate(SimpleNamespace(id=3, name="r"))
    assert [entry["key"] for entry in rating.vm.groups] == [GROUP_OVERVIEW]
    assert find_item(rating.quick, "entityGroupTabs").property("visible") is False


def test_host_duplicate_key_first_source_wins_and_raise_release_survives(qtbot):
    class _RaisingWidget(QWidget):
        def release_tab(self) -> None:
            raise RuntimeError("таб не отпускает")

    def factory(wiring, source_id):
        return _RaisingWidget()

    class _Dup:
        visible = True

        def __init__(self, tag):
            self.tag = tag

        def card_tabs(self, target):
            return (CardTabSpec(key="dup", title=self.tag, factory=factory),)

    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    host = _host(dialog, [_Dup("первый"), _Dup("второй")])
    host.refresh("5")
    titles = [entry["title"] for entry in dialog.vm.groups]
    assert "первый" in titles and "второй" not in titles
    assert len(dialog.findChildren(_RaisingWidget)) == 1
    # Teardown never raises even when the widget's own release does.
    host.release()
    assert dialog.findChildren(_RaisingWidget) == []


def test_host_release_after_the_vm_died_still_frees_the_widget(qtbot):
    # The island teardown can race the scene: the VM's C++ side may already
    # be gone when release() disconnects. The widget must still leave.
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    source = _Source(["dnd.sheet"])
    host = _host(dialog, [source])
    host.refresh("1")
    widget = next(iter(dialog.findChildren(_TabWidget)))
    shiboken6.delete(dialog.vm)
    host.release()
    assert widget.released == 1
    assert widget.parent() is None


def test_card_module_tab_follows_the_populated_record(qtbot):
    # The dialog facade drives the host: the construction-time collection
    # stands the module lineup on a fresh card (spec «Новая карточка с
    # пустыми разделами»), and populate() re-aims it at the record being
    # edited — the fresh-id widget retires, the record's widget takes its
    # place, the strip never grows a second module tail.
    dialog = EntityCardDialog(
        None,
        "character",
        external_sources=[_Source(["dnd.sheet"])],
    )
    qtbot.addWidget(dialog)
    assert [entry["key"] for entry in dialog.vm.groups] == [
        GROUP_OVERVIEW,
        "dnd.sheet",
    ]
    fresh = dialog.findChildren(_TabWidget)[0]
    dialog.populate(SimpleNamespace(id=9, name="Тринити"))
    assert [entry["key"] for entry in dialog.vm.groups] == [
        GROUP_OVERVIEW,
        "dnd.sheet",
    ]
    assert fresh.released == 1
    widgets = dialog.findChildren(_TabWidget)
    assert len(widgets) == 1
    # Re-populate onto another record: the old widget is released exactly
    # once and replaced, the strip never grows a second module tail.
    dialog.populate(SimpleNamespace(id=10, name="Нео"))
    assert widgets[0].released == 1
    assert [entry["key"] for entry in dialog.vm.groups] == [
        GROUP_OVERVIEW,
        "dnd.sheet",
    ]
    assert len(dialog.findChildren(_TabWidget)) == 1


def test_save_hooks_collect_the_staged_writers_in_tab_order(qtbot):
    """add-dnd-game-face task 11.1 (design Д10): the connector's save flow
    asks the host for the module tabs' staged writes. A widget answering the
    duck door ``save_tab`` contributes its bound callable in tab order; the
    write-through tabs (``_TabWidget`` above — the character tabs' shape)
    carry no door and contribute nothing; after ``release`` nobody is left
    to write."""

    class _StagingWidget(_TabWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.saved = 0

        async def save_tab(self) -> None:
            self.saved += 1

    class _MixedSource(_Source):
        def __init__(self, widgets):
            super().__init__(tuple(f"k{i}" for i in range(len(widgets))))
            self._widgets = list(widgets)

        def card_tabs(self, target):
            specs = super().card_tabs(target)

            def factory(wiring, source_id, _i=[0]):
                widget = self._widgets[_i[0]]
                _i[0] += 1
                return widget

            return tuple(
                dataclasses.replace(spec, factory=factory)
                for spec in specs
            )

    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    host = _host(dialog, [])
    assert host.save_hooks() == ()  # kernel-only cards stage nothing

    first, plain, second = _StagingWidget(), _TabWidget(), _StagingWidget()
    host = _host(dialog, [_MixedSource([first, plain, second])])
    host.refresh("42")
    hooks = host.save_hooks()
    assert len(hooks) == 2  # the write-through tab contributes nothing
    assert {id(h.__self__) for h in hooks} == {id(first), id(second)}

    # The dialog's forwarding door (EventDialog.external_tab_saves) is a
    # plain pass-through of the host's tuple — the connector never reaches
    # into the host's widget bookkeeping (the tuple identity is the pin).
    sentinel = ("hook",)
    # The stub answers the dialog's whole host surface — the close path in
    # this test's teardown knocks on it too.
    dialog._card_tabs = SimpleNamespace(
        save_hooks=lambda: sentinel,
        refresh=lambda target: None,
        release=lambda: None,
    )
    assert dialog.external_tab_saves() == sentinel

    host.release()
    assert host.save_hooks() == ()


def test_module_tab_join_and_leave_keep_the_strip_painting(qtbot, tmp_path):
    # DND-LIVE-1 (2026-10-10 live audit): the module tab joining REPLACES the
    # usage Repeater's model, and on the hand-laid bar this stranded the
    # whole strip render subtree — the accessibility face stayed complete
    # while the band printed no pixels from the first frame. dd-card-redesign
    # adds a second face to the same churn: alone the strip is HIDDEN (no
    # pixels expected), with the guest tab it must paint again, and leaving
    # must put it back to sleep. The hairline every tab draws along the
    # band's bottom is the painted witness: at least strip-width device
    # pixels must differ from the surface token color in the band region.
    def band_hits(dialog) -> tuple[int, float]:
        root = dialog.quick.rootObject()
        strip = find_item(dialog.quick, "eventGroupTabs")
        img = dialog.grab().toImage()
        surface = img.pixelColor(4, 4)
        off = dialog.quick.mapTo(dialog, dialog.quick.rect().topLeft())
        top = strip.mapToItem(root, 0, 0).y()
        y0 = int(top + off.y()) - 4
        y1 = int(top + off.y() + strip.height() + 4)
        hits = sum(
            1
            for y in range(max(y0, 0), min(y1, img.height()))
            for x in range(img.width())
            if img.pixelColor(x, y) != surface
        )
        return hits, strip.width() * (img.width() / max(dialog.width(), 1))

    source = _Source(["dnd.sheet"])
    dialog = EventDialog(
        None, theme=make_runtime(tmp_path, "dark"), external_sources=[]
    )
    qtbot.addWidget(dialog)
    host = _host(dialog, [source])
    dialog.show()
    qtbot.wait(50)
    strip = find_item(dialog.quick, "eventGroupTabs")
    assert strip.property("visible") is False  # kernel alone: the strip sleeps

    def tab_texts():
        return [
            tab.property("text")
            for tab in sorted(
                (
                    item
                    for item in walk_items(strip)
                    if item.metaObject().className().startswith("ThemeTabButton")
                ),
                key=lambda item: item.x(),
            )
        ]

    # The join: the strip wakes with «Основное» + «Таб dnd.sheet» and the
    # band must paint — this exact leg measured zero pixels on the broken bar.
    host.refresh("42")
    qtbot.wait(50)
    assert strip.property("visible") is True
    assert tab_texts() == ["Основное", "Таб dnd.sheet"]
    hits, floor = band_hits(dialog)
    assert hits >= floor

    # The module tab leaving puts the strip back to sleep (the single screen
    # carries no strip region at all). Leaving is the detach — the source
    # goes not-visible (spec «Таб модуля живёт с модулем»); under the fixed
    # contract an empty target is a real target and collects. Joining again
    # re-runs the churn and every frame of it paints.
    source.visible = False
    host.refresh("42")
    qtbot.wait(50)
    assert strip.property("visible") is False

    source.visible = True
    host.refresh("42")
    qtbot.wait(50)
    assert tab_texts() == ["Основное", "Таб dnd.sheet"]
    hits, floor = band_hits(dialog)
    assert hits >= floor


# ── the late module frame and the window (live-audit 2026-10-13 blocker) ─────


def _tall_table(rows: int = 24) -> ModuleBlock:
    """A loaded controller answer: the tall module table the live card grew by."""
    return ModuleBlock(
        kind="table",
        id="skills",
        label="Навыки",
        anchor="after_short_fields",
        columns=("Навык", "Мод"),
        rows=tuple(
            ModuleBlockRow(
                id=f"row{i}",
                cells=(
                    ModuleBlockCell(field=f"n{i}", kind="text", label=f"Навык {i}"),
                    ModuleBlockCell(field=f"m{i}", kind="number", value=str(i % 5)),
                ),
            )
            for i in range(rows)
        ),
    )


class _LateFrameSource:
    """The real controller's posture (DND-LIVE): the construction-time answer
    hides the module's kernel texts but the rows load later — the frame is
    republished for the saved record, after the window opened."""

    visible = True

    def __init__(self, key: str, tab: str) -> None:
        self._key = key
        self._tab = tab
        self._tall = _tall_table()

    def card_tabs(self, target):
        if target.key != self._key:
            return ()

        def factory(wiring, source_id):
            return _TabWidget()

        return (
            CardTabSpec(
                key=f"dnd.{self._tab}",
                title=f"Таб {self._tab}",
                factory=factory,
            ),
        )

    def module_blocks(self, target):
        if target.source_id == "":
            return ModuleBlockFrame(hidden_fields=("characteristics", "backstory"))
        return ModuleBlockFrame(
            blocks=(self._tall,),
            hidden_fields=("characteristics", "backstory"),
        )


def test_late_module_frame_regrows_the_card_window(qtbot, tmp_path, monkeypatch):
    # Spec «Размер окна с табами следует самому высокому содержимому плюс
    # полосу связей и кнопки», live blocker of 2026-10-13: the loaded frame
    # arrives while the sheet is already up; the ask doubles (the live card:
    # 1116 → 1440). If the window stays where the constructor fitted it, the
    # scene takes the new height for itself (cocoa) and the stitched band
    # with «Сохранить»/«Отмена» falls off the bottom edge — on every tab.
    # The offscreen screen caps at 720, below both asks, so the test lifts
    # the screen cap — growth itself is the half the offscreen suite can pin.
    from app.presentation.qml import island_size

    monkeypatch.setattr(
        island_size, "_screen_limit", lambda dialog: QSize(10000, 4000)
    )
    dialog = EntityCardDialog(
        None,
        "character",
        theme=make_runtime(tmp_path, "dark"),
        external_sources=[_LateFrameSource("character", "sheet")],
    )
    qtbot.addWidget(dialog)
    dialog.show()
    QApplication.processEvents()
    assert dialog.vm.moduleGroups  # the tabbed assembly is up
    h0 = dialog.height()
    root = dialog.quick.rootObject()
    assert abs(h0 - root.implicitHeight()) <= 1  # the opening fit settled on the ask

    dialog.populate(
        SimpleNamespace(
            id=7,
            name="QA Проверщик",
            rating=1,
            characteristics="",
            backstory="",
            personality="",
            tasks="",
            music_url="",
            image_id=None,
        )
    )
    QApplication.processEvents()
    QApplication.processEvents()

    h1 = dialog.height()
    assert h1 > h0  # the window followed the late frame's ask
    assert abs(h1 - root.implicitHeight()) <= 1
    for name in ("entityRelationsBand", "entitySaveButton", "entityCancelButton"):
        item = find_item(dialog.quick, name)
        assert item.property("visible") is True
        bottom = item.mapToScene(QPointF(0, 0)).y() + item.height()
        assert bottom <= dialog.height() + 1  # stitched rows inside the window


def test_late_module_frame_regrows_the_event_window(qtbot, tmp_path, monkeypatch):
    # The event dialog shares the declarative block channel (design Д2) and
    # the same sizing door — the late frame has to regrow it the same way.
    from app.presentation.qml import island_size

    monkeypatch.setattr(
        island_size, "_screen_limit", lambda dialog: QSize(10000, 4000)
    )
    dialog = EventDialog(
        None,
        theme=make_runtime(tmp_path, "dark"),
        external_sources=[_LateFrameSource("event", "sheet")],
    )
    qtbot.addWidget(dialog)
    dialog.show()
    QApplication.processEvents()
    assert dialog.vm.moduleGroups
    h0 = dialog.height()
    root = dialog.quick.rootObject()
    assert abs(h0 - root.implicitHeight()) <= 1

    dialog.populate(SimpleNamespace(id=9, name="Морфеус"))
    QApplication.processEvents()
    QApplication.processEvents()

    h1 = dialog.height()
    assert h1 > h0
    assert abs(h1 - root.implicitHeight()) <= 1
    for name in ("eventRelationsBand", "eventSaveButton", "eventCancelButton"):
        item = find_item(dialog.quick, name)
        assert item.property("visible") is True
        bottom = item.mapToScene(QPointF(0, 0)).y() + item.height()
        assert bottom <= dialog.height() + 1


def test_single_screen_never_refits_on_a_late_frame(qtbot, tmp_path):
    # Profile pin «ядро неотличимо от 0.19.1»: the same implicit growth on a
    # card WITHOUT guest tabs must not touch the window — the refit door
    # stays shut while the kernel stands alone.
    dialog = EntityCardDialog(None, "character", theme=make_runtime(tmp_path, "dark"))
    qtbot.addWidget(dialog)
    assert not dialog.vm.moduleGroups
    h0 = dialog.height()
    dialog.vm.set_module_frame([_tall_table().to_dict()], [])
    QApplication.processEvents()
    QApplication.processEvents()
    assert dialog.height() == h0
