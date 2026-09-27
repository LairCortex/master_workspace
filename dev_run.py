#!/usr/bin/env python3
"""Run the app from a source checkout with its real desktop identity.

Why this exists: on macOS ``python -m app.main`` runs the Homebrew framework
launcher, which execs the interpreter stub inside its own Python.app — so
LaunchServices attributes the process to Python.app and the Dock tooltip, the
Dock menu and the app menu all say "Python". The label follows the bundle
around the window-owning process's executable; no Qt or AppKit call renames
it at runtime (verified: lsappinfo reports bundle path Python.app, private
setinfo is rejected). Therefore the fix is structural: this script assembles
a throwaway .app wrapper under build/dev_app/ (gitignored) whose
CFBundleExecutable is a copy of the interpreter stub itself — the process
then lives inside OUR bundle and macOS labels it "Master Workspace", the
same way the release .app is labelled through nri_manager.spec.

The copied stub resolves the stdlib on its own (framework home is baked in);
the checkout and the venv's site-packages reach sys.path through
LSEnvironment.PYTHONPATH in the generated Info.plist. Fallback: a python
whose stub cannot be located (non-framework build) still runs through the
wrapper as a child process, with the interpreter's own label — the release
.app remains the fully correct identity there.

On Windows and Linux the taskbar reads the window title and the desktop
identity set in app/main.py (applicationName/desktopFileName/AppUserModelID),
so there the script simply runs the module.

Usage (with the venv active):
    python dev_run.py
"""
from __future__ import annotations

import importlib.util
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESOURCES = ROOT / "app" / "resources"
DEV_APP = ROOT / "build" / "dev_app" / "Master Workspace Dev.app"
CONTENTS = DEV_APP / "Contents"
MACOS_DIR = CONTENTS / "MacOS"
BUNDLE_RESOURCES = CONTENTS / "Resources"
# The executable file name doubles as the label fallback; the plist display
# name below is what the Dock and the app menu actually show.
EXECUTABLE_NAME = "Master Workspace"
APP_NAME = "Master Workspace"
# The .dev suffix keeps LaunchServices from conflating the wrapper with the
# release bundle of nri_manager.spec.
BUNDLE_ID = "com.nri.scenario-manager.dev"


def framework_stub() -> Path | None:
    """Locate the executable stub of the framework interpreter behind us.

    ``sys._base_executable`` is the real interpreter (venv links point here);
    a macOS framework build ships the executable inside Python.app next to
    the framework version directory that holds ``bin``.
    """
    base = Path(sys._base_executable).resolve()
    stub = base.parent.parent / "Resources" / "Python.app" / "Contents" / "MacOS" / "Python"
    return stub if stub.is_file() else None


def python_path() -> str:
    """PYTHONPATH for the wrapper: the checkout plus the venv's site-packages."""
    entries = [str(ROOT)]
    if sys.prefix != sys.base_prefix:
        minor = f"python{sys.version_info.major}.{sys.version_info.minor}"
        entries.append(str(Path(sys.prefix) / "lib" / minor / "site-packages"))
    return ":".join(entries)


def assemble_bundle(stub: Path) -> None:
    """(Re)build the throwaway wrapper; cheap enough to redo every run."""
    # Full rebuild: a stale executable or launcher from an older iteration
    # inside the bundle confuses both codesign and LaunchServices.
    shutil.rmtree(DEV_APP, ignore_errors=True)
    MACOS_DIR.mkdir(parents=True, exist_ok=True)
    BUNDLE_RESOURCES.mkdir(parents=True, exist_ok=True)
    info_plist = {
        # The Dock/menu label: display name first, CFBundleName as fallback —
        # the same pair the release BUNDLE writes (nri_manager.spec).
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": EXECUTABLE_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "dev",
        "CFBundleIconFile": "app_icon",
        "NSHighResolutionCapable": True,
        # The copied stub starts with no venv of its own, so the checkout and
        # the venv libraries are injected the Apple way (``open`` has no env
        # flag). cwd stays "/" — every app path is resolved absolutely.
        "LSEnvironment": {"PYTHONPATH": python_path()},
    }
    with open(CONTENTS / "Info.plist", "wb") as fh:
        plistlib.dump(info_plist, fh)
    # Copy every run: survives a Homebrew upgrade and re-signing of the stub.
    executable = MACOS_DIR / EXECUTABLE_NAME
    shutil.copy2(stub, executable)
    executable.chmod(0o755)
    # The copied stub carries the source ad-hoc signature; LaunchServices
    # rejects it in the foreign bundle (open error -54) until the copy is
    # re-signed at its own path.
    subprocess.run(
        ["codesign", "-s", "-", "--force", str(executable)],
        check=True,
        capture_output=True,
    )
    shutil.copy2(RESOURCES / "app_icon.icns", BUNDLE_RESOURCES / "app_icon.icns")
    # Touch the bundle root so LaunchServices re-reads plist and icon.
    DEV_APP.touch()


def assemble_fallback_bundle() -> None:
    """Wrapper for interpreters without a locatable framework stub.

    The app runs as a child of the wrapper's shell — correct icon, but the
    Dock label stays the interpreter's (documented fallback in the module
    docstring).
    """
    shutil.rmtree(DEV_APP, ignore_errors=True)
    MACOS_DIR.mkdir(parents=True, exist_ok=True)
    BUNDLE_RESOURCES.mkdir(parents=True, exist_ok=True)
    info_plist = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": "run-master-workspace",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "dev",
        "CFBundleIconFile": "app_icon",
        "NSHighResolutionCapable": True,
    }
    with open(CONTENTS / "Info.plist", "wb") as fh:
        plistlib.dump(info_plist, fh)
    launcher = MACOS_DIR / "run-master-workspace"
    # ``open`` starts a bundle with cwd=/, hence the explicit cd: the games
    # directory and relative paths are resolved from the repo root.
    launcher.write_text(
        "#!/bin/sh\n"
        f'cd "{ROOT}" || exit 1\n'
        f'exec "{sys.executable}" -m app.main\n'
    )
    launcher.chmod(0o755)
    shutil.copy2(RESOURCES / "app_icon.icns", BUNDLE_RESOURCES / "app_icon.icns")
    DEV_APP.touch()


def main() -> int:
    if importlib.util.find_spec("PySide6") is None:
        print("  PySide6 not importable — run inside the project venv (AGENTS.md Setup)")
        return 1
    if sys.platform != "darwin":
        # Windows/Linux: no bundle attribution problem — run the module.
        return subprocess.call([sys.executable, "-m", "app.main"], cwd=ROOT)
    stub = framework_stub()
    if stub is not None:
        assemble_bundle(stub)
    else:
        print("  no framework interpreter stub — using the child-process fallback")
        assemble_fallback_bundle()
    print(f"  opening {DEV_APP}")
    args = ["open", str(DEV_APP)]
    if stub is not None:
        # The copied stub IS the interpreter: feed it the module launch.
        args += ["--args", "-m", "app.main"]
    subprocess.check_call(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
