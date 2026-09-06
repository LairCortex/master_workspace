"""Unit acceptance for the service-free QML mention field host."""
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QWidget

from app.presentation.viewmodels.mention_field_host import MentionFieldHost
from app.presentation.views.mention_popup import _MentionPopup


def test_storage_round_trip_builds_display_and_ranges(qapp):
    host = MentionFieldHost()
    marker = "@[Алиса](character:42)"
    host.storage = f"До {marker} после"

    assert host.storage == f"До {marker} после"
    assert host.display == "До Алиса после"
    assert host.spans == [{
        "start": 3,
        "end": 8,
        "storageStart": 3,
        "storageEnd": 3 + len(marker),
        "display": "Алиса",
        "type": "character",
        "id": 42,
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

    assert clicked == [("event", 7)]


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
