"""Domain mention grammar — parse, strip_brackets, rewrite_display_name.

add-dnd-game-face (design Д4, spec mentions «Единая грамматика маркеров»):
the id slot is textual — kernel types keep the digits-only shape, registered
external types add string/composite ids. The golden block below re-pins the
EXACT texts the pre-change grammar saw (storage fixtures, rewrite texts,
render fixtures of the suite) and proves the widened parser reads every one
of them with the same display/type/spans; the fuzz block walks the boundary
in both directions (round-trip of assembled markers, non-reinterpretation of
any text the old grammar did not match under a kernel/unknown type).
"""
import random
import re

import pytest

from app.domain import entity_registry as reg
from app.domain.mentions import (
    format_marker,
    is_admissible_id,
    parse,
    rewrite_display_name,
    strip_brackets,
)


# The external section is process state the composition root owns; the tests
# that register borrow the same isolation discipline as the registry tests
# (hand every test back the kernel-only shape it found).
@pytest.fixture(autouse=True)
def restore_external_section():
    saved = dict(reg._EXTERNAL)
    yield
    reg._EXTERNAL.clear()
    reg._EXTERNAL.update(saved)


def _feat(**over):
    base = dict(
        key="dd_feat", label="Черта", plural_label="Черты", icon_key="crosshair",
        reference=True,
    )
    base.update(over)
    return reg.ExternalTypeDescriptor(**base)


#: The pre-change regex, kept here as the golden oracle: the new parser must
#: never differ from it on any text whose types are kernel/unknown.
_OLD_MENTION_RE = re.compile(r"@\[([^\]]+)\]\((\w+):(\d+)\)")


def _old_parse(text):
    return [
        (m.group(1), m.group(2), int(m.group(3)), m.start(), m.end())
        for m in _OLD_MENTION_RE.finditer(text or "")
    ]


class TestParse:
    def test_single_marker(self):
        hits = parse("@[Алиса](character:42)")
        assert len(hits) == 1
        m = hits[0]
        assert m.display == "Алиса"
        assert m.type == "character"
        # the grammar is textual (design Д4): the digits ride as the string
        # they are in storage; the kernel boundary converts them back
        assert m.id == "42"
        assert (m.start, m.end) == (0, len("@[Алиса](character:42)"))

    def test_several_markers_and_tail(self):
        text = "до @[Алиса](character:42) и @[Бой](event:7) хвост"
        hits = parse(text)
        assert [(h.display, h.type, h.id) for h in hits] == [
            ("Алиса", "character", "42"),
            ("Бой", "event", "7"),
        ]
        assert text[hits[-1].end:] == " хвост"
        assert text[:hits[0].start] == "до "


# ── golden block: the texts the pre-change grammar already saw ───────────────
#
# Every entry is a shape the shipped app can hold in the six rewrite columns
# (and the chips/summaries render): the spans pin that the byte windows are
# the same the old parser cut, so no storage text shifts under the widening.

_GOLDEN_TEXTS = (
    # plain single marker at the edges of a sentence
    "До @[Алиса](character:42) после",
    # the rewrite tests' six-column shapes
    "@[Old](character:1) and ( character:1 )",
    "bs @[Old](character:1)",
    "@[старое](character:42) x @[?](character:42) y @[чужой](character:7) z",
    # adjacent markers, back-to-back (the span arithmetic of _to_display)
    "@[A](event:1)@[B](event:2)",
    # marker inside parentheses of another sentence (partition confusion risk)
    "см. (@[Гоблин](item:9)) и ещё (item:9)",
    # names with spaces and dots — display keeps them, brackets would not
    "@[Фродо Бэггинс-младший.](character:13)",
    # empty display is impossible for the grammar (at least one char); '?' of
    # the assembly rule shows up in storage after a nameless rename
    "@[?](location:5)",
)


class TestGoldenOldTexts:
    @pytest.mark.parametrize("text", _GOLDEN_TEXTS)
    def test_old_texts_parse_identically_to_the_old_grammar(self, text):
        """The risk named in design (Risks): «общий разбор, риск регресса
        старых маркеров». For every shipped text shape the new parser yields
        exactly what the old one did — same display, same type, digits (as
        text), same byte span — and the old regex oracle agrees on the span
        set; nothing was gained or lost under kernel/unknown types."""
        hits = parse(text)
        old = _old_parse(text)
        assert [(h.display, h.type, h.id, h.start, h.end) for h in hits] == [
            (d, t, str(i), s, e) for d, t, i, s, e in old
        ]

    def test_kernel_marker_with_a_string_id_never_parses(self):
        """Reverse direction barred (design Д4): a forged ``character:abc``
        is not a marker — the bytes stay plain text, so no old text is ever
        re-read as a mention and no forged chip impersonates a row."""
        for text in (
            "@[X](character:abc)",
            "@[X](event:srd51/Darkvision)",
            "@[X](character:42abc)",
            "@[X](character:)",
            "@[X](character:4ab)",
        ):
            assert parse(text) == []
        # the same bytes under an EXTERNAL registered type DO parse (below),
        # and under the old grammar parsed nowhere (digits oracle empty)
        assert _old_parse("@[X](character:abc)") == []

    def test_unknown_type_keeps_the_kernel_half(self):
        """A type the registry does not know admits digits only — exactly
        the set the pre-change grammar matched. ``planet:7`` rendered as text
        before (no service at click time) and still parses/not-parses the
        same by shape; ``planet:abc`` parsed nowhere before and parses
        nowhere now."""
        assert [(h.type, h.id) for h in parse("@[П](planet:7)")] == [("planet", "7")]
        assert parse("@[П](planet:abc)") == []


# ── external string ids (spec «Строковый id внешнего типа») ──────────────────


class TestExternalStringIds:
    def test_composite_id_round_trips_byte_for_byte(self):
        """Spec scenario: ``@[Тёмное зрение](feat:srd51/Darkvision)`` — the
        grammar reads display, type and the composite string id; assembling
        the marker back preserves it unchanged."""
        reg.register_external((_feat(),))
        text = "@[Тёмное зрение](dd_feat:srd51/Darkvision)"
        (hit,) = parse(text)
        assert (hit.display, hit.type, hit.id) == (
            "Тёмное зрение",
            "dd_feat",
            "srd51/Darkvision",
        )
        assert format_marker(hit.type, hit.id, hit.display) == text
        assert text[hit.start:hit.end] == text

    def test_simple_string_id_and_digits_only_id(self):
        """A non-composite external id parses; so does an all-digit string
        id under an external type (the record's key is a string, digits are
        legal strings — only the KERNEL half is numeric-exclusive)."""
        reg.register_external((_feat(),))
        (hit,) = parse("@[Ш](dd_feat:Darkvision)")
        assert hit.id == "Darkvision"
        (hit,) = parse("@[Ш](dd_feat:42)")
        assert hit.id == "42"

    def test_id_alphabet(self):
        """The id alphabet is ``\\d+ | [A-Za-z0-9][A-Za-z0-9._/+-]*`` (Д4):
        dots, slashes, underscores, pluses and dashes ride inside; spaces,
        brackets, colons, unicode letters and an empty id do not open or
        extend an id."""
        reg.register_external((_feat(),))
        for good in ("a", "a.b/c", "a_b+c-d", "9lives", "9.b", "a+b/c-d.e"):
            assert parse(f"@[X](dd_feat:{good})")[0].id == good
        for bad in ("", " a", "a b", "[a]", "a(b", "привет", "-a", ".a", "/a", "a:b"):
            assert parse(f"@[X](dd_feat:{bad})") == []

    def test_type_still_drives_the_shape(self):
        """Admissibility is BY THE TYPE: with the very same marker bytes a
        kernel type refuses the string id and the registered external type
        admits it — and de-registering the type returns the text to inert
        plain bytes (the section is the whole door)."""
        text = "@[Т](dd_feat:srd51/Darkvision)"
        assert parse(text) == []  # kernel-only registry: nothing opens
        reg.register_external((_feat(),))
        assert len(parse(text)) == 1
        reg.register_external(())
        assert parse(text) == []


class TestAdmissibleId:
    def test_direct_admissibility(self):
        assert is_admissible_id("character", "42")
        assert not is_admissible_id("character", "42a")
        assert not is_admissible_id("character", "srd51/Darkvision")
        reg.register_external((_feat(),))
        assert is_admissible_id("dd_feat", "srd51/Darkvision")
        assert is_admissible_id("dd_feat", "42")
        # outside the alphabet nothing is admissible for anybody
        assert not is_admissible_id("dd_feat", "")
        assert not is_admissible_id("dd_feat", "a b")
        assert not is_admissible_id("dd_feat", "привет")


# ── two-way fuzz (the design's named regression risk) ────────────────────────

_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-+"
_JUNK = "([])@ \\«»абв.-_+/:,0123456789abcxyz"


class TestFuzz:
    def test_round_trip_fuzz_external(self):
        """Direction one: any marker ASSEMBLED from an alphabet id and a
        bracket-free display parses back to the exact triple with exact
        spans, byte-for-byte, for the whole seeded sweep."""
        reg.register_external((_feat(),))
        rnd = random.Random(20261010)
        for _ in range(400):
            marker_id = rnd.choice("abzAZ09") + "".join(
                rnd.choice(_ID_ALPHABET) for _ in range(rnd.randrange(0, 12))
            )
            display = "".join(
                rnd.choice(_JUNK.replace("[", "").replace("]", ""))
                for _ in range(rnd.randrange(1, 9))
            ).strip()
            if not display:
                continue
            prefix = "до " * rnd.randrange(0, 2)
            text = f"{prefix}{format_marker('dd_feat', marker_id, display)} хвост"
            (hit,) = parse(text)
            assert (hit.display, hit.type, hit.id) == (display, "dd_feat", marker_id)
            assert text[hit.start:hit.end] == text[len(prefix):len(text) - len(" хвост")]

    def test_old_texts_are_never_reinterpreted_fuzz(self):
        """Direction two: over a seeded sweep of random junk (marker-shaped
        fragments included), the new parser's answer on a kernel-only or
        unknown type equals the OLD regex byte-for-byte — no text the old
        grammar left as plain text becomes a marker, and none of the old
        markers changed shape. External types are absent from the sweep's
        registry, which is exactly the ordinary-game posture."""
        reg.register_external(())
        rnd = random.Random(4242)
        for _ in range(600):
            parts = []
            for _ in range(rnd.randrange(1, 6)):
                kind = rnd.randrange(0, 5)
                if kind == 0:
                    t = rnd.choice(["character", "event", "item", "planet"])
                    i = "".join(rnd.choice(_JUNK) for _ in range(rnd.randrange(0, 6)))
                    d = "".join(rnd.choice(_JUNK) for _ in range(rnd.randrange(0, 5)))
                    parts.append(f"@[{d}]({t}:{i})")
                else:
                    parts.append("".join(rnd.choice(_JUNK) for _ in range(
                        rnd.randrange(1, 8))))
            text = "".join(parts)
            hits = parse(text)
            old = _old_parse(text)
            assert [(h.display, h.type, h.id, h.start, h.end) for h in hits] == [
                (d, t, str(i), s, e) for d, t, i, s, e in old
            ]


class TestStripAndRewrite:
    def test_strip_brackets(self):
        assert strip_brackets("[Алиса]") == "Алиса"
        assert strip_brackets("a]b[c") == "abc"
        assert strip_brackets("  Bob  ") == "Bob"
        assert strip_brackets("[]") == "?"
        assert strip_brackets("[[[ ]]]") == "?"
        assert strip_brackets("") == "?"

    def test_format_marker_strips_brackets_only_in_display(self):
        """Assembly rule (spec «Скобки снимаются только в маркере» /
        «Пустой display после strip»): the display loses every '[' and ']'
        (empty becomes '?'), the id bytes are quoted whole — brackets are
        outside the id alphabet anyway, nothing is cleaned there."""
        assert format_marker("character", 42, "[Алиса]") == "@[Алиса](character:42)"
        assert format_marker("event", "7", "[[ ]]") == "@[?](event:7)"
        assert format_marker("dd_feat", "srd51/Darkvision", "Тёмное зрение") == (
            "@[Тёмное зрение](dd_feat:srd51/Darkvision)"
        )

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

    def test_rewrite_never_touches_a_different_shape(self):
        """The rename pass is kernel-only; even asked for a pair an external
        marker quotes, the digits/strings comparison is textual and exact:
        an external composite id never matches a kernel int request, and
        the marker bytes survive untouched."""
        reg.register_external((_feat(),))
        text = "@[Старое](dd_feat:srd51/Darkvision) x @[X](character:42)"
        assert rewrite_display_name(text, "dd_feat", 42, "Новое") == text
        out = rewrite_display_name(text, "character", 42, "Новое")
        assert out == "@[Старое](dd_feat:srd51/Darkvision) x @[Новое](character:42)"
