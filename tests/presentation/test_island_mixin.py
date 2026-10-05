"""The IslandDialogMixin's own contract (task 2.3, design D3).

The facades exercise the mixin's happy path from their suites; this file
pins what no facade overrides: the abstract island source, the two
release-scheduling strategies (deferred default vs. the preset dialog's
synchronous pin), the shared Return→``defaultButton`` bridge (PR-029) and
the close parking behind a nested modal/popup show (PR-003) — the contract
every migrated window rides on.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog

from app.presentation.qml.island import IslandDialogMixin


class _Shell(IslandDialogMixin, QDialog):
    """A window that never loads a scene — only the lifecycle is tested."""


class _Clicked:
    """Duck of a QML button's ``clicked`` signal, counting the emissions."""

    def __init__(self) -> None:
        self.count = 0

    def emit(self) -> None:
        self.count += 1


class _Marker:
    """Duck of the island's default-action button (``clicked`` + ``enabled``)."""

    def __init__(self, enabled: bool = True, clickable: bool = True) -> None:
        self._enabled = enabled
        if clickable:
            self.clicked = _Clicked()

    def property(self, name: str):
        return self._enabled if name == "enabled" else None


class _Scene:
    """Duck of an island root answering the ``defaultButton`` marker."""

    def __init__(self, marker) -> None:
        self._marker = marker

    def property(self, name: str):
        return self._marker if name == "defaultButton" else None


def _key(key: Qt.Key = Qt.Key.Key_Return) -> QKeyEvent:
    return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)


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


def test_default_keys_press_the_island_marker(qtbot):
    """PR-029: Return and numpad Enter are the marker's; every other key and
    every window without a live marker stay the window's own business."""
    shell = _Shell()
    qtbot.addWidget(shell)
    marker = _Marker()
    shell._root = _Scene(marker)

    assert shell.take_island_default_key(_key()) is True
    assert shell.take_island_default_key(_key(Qt.Key_Enter)) is True
    assert marker.clicked.count == 2

    assert shell.take_island_default_key(_key(Qt.Key_Tab)) is False
    assert marker.clicked.count == 2


def _run_nested_modal(qtbot, inside, close_after_ms: int = 10) -> QDialog:
    """Exec an application-modal dialog and run ``inside`` INSIDE its loop.

    This is the PR-003 zombie shape without the flakiness: the static
    ``QFileDialog``/``QMessageBox`` conveniences run exactly such a nested
    loop on the stack of the QML handler that opened them, and here a close
    of the tested window is attempted from inside it — the press QA's
    accessibility channel delivered to the covered sheet.
    """
    modal = QDialog()
    modal.setWindowModality(Qt.ApplicationModal)
    qtbot.addWidget(modal)
    QTimer.singleShot(0, inside)
    QTimer.singleShot(close_after_ms, modal.reject)
    modal.exec()
    qtbot.wait(30)  # the outer loop turn where a parked close replays
    return modal


def test_reject_inside_nested_modal_parks_and_replays(qtbot, monkeypatch):
    """PR-003: a close landing inside a nested modal loop must schedule NO
    teardown there — Qt 6.10 dispatches the zero-timer (and DeferredDelete)
    right inside that loop, destroying QML objects whose handler opened the
    modal («Object destroyed while one of its QML signal handlers is in
    progress», XlsxImportRoot.qml:101). The close parks and replays on the
    outer loop instead."""
    releases: list[int] = []
    monkeypatch.setattr(
        IslandDialogMixin, "_release_island", lambda self: releases.append(1)
    )
    shell = _Shell()
    qtbot.addWidget(shell)
    shell.show()
    facts: dict = {}

    def inside() -> None:
        # The nested show is live: the attempt lands on the covered window.
        assert QApplication.instance().activeModalWidget() is not None
        shell.reject()
        facts["visible"] = shell.isVisible()
        facts["result"] = shell.result()
        facts["pending"] = shell._pending_close is not None
        facts["releases"] = list(releases)

    _run_nested_modal(qtbot, inside)
    # Nothing ran while the nested loop was live: no close, no teardown.
    # (A QDialog answers result() 0 from the start — visibility and the
    # park are the states that prove the close did not run there.)
    assert facts == {
        "visible": True, "result": 0, "pending": True, "releases": [],
    }
    # After the loop, the replayed close went through the normal path.
    assert not shell.isVisible()
    assert shell.result() == 0
    assert shell._pending_close is None
    assert releases


def test_accept_and_done_park_behind_the_nested_modal(qtbot, monkeypatch):
    """Every public close entry parks — accept, reject, done alike (done
    covers the result code the replayed close must keep)."""
    monkeypatch.setattr(
        IslandDialogMixin, "_release_island", lambda self: None
    )
    accepted = _Shell()
    qtbot.addWidget(accepted)
    accepted.show()
    inner_visible: list[bool] = []
    _run_nested_modal(
        qtbot,
        lambda: (accepted.accept(), inner_visible.append(accepted.isVisible())),
    )
    assert inner_visible == [True]  # still open while the nested loop ran
    assert accepted.result() == 1 and not accepted.isVisible()

    coded = _Shell()
    qtbot.addWidget(coded)
    coded.show()
    _run_nested_modal(qtbot, lambda: coded.done(42))
    assert coded.result() == 42 and not coded.isVisible()


def test_second_press_rides_the_first_park(qtbot, monkeypatch):
    """Re-pressing during the park window is ignored: one parked close, the
    first one, exactly once."""
    monkeypatch.setattr(IslandDialogMixin, "_release_island", lambda self: None)
    shell = _Shell()
    qtbot.addWidget(shell)
    shell.show()
    pending_ids: list[int] = []

    def inside() -> None:
        shell.reject()
        pending_ids.append(id(shell._pending_close))
        shell.accept()  # a second, contradicting press — ignored
        assert id(shell._pending_close) == pending_ids[0]

    _run_nested_modal(qtbot, inside)
    assert shell.result() == 0  # the FIRST parked close won


def test_close_event_parks_as_a_fresh_close(qtbot, monkeypatch):
    """The window-manager close parks too, replayed as a NEW ``close()`` —
    the arriving QCloseEvent is owned by the nested dispatch and must not
    outlive it."""
    monkeypatch.setattr(IslandDialogMixin, "_release_island", lambda self: None)
    shell = _Shell()
    qtbot.addWidget(shell)
    shell.show()
    inner: list[bool] = []

    def inside() -> None:
        shell.close()
        inner.append(shell.isVisible())

    _run_nested_modal(qtbot, inside)
    assert inner == [True]
    assert not shell.isVisible()
    assert shell.result() == 0  # QDialog::closeEvent → done(0) on replay


def test_own_modal_does_not_park_the_close(qtbot, monkeypatch):
    """A modal that IS this window (the launcher under its own ``exec()``)
    is not a nesting above the handler: its close must run synchronously,
    or the show it answers could never end — this is what keeps the launcher
    closable under the PR-003 contract."""
    monkeypatch.setattr(IslandDialogMixin, "_release_island", lambda self: None)
    shell = _Shell()
    qtbot.addWidget(shell)
    shell.setWindowModality(Qt.ApplicationModal)
    QTimer.singleShot(0, shell.reject)
    assert shell.exec() == 0  # returns: the close ran inside its own loop


def test_pending_close_rearms_while_still_nested(qtbot, monkeypatch):
    """Stacked shows (the QA zombie: two file dialogs, two loops) hold the
    park across retries: every replay attempt that still finds a nested
    show re-arms instead of tearing down."""
    monkeypatch.setattr(IslandDialogMixin, "_release_island", lambda self: None)
    shell = _Shell()
    qtbot.addWidget(shell)
    shell.show()
    # park(True) → reject parks; run#1 nested(True) → re-arm; run#2 nested
    # (False) → replay reject, whose own probe sees (False) and whose done
    # chain sees (False) too — every later probe is (False) as well.
    nested = iter([True, True] + [False] * 8)
    monkeypatch.setattr(shell, "_close_is_nested", lambda: next(nested))
    shell.reject()
    assert shell._pending_close is not None
    qtbot.wait(50)
    assert not shell.isVisible() and shell._pending_close is None


def test_run_pending_close_without_a_park_is_quiet(qtbot):
    """A stray replay callback (park already consumed) must no-op."""
    shell = _Shell()
    qtbot.addWidget(shell)
    shell._run_pending_close()  # must not raise
    assert shell._pending_close is None


def test_default_key_is_left_alone_without_a_live_marker(qtbot):
    """The three shapes in which the bridge must NOT eat the key (PR-029):
    no island yet, an island with no marker, a marker that cannot be clicked
    — and the disabled Save of a form the sheet refuses to save."""
    shell = _Shell()
    qtbot.addWidget(shell)

    assert shell.take_island_default_key(_key()) is False  # no _root at all

    shell._root = _Scene(None)
    assert shell.take_island_default_key(_key()) is False  # island without a marker

    shell._root = _Scene(_Marker(clickable=False))
    assert shell.take_island_default_key(_key()) is False  # marker is no button

    disabled = _Marker(enabled=False)
    shell._root = _Scene(disabled)
    assert shell.take_island_default_key(_key()) is False
    assert disabled.clicked.count == 0
