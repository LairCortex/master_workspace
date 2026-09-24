"""DocViewer island scroll contract (NRI-0014 task 2.1, defect AB1).

Offscreen pin that the document island is genuinely scrollable: the root
carries a stock ``ScrollView`` (the ``SheetPresetRoot.qml`` pattern) around the
read-only ``mono`` ``ThemeTextArea``, its content is taller than the viewport,
and a programmatic ``contentY`` visibly moves the text. Before this change the
island had no scroll container at all — only the fragment that fit at open
time was reachable.
"""
from __future__ import annotations

from app.presentation.views.doc_viewer_dialog import DocViewerDialog
from tests.presentation.qml_helpers import find_item, walk_items


def _long_document(tmp_path) -> "object":
    path = tmp_path / "doc.md"
    path.write_text(
        "\n".join(f"строка {i} длинного документа" for i in range(600)),
        encoding="utf-8",
    )
    return path


def _scroll_views(root):
    return [
        item
        for item in walk_items(root)
        if "ScrollView" in item.metaObject().className()
    ]


def _flick_of(dlg):
    """The Flickable a ScrollView scrolls its content with (contentY holder)."""
    scroll = find_item(dlg.quick, "docScroll")
    flick = scroll.property("contentItem")
    assert flick is not None, "ScrollView exposes no contentItem (Flickable)"
    return scroll, flick


def test_doc_viewer_root_wraps_the_text_in_a_scroll_view(qtbot, tmp_path):
    dlg = DocViewerDialog("T", _long_document(tmp_path))
    qtbot.addWidget(dlg)
    root = dlg.quick.rootObject()

    # The root contains the stock ScrollView content (by class, not by hand —
    # the QML ScrollView is projected as the QQuickScrollView template).
    assert _scroll_views(root), "no ScrollView in the doc-viewer island"
    scroll, flick = _flick_of(dlg)
    assert "ScrollView" in scroll.metaObject().className()

    # The document itself is still the same read-only monospace field.
    text = find_item(dlg.quick, "docText")
    assert text.property("readOnly") is True
    assert text.property("mono") is True
    # …and it lives inside the scrolling content (the flickable's subtree),
    # which is what makes the content clip and move with contentY.
    assert any(i is text for i in walk_items(flick))


def test_doc_viewer_content_is_taller_than_the_viewport(qtbot, tmp_path):
    dlg = DocViewerDialog("T", _long_document(tmp_path))
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    _scroll, flick = _flick_of(dlg)

    content_h = float(flick.property("contentHeight"))
    viewport_h = float(flick.height())
    assert viewport_h > 0
    assert content_h > viewport_h, (
        f"600-line document must exceed the viewport, got "
        f"contentHeight={content_h} viewport={viewport_h}"
    )


def test_doc_viewer_programmatic_scroll_moves_the_text(qtbot, tmp_path):
    dlg = DocViewerDialog("T", _long_document(tmp_path))
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    _scroll, flick = _flick_of(dlg)
    text = find_item(dlg.quick, "docText")

    assert float(flick.property("contentY")) == 0.0
    y_at_rest = text.mapToItem(flick, 0.0, 0.0).y()

    flick.setProperty("contentY", 300.0)
    qtbot.wait(0)

    # The scroll stuck (content is tall enough that 300 is a legal offset)…
    assert float(flick.property("contentY")) == 300.0
    # …and the text really moved up inside the viewport.
    y_scrolled = text.mapToItem(flick, 0.0, 0.0).y()
    assert y_scrolled < y_at_rest - 250.0


def test_doc_viewer_page_keys_scroll_with_focus_in_the_text(qtbot, tmp_path):
    """Spec document-viewer «Клавиатура прокручивает», the independently
    audited page-key half (audit addendum 2026-09-24).

    The requirement names «клавиши перемещения и PageUp/PageDown». Arrow
    keys already scroll: the readOnly TextArea ignores them for the cursor
    and the keys bubble to the ScrollView's Flickable — but PageUp/PageDown
    are ACCEPTED by the readOnly text edit without moving anything, and the
    ScrollView itself owns no key handler, so the page keys died silently.
    The island now pages the view itself while the focus sits in the text
    (root.pageScroll — one viewport height per press); this test drives
    exactly the user path: focus into the text, PageDown, PageUp.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dlg = DocViewerDialog("T", _long_document(tmp_path))
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    _scroll, flick = _flick_of(dlg)
    text = find_item(dlg.quick, "docText")

    # Focus into the text area (the scenario's WHEN half).
    dlg.quick.setFocus(Qt.FocusReason.OtherFocusReason)
    text.forceActiveFocus()
    qtbot.waitUntil(lambda: text.hasActiveFocus(), timeout=2000)

    QTest.keyClick(dlg.quick, Qt.Key_PageDown)
    qtbot.waitUntil(lambda: float(flick.property("contentY")) > 0.0, timeout=2000)
    y_down = float(flick.property("contentY"))

    QTest.keyClick(dlg.quick, Qt.Key_PageUp)
    qtbot.waitUntil(lambda: float(flick.property("contentY")) < y_down, timeout=2000)
    assert float(flick.property("contentY")) == 0.0
