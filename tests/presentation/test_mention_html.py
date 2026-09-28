"""Unit pins for the shared mention-HTML generator (NRI-0022, task 4.5).

The one generator behind the preview's rich-text sections: escaping, the
``nri://<type>/<id>`` href shape, and the reader half the ``onLinkActivated``
interception uses. Both halves are pinned here so the island tests only prove
the wiring of the generator into the scene.
"""
from __future__ import annotations

import pytest

from app.presentation.utils.mention_html import (
    MENTION_LINK_SCHEME,
    build_mention_html,
    parse_mention_link,
)


class TestBuildMentionHtml:
    def test_plain_text_is_escaped_and_breaks_become_br(self):
        assert build_mention_html("a & b <c> d\ne") == "a &amp; b &lt;c&gt; d<br>e"

    def test_empty_and_none_read_as_empty_html(self):
        assert build_mention_html("") == ""
        assert build_mention_html(None) == ""

    def test_marker_becomes_the_scheme_anchor(self):
        html = build_mention_html("до @[Банн](character:7) после")
        assert html == (
            f"до <a href=\"{MENTION_LINK_SCHEME}character/7\">Банн</a> после"
        )

    def test_display_is_escaped_inside_the_anchor(self):
        html = build_mention_html("@[<b>&</b>](organization:3)")
        assert "&lt;b&gt;&amp;&lt;/b&gt;" in html

    def test_several_markers_keep_their_pairs(self):
        html = build_mention_html("@[A](item:1) и @[B](location:2)")
        assert (
            f"<a href=\"{MENTION_LINK_SCHEME}item/1\">A</a>" in html
            and f"<a href=\"{MENTION_LINK_SCHEME}location/2\">B</a>" in html
        )


class TestParseMentionLink:
    @pytest.mark.parametrize(
        "link, expected",
        [
            ("nri://character/7", ("character", 7)),
            ("nri://organization/1", ("organization", 1)),
            ("nri://item/123456", ("item", 123456)),
        ],
    )
    def test_generated_anchors_read_back(self, link, expected):
        assert parse_mention_link(link) == expected

    @pytest.mark.parametrize(
        "link",
        [
            "",
            None,
            "https://example.com/song",  # external URL — not a navigation
            "nri://no-such-type/1",  # a type outside the registry
            "nri://character/abc",  # a non-numeric id
            "nri://character/",  # a missing id
            "nri://character",  # a truncated href
        ],
    )
    def test_foreign_or_broken_hrefs_navigate_nothing(self, link):
        assert parse_mention_link(link) is None
