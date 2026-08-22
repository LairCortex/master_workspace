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

- Entrypoint `app/main.py`: manual DI (no framework). `Application.start()` wires repositories → services → viewmodels → `MainWindow`; signal wiring lives in `Application._wire_signals` and the `_wire_*` helpers.
- Layers: `presentation/` (Qt views + viewmodels, Qt signals) → `application/services/` (plain async services) → `infrastructure/` (SQLAlchemy ORM `db/models.py`, per-entity repositories, LLM providers) ; `domain/` holds dataclasses and enums.
- Models: 7 entity tables + 13 M2M association tables. Search relies on a registered SQLite `lower()` function for case-insensitive matching.
- Per-game settings (custom month names, LLM world/field prompts) live in the key/value `game_settings` table — follow this pattern for new per-game config.

## Migrations — do NOT use alembic

`alembic/` contains only the initial schema and is not run at startup. Real schema changes happen in `init_db()` in `app/main.py` (inline `_MIGRATIONS` list + ad-hoc table rebuilds like `_migrate_nullable_end_dates`). Add new column/table changes there — the CHANGELOG also records migrations "через init_db()".

## Build & release

- PyInstaller via `nri_manager.spec` (directory bundle; do NOT switch to `--onefile` — Qt 6 breaks). Spec bundles `docs/` and lists hiddenimports — keep both in sync with dependencies.
- `python build_app.py --clean` — builds for the current OS only (no cross-compilation); on macOS it ad-hoc codesigns `dist/НРИ Сценарий Менеджер.app` (required to bypass Gatekeeper).
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
