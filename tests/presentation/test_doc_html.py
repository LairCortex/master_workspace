"""Unit pins for the doc viewer's Markdown→HTML converter (rendering pass).

The one generator behind the doc-viewer island: Qt's own Markdown engine
(md4c inside PySide6, no third-party dependency) prints the document as
rich text. These pins fix what the island relies on — the heading hierarchy,
lists, weights, the monospace of code, the href of links — and the converter's
ONE intervention into Qt's print: the stripped hardcoded link colour, so the
island's themed ``linkColor`` keeps painting the anchors.
"""
from __future__ import annotations

from app.presentation.utils.doc_html import build_doc_html


class TestBuildDocHtml:
    def test_heading_prints_a_bolder_larger_heading(self):
        html_text = build_doc_html("# Заголовок\n")
        assert "<h1" in html_text and "</h1>" in html_text
        assert "Заголовок" in html_text
        # The heading typesets larger than the body — the document's own
        # relative size scale survives the print.
        assert "xx-large" in html_text

    def test_bold_rides_the_weight_not_the_asterisks(self):
        html_text = build_doc_html("обычный **текст**")
        assert "**" not in html_text
        assert "font-weight:700" in html_text

    def test_lists_become_real_lists(self):
        html_text = build_doc_html("- раз\n- два\n")
        assert "<ul" in html_text
        assert html_text.count("<li") == 2
        assert "раз" in html_text and "два" in html_text

    def test_inline_code_and_fenced_block_get_monospace(self):
        html_text = build_doc_html("текст `кодом`\n\n```\nблок\n```\n")
        assert "monospace" in html_text
        assert "<pre" in html_text and "блок" in html_text

    def test_links_keep_the_href_without_qts_link_color(self):
        html_text = build_doc_html("[сайт](https://example.com)")
        assert '<a href="https://example.com"' in html_text
        assert "сайт" in html_text
        # The stripped fixed blue is the converter's only edit — an embedded
        # color would mute the island's themed linkColor on a dark surface.
        assert "color:#0000ff" not in html_text.lower()

    def test_html_typed_into_the_source_cannot_smuggle_a_script(self):
        # Qt's rich-text print keeps a document data, never an executable
        # surface: a script tag written into the Markdown never reaches the
        # HTML, and the surrounding text survives.
        html_text = build_doc_html("привет <script>alert(1)</script>")
        assert "<script" not in html_text.lower()
        assert "alert" not in html_text
        assert "привет" in html_text

    def test_empty_source_still_prints_a_document(self):
        html_text = build_doc_html("")
        assert "<html" in html_text
