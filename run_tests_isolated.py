"""Run the test suite with one pytest process per test module (PR-033).

Why this exists: the offscreen Qt/PySide suite contains a crash class the
repository cannot fix from Python — the Qt 6.10 QML engine keeps JS property
lookups on ``QObject`` wrappers whose Python side is already dead, and the
next engine work detonates (exit 139; measured under a debugger: an
``EXC_BAD_ACCESS`` inside ``PyUnicode_PythonToCpp_QString`` called from
``QV4::QObjectWrapper::getProperty``). The poison travels only BETWEEN test
modules: every file under ``tests/presentation`` is green in its own process
(a full sweep of all 130 files confirmed it), while module combinations in
one process crash nondeterministically (the layout lottery even makes the
crash vanish under any attaching debugger). Production uses one engine for
its whole life and shows each window from application-owned Python — the
posture tests structurally cannot share across dozens of module churns.

One process per module restores exactly that: each module starts from the
same known-good heap, the gate becomes deterministic, and coverage merges
from per-file data files (the same 100 % line gate is evaluated on the
combined result).

A failed/timed-out module gets ONE serial retry after the parallel pass:
the only observed residue of parallelism is an under-load wedge of the Qt
pixmap/engine teardown inside one heavy module (green serially, every time),
and a retry without siblings separates that from a real failure. A module
that passes only on retry is reported as FLAKY-but-green; two losses end the
run.

Usage:
    QT_QPA_PLATFORM=offscreen python run_tests_isolated.py            # whole tests/
    QT_QPA_PLATFORM=offscreen python run_tests_isolated.py tests/presentation -j 8
    python run_tests_isolated.py --no-cov tests/presentation/test_dialogs.py

Exit status: 0 only when every module passed AND (unless ``--no-cov``) the
combined line-coverage report met its configured ``fail_under``.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TIMEOUT_S = 1200  # a wedged Qt test must read as a failure, not a hung runner


def discover(paths: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for path in paths:
        if path.is_file():
            files.add(path)
            continue
        files.update(sorted(path.rglob("test_*.py")))
    return sorted(files)


def run_module(index: int, module: Path, cov_dir: Path | None, extra: list[str]) -> tuple[Path, int, float]:
    env = dict(os.environ)
    if cov_dir is not None:
        # one data file per module; `coverage combine` merges them at the end
        key = module.relative_to(ROOT).as_posix().replace("/", "_").removesuffix(".py")
        env["COVERAGE_FILE"] = str(cov_dir / f".coverage.{index:03d}-{key}")
    cmd = [
        sys.executable, "-m", "pytest", str(module),
        "-q", "--no-header", "-p", "no:cacheprovider", "-o", "faulthandler_timeout=120",
        *extra,
    ]
    if cov_dir is not None:
        cmd += ["--cov=app", "--cov-report=", "--cov-fail-under=0"]
    started = time.monotonic()
    log_path = (cov_dir or ROOT / "build").joinpath(f"{index:03d}-{module.stem}.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "wb") as log:
        try:
            proc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=TIMEOUT_S)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = 124
    return module, code, time.monotonic() - started


LOG_TAIL_LINES = 60


def print_log_tail(module: Path, cov_dir: Path | None, limit: int = LOG_TAIL_LINES) -> None:
    """Echo the tail of the module's most recent log (its serial-retry run).

    CI reads stdout only: without this, a module failure surfaces as nothing
    but an rc line while the pytest output sits in an un-fetched log file.
    """
    log_dir = cov_dir if cov_dir is not None else ROOT / "build"
    pattern = re.compile(rf"\d+-{re.escape(module.stem)}\.log")
    logs = [p for p in log_dir.glob(f"*-{module.stem}.log") if pattern.fullmatch(p.name)]
    if not logs:
        return
    log = max(logs, key=lambda p: p.stat().st_mtime)
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    tail = lines[-limit:]
    print(f"  --- last {len(tail)} of {len(lines)} log lines ({log.name}) ---")
    for line in tail:
        print(f"  | {line}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", default=None, help="test files/dirs (default: tests/)")
    parser.add_argument("-j", type=int, default=6, help="parallel processes (default 6)")
    parser.add_argument("--no-cov", action="store_true", help="skip coverage collection and the merge")
    parser.add_argument("--keep-logs", action="store_true", help="keep per-module logs (default: failures only)")
    parser.add_argument("--branch", action="store_true",
                        help="also measure branch coverage (report-only, mirrors CI run 2: never a gate)")
    args = parser.parse_args(argv)
    extra: list[str] = ["--cov-branch"] if (args.branch and not args.no_cov) else []

    raw_paths = [Path(p) for p in (args.paths or ["tests"])]
    modules = discover([ROOT / p if not p.is_absolute() else p for p in raw_paths])
    if not modules:
        print("no test modules found", file=sys.stderr)
        return 2

    cov_dir: Path | None = None
    if not args.no_cov:
        cov_dir = ROOT / "build" / "pr033-cov"
        if cov_dir.exists():
            shutil.rmtree(cov_dir)
        cov_dir.mkdir(parents=True)
        os.environ.pop("COVERAGE_FILE", None)  # children get their own per file

    print(f"running {len(modules)} modules, -j {args.j}, coverage={'off' if cov_dir is None else 'on'}")
    failures: list[tuple[Path, int, float]] = []
    wall_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.j) as pool:
        futures = [pool.submit(run_module, i, m, cov_dir, extra) for i, m in enumerate(modules)]
        done = 0
        for future in as_completed(futures):
            module, code, secs = future.result()
            done += 1
            status = {0: "ok", 139: "SEGFAULT", 124: "TIMEOUT"}.get(code, f"rc={code}")
            if code != 0:
                failures.append((module, code, secs))
                print(f"[{done}/{len(modules)}] {status}: {module}")
            elif done % 25 == 0:
                print(f"[{done}/{len(modules)}] ... ok so far")

    wall = time.monotonic() - wall_start
    flaky: list[Path] = []
    if failures:
        print(f"\nserial retry pass for {len(failures)} module(s) ...")
        still_failing: list[tuple[Path, int, float]] = []
        for i, (module, code, _) in enumerate(failures, start=len(modules)):
            _, retry_code, retry_secs = run_module(i, module, cov_dir, extra)
            if retry_code == 0:
                flaky.append(module)
                print(f"  FLAKY-but-green on serial retry ({retry_secs:.0f}s): {module}")
            else:
                still_failing.append((module, retry_code, retry_secs))
        failures = still_failing

    print(f"\n{len(modules) - len(failures)}/{len(modules)} modules green in {wall:.0f}s")
    for module in flaky:
        print(f"  FLAKY (parallel pass failed, serial retry green): {module}")
    for module, code, _ in failures:
        label = {139: "SEGFAULT", 1: "FAILED", 124: "TIMEOUT"}.get(code, f"rc={code}")
        print(f"  {label}: {module}")
        print_log_tail(module, cov_dir)

    coverage_ok = True
    if cov_dir is not None:
        data_files = sorted(p for p in cov_dir.iterdir() if p.name.startswith(".coverage."))
        combine = subprocess.run(
            [sys.executable, "-m", "coverage", "combine", "--quiet", *[str(p) for p in data_files]],
            cwd=cov_dir, env={**os.environ, "COVERAGE_FILE": str(cov_dir / ".coverage")})
        if combine.returncode != 0:
            print("coverage combine failed", file=sys.stderr)
            coverage_ok = False
        else:
            report = subprocess.run(
                [sys.executable, "-m", "coverage", "report",
                 *(["--fail-under=0"] if args.branch else [])],
                cwd=ROOT, env={**os.environ, "COVERAGE_FILE": str(cov_dir / ".coverage")})
            coverage_ok = report.returncode == 0

    if not args.keep_logs:
        if cov_dir is not None:
            for log in cov_dir.glob("*.log"):
                ok_module = all(log.stem.split("-", 1)[-1] != m.stem for m, _, _ in failures)
                if ok_module:
                    log.unlink(missing_ok=True)

    return 0 if (not failures and coverage_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
