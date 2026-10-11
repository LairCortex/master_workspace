"""The grimoire domain: a tolerant parser of Foundry-VTT spell files
(add-dnd-game-face, task 4.1; design Д8; spec dnd-grimoire-import «Гримуарный
файл проходит проверку с отчётом и ложится в глобальное хранилище»).

Long Story Short has no public JSON Schema for a spell file (design Д8), so
the check here is DOMAINE, not schema-shaped, and it reuses the module's
existing report posture: an ERROR refuses the import, a WARNING lets it
through and travels with it. Exactly the codes Д8 fixes live here:

* ``GRIMOIRE_UNPARSEABLE`` — the bytes are not JSON or their structure is not
  a spell document at all (nothing to store);
* ``GRIMOIRE_EMPTY`` — a readable spell document holding no printable spell;
* ``GRIMOIRE_DUP_SLUG`` — the same spell slug twice in one file (the second
  copy is what a dataset reference would silently resolve to);
* ``GRIMOIRE_SLUG_IN_SRD`` — the file re-declares a slug the public SRD lists
  already carry (legal, just redundant — the master owns the copy).

The format itself is the parser's decision, fixed here and pinned by the
golden tests (design Open Questions: «формат зафиксирован парсером, не вопрос
спецификации»). What the parser accepts is the shape a Foundry export really
carries:

* a top-level ARRAY of items (a World/compendium item export), or
* an OBJECT with the list under ``items``/``spells``, or
* an OBJECT that IS one item (``name`` + description).

An item is a spell when its ``type`` says so or names nothing (a bare LSS
export needs no type); its parts are read forgivingly:

* name     — ``name``;
* slug     — the first text of ``flags.lss.slug``, ``flags.slug``, ``slug``,
  ``system.slug``, ``id``, normalized (LSS references spells by slug, so this
  is the part the validator's dictionary consumes);
* text     — the HTML of ``system.description.value``, ``description.value``,
  ``system.description`` or ``description``, converted to plain text
  (:func:`html_to_plain_text`) — the module prints plain-text fields, so the
  markup never reaches a card.

Pure module: no Qt, no I/O, no network, no clock. Same input — same report.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Mapping, Sequence

from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport

# --- issue codes (stable machine contract, design Д8) ----------------------
CODE_GRIMOIRE_UNPARSEABLE = "GRIMOIRE_UNPARSEABLE"
CODE_GRIMOIRE_EMPTY = "GRIMOIRE_EMPTY"
CODE_GRIMOIRE_DUP_SLUG = "GRIMOIRE_DUP_SLUG"
CODE_GRIMOIRE_SLUG_IN_SRD = "GRIMOIRE_SLUG_IN_SRD"

#: Item keys a spell list hides under in the exports the parser accepts.
_LIST_KEYS: tuple[str, ...] = ("items", "spells")
#: Where a spell's slug may live, in the order the parser trusts (LSS keeps
#: it under its own flag; a bare LSS-flavoured entry names it ``id``).
_SLUG_KEYS: tuple[tuple[str, ...], ...] = (
    ("flags", "lss", "slug"),
    ("flags", "slug"),
    ("slug",),
    ("system", "slug"),
    ("id",),
)
#: Where the description HTML may live, in the order the parser trusts.
_TEXT_KEYS: tuple[tuple[str, ...], ...] = (
    ("system", "description", "value"),
    ("description", "value"),
    ("system", "description",),
    ("description",),
)
#: The item ``type`` of a spell (an item naming no type is accepted — the
#: tolerance Д8 asks for; an item naming another type is not a spell).
_SPELL_TYPE = "spell"

# ── HTML → plain text ──────────────────────────────────────────────────────

#: Tags that end a line of text; their opening AND closing edges break the
#: line, so a nested list still reads one item per line.
_BLOCK_TAGS = frozenset(
    {
        "address",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "ol",
        "p",
        "pre",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
#: Markup whose text is never prose (a stray script/style never prints).
_HIDDEN_TAGS = frozenset({"script", "style"})

_LINE_BREAK = "\n"


class _PlainTextExtractor(HTMLParser):
    """Collects the readable text of an HTML fragment (stdlib parser, so
    malformed markup degrades instead of failing: ``convert_charrefs`` decodes
    entities, and an unbalanced tag is just a tag the parser never saw)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _HIDDEN_TAGS:
            self._hidden_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append(_LINE_BREAK)

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN_TAGS:
            self._hidden_depth = max(0, self._hidden_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._parts.append(_LINE_BREAK)

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self._parts.append(data)

    def collected(self) -> str:
        """Everything gathered so far, line breaks where the block edges were."""
        return "".join(self._parts)


def html_to_plain_text(markup: str) -> str:
    """The HTML of a Foundry description as plain text: tags disappear,
    block edges become line breaks, every line's whitespace (a ``&nbsp;``
    included) collapses to single spaces, empty lines vanish.

    Nothing is invented and nothing is dropped from prose: inline tags keep
    their text, ``@Damage[1d8]``-style Foundry rolls ride along as written."""
    extractor = _PlainTextExtractor()
    extractor.feed(markup)
    extractor.close()
    lines = [
        " ".join(line.split()) for line in extractor.collected().split(_LINE_BREAK)
    ]
    return "\n".join(line for line in lines if line).strip()


# ── forgiving field reading ────────────────────────────────────────────────


def _text_at(document: Mapping[str, Any], path: Sequence[str]) -> str | None:
    """The text at a nested path, ``None`` when any step is absent or is not
    an object, or when the leaf is not a non-blank string."""
    current: Any = document
    for step in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(step)
    if isinstance(current, str) and current.strip():
        return current
    return None


def _first_text(document: Mapping[str, Any], paths: Sequence[Sequence[str]]) -> str | None:
    """The first readable text among the candidate paths (the tolerant read
    the format decision above prescribes)."""
    for path in paths:
        found = _text_at(document, path)
        if found is not None:
            return found
    return None


_SLUG_DROP_RE = re.compile(r"[^a-z0-9-]+")
_SLUG_DASH_RE = re.compile(r"-{2,}")


def normalize_spell_slug(raw: str) -> str:
    """A spell slug as the validator's dictionary knows it: lower case,
    spaces/underscores become dashes, characters outside ``a-z0-9-`` fall out,
    repeated and dangling dashes collapse.

    The rule is mechanical (the same posture as SRD-slug humanization in
    design Д11): a name the LSS namespace cannot spell (Cyrillic, punctuation
    only) yields the empty string, and the caller treats «no slug» honestly
    instead of inventing one."""
    lowered = raw.strip().lower()
    dashed = re.sub(r"[\s_]+", "-", lowered)
    return _SLUG_DASH_RE.sub("-", _SLUG_DROP_RE.sub("", dashed)).strip("-")


# ── parse result ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GrimoireSpell:
    """One spell the file declares: the normalized slug (``""`` when the
    entry names none — the spell still reads, it just cannot be referenced),
    the visible name and the plain-text description."""

    slug: str
    name: str
    description: str


@dataclass(frozen=True)
class GrimoireParse:
    """The check verdict and the spells behind it.

    ``document_id`` is the file's OWN identifier candidate as written (``id``,
    ``_id`` or ``slug`` of the document object) — raw and unvalidated, because
    turning an identifier into a file name is the storage's rule, not the
    parser's. ``title`` is the document's own caption (empty when the file
    names none — the storage falls back to the id, the way the dataset shelf
    lists an unreadable document under its file name)."""

    report: ValidationReport
    spells: tuple[GrimoireSpell, ...] = ()
    document_id: str | None = None
    title: str = ""


def _error(reason: str) -> GrimoireParse:
    return GrimoireParse(
        report=ValidationReport.of(
            [
                CheckIssue(
                    code=CODE_GRIMOIRE_UNPARSEABLE,
                    severity=Severity.ERROR,
                    path="<файл>",
                    message=reason,
                )
            ]
        )
    )


def _item_entries(root: Any) -> list[Any] | None:
    """The list of items behind a Foundry export root, ``None`` when the root
    is not a spell document at all (the spec's «структура вне формата»)."""
    if isinstance(root, list):
        return root
    if isinstance(root, dict):
        for key in _LIST_KEYS:
            candidate = root.get(key)
            if isinstance(candidate, list):
                return candidate
        # A single exported item carries its name at the top level.
        if isinstance(root.get("name"), str):
            return [root]
    return None


def _is_spell_entry(entry: Mapping[str, Any]) -> bool:
    """True unless the item names a type that is not a spell (an item without
    a usable ``type`` rides on the name/description the caller checks)."""
    item_type = entry.get("type")
    return not isinstance(item_type, str) or item_type.strip().lower() == _SPELL_TYPE


def _document_identity(root: Any) -> tuple[str | None, str]:
    """The document's own id candidate and caption (object roots only; a bare
    item list names neither)."""
    if not isinstance(root, dict):
        return None, ""
    document_id = _text_at(root, ("id",)) or _text_at(root, ("_id",)) or _text_at(
        root, ("slug",)
    )
    title = (
        _text_at(root, ("name",))
        or _text_at(root, ("title",))
        or _text_at(root, ("label",))
        or ""
    )
    return document_id, title


def parse_grimoire(
    content: str, srd_slugs: Sequence[str] | None = None
) -> GrimoireParse:
    """Check and read one grimoire's text (module docstring for the format).

    ``srd_slugs`` is the public SRD spell-slug list (the same union the
    dataset validator reads): with a list given, a file re-declaring one of
    its slugs earns «слаг из SRD»; ``None`` skips exactly that check, the LSS
    posture of the dataset validator (absent lists check nothing)."""
    try:
        root = json.loads(content)
    except json.JSONDecodeError as error:
        # ``json.loads`` on text raises nothing else: the caller decoded the
        # bytes (a screen reads the file as UTF-8), so a decode failure is not
        # this function's state to invent a branch for.
        return _error(
            f"файл не является корректным JSON: {error.msg} (строка {error.lineno})"
        )
    entries = _item_entries(root)
    if entries is None:
        return _error(
            "в файле нет документа заклинаний Foundry: ожидается список предметов "
            "в ключе items/spells, массив предметов или один предмет с именем"
        )
    document_id, title = _document_identity(root)
    issues: list[CheckIssue] = []
    spells: list[GrimoireSpell] = []
    seen: dict[str, str] = {}
    srd = frozenset(srd_slugs) if srd_slugs is not None else None
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not _is_spell_entry(entry):
            continue
        name = _text_at(entry, ("name",))
        if name is None:
            # Nothing to print the spell under: an entry without a name is
            # not a spell this product can show (the same tolerance the
            # dataset index keeps for a record without a usable id).
            continue
        slug = _first_text(entry, _SLUG_KEYS)
        normalized = normalize_spell_slug(slug) if slug is not None else ""
        path = f"spells[{normalized or name}]"
        markup = _first_text(entry, _TEXT_KEYS)
        spells.append(
            GrimoireSpell(
                slug=normalized,
                name=name.strip(),
                description=html_to_plain_text(markup) if markup is not None else "",
            )
        )
        if normalized:
            first = seen.get(normalized)
            if first is not None:
                issues.append(
                    CheckIssue(
                        code=CODE_GRIMOIRE_DUP_SLUG,
                        severity=Severity.WARNING,
                        path=path,
                        message=(
                            f"слаг {normalized!r} уже занят в файле: {first} и {path}"
                        ),
                    )
                )
            else:
                seen[normalized] = path
            if srd is not None and normalized in srd:
                issues.append(
                    CheckIssue(
                        code=CODE_GRIMOIRE_SLUG_IN_SRD,
                        severity=Severity.WARNING,
                        path=path,
                        message=(
                            f"слаг {normalized!r} есть в публичных SRD-списках — "
                            "копия гримуара избыточна"
                        ),
                    )
                )
    if not spells:
        return GrimoireParse(
            report=ValidationReport.of(
                issues
                + [
                    CheckIssue(
                        code=CODE_GRIMOIRE_EMPTY,
                        severity=Severity.ERROR,
                        path="<файл>",
                        message="в файле нет ни одного заклинания с именем",
                    )
                ]
            ),
            document_id=document_id,
            title=title,
        )
    return GrimoireParse(
        report=ValidationReport.of(issues),
        spells=tuple(spells),
        document_id=document_id,
        title=title,
    )


def grimoire_title_from_document(data: object, fallback: str) -> str:
    """The caption the storage list prints for a stored file: the document's
    own name/title/label, else the fallback. Forgiving by the same rule as
    :func:`app.dd.domain.dataset.dataset_title_from_document` — the title only
    labels screens; whether the file is importable is :func:`parse_grimoire`'s
    decision, not this reader's."""
    if isinstance(data, dict):
        for key in ("name", "title", "label"):
            candidate = data.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return fallback


def grimoire_spell_slugs(parse: GrimoireParse) -> tuple[str, ...]:
    """The parser's non-empty slugs, file order, deduplicated — the slice the
    dataset validator's dictionary absorbs (task 4.3)."""
    slugs: list[str] = []
    for spell in parse.spells:
        if spell.slug and spell.slug not in slugs:
            slugs.append(spell.slug)
    return tuple(slugs)
