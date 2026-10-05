"""PR-026 anti-regression: the entity card's «Выбрать файл» channel must
never tear the island down while the button's QML handler is in progress.

The QA record (docs/qa/test-plan-2026-10-03.md, «### PR-026»): after
«Выбрать файл» → path typed in the file panel → «Сохранить», the process died
in ~1/4 of the galop passes with Qt's «Object destroyed while one of its QML
signal handlers is in progress ... EntityCardRoot.qml» naming the browse
button's ``onClicked``. The fix is PR-003's close parking in the shared
``IslandDialogMixin`` — the card sits on the same mixin (EntityCardDialog
mixes IslandDialogMixin and leaves only through its accept/reject/done/
closeEvent), so this module pins the card's OWN channel the way
test_xlsx_import_close_crash.py pinned the sheet's.

Two directions, both honest:

* green: ten alternating cycles (reject / «Сохранить»-completion accept) of
  closing the card from inside the browse button's nested file-dialog loop
  leave the child alive, each close replayed on the outer loop;
* red-shape (the channel's proof-of-life): with the park neutralized in the
  child (pre-fix close scheduling), the same channel reproduces Qt's guard
  abort — so this pin really guards the crash, not a no-op.

The children run as subprocesses because the red shape is a process abort —
an in-process red would take the pytest worker with it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHILD = Path(__file__).with_name("pr026_close_channel_child.py")

#: Qt's abort line; its presence in a green child's stderr means the defect
#: is back (and the child would not survive to exit cleanly anyway).
GUARD_LINE = "destroyed while one of its QML signal handlers is in progress"


def _run_child(extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **(extra_env or {})}
    return subprocess.run(
        [sys.executable, str(CHILD)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )


def test_card_close_inside_image_pick_handler_survives_ten_cycles():
    proc = _run_child()
    assert GUARD_LINE not in proc.stderr, (
        f"Qt destroyed a QML object inside the card's browse handler:\n{proc.stderr}"
    )
    assert proc.returncode == 0, (
        f"the card close-channel child died (exit {proc.returncode}):\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert "10 cycles survived" in proc.stdout


def test_card_channel_without_the_park_reproduces_the_qt_guard():
    """The channel really reaches Qt's guard once the park is neutralized —
    the pre-fix shape of PR-026 pinned inside the module (red direction)."""
    proc = _run_child({"PR026_NOPARK": "1"})
    assert proc.returncode != 0, (
        f"the un-parked card channel exited cleanly — the red-shape of this "
        f"pin is gone (the channel no longer forces the crash?), so the green "
        f"pin above guards nothing:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert GUARD_LINE in proc.stderr, (
        f"the un-parked child died for another reason:\n{proc.stderr}"
    )
