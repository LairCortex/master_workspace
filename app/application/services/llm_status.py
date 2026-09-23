"""LLM connection statuses — the single source of the wire values.

The two textual statuses travel to QML and are compared across view models,
so the enum mixes in ``str``: every existing equality, signal and property
hand-off keeps working unchanged (nri-0011, design D2). Re-spelling the
literal values anywhere else in ``app/`` is pinned off by rule R6 in
``tests/test_architecture_layers.py``.
"""
from __future__ import annotations

from enum import Enum


class LlmStatus(str, Enum):
    """Connection readiness, decided from the stored config without network."""

    #: The connection config is incomplete (empty base_url or model).
    NOT_CONFIGURED = "not_configured"
    #: The config is complete; the endpoint itself is probed only on demand.
    READY = "ready"
