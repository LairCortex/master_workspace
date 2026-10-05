"""PR-003 anti-regression: closing a sheet from inside its own QML signal
handler must never tear the island down while that handler is in progress.

The QA record (docs/qa/test-plan-2026-10-03.md, «### PR-003»): closing the
.xlsx import sheet aborted the process in ~1/3 of the gallery passes with
Qt's «Object destroyed while one of its QML signal handlers is in
progress ... XlsxImportRoot.qml:101». The flaky part is the zombie file
dialog (a broken-modality state letting a press reach the covered sheet);
the crash itself is deterministic the moment the state is forced — the
nested ``exec()`` loop of the static ``QFileDialog`` shows it how Qt names
it in the very message:

    Most likely the object was deleted synchronously (use
    QObject::deleteLater() instead), or the application is running a nested
    event loop. This behavior is NOT supported!

Offscreen the forced state is exact: press the browse button through its
accessibility action (QML handler on the stack), reject the sheet from a
timer that fires inside the file dialog's loop (QA's zombie press). Pre-fix
this aborts with SIGABRT (observed exit code 134 at the first cycle — the
flaky 1/3 lives in the live app's ability to reach the zombie state, not in
the crash); post-fix the close parks behind the nested show and replays on
the outer loop, ten cycles deep (tests/presentation/pr003_close_channel_child.py).

The same mechanism covers the entity card's «Выбрать файл» channel
(EntityCardRoot.qml:153, PR-026 — the record there names XlsxImportRoot.qml:101
as «тот же класс»): the card leaves through these same mixin close entries
and its deleteLater rides the same replayed ``finished``.

The child runs as a subprocess because the red shape of this defect is a
process abort — an in-process red would take the pytest worker with it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHILD = Path(__file__).with_name("pr003_close_channel_child.py")

#: Qt's abort line; its presence in the child's stderr means the defect is
#: back (and the child would not survive to exit cleanly anyway).
GUARD_LINE = "destroyed while one of its QML signal handlers is in progress"


def test_close_inside_qml_handler_does_not_kill_the_process():
    proc = subprocess.run(
        [sys.executable, str(CHILD)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert GUARD_LINE not in proc.stderr, (
        f"Qt destroyed a QML object inside its running signal handler:\n{proc.stderr}"
    )
    assert proc.returncode == 0, (
        f"the close-channel child died (exit {proc.returncode}):\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert "10 cycles survived" in proc.stdout
