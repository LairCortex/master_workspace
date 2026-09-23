"""The IslandDialogMixin's own contract (task 2.3, design D3).

The facades exercise the mixin's happy path from their suites; this file
pins what no facade overrides: the abstract island source, and the two
release-scheduling strategies (deferred default vs. the preset dialog's
synchronous pin) — the contract every migrated window rides on.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog

from app.presentation.qml.island import IslandDialogMixin


class _Shell(IslandDialogMixin, QDialog):
    """A window that never loads a scene — only the lifecycle is tested."""


def test_island_source_is_abstract(qtbot):
    shell = _Shell()
    qtbot.addWidget(shell)
    with pytest.raises(NotImplementedError):
        shell.island_source()


def test_release_is_deferred_one_loop_turn_by_default(qtbot, monkeypatch):
    releases: list[int] = []
    monkeypatch.setattr(
        IslandDialogMixin, "_release_island", lambda self: releases.append(1)
    )
    dialog = _Shell()
    qtbot.addWidget(dialog)
    dialog.reject()  # close() funnels through reject() -> done() as well
    assert releases == []  # nothing is torn down inside the closing frame
    qtbot.wait(20)  # the singleShot fires once the JS stack has unwound
    assert releases


def test_release_runs_synchronously_when_defer_is_off(qtbot, monkeypatch):
    releases: list[int] = []
    monkeypatch.setattr(
        IslandDialogMixin, "_release_island", lambda self: releases.append(1)
    )

    class _Sync(_Shell):
        island_release_deferred = False

    dialog = _Sync()
    qtbot.addWidget(dialog)
    dialog.reject()
    # The release already happened before reject() returned (WA_DeleteOnClose
    # rule — the one-shot could outlive the dialog's C++ object there).
    assert releases
    qtbot.wait(10)
    assert releases  # no second, late teardown
