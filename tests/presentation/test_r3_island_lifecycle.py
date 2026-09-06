"""Shared-engine and deferred-teardown checks for the R3 pack-2 islands."""
from __future__ import annotations

from PySide6.QtQml import QQmlEngine
from PySide6.QtQuickWidgets import QQuickWidget

from app.infrastructure.llm.config import LlmConfig
from app.presentation.qml.engine import qml_engine
from app.presentation.views.event_types_dialog import EventTypesDialog
from app.presentation.views.llm_setup_dialog import LlmSetupDialog


class _EmptyEventTypesService:
    async def get_event_types(self):
        return []


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
