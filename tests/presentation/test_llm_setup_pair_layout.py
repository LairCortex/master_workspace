"""NRI-0016 group 4 (LS1–LS4) — the LLM wizard island: pairs, footer, names.

LS1 (spec «Подпись стоит у своего поля»): ONE Repeater now emits per-row
``ColumnLayout { label; field }`` delegates — the caption on top, its own
multiline field directly under it (owner design note 2026-09-26; the pair
was side-by-side before) — so an ordered walk of a page's children reads
label, field, label, field… and each field's accessibility name equals the
very caption its own label paints — on every real FIELD_CONFIG page and,
with synthetic 1-field / 5-field pages, at any row count. This pins out the
two-old-Repeater structure (all labels above all fields), which was the
LS1 defect.

LS2 (spec «Оконный формат wizard с постоянным выходом и счётчиком»): the
counter «N из M» and «Закрыть» live in the footer OUTSIDE the StackLayout,
visible on every page; «Закрыть» is a plain reject — the offscreen press
below proves nothing stands between it and ``finished`` (a confirmation
would have spun a modal loop and hung this test).

LS4 (DEFECT-LS4 re-diagnosis): the «Ключ API» field's accessible caption is
the root's constant everywhere; the explanatory hint is not allowed to sit
in any slot assistive tools read as the field's name (live cocoa: Qt zeroes
the password field's Accessible.name on AT attach and keeps the placeholder
as the fallback label — so the placeholder must BE the caption).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QAccessible
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QDialog

from app.application.services.llm_service import FIELD_LABELS
from app.domain import entity_registry
from app.infrastructure.llm.config import LlmConfig
from app.presentation.views.llm_setup_dialog import LlmSetupDialog
from tests.presentation.qml_helpers import find_item

# The page model as the VM derives it from the domain registry (the same
# view tests/presentation/test_llm_setup_island.py keeps locally).
_PAGES = {
    desc.key: list(desc.llm_fields)
    for desc in map(entity_registry.descriptor, entity_registry.LLM_TYPES)
}

_LABEL = "fieldPromptLabel_"
_FIELD = "fieldPrompt_"


@pytest.fixture
def dialog(qtbot):
    dlg = LlmSetupDialog(
        config=LlmConfig("https://api.openai.com/v1", "gpt-4o-mini", "sk-123"),
        world_prompt="Test world",
        field_prompts={"event": {"name": "Evt name"}},
    )
    qtbot.addWidget(dlg)
    return dlg


def _ordered_items(item: QQuickItem):
    """Depth-first pre-order over the visual tree in child order — the
    «развёртка детей страницы» the pair order is read from (walk_items in
    qml_helpers is stack-based and does not preserve the sibling order)."""
    yield item
    for child in item.childItems():
        yield from _ordered_items(child)


def _a11y_name(item: QQuickItem) -> str:
    iface = QAccessible.queryAccessibleInterface(item)
    assert iface is not None, f"no accessibility interface on {item.objectName()!r}"
    return iface.text(QAccessible.Name)


def _caption_pairs(page: QQuickItem) -> list[tuple[QQuickItem, QQuickItem]]:
    """(label, field) pairs in the page's child order, alternation enforced:
    any drift back to «all labels, then all fields» fails the kinds check."""
    seq: list[tuple[str, QQuickItem]] = []
    for item in _ordered_items(page):
        name = item.objectName()
        if name.startswith(_LABEL):
            seq.append(("label", item))
        elif name.startswith(_FIELD):
            seq.append(("field", item))
    kinds = [kind for kind, _item in seq]
    assert kinds == ["label", "field"] * (len(kinds) // 2), (
        f"page {page.objectName()}: no strict label→field alternation: {kinds}"
    )
    return [(seq[i][1], seq[i + 1][1]) for i in range(0, len(seq), 2)]


def _scene_rect(item: QQuickItem) -> tuple[float, float, float, float]:
    top_left = item.mapToScene(QPointF(0, 0))
    return top_left.x(), top_left.y(), item.width(), item.height()


def _press(widget, object_name: str) -> None:
    """The offscreen press contract (AGENTS): QAccessible actionInterface."""
    iface = QAccessible.queryAccessibleInterface(find_item(widget, object_name))
    assert iface is not None
    actions = iface.actionInterface()
    assert actions is not None and "Press" in actions.actionNames()
    actions.doAction("Press")


# ── LS1: the tree pairs every label with its own field ───────────────────────


def test_labels_alternate_with_their_own_fields_on_every_real_page(dialog):
    """Task 4.1 check: for every FIELD_CONFIG page the ordered children read
    label, field, … and the field's name equals its own painted caption."""
    for entity_type, field_names in _PAGES.items():
        page = find_item(dialog.quick, f"fieldPromptsPage_{entity_type}")
        pairs = _caption_pairs(page)
        assert len(pairs) == len(field_names), entity_type
        for (label, field), name in zip(pairs, field_names):
            suffix = f"{entity_type}_{name}"
            assert label.objectName() == _LABEL + suffix
            assert field.objectName() == _FIELD + suffix
            caption = FIELD_LABELS[name]
            assert label.property("text") == caption + ":"
            assert _a11y_name(field) == caption
            # one shared row delegate is the pair's only container
            assert field.parentItem() is label.parentItem()
            assert field.parentItem().objectName() == "fieldPromptRow_" + suffix


def _fake_pages(monkeypatch, key: str, fields: tuple[str, ...]) -> None:
    """A registry with a single <key>-typed entity carrying `fields` — the
    seam for the «при одном поле и при пяти» half of the 4.1 check."""
    monkeypatch.setattr(entity_registry, "LLM_TYPES", ("fake-type",))
    monkeypatch.setattr(
        entity_registry,
        "descriptor",
        lambda _etype: SimpleNamespace(
            key=key, plural_label="Тестовые сущности", llm_fields=fields
        ),
    )


@pytest.mark.parametrize(
    "key,fields",
    [
        pytest.param("qaone", ("backstory",), id="one-field"),
        pytest.param(
            "qafive", ("name", "characteristics", "backstory", "personality", "tasks"),
            id="five-fields",
        ),
    ],
)
def test_pair_order_is_correct_for_one_and_five_fields(qtbot, monkeypatch, key, fields):
    _fake_pages(monkeypatch, key, fields)
    dlg = LlmSetupDialog(config=LlmConfig("http://x/v1", "m", ""))
    qtbot.addWidget(dlg)

    page = find_item(dlg.quick, f"fieldPromptsPage_{key}")
    pairs = _caption_pairs(page)
    assert len(pairs) == len(fields)
    for (label, field), name in zip(pairs, fields):
        assert _a11y_name(field) == FIELD_LABELS[name]

    # The layout half of the check on the MATERIALIZED page: show it, so the
    # ColumnLayout is held to really putting the caption directly ABOVE its
    # own field (owner design note 2026-09-26: «поля ввода под название»).
    dlg.vm.goNext()  # world page
    dlg.vm.goNext()  # → the (only) field page, StackLayout index 2
    assert dlg.vm.currentPage == 2
    dlg.quick.grab()  # the layout/materialization pass (island_rows precedent)
    for (label, field), name in zip(pairs, fields):
        lx, ly, lw, lh = _scene_rect(label)
        fx, fy, fw, fh = _scene_rect(field)
        assert lw > 0 and fh > 0, name
        # The field starts no higher than where its caption ends (one raster
        # of tolerance): the caption is above, never beside or below.
        assert fy >= ly + lh - 1, f"field not below its label: {name}"
        # Same left edge — the pair is one column, not a floating field.
        assert abs(fx - lx) <= 1, f"field not left-aligned under its label: {name}"


# ── design 2026-09-26: the vertical pair column stays fully reachable ───────


def _flickable_of(item: QQuickItem) -> QQuickItem | None:
    """The Flickable ancestor of a pair (the ScrollView's content viewport)."""
    anc = item.parentItem()
    while anc is not None:
        if anc.property("contentHeight") is not None and anc.property("contentY") is not None:
            return anc
        anc = anc.parentItem()
    return None


def _field_page(qtbot, monkeypatch, key: str, fields: tuple[str, ...]):
    _fake_pages(monkeypatch, key, fields)
    dlg = LlmSetupDialog(config=LlmConfig("http://x/v1", "m", ""))
    qtbot.addWidget(dlg)
    dlg.resize(640, 480)
    dlg.vm.goNext()  # world page
    dlg.vm.goNext()  # → the (only) field page
    dlg.quick.grab()
    return dlg


def test_tall_field_page_reaches_every_field_via_scroll(qtbot, monkeypatch):
    """Five multiline pairs at the window's minimum height overflow the page
    (measured +2 px offscreen 2026-09-26) — the column therefore rides a
    ScrollView: the Flickable exists, is scrolled, and after the scroll the
    last field's bottom edge stands no lower than the viewport's own."""
    fields = ("name", "characteristics", "backstory", "personality", "tasks")
    dlg = _field_page(qtbot, monkeypatch, "qatall", fields)
    last = find_item(dlg.quick, "fieldPrompt_qatall_tasks")
    flick = _flickable_of(last)
    assert flick is not None, "the pair column must live inside a ScrollView"
    slack = flick.property("contentHeight") - flick.height()
    assert slack > 0, "the five-field page must be scrollable at 480 px"
    flick.setProperty("contentY", slack)
    dlg.quick.grab()
    bottom = last.mapToScene(QPointF(0, last.height())).y()
    viewport_bottom = flick.mapToScene(QPointF(0, flick.height())).y()
    assert bottom <= viewport_bottom + 1, (
        f"last field clipped below the viewport: {bottom} > {viewport_bottom}"
    )


def test_short_field_page_fits_without_scrolling(qtbot, monkeypatch):
    """The usual three-field page (the «События» shape) stays fully visible
    at the default 480 px without any scroll — the compactness half of the
    owner note («многострочно, но не занимало много места»)."""
    fields = ("name", "characteristics", "backstory")
    dlg = _field_page(qtbot, monkeypatch, "qashort", fields)
    last = find_item(dlg.quick, "fieldPrompt_qashort_backstory")
    flick = _flickable_of(last)
    assert flick is not None
    assert flick.property("contentHeight") <= flick.height() + 1, (
        "the three-field page must fit without scrolling"
    )
    bottom = last.mapToScene(QPointF(0, last.height())).y()
    viewport_bottom = flick.mapToScene(QPointF(0, flick.height())).y()
    assert bottom <= viewport_bottom + 1


# ── LS2: persistent footer «N из M» + «Закрыть» on every page ────────────────


def test_footer_counter_and_close_are_visible_on_every_page(dialog):
    """Task 4.2 check: counter == «current из total» and «Закрыть» visible on
    all pages, including the field-prompt ones and the last one (spec
    scenario «Счётчик страниц виден всегда»)."""
    vm = dialog.vm
    assert vm.pageCount == len(_PAGES) + 3  # 2 statics + field pages + warnings
    for page in range(vm.pageCount):
        assert vm.currentPage == page
        counter = find_item(dialog.quick, "pageCounterLabel")
        assert counter.property("visible") is True
        assert counter.property("text") == f"{page + 1} из {vm.pageCount}"
        close = find_item(dialog.quick, "setupCloseButton")
        assert close.property("visible") is True
        assert close.property("text") == "Закрыть"
        assert close.property("enabled") is True
        if page < vm.pageCount - 1:
            vm.goNext()
    assert vm.currentPage == vm.pageCount - 1


def test_close_button_press_is_a_plain_reject(dialog):
    """Task 4.2 check: «Закрыть» → finished(Rejected) with no confirmation —
    offscreen a real QMessageBox would spin a nested modal loop and hang this
    test instead of returning; the edits stay in the island, nothing saves."""
    finished: list[int] = []
    dialog.finished.connect(finished.append)

    _press(dialog.quick, "setupCloseButton")

    assert finished == [int(QDialog.DialogCode.Rejected)]
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.vm.endpoint == "https://api.openai.com/v1"


def test_close_button_follows_the_running_save_gate(dialog):
    """The D4 rule («во время генерации окно закрыть нельзя») shows on the
    button instead of a silently inert press."""
    dialog.vm.set_saving(True)
    assert find_item(dialog.quick, "setupCloseButton").property("enabled") is False
    dialog.vm.set_saving(False)
    assert find_item(dialog.quick, "setupCloseButton").property("enabled") is True


# ── LS4: every readable name slot of «Ключ API» carries the caption ──────────


def test_key_api_field_name_is_the_caption_not_the_hint(dialog):
    """Task 4.3 check (LS4) + DEFECT-LS4 fix.

    Offscreen Qt keeps Accessible.name intact, so the interface name is the
    caption («Ключ API»). On the live cocoa tree Qt *zeroes* a password
    field's Accessible.name the moment an assistive technology attaches and
    keeps placeholderText as the slot tools fall back to — which is how the
    old hint placeholder surfaced as the field's name. The fix makes the
    placeholder carry the same stable caption and moves the explanatory
    hint into its own text node, so every readable slot shows «Ключ API».
    The zeroed-name half of the live tree stays a live-only check (see the
    QA report's fix-verification section)."""
    key = find_item(dialog.quick, "keyField")
    assert _a11y_name(key) == "Ключ API"
    placeholder = str(key.property("placeholderText"))
    assert placeholder == "Ключ API"          # fallback label == caption
    assert "необяз" not in placeholder.lower()  # no hint text in the slot
    hint = find_item(dialog.quick, "apiKeyHint")
    assert "необязательно" in str(hint.property("text")).lower()
    root = dialog.quick.rootObject()
    assert root.property("apiKeyFieldName") == "Ключ API"
