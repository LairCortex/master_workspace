#!/usr/bin/env python3
"""Build script for НРИ Сценарий Менеджер.

Usage:
    python build_app.py          # build for current platform
    python build_app.py --clean  # clean previous build first
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "nri_manager.spec"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def clean() -> None:
    """Remove previous build artefacts."""
    for d in (DIST, BUILD):
        if d.exists():
            shutil.rmtree(d)
            print(f"  removed {d}")


def build() -> None:
    """Run PyInstaller with the spec file."""
    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm"]
    print(f"  running: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(ROOT))


def codesign_macos(app_path: Path) -> None:
    """Ad-hoc sign the .app bundle so macOS Gatekeeper allows launching."""
    print("  Ad-hoc signing .app bundle...")
    try:
        subprocess.check_call([
            "codesign", "--force", "--deep", "--sign", "-",
            str(app_path),
        ])
        print("  Signing OK")
    except FileNotFoundError:
        print("  WARNING: codesign not found, skipping")
    except subprocess.CalledProcessError as exc:
        print(f"  WARNING: codesign failed (exit {exc.returncode}), app may not launch on other Macs")


def post_build() -> None:
    """Print summary of build results."""
    system = platform.system()
    if system == "Darwin":
        app_bundle = DIST / "НРИ Сценарий Менеджер.app"
        folder = DIST / "nri_manager"
        if app_bundle.exists():
            codesign_macos(app_bundle)
            print(f"\n  macOS app bundle: {app_bundle}")
        elif folder.exists():
            print(f"\n  macOS folder:     {folder}")
            print(f"  Run with:         ./{folder / 'nri_manager'}")
    elif system == "Windows":
        exe = DIST / "nri_manager" / "nri_manager.exe"
        print(f"\n  Windows exe: {exe}")
    else:
        binary = DIST / "nri_manager" / "nri_manager"
        print(f"\n  Linux binary: {binary}")

    print("\n  The 'games/' folder will be created next to the executable on first launch.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build НРИ Сценарий Менеджер")
    parser.add_argument("--clean", action="store_true", help="Remove previous build first")
    args = parser.parse_args()

    print(f"Platform: {platform.system()} {platform.machine()}")

    if args.clean:
        print("Cleaning...")
        clean()

    print("Building...")
    build()
    post_build()


if __name__ == "__main__":
    main()
