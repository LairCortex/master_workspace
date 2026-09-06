"""Shared-engine and deferred-teardown checks for the R3 pack-2 islands."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtQml import QQmlEngine
from PySide6.QtQuickWidgets import QQuickWidget

import app.presentation.views as views_package

from app.infrastructure.llm.config import LlmConfig
from app.presentation.qml.engine import qml_engine
from app.presentation.views.event_types_dialog import EventTypesDialog
from app.presentation.views.llm_setup_dialog import LlmSetupDialog


class _EmptyEventTypesService:
    async def get_event_types(self):
        return []


def test_no_facade_writes_its_context_names_into_the_shared_engine():
    """``rootContext()`` of a QQuickWidget on the shared engine IS the engine
    root context, so a name written there is one global slot: the facade that
    wrote it last owns it, and when that facade dies the entry is nulled for
    every island still alive — closing the chars-list used to leave the
    timeline on the off-skin whites. Facades bind through ``island_context``
    (a private child context) instead; this grep keeps the seam closed."""
    views_root = Path(views_package.__file__).parent
    offenders = sorted(
        str(path.relative_to(views_root))
        for path in views_root.rglob("*.py")
        if "rootContext().setContextProperty" in path.read_text(encoding="utf-8")
    )
    assert offenders == []


async def test_both_islands_reopen_on_one_engine_after_deferred_teardown(qtbot, qapp):
    llm = LlmSetupDialog(LlmConfig())
    event_types = EventTypesDialog(_EmptyEventTypesService())
    qtbot.addWidget(llm)
    qtbot.addWidget(event_types)
    await event_types.wait_idle()

    shared = qml_engine()
    assert llm.quick.engine() is shared
    assert event_types.quick.engine() is shared
    assert QQmlEngine.contextForObject(llm.quick.rootObject()).engine() is shared
    assert QQmlEngine.contextForObject(event_types.quick.rootObject()).engine() is shared
    assert shared.rootContext().contextProperty("llmSetupVm") is None
    assert shared.rootContext().contextProperty("eventTypesVm") is None

    llm.reject()
    event_types.accept()
    qapp.processEvents()
    qapp.processEvents()
    assert llm.quick.status() == QQuickWidget.Status.Null
    assert event_types.quick.status() == QQuickWidget.Status.Null

    reopened_llm = LlmSetupDialog(LlmConfig())
    reopened_types = EventTypesDialog(_EmptyEventTypesService())
    qtbot.addWidget(reopened_llm)
    qtbot.addWidget(reopened_types)
    await reopened_types.wait_idle()
    assert reopened_llm.quick.engine() is shared
    assert reopened_types.quick.engine() is shared
    assert reopened_llm.quick.status() == QQuickWidget.Status.Ready
    assert reopened_types.quick.status() == QQuickWidget.Status.Ready
