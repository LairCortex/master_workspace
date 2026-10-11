"""The two-profile acceptance mechanism of ``run_tests_isolated.py`` (task 6.4).

Spec ui-testing «Приёмка в двух профилях»: profile «ядро» runs with the module
out of the composition and measures coverage over the profile's composition
(``app/dd`` leaves the measurement), profile «ядро + модуль» measures the whole
``app/`` including ``app/dd/`` — both green or the gate has not passed. Design
Д11 fixes the shape: a profile run config, never ``exclude_lines``/pragma edits.

Pins:
* the env name and value semantics cannot drift from the composition switch
  (``app.main`` is the normative bearer);
* the omit pattern really excludes module files and keeps kernel files;
* the wiring — a scripted runner pass shows ``--omit`` on the ``coverage
  report`` child ONLY in the kernel profile;
* the gate config in ``pyproject.toml`` grows no omit/include of its own, so
  the full profile keeps measuring 100 % over the whole ``app/``.
"""
from __future__ import annotations

import fnmatch
import os
import tomllib
import types
from pathlib import Path

import pytest

import run_tests_isolated as rt
from app.main import DD_MODULE_PROFILE_DISABLE_ENV, _dd_module_disabled_by_profile

# ── one knowledge: the switch the composition reads is THE same switch ───────


def test_runner_env_name_matches_the_composition_constant():
    assert rt.DD_MODULE_PROFILE_DISABLE_ENV == DD_MODULE_PROFILE_DISABLE_ENV


@pytest.mark.parametrize("value", [None, "", "0", "1"])
def test_profile_scope_fires_exactly_where_the_composition_disables(monkeypatch, value):
    """The measured scope shrinks exactly on the value that also removes the
    module from the composition — one switch, one meaning («1» is the switch)."""
    if value is None:
        monkeypatch.delenv(DD_MODULE_PROFILE_DISABLE_ENV, raising=False)
    else:
        monkeypatch.setenv(DD_MODULE_PROFILE_DISABLE_ENV, value)
    kernel = bool(rt.profile_coverage_omits(dict(os.environ)))
    assert kernel is _dd_module_disabled_by_profile()
    assert kernel is (value == "1")


# ── the omit pattern excludes the module and nothing else ────────────────────


def test_kernel_omit_pattern_leaves_the_kernel_files_measured():
    (pattern,) = rt.profile_coverage_omits({DD_MODULE_PROFILE_DISABLE_ENV: "1"})
    # pytest-cov records absolute paths and the ``*/``-idiom pattern is
    # matched against them — the module files must fall out of the report…
    assert fnmatch.fnmatch("/Users/x/proj/app/dd/module.py", pattern)
    assert fnmatch.fnmatch("/repo/app/dd/infrastructure/dataset_storage.py", pattern)
    # …while no form of a kernel file may match (the profile keeps counting it).
    for kernel_file in (
        "/Users/x/proj/app/main.py",
        "app/main.py",
        "/Users/x/proj/app/application/services/export_service.py",
        "app/infrastructure/db/game_manager.py",
        "/Users/x/proj/tests/test_dnd_module_nri_roundtrip.py",
    ):
        assert not fnmatch.fnmatch(kernel_file, pattern)


def test_full_profile_omits_nothing():
    """«ядро + модуль»: no switch — the gate keeps measuring all of ``app/``
    including ``app/dd/``; the runner adds no flags at all."""
    assert rt.profile_coverage_omits({}) == []
    assert rt.coverage_report_cli_args([]) == []


def test_cli_args_join_patterns_into_one_flag():
    assert rt.coverage_report_cli_args(["*/app/dd/*", "*/other/*"]) == [
        "--omit=*/app/dd/*,*/other/*"
    ]


# ── the wiring: the flag reaches the coverage report child (and only there) ──


def _scripted_runner_report_args(monkeypatch, tmp_path, kernel: bool) -> list[list[str]]:
    """Run ``main()`` end to end with the test children and the coverage
    children replaced: returns the recorded argv of every ``coverage`` call."""
    if kernel:
        monkeypatch.setenv(rt.DD_MODULE_PROFILE_DISABLE_ENV, "1")
    else:
        monkeypatch.delenv(rt.DD_MODULE_PROFILE_DISABLE_ENV, raising=False)

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # noqa: ARG001 — kwargs are cwd/env/timeout
        calls.append(list(cmd))
        return types.SimpleNamespace(returncode=0)

    # Hermeticity pin: ``main()`` wipes and recreates its coverage dir under
    # ``ROOT`` — this scripted pass must run under ``tmp_path``, never against
    # the live ``build/pr033-cov`` of a suite that may be running right now.
    monkeypatch.setattr(rt, "ROOT", tmp_path)
    monkeypatch.setattr(rt.subprocess, "run", fake_run)
    monkeypatch.setattr(rt, "discover", lambda paths: [tmp_path / "test_fake.py"])
    monkeypatch.setattr(
        rt, "run_module", lambda index, module, cov_dir, extra: (module, 0, 0.0)
    )
    assert rt.main([]) == 0

    return [c for c in calls if "coverage" in c]


def test_kernel_profile_report_child_carries_the_omit(monkeypatch, tmp_path):
    reports = [c for c in _scripted_runner_report_args(monkeypatch, tmp_path, True) if "report" in c]
    assert len(reports) == 1
    assert "--omit=*/app/dd/*" in reports[0]


def test_full_profile_report_child_stays_untouched(monkeypatch, tmp_path):
    reports = [c for c in _scripted_runner_report_args(monkeypatch, tmp_path, False) if "report" in c]
    assert len(reports) == 1
    assert not any(arg.startswith("--omit") for arg in reports[0])


# ── no new exclusions: the config-level gate stays the whole app ─────────────


def test_coverage_config_grew_no_profile_exclusions():
    """The profile scope is a run config ONLY (design Д11): the shared
    ``[tool.coverage.*]`` config must not grow omit/include keys — otherwise
    the «ядро + модуль» profile would quietly stop measuring ``app/dd`` and
    the 100 % gate would no longer cover the whole of ``app/``."""
    config = tomllib.loads((Path(rt.ROOT) / "pyproject.toml").read_text(encoding="utf-8"))
    coverage = config["tool"]["coverage"]
    for section in ("run", "report"):
        assert "omit" not in coverage.get(section, {})
        assert "include" not in coverage.get(section, {})
    # sanity: the gate itself is still the 100 % line gate over the app source
    assert coverage["report"]["fail_under"] == 100
    assert coverage["run"]["source"] == ["app"]


def test_branch_report_child_also_honours_the_scope(monkeypatch, tmp_path):
    """The report-only branch run keeps the same scope (visible numbers), even
    though it never gates (``--fail-under=0``)."""
    monkeypatch.setenv(rt.DD_MODULE_PROFILE_DISABLE_ENV, "1")
    monkeypatch.setattr(rt, "ROOT", tmp_path)  # same hermeticity pin as above
    calls: list[list[str]] = []
    monkeypatch.setattr(
        rt.subprocess,
        "run",
        lambda cmd, **kwargs: (calls.append(list(cmd)), types.SimpleNamespace(returncode=0))[1],
    )
    monkeypatch.setattr(rt, "discover", lambda paths: [tmp_path / "test_fake.py"])
    monkeypatch.setattr(
        rt, "run_module", lambda index, module, cov_dir, extra: (module, 0, 0.0)
    )
    assert rt.main(["--branch"]) == 0
    reports = [c for c in calls if "coverage" in c and "report" in c]
    assert len(reports) == 1
    assert "--omit=*/app/dd/*" in reports[0]
    assert "--fail-under=0" in reports[0]
