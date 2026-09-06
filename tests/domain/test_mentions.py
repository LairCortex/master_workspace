"""Domain mention grammar — parse, strip_brackets, rewrite_display_name."""
from app.domain.mentions import parse, rewrite_display_name, strip_brackets


class TestParse:
    def test_single_marker(self):
        hits = parse("@[Алиса](character:42)")
        assert len(hits) == 1
        m = hits[0]
        assert m.display == "Алиса"
        assert m.type == "character"
        assert m.id == 42
        assert (m.start, m.end) == (0, len("@[Алиса](character:42)"))

    def test_several_markers_and_tail(self):
        text = "до @[Алиса](character:42) и @[Бой](event:7) хвост"
        hits = parse(text)
        assert [(h.display, h.type, h.id) for h in hits] == [
            ("Алиса", "character", 42),
            ("Бой", "event", 7),
        ]
        assert text[hits[-1].end:] == " хвост"
        assert text[:hits[0].start] == "до "


class TestStripAndRewrite:
    def test_strip_brackets(self):
        assert strip_brackets("[Алиса]") == "Алиса"
        assert strip_brackets("a]b[c") == "abc"
        assert strip_brackets("  Bob  ") == "Bob"
        assert strip_brackets("[]") == "?"
        assert strip_brackets("[[[ ]]]") == "?"
        assert strip_brackets("") == "?"

    def test_rewrite_by_type_and_id_any_old_display(self):
        text = (
            "x @[старое](character:42) y @[?](character:42) "
            "z @[чужой](character:7) w (character:42) хвост"
        )
        out = rewrite_display_name(text, "character", 42, "[Новое]")
        assert "@[Новое](character:42)" in out
        assert out.count("@[Новое](character:42)") == 2
        assert "@[чужой](character:7)" in out
        assert "(character:42)" in out
        assert "хвост" in out
        assert "старое" not in out
        assert "@[?]" not in out
