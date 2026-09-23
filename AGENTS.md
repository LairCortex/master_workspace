# AGENTS.md

PySide6 desktop app: RPG scenario manager. MVVM + qasync (all async code runs on the Qt event loop), SQLAlchemy 2.0 async + aiosqlite. One SQLite file per game in `games/<name>.db`. Main docs: `docs/README.md` (there is no root README) and `docs/CHANGELOG.md`.

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # app + test deps
pip install -e ".[build]"          # optional: PyInstaller
```

Python 3.11+ (CI and venv use 3.12). Tests must not require the network (LLM is tested with `httpx.MockTransport`).

## Run

```bash
python -m app.main                 # GUI app; game launcher dialog opens first
```

## Test

```bash
python -m pytest                   # or: python -m pytest tests/<file> -k <name>
QT_QPA_PLATFORM=offscreen python -m pytest   # headless (used by CI)
```

- `asyncio_mode = auto` in pyproject — do not add `@pytest.mark.asyncio`.
- `qt_api = pyside6`; DB tests use in-memory aiosqlite fixtures (`async_engine`, `async_session`) in `tests/conftest.py`.
- Linux CI/execution needs system libs: `libegl1 libxkbcommon0 libdbus-1-3`.
- No linter, formatter, or type checker is configured — match surrounding code style, don't impose new tooling. Run tests before committing; that is the verification gate.

## Architecture

- Entrypoint `app/main.py`: manual DI (no framework) — the composition root and the ONLY place that composes concrete repositories/services/unit-of-work into each other. `Application.start()` wires repositories → services → viewmodels → `MainWindow`. Dialog↔service signal wiring lives in the presentation-layer connector `app/presentation/wiring.py` (`ApplicationWiring.connect`); dialog lifecycle is split into `presentation/sheet_windows.py`, `presentation/ai_generation_controller.py` and `application/services/export_service.py`.
- Layers: `presentation/` (Qt views + viewmodels, Qt signals) → `application/services/` (plain async services) → `infrastructure/` (SQLAlchemy ORM `db/models.py`, per-entity repositories, LLM providers) ; `domain/` holds dataclasses and enums. `domain` and `application` never import `presentation`; `presentation` never sees `AsyncSession`/ORM models/`commit`/`rollback`. `tests/test_architecture_layers.py` enforces these boundaries in every test run.
- Writes finish exclusively through the `GameSessionUoW` (`infrastructure/db/uow.py`): one `async with uow.transaction()` per user operation (calendar wizard stage commits are the documented design exception).
- Models: 7 entity tables + 13 M2M association tables. Search relies on a registered SQLite `lower()` function for case-insensitive matching.
- Per-game settings (custom month names, LLM world/field prompts) live in the key/value `game_settings` table, accessed through `infrastructure/repositories/game_settings_repository.py` and its sibling `llm_settings_repository.py` (`LlmSettingsRepository` for the LLM prompt keys) — follow this pattern for new per-game config.

## Migrations — do NOT use alembic

`alembic/` contains only the initial schema and is not run at startup. Real schema changes live in `app/infrastructure/db/migrations.py` and run at startup through its `init_db()` entrypoint (inline `_MIGRATIONS` list + ad-hoc table rebuilds like `_migrate_nullable_end_dates`); `app/main.py` only calls `init_db(self.engine)`. Add new column/table changes in `migrations.py` — the CHANGELOG also records migrations "через init_db()".

## Coding principles

Normative for every future change, including AI sessions (source: `docs/refactoring-audit.md`, OpenSpec change `nri-0005-architecture-refactor`). Violations of items 1–3 are caught by `tests/test_architecture_layers.py`.

1. **Layers are one-way.** `domain`/`application` never import `presentation` or Qt; `presentation` never touches `AsyncSession`, ORM models (`app/infrastructure/db/models.py`) or `commit/rollback` — data access goes through application services, and only the composition root `app/main.py` plus the presentation connector `presentation/wiring.py` bind concrete classes to each other. Preset data is domain data (`domain/character_sheets/`), not presentation.
2. **One knowledge, one place.** Entity-type facts (labels, plurals, relations, search/LLM flags) live in `domain/entity_registry.py` keyed by `EntityType`; the sanctioned type↔ORM map is `infrastructure/repositories/__init__.py` and the type↔repository map is `main.py:_build_entity_services` — no parallel string-keyed type dicts elsewhere in `application/domain`. Date-slot/coordinate rules only in `infrastructure/repositories/coord_mapping.py`; cross-cutting constants once: app root `~/.nri_manager` in `infrastructure/paths.py`, image extensions in `domain/allowed_image_extensions.py`, `game_settings` keys in `game_settings_repository.py`/`llm_settings_repository.py`.
3. **One transaction finish point.** A user operation commits/rolls back exactly once, via `GameSessionUoW.transaction()`; services never end transactions mid-chain and never reach into `repo._session`/`repo._model` (`BaseRepository.session/.model` are public). Post-write work goes to the UoW's after-commit hooks (image GC), and any persistence error reaches the user — never swallowed.
4. **Frozen contracts.** Dialog results are frozen dataclasses in `presentation/dialog_results.py` consumed by one `_apply_*` handler — not anonymous dicts with `.pop()`. No cross-module access to private members (`obj._x` / importing `_name` from another package). Prefer composition over inheritance; the single sanctioned exception is `IslandDialogMixin` (QML island lifecycle is window-bound).
5. **Refactor only in green slices.** Behavior, DB schema and file formats are unchanged; cover with tests first when uncovered; documentation (AGENTS.md/CHANGELOG/checklist) is updated in the same change.
6. **Coverage 100% lines is a non-decreasing gate.** `[tool.coverage.report] fail_under = 100` (CI "line coverage gate") must stay green at 100: every new/changed production line needs a test. Lowering `fail_under`, widening `exclude_lines` or adding `# pragma: no cover` in `app/` (currently exactly two, each reason-signed) is allowed only with an explicit justification in the change proposal.

## Build & release

- PyInstaller via `nri_manager.spec` (directory bundle; do NOT switch to `--onefile` — Qt 6 breaks). Spec bundles `docs/` and lists hiddenimports — keep both in sync with dependencies.
- `python build_app.py --clean` — builds for the current OS only (no cross-compilation); on macOS it ad-hoc codesigns `dist/Master Workspace.app` (required to bypass Gatekeeper).
- Branch `main`. CI (`.github/workflows/build.yml`): push → tests + 3-OS builds with artifacts; tag `v*` → GitHub Release.
- Version is NOT single-sourced: `pyproject.toml`, `CFBundleShortVersionString` in `nri_manager.spec`, and `docs/CHANGELOG.md` all need updating together.
- Commit format: `<TASK-KEY>: imperative English description` (e.g. `NRI-0001: add ...`).

## LLM

- External OpenAI-compatible LLM only. `RemoteLlmProvider` (`POST {base_url}/chat/completions`, `base_url` is user-provided up to `/v1`) covers cloud backends (OpenAI, OpenRouter, Groq) and local servers (Ollama, vLLM, LM Studio, llama.cpp server). There is no local model: nothing is downloaded or installed at runtime.
- Global connection config: `~/.nri_manager/llm_config.json` — `base_url` + `model` (required) and `api_key` (optional, `""` = no auth), written with `chmod 0600` by `LlmConfigManager`. World/field prompts stay per-game in the `game_settings` DB table.
- All network traffic goes through the single app-wide `httpx.AsyncClient` in `app/infrastructure/http/` (connect 10 s / read 120 s, constants), created in `Application.start()` and closed in `shutdown()`. Provider and dialog receive it via DI.
- Errors: `LlmError → LlmHttpError(status, server_message) / LlmNetworkError / LlmTimeoutError` with RU user-facing messages (401/403, 404, 429, …); `str(exc)` is displayable. Retries: max 2 with 0.5/1 s backoff, only on timeout/network error/429/5xx — never on other 4xx.
- Statuses are `not_configured` / `ready`; `ready` = non-empty `base_url` + `model`, decided without any network at startup.

## Workflow conventions

- OpenSpec is set up (`openspec/`, skills in `.kilocode/skills/`, workflows in `.kilocode/workflows/`): propose creates planning artifacts only (proposal/spec delta/design/tasks) and must not edit code; implementation starts in a separate apply step.
