"""Card grouping tabs (add-dnd-game-face task 7.1/7.2, spec entity-card-tabs).

Three halves, all offscreen:

* the Qt-free strip state (``CardGroupState``): kernel head, module tail,
  active-index rules, field→group reveal, shortening fallback;
* both islands' Qt face: the strip model reaches QML as named tabs, the
  entered value survives a tab switch, a refused save reveals (and marks)
  the offended tab, an accepted save clears the mark; the field itself keeps
  working through the switch because the pages are built once and only shown;
* the module-tab mechanism (``CardTabHost``): a stub source's ``CardTabSpec``
  lands after the kernel entries, the factory widget overlays the body slot
  the QML page publishes while its tab is active, ``release_tab`` + teardown
  retire it with the island, and a module that is absent / hidden / broken
  never disturbs the kernel strip (spec «Таб модуля живёт с модулем»).
"""
from __future__ import annotations

import dataclasses
from datetime import date
from types import SimpleNamespace

import shiboken6
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget

from app.domain import entity_registry
from app.presentation.card_tab_groups import (
    GROUP_OVERVIEW,
    GROUP_RELATIONS,
    GROUP_TEXTS,
    CardGroupState,
    kernel_card_groups,
)
from app.presentation.card_tab_host import CardTabHost
from app.presentation.modules.protocol import CardTabSpec
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


# ── the Qt-free strip state ─────────────────────────────────────────────────


def test_kernel_strip_composition_and_titles():
    trio = kernel_card_groups(has_relations=True)
    assert [entry["key"] for entry in trio] == [GROUP_OVERVIEW, GROUP_TEXTS, GROUP_RELATIONS]
    assert [entry["title"] for entry in trio] == ["Обзор", "Тексты", "Связи"]
    pair = kernel_card_groups(has_relations=False)
    assert [entry["key"] for entry in pair] == [GROUP_OVERVIEW, GROUP_TEXTS]


def test_state_module_tail_heads_after_kernel_and_shortening_falls_back():
    state = CardGroupState(kernel_card_groups(has_relations=True))
    changed, active_changed = state.set_external_groups(
        [{"key": "dnd.sheet", "title": "Лист"}]
    )
    assert (changed, active_changed) == (True, False)
    assert [entry["key"] for entry in state.entries()] == [
        GROUP_OVERVIEW, GROUP_TEXTS, GROUP_RELATIONS, "dnd.sheet",
    ]
    # Selecting the module tab, then the module tail empties: the reader is
    # returned to the first kernel group (the kernel never shifts).
    assert state.set_active(3)
    assert state.key_at(3) == "dnd.sheet"
    changed, active_changed = state.set_external_groups([])
    assert (changed, active_changed) == (True, True)
    assert state.active == 0
    assert [entry["key"] for entry in state.entries()] == [
        GROUP_OVERVIEW, GROUP_TEXTS, GROUP_RELATIONS,
    ]
    # A no-op replacement stays silent (the populate echo must not churn).
    assert state.set_external_groups([]) == (False, False)


def test_state_absent_safe_moves_and_field_reveal():
    state = CardGroupState(kernel_card_groups(has_relations=True))
    assert state.set_active(-1) is False
    assert state.set_active(99) is False
    assert state.key_at(99) is None
    assert state.set_active(0) is False  # already active
    assert state.group_index_for_field("characteristics") == 1
    assert state.group_index_for_field("name") == 0
    assert state.group_index_for_field("nothing-like-this") is None
    # A narrower strip (no «Связи») still resolves the groups it does have.
    pair = CardGroupState(kernel_card_groups(has_relations=False))
    assert pair.group_index_for_field("characteristics") == 1
    assert pair.kernel_count() == 2
    # A mapped field whose group is not on this card's strip at all reveals
    # nothing (the defensive leg: the map is shared, the strips are not).
    lone = CardGroupState([{"key": GROUP_OVERVIEW, "title": "Обзор"}])
    assert lone.group_index_for_field("characteristics") is None


# ── the shared Qt face on both view models ──────────────────────────────────


def test_event_vm_strip_reveal_and_clear(qtbot):
    vm = EventDialogIslandViewModel(owner=object())
    assert vm.active_group_key() == GROUP_OVERVIEW
    assert [entry["key"] for entry in vm.groups] == [
        GROUP_OVERVIEW, GROUP_TEXTS, GROUP_RELATIONS,
    ]
    emitted: list[str] = []
    vm.activeGroupChanged.connect(lambda: emitted.append("active"))
    vm.invalidatedFieldChanged.connect(lambda: emitted.append("invalid"))

    vm.reveal_field("characteristics")
    assert vm.activeGroup == 1 and vm.activeGroupKey == GROUP_TEXTS
    assert vm.invalidatedField == "characteristics"
    # Re-revealing the same pair is silent (no echo at QML).
    vm.reveal_field("characteristics")
    assert emitted == ["active", "invalid"]
    vm.clear_invalidated_field()
    assert vm.invalidatedField == ""
    assert emitted == ["active", "invalid", "invalid"]
    # Clearing an already-clear mark is silent too.
    vm.clear_invalidated_field()
    assert emitted == ["active", "invalid", "invalid"]

    # An out-of-strip selection changes nothing.
    vm.selectGroup(77)
    assert vm.activeGroup == 1
    vm.selectGroup(0)
    assert vm.activeGroup == 0
    # reportBodyRect relays AND stamps the last rect (DND-LIVE-1: the host
    # may only subscribe after the island's final publish).
    seen: list[tuple] = []
    vm.bodyRectChanged.connect(lambda *a: seen.append(a))
    vm.reportBodyRect(1.0, 2.0, 300.0, 400.0)
    assert seen == [(1.0, 2.0, 300.0, 400.0)]
    assert vm.last_body_rect() == (1.0, 2.0, 300.0, 400.0)


def test_entity_vm_strip_matches_type_relations(qtbot):
    related = entity_registry.related_refs_for_key("character")
    assert related  # the trio type
    vm = EntityCardIslandViewModel("character", [], related, owner=object())
    assert [entry["key"] for entry in vm.groups] == [
        GROUP_OVERVIEW, GROUP_TEXTS, GROUP_RELATIONS,
    ]
    rating = EntityCardIslandViewModel("rating", [], [], owner=object())
    assert [entry["key"] for entry in rating.groups] == [GROUP_OVERVIEW, GROUP_TEXTS]
    # The reveal moves between the two groups the rating pair actually has.
    rating.reveal_field("characteristics")
    assert rating.active_group_key() == GROUP_TEXTS
    # An unknown field name reveals nothing, moves nothing, and does not
    # clobber the mark that is already up.
    rating.reveal_field("no-such-field")
    assert rating.invalidatedField == "characteristics"
    assert rating.active_group_key() == GROUP_TEXTS


# ── the islands: QML strip, input across switches, save over hidden tabs ────


def test_event_dialog_qml_strip_pages_and_reveal(qtbot, tmp_path):
    dialog = EventDialog(None, theme=make_runtime(tmp_path, "dark"))
    qtbot.addWidget(dialog)
    root = dialog.quick.rootObject()
    strip = find_item(dialog.quick, "eventGroupTabs")
    tabs = sorted(
        (
            item
            for item in walk_items(strip)
            if item.metaObject().className().startswith("ThemeTabButton")
        ),
        key=lambda item: item.x(),
    )
    assert [tab.property("text") for tab in tabs] == ["Обзор", "Тексты", "Связи"]
    for tab, key in zip(tabs, (GROUP_OVERVIEW, GROUP_TEXTS, GROUP_RELATIONS)):
        assert tab.objectName() == f"eventGroupTab_{key}"
    # Equal shares — the library bar law holds for this consumer too.
    assert tabs[0].width() > 0
    assert max(tab.width() for tab in tabs) - min(tab.width() for tab in tabs) <= 1

    # The body slot is published (task 7.2 dependency): a non-empty rect the
    # host can overlay onto was reported at least once.
    published: list[tuple] = []
    dialog.vm.bodyRectChanged.connect(lambda *a: published.append(a))
    body = find_item(dialog.quick, "eventGroupBody")
    body.setWidth(body.width() + 1)
    assert published and published[-1][2] > 0 and published[-1][3] > 0

    # «Ошибка указывает дорогу»: from the Тексты tab an empty name reveals
    # Обзор and marks the name caption in the accent.
    saves: list[object] = []
    dialog.saved.connect(saves.append)
    dialog.vm.selectGroup(1)
    dialog.vm.requestSave()
    assert dialog.vm.active_group_key() == GROUP_OVERVIEW
    assert dialog.vm.invalidatedField == "name"
    assert saves == []  # nothing saved (valid gate)
    label = find_item(dialog.quick, "eventNameLabel")
    assert label.property("color") == root.property("accentColor")

    # The relations strip is whole on its tab (the 4 sections were moved, not
    # rebuilt): every section objectName is present in the tree.
    dialog.vm.selectGroup(2)
    for name in (
        "organizationsRelatedSection",
        "charactersRelatedSection",
        "itemsRelatedSection",
        "locationsRelatedSection",
    ):
        assert find_item(dialog.quick, name) is not None


def test_entity_card_qml_input_survives_switch_and_save_reads_hidden_tab(qtbot, tmp_path):
    dialog = EntityCardDialog(None, "character", theme=make_runtime(tmp_path, "dark"))
    qtbot.addWidget(dialog)
    root = dialog.quick.rootObject()
    strip = find_item(dialog.quick, "entityGroupTabs")
    assert strip is not None and strip.property("visible") is True

    # Input entered on one tab is intact after a round trip (the pages are
    # built once — the switch only moves the visible page, spec «Ввод
    # переживает смену таба»).
    name_field = find_item(dialog.quick, "entityNameField")
    name_field.setProperty("text", "Морфеус")
    chars_field = find_item(dialog.quick, "entityCharacteristicsField")
    chars_field.setProperty("text", "Архитектор")
    QApplication.processEvents()
    assert dialog.vm.name == "Морфеус"
    dialog.vm.selectGroup(1)  # Тексты
    dialog.vm.selectGroup(2)  # Связи
    dialog.vm.selectGroup(0)  # Обзор again
    assert name_field.property("text") == "Морфеус"
    assert chars_field.property("text") == "Архитектор"

    # A save issued while the Тексты tab is up still reads every group's
    # fields into the result (the field values live in the VM, not on screen).
    dialog.vm.selectGroup(1)
    assert dialog.vm.saveEnabled
    assert find_item(dialog.quick, "entityCharacteristicsLabel").property(
        "color"
    ) != root.property("accentColor")
    dialog.vm.requestSave()
    data = dialog.get_data()
    assert data["name"] == "Морфеус"
    assert data["characteristics"] == "Архитектор"


def test_event_dialog_reveal_points_at_texts_group(qtbot, tmp_path):
    dialog = EventDialog(None, theme=make_runtime(tmp_path, "dark"))
    qtbot.addWidget(dialog)
    root = dialog.quick.rootObject()
    dialog.vm.name = "Погоня"  # name whole; the empty-text pair offends
    dialog.vm.selectGroup(0)
    dialog.vm.requestSave()
    assert dialog.vm.invalidatedField == "characteristics"
    assert dialog.vm.active_group_key() == GROUP_TEXTS
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
    dialog.vm.selectGroup(1)
    dialog.vm.requestSave()
    assert dialog.vm.invalidatedField == "end_date"
    assert dialog.vm.active_group_key() == GROUP_OVERVIEW  # the dates live here
    # A refusal caused by the save lock is not a field problem: no tab moves
    # off its own, no mark appears, nothing saves. (First an accepted save
    # washes the end_date mark away — the mark only ever clears on success.)
    dialog.vm.set_dates(end=date(2025, 5, 9))
    assert dialog.vm.valid
    saves: list[object] = []
    dialog.saved.connect(saves.append)
    dialog.vm.requestSave()
    assert len(saves) == 1 and dialog.vm.invalidatedField == ""
    dialog.vm.set_save_locked(True)
    dialog.vm.selectGroup(1)
    dialog.vm.requestSave()
    assert len(saves) == 1  # the lock refused the attempt
    assert dialog.vm.invalidatedField == ""
    assert dialog.vm.active_group_key() == GROUP_TEXTS  # stayed where it was


def test_card_reveal_marks_name_and_accepted_save_clears(qtbot):
    dialog = EntityCardDialog(None, "item")
    qtbot.addWidget(dialog)
    saves: list[object] = []
    dialog.saved.connect(saves.append)
    dialog.vm.selectGroup(1)
    dialog.vm.requestSave()  # empty name from the Тексты tab
    assert dialog.vm.active_group_key() == GROUP_OVERVIEW
    assert dialog.vm.invalidatedField == "name"
    assert saves == []
    dialog.vm.name = "Кольцо"
    dialog.vm.requestSave()
    assert len(saves) == 1  # saveRequested reached the facade
    assert dialog.vm.invalidatedField == ""


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
    assert kernel == [GROUP_OVERVIEW, GROUP_TEXTS, GROUP_RELATIONS]
    source = _Source(["dnd.sheet"])
    host = _host(dialog, [source])
    # Before the target id exists the strip is kernel-only.
    host.refresh(None)
    assert [entry["key"] for entry in dialog.vm.groups] == kernel
    # The record is known: the tab joins the tail, the widget is built with
    # (wiring, source_id), parented to the dialog and hidden.
    host.refresh("42")
    assert source.last_target.key == "event" and source.last_target.source_id == "42"
    assert [entry["key"] for entry in dialog.vm.groups] == kernel + ["dnd.sheet"]
    widget = next(iter(dialog.findChildren(_TabWidget)))
    assert widget.parent() is dialog
    assert widget.isVisible() is False
    assert source.built == [("WIRING", "42")]

    # The QML page publishes its body slot when the scene lays out; while
    # the module tab is active the widget overlays that slot, hidden away
    # otherwise, and the card itself keeps working.
    dialog.show()
    QApplication.processEvents()
    dialog.vm.selectGroup(3)
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
    dialog.vm.selectGroup(3)
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
    vm.selectGroup(3)
    assert not widget.isVisibleTo(dialog)
    vm.reportBodyRect(10.0, 20.0, 300.0, 400.0)
    assert widget.isVisibleTo(dialog)
    assert widget.geometry() == QRect(10, 20, 300, 400)
    host.release()


def test_host_module_off_returns_the_kernel_strip(qtbot):
    # A target goes away (module switched off mid-life): the tab leaves the
    # strip, its widget releases and departs, the kernel stands untouched.
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    source = _Source(["dnd.sheet"])
    host = _host(dialog, [source])
    host.refresh("42")
    widget = next(iter(dialog.findChildren(_TabWidget)))
    dialog.vm.selectGroup(3)  # active on the tab about to disappear
    host.refresh(None)
    assert widget.released == 1
    assert widget.parent() is None
    assert [entry["key"] for entry in dialog.vm.groups] == [
        GROUP_OVERVIEW, GROUP_TEXTS, GROUP_RELATIONS,
    ]
    assert dialog.vm.active_group_key() == GROUP_OVERVIEW  # fallback onto Обзор
    host.release()


def test_host_broken_and_hidden_sources_never_move_the_kernel_strip(qtbot):
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


def test_plain_profile_cards_have_no_module_tabs(qtbot):
    # The kernel profile passes no external sources at all (the module-off
    # route): both dialogs populate/refresh with an empty tuple and the strip
    # stays the kernel trio/pair — «табы dd не видны в ядре/без модуля».
    event = EventDialog(None)
    qtbot.addWidget(event)
    event.populate(SimpleNamespace(id=1, name="e"))
    assert [entry["key"] for entry in event.vm.groups] == [
        GROUP_OVERVIEW, GROUP_TEXTS, GROUP_RELATIONS,
    ]
    card = EntityCardDialog(None, "character")
    qtbot.addWidget(card)
    card.populate(SimpleNamespace(id=2, name="c"))
    assert [entry["key"] for entry in card.vm.groups] == [
        GROUP_OVERVIEW, GROUP_TEXTS, GROUP_RELATIONS,
    ]
    rating = EntityCardDialog(None, "rating")
    qtbot.addWidget(rating)
    rating.populate(SimpleNamespace(id=3, name="r"))
    assert [entry["key"] for entry in rating.vm.groups] == [GROUP_OVERVIEW, GROUP_TEXTS]


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
    # The dialog facade drives the host: populate() re-aims the module tail
    # at the record being edited — an edited card carries the tabs its source
    # declares for that record, a fresh one carries none.
    dialog = EntityCardDialog(
        None,
        "character",
        external_sources=[_Source(["dnd.sheet"])],
    )
    qtbot.addWidget(dialog)
    kernel = [entry["key"] for entry in dialog.vm.groups]
    assert kernel == [GROUP_OVERVIEW, GROUP_TEXTS, GROUP_RELATIONS]
    dialog.populate(SimpleNamespace(id=9, name="Тринити"))
    assert [entry["key"] for entry in dialog.vm.groups] == kernel + ["dnd.sheet"]
    widgets = dialog.findChildren(_TabWidget)
    assert len(widgets) == 1
    # Re-populate onto another record: the old widget is released exactly
    # once and replaced, the strip never grows a second module tail.
    dialog.populate(SimpleNamespace(id=10, name="Нео"))
    assert widgets[0].released == 1
    assert [entry["key"] for entry in dialog.vm.groups] == kernel + ["dnd.sheet"]
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


def test_module_tab_join_keeps_the_strip_painting(qtbot, tmp_path):
    # DND-LIVE-1 (2026-10-10 live audit): the module tab joining REPLACES the
    # usage Repeater's model, and on the hand-laid bar this stranded the
    # whole strip render subtree — the accessibility face stayed complete
    # (four named, visible, laid-out tabs) while the band printed no pixels
    # from the first frame (the join rides populate, before the window shows).
    # The structural pins above are face-level and stayed green through the
    # defect — the offscreen grab of the band is the boundary they cannot
    # see, so it is the gate here. The hairline every tab draws along the
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
        None, theme=make_runtime(tmp_path, "dark"), external_sources=[source]
    )
    qtbot.addWidget(dialog)
    host = _host(dialog, [source])
    dialog.show()
    qtbot.wait(50)

    hits, floor = band_hits(dialog)
    assert hits >= floor  # the kernel trio paints

    def tab_texts():
        strip = find_item(dialog.quick, "eventGroupTabs")
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

    # The join: the face gains «Таб dnd.sheet» and the band must keep painting
    # — this exact leg measured zero pixels on the broken bar.
    host.refresh("42")
    qtbot.wait(50)
    assert tab_texts() == ["Обзор", "Тексты", "Связи", "Таб dnd.sheet"]
    hits, floor = band_hits(dialog)
    assert hits >= floor

    # The module tab leaving and joining again re-runs the same churn; every
    # frame of it paints.
    host.refresh(None)
    qtbot.wait(50)
    assert tab_texts() == ["Обзор", "Тексты", "Связи"]
    hits, floor = band_hits(dialog)
    assert hits >= floor

    host.refresh("42")
    qtbot.wait(50)
    assert tab_texts() == ["Обзор", "Тексты", "Связи", "Таб dnd.sheet"]
    hits, floor = band_hits(dialog)
    assert hits >= floor
