"""Unit acceptance for the service-free QML mention field host."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QWidget

from app.domain import entity_registry
from app.presentation.viewmodels.mention_field_host import MentionFieldHost
from app.presentation.views.mention_popup import _MentionPopup


@pytest.fixture
def feat_registered():
    """The external type section is composition state; the popup-label test
    borrows the registry tests' isolation discipline."""
    saved = dict(entity_registry._EXTERNAL)
    entity_registry.register_external((entity_registry.ExternalTypeDescriptor(
        key="dd_feat", label="Черта", plural_label="Черты",
        icon_key="crosshair", reference=True,
    ),))
    yield
    entity_registry._EXTERNAL.clear()
    entity_registry._EXTERNAL.update(saved)


def test_storage_round_trip_builds_display_and_ranges(qapp):
    host = MentionFieldHost()
    marker = "@[Алиса](character:42)"
    host.storage = f"До {marker} после"

    assert host.storage == f"До {marker} после"
    assert host.display == "До Алиса после"
    # design Д4: the grammar is textual — the span quotes the stored id as
    # text for every type, kernel digits included (the kernel boundary
    # converts them back in main._on_mention_clicked)
    assert host.spans == [{
        "start": 3,
        "end": 8,
        "storageStart": 3,
        "storageEnd": 3 + len(marker),
        "display": "Алиса",
        "type": "character",
        "id": "42",
    }]


def test_native_popup_empty_and_navigation_edges(qtbot):
    popup = _MentionPopup()
    qtbot.addWidget(popup)
    popup.show_results([], QPoint())
    assert not popup.isVisible()
    popup.show_results(
        [
            {"name": "A", "type": "character", "id": 1},
            {"name": "B", "type": "item", "id": 2},
        ],
        QPoint(),
    )
    popup.select_next()
    assert popup._list.currentRow() == 1
    popup.select_prev()
    assert popup._list.currentRow() == 0


def test_popup_signs_external_rows_with_the_type(qtbot, feat_registered):
    """Task 5.2 «кандидаты с пометкой типа»: an external row is signed with
    its descriptor label and (when the source names it) the origin — the
    search list's «[источник]» reading, kept for the popup; a same-named
    record of another set is a distinguishable row. Kernel rows keep their
    glyph-only reading byte-for-byte (no new sign on the old candidates)."""
    popup = _MentionPopup()
    qtbot.addWidget(popup)
    popup.show_results(
        [
            {"name": "Банн", "type": "character", "id": 1},
            {
                "name": "Тёмное зрение", "type": "dd_feat",
                "id": "srd51/Darkvision", "origin": "SRD 5.1",
            },
            {
                "name": "Тёмное зрение", "type": "dd_feat",
                "id": "srd52/Darkvision", "origin": "SRD 5.2",
            },
        ],
        QPoint(),
    )
    texts = [
        popup._list.item(i).text() for i in range(popup._list.count())
    ]
    assert texts[0] == "\U0001f9d1  Банн"
    assert "Тёмное зрение" in texts[1] and "Черта" in texts[1]
    assert "SRD 5.1" in texts[1]
    assert texts[1] != texts[2]  # two same-named records, two origins
    assert "SRD 5.2" in texts[2]
    # the row data rides whole — the composite id survives to the insert
    assert popup._list.item(1).data(Qt.ItemDataRole.UserRole) == {
        "name": "Тёмное зрение", "type": "dd_feat",
        "id": "srd51/Darkvision", "origin": "SRD 5.1",
    }


def test_typing_two_query_chars_requests_search(qapp):
    host = MentionFieldHost()
    requested = []
    host.searchRequested.connect(requested.append)

    host.updateDisplay("@a", 2, False)
    assert requested == []
    host.updateDisplay("@al", 3, False)

    assert requested == ["al"]
    assert host.popupVisible is False


def test_insert_mention_replaces_query_and_strips_popup_name(qapp):
    host = MentionFieldHost()
    host.updateDisplay("see @al", 7, False)
    host.storage = host.storage
    assert host.modified is False

    host.insertMention("character", 42, "[Алиса]")

    assert host.storage == "see @[Алиса](character:42) "
    assert host.display == "see Алиса "
    assert host.popupVisible is False


def test_empty_results_hide_popup_and_popup_navigation_confirms(qapp):
    host = MentionFieldHost()
    host.updateDisplay("@al", 3, False)
    host.showResults([{"type": "character", "id": 1, "name": "Alice"}])
    assert host.popupVisible is True

    host.showResults([])
    assert host.popupVisible is False


def test_activate_mention_emits_type_and_id(qapp):
    host = MentionFieldHost()
    clicked = []
    host.mentionClicked.connect(lambda type_, id_: clicked.append((type_, id_)))

    host.activateMention("event", 7)

    # the relay channel is textual (design Д4): the kernel int arrives as the
    # string of the same number
    assert clicked == [("event", "7")]


def test_external_string_id_round_trips_through_the_host(qapp, feat_registered):
    """Task 5.1 «MentionFieldHost на str-id без регресса числовых»: a
    candidate row whose id is a composite string (protocol Д4) inserts its
    marker verbatim, the span quotes the id whole, and the chip click relays
    the SAME text — nothing numeric is attempted on the way (the numeric
    rows' no-regression half is every pre-change test of this file)."""
    host = MentionFieldHost()
    host.updateDisplay("вид @те", 6, False)
    host.insertMention("dd_feat", "srd51/Darkvision", "Тёмное зрение")
    assert host.storage == "вид @[Тёмное зрение](dd_feat:srd51/Darkvision) "
    assert host.display == "вид Тёмное зрение "
    (span,) = host.spans
    assert (span["type"], span["id"], span["display"]) == (
        "dd_feat", "srd51/Darkvision", "Тёмное зрение",
    )

    clicked = []
    host.mentionClicked.connect(lambda t, i: clicked.append((t, i)))
    host.activateMention(span["type"], span["id"])
    assert clicked == [("dd_feat", "srd51/Darkvision")]


def test_popup_row_external_id_inserts_without_int_conversion(qapp, feat_registered):
    """The popup confirm path carries the candidate row whole (design Д4):
    a composite id is NOT passed through int() on the way to the marker,
    while a kernel row's int id still textualises to the same digits."""
    host = MentionFieldHost()
    host.updateDisplay("@те", 3, False)
    host._insert_result(
        {"type": "dd_feat", "id": "srd51/Darkvision", "name": "Тёмное зрение"},
    )
    assert host.storage == "@[Тёмное зрение](dd_feat:srd51/Darkvision) "
    assert host.display == "Тёмное зрение "

    # a fresh plain edit replaces the whole field (chips are atomic), then
    # the kernel row of the same popup still yields the old digits marker
    host.updateDisplay("@ци", 3, False)
    host._insert_result({"type": "character", "id": 42, "name": "Банн"})
    assert host.storage == "@[Банн](character:42) "


def test_display_edit_preserves_marker_and_storage_paste(qapp):
    host = MentionFieldHost()
    host.storage = "x @[A](character:1) y"

    host.updateDisplay("!x A y", 1, False)
    assert host.storage == "!x @[A](character:1) y"

    host.updateDisplay(
        "!x A y @[Raw](event:9)",
        len("!x A y @[Raw](event:9)"),
        False,
    )
    assert host.storage == "!x @[A](character:1) y @[Raw](event:9)"
    assert host.display == "!x A y Raw"


def test_atomic_marker_backspace_delete_selection_and_snap(qapp):
    host = MentionFieldHost()
    marker = "@[Alice](character:1)"
    host.storage = f"x {marker} y"
    span = host.spans[0]

    assert host.snapCursor(span["start"] + 1) == span["start"]
    assert host.snapCursor(span["end"] - 1) == span["end"]
    assert host.snapCursor(span["start"]) == span["start"]
    assert host.expandSelection(span["start"] + 1, span["end"] + 1) == [
        span["start"],
        span["end"] + 1,
    ]
    assert host._display_to_storage(span["start"] + 1) == span["storageStart"]
    assert host._display_to_storage(span["end"] - 1) == span["storageEnd"]

    inserted = host.display[:span["start"] + 1] + "Z" + host.display[span["start"] + 1:]
    assert host.updateDisplay(inserted, span["start"] + 2, False) == span["start"]
    assert host.storage == f"x {marker} y"

    # Native Backspace removed the last visible marker character; host expands
    # that single-char edit to the full storage marker.
    host.updateDisplay("x Alic y", span["end"] - 1, False)
    assert host.storage == "x  y"

    host.storage = f"x {marker} y"
    # A replacement intersecting a marker replaces the entire marker.
    host.updateDisplay("x Z y", 3, False)
    assert host.storage == "x Z y"


def test_composition_defers_mapping_and_modified_flag(qapp):
    host = MentionFieldHost()
    host.storage = "@[A](character:1)"
    assert host.modified is False

    cursor = host.updateDisplay("A中", 2, True)
    assert cursor == 2
    assert host.storage == "@[A](character:1)"
    assert host.modified is False

    host.updateDisplay("A中", 2, False)
    assert host.storage == "@[A](character:1)中"
    assert host.modified is True


def test_popup_position_and_empty_query_cancel(qapp):
    host = MentionFieldHost()
    host.setCaretRect(10, 20, 12)
    assert host.caretPoint == QPoint(10, 36)

    host.updateDisplay("@al", 3, False)
    host.showResults([{"type": "item", "id": 2, "name": "A"}])
    assert host.popupVisible is True
    host.cancelMention()
    assert host.popupVisible is False


def test_attached_host_positions_shared_native_popup(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.move(40, 50)
    host = MentionFieldHost()
    host.attachWidget(widget)
    host.setCaretRect(10, 20, 12)
    host.updateDisplay("@al", 3, False)

    host.showResults([{"type": "item", "id": 2, "name": "A"}])

    assert host._popup is not None
    assert host._popup.parent() is widget
    assert host._popup.pos() == widget.mapToGlobal(QPoint(10, 36))
    host.popupDown()
    host.popupUp()
    host.confirmPopup()
    assert host.storage == "@[A](item:2) "
    host.cancelMention()
    assert host._popup.isVisible() is False
    host.confirmPopup()  # hidden popup is a no-op
    host.cancelMention()  # already hidden is a no-op


def test_shortened_query_hides_results_and_insert_without_query_is_noop(qapp):
    host = MentionFieldHost()
    host.insertMention("item", 1, "No query")
    assert host.storage == ""

    host.updateDisplay("@ab", 3, False)
    host.showResults([{"type": "item", "id": 1, "name": "A"}])
    assert host.popupVisible is True
    host.updateDisplay("@a", 2, False)
    assert host.popupVisible is False


def test_known_display_restore_marks_clean_host_modified(qapp):
    host = MentionFieldHost()
    host._known_displays["restored"] = "@[restored](item:7)"
    host.updateDisplay("restored", len("restored"), False)
    assert host.storage == "@[restored](item:7)"
    assert host.modified is True


# ── zombie guard: the popup leaves with its host (12.5, приёмка 2026-10-11) ──


def test_closing_the_host_sheet_takes_the_popup_with_it(qtbot):
    """FOLLOW-UP 12.5: the popup is a top-level Tool window parented to the
    island WIDGET, and Qt does not propagate a window's close/hide to child
    top-level windows — without the host-side hook the candidate list
    survived its sheet as a zombie window (the acceptance report of
    2026-10-11). The host here is the production class (QDialog — the
    sheet's own): its «Закрыть»-equivalent reject() hides the dialog, the
    island receives the Hide event (Qt propagates it through the dialog's
    recursive hide), and the popup leaves with the field; the pending
    ``@``-query is cancelled, so a late search answer inserts nothing."""
    from PySide6.QtWidgets import QDialog

    sheet = QDialog()
    qtbot.addWidget(sheet)
    # the island exists before the sheet is shown and is shown with it —
    # exactly the production seat (the QQuickWidget lives in the dialog's
    # layout from construction; the sheet only opens after)
    island = QWidget(sheet)  # the island's seat: plain child, not a window
    sheet.show()
    host = MentionFieldHost()
    host.attachWidget(island)
    host.setCaretRect(2, 2, 10)
    host.updateDisplay("@al", 3, False)
    host.showResults([{"type": "item", "id": 2, "name": "A"}])
    assert host._popup is not None
    assert host._popup.isVisible()

    sheet.reject()

    assert not host._popup.isVisible()
    assert host.popupVisible is False
    # the pending @-query died with the sheet: a late answer inserts nothing
    host.insertMention("item", 2, "A")
    assert host.storage == "@al"


def test_hiding_the_island_widget_takes_the_popup_with_it(qtbot):
    """The same door for the hide without a close (an island swapped out
    under a still-visible window): the popup of an invisible field goes, and
    the pending mention is cancelled — the next field edit starts clean."""
    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    island = QWidget(window)
    island.show()
    host = MentionFieldHost()
    host.attachWidget(island)
    host.setCaretRect(2, 2, 10)
    host.updateDisplay("@al", 3, False)
    host.showResults([{"type": "item", "id": 2, "name": "A"}])
    assert host._popup.isVisible()

    island.hide()

    assert not host._popup.isVisible()
    assert host.popupVisible is False
    # the pending @-query died with the field: a late answer inserts nothing
    host.insertMention("item", 2, "A")
    assert host.storage == "@al"
