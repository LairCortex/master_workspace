"""Tests for AppState — shared signal-based state object."""
from __future__ import annotations

import pytest

from app.presentation.state.app_state import AppState


@pytest.fixture
def app_state():
    # A plain (unparented) QObject: no widget-tree registration needed
    return AppState()


def test_current_event_defaults_to_none(app_state):
    assert app_state.current_event is None


def test_set_current_event_updates_property(app_state):
    event = object()
    app_state.current_event = event
    assert app_state.current_event is event


def test_set_current_event_emits_changed_signal(app_state):
    received: list = []
    app_state.current_event_changed.connect(received.append)
    app_state.current_event = "event-A"
    app_state.current_event = "event-B"
    assert received == ["event-A", "event-B"]


def test_events_updated_signal(app_state):
    received: list = []
    app_state.events_updated.connect(lambda: received.append(1))
    app_state.events_updated.emit()
    assert received == [1]


def test_search_results_changed_signal(app_state):
    received: list = []
    app_state.search_results_changed.connect(received.append)
    app_state.search_results_changed.emit({"events": [1]})
    assert received == [{"events": [1]}]
