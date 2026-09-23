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

## GUI verification on a real display (computer-use MCP)

`munim-computer-use` (MCP server `computer-use`) gives the agent eyes and hands on the real desktop: it reads the app's accessibility tree, presses/types into a target window without moving the user's pointer, and captures whole windows or zoomed regions. Registered in `.kilo/kilo.json` — that directory is git-ignored, so a fresh machine re-registers it. Binaries: npm launcher `/opt/homebrew/bin/munim-computer-use`, native binary cached under `~/.cache/munim-computer-use/<version>/`. Browser tools are switched off with `COMPUTER_USE_BROWSER=0`; only the 18 desktop tools load.

Install / re-check permissions:

```bash
npm install -g munim-computer-use
munim-computer-use request-permissions   # {"accessibility":true,"screenRecording":true}
```

macOS attributes Accessibility and Screen Recording to the app that spawns the CLI, not to the window you typed in (this machine: Android Studio spawns the `kilo` binary; check the chain with `ps -o pid=,ppid=,comm=`). Both must report `true`, otherwise `get_app_state` works and `screenshot` fails with "screen capture failed".

Use it only for what the offscreen Qt suite structurally cannot see: real window placement, size and stacking of the launcher / `MainWindow` / dialogs / popups, the native menu bar, keyboard focus and modal behaviour, Retina rendering, and what a user can actually read on screen. It is NOT a substitute for `tests/ui/`: it adds no line coverage (the 100 % gate is untouched), its verdicts are not reproducible, and it cannot run in CI (headless runners have no display and no granted permissions). Every defect it finds must be re-pinned by a pytest-qt test.

Working loop: `list_apps` → `get_app_state(app=<pid>)` → act by element id → `get_app_state` or `screenshot` again before the next step. Element ids belong to one snapshot and go stale after any UI change; `screenshot`/`zoom` answers carry the screen origin and pixels-per-point, which is how an image position becomes a click coordinate.

Capture modes: `screenshot {"app": …}` grabs ONE window — the app's largest one, so with two windows open the dialog may be the one left out; use `zoom` (`x0,y0,x1,y1` in screen points) to read a specific window or region, and `screenshot {"display": N}` for the whole desktop. `zoom` renders at 2 px per point on Retina, which is what makes small labels legible.

Two press paths, both verified: `click` with `element_id` uses the accessibility press action (reported as `via AXPress`) and works on the QML island buttons; `click` with `x`/`y` uses coordinates. A failed press can still have landed — `click` has been observed returning "e2 is not visible in its window" while the action behind it did fire — so after any press error re-read `get_app_state` before retrying, or a retry opens a second dialog.

Measured on this app (macOS, server 0.4.3, launcher dialog): the window and its buttons come through with their Russian labels («Открыть», «Новая игра», «Импорт», «Светлая тема», «Удалить»), and the three remaining label-less / disabled `Button` entries under `Window` are the native close/minimise/zoom controls, not app widgets (a native app's tree shows the same three). Pressing «Светлая тема» by element id flipped the toggle to «Тёмная тема» and wrote `~/.nri_manager/ui.json`. The QML game-list rows — absent from the pre-NRI-0012 tree (`query` gave 0 matches) — now carry their full name and a working AXPress (row activation opened the game); the tool labels the node `StaticText`, the `ListItem` role label does not survive the Qt6.10/cocoa projection (follow-up FI-2, see `docs/qa/2026-09-23-accessibility-audit.md`).

Accessibility tree contract (change `nri-0012-qml-accessibility`; the annotations are in `app/presentation/qml/`, the design map lives in that change's `design.md`). Slot rules:

- **role is the component's** — list rows are `ListItem`, the color swatch `RadioButton`, `MentionField` and the sheet inline editor `EditableText`, mention chips `Link`, openers/icon buttons `Button`; role and press handler live inside the library component (`RowItem`/`ThemeSwatch`/`MentionField`) so a forgetful usage-site cannot silently break the contract.
- **name is the usage-site's** — an input control's name is the target caption at the point of application (bound `modelData.label` where the label is already a binding), a list row's name is its visible content; a stock text `Button`/`CheckBox`/`TabButton` is NOT annotated — Qt names it from `text`. Icon buttons and AI buttons are named by the action/subject: `ThemeAiButton` carries `Accessible.name: "Сгенерировать: " + fieldLabel` (`fieldLabel: "Событие"` on the whole-world buttons — implemented convention; design.md's map is aligned to this wording).
- **value belongs only to штатные text controls** — `TextField`/`TextArea`/`SpinBox` deliver the typed value in the value slot automatically; a custom Item has no annotation path to that slot (§limit ②; bridging it is the follow-up change NRI-0013).
- **description carries the hidden meaning of an activation** — the implemented set is exactly «Открывает карточку», «Открывает событие», «Открыть изображение» (detail panel/image, timeline row), «Открывает упомянутую сущность» (mention chip), «Переходит к сущности» and «Развернуть или свернуть раздел» (world-snapshot rows/headers) — only where the name doesn't already spell the action; readers read it via `queryAccessibleInterface().text(QAccessible.Description)`/raw `AXDescription`, and the tool not painting it is NOT a defect. (design.md's map also sketched «Открывает игру»-style row descriptions for plain `RowItem` rows; rows carry role+name+press only — recorded as a map-vs-tree deviation in `docs/qa/2026-09-23-accessibility-audit.md`.)
- **Forbidden, guard-pinned by `tests/test_qml_accessibility_conventions.py`:** `Accessible.role: Accessible.NoRole` (nameless AXStaticText junk), `Accessible.ignored`, `Accessible.value` (the attached property doesn't exist), and `Accessible.name` on a stock text control (re-annotation).
- **A custom Item is pressable only through `Accessible.onPressAction`** — AXPress without a handler is a silent no-op even when `click` reports success; the offscreen pin of every action is `QAccessible` `actionInterface().doAction("Press"/"SetFocus")` (pattern of `tests/presentation/test_*_accessibility*.py`). For EditableText fields `SetFocus` lands on the annotated item itself (`onSetFocusAction` doesn't exist in this Qt 6.10) — `MentionField` forwards it to its plain text layer via root-level focus delegation.

Two offscreen-only quirks, pinned in `tests/test_qml_stock_controls_accessibility.py`: an unannotated stock Button/CheckBox/TabButton reports an EMPTY `QAccessible.Name` offscreen — text-derived naming exists on the live display only, so the guard pins the offscreen-pinnable half (interface + role + no name-contradiction + no annotation in source) while the "Name equals the visible text, non-empty" half is a live-audit check. And with a name set, raw tree reads carry the description — `get_app_state` does not paint it.

What the tree CANNOT address — exactly four fixed limits, everything else must be reachable without coordinates (§spec «Пределы координатности зафиксированы»): ① mention-popup rows — no `Accessible.*` on popup delegates, keyboard-only after SetFocus on the field (arrows + Enter); ② typed text of `MentionField` and of the sheet inline editor — the tree offers role and focus but no readable value slot (screenshot for content; the value bridge `QAccessible.installFactory` is follow-up NRI-0013; live, the field's plain text layer does surface its text as its own plain-control name); ③ native date popups and `ThemeComboBox` drop-down menus — separate native windows, their items are not island nodes (the trigger button itself is named); ④ tooltip text via `tooltip_shim.py` — never propagated into the tree. Silently growing this list is a defect: the live `accessibility-audit` diffs the tree against it, and a real fifth limit gets added here in the same change that discovers it. Where an element is missing beyond these four, record it in the QA report and file a follow-up rather than faking coordinates. Open follow-ups from the 2026-09-23 live audit (`docs/qa/2026-09-23-accessibility-audit.md`), defects rather than limits: FI-1 `ThemeDateField` (dates in dialogs/snapshot) is live-invisible (usage-site name on a role-less Control is not projected) — needs role+press inside the component; FI-2 `ListItem` row role projected as `StaticText`; FI-3 `RowItem` has no description slot (design-map row descriptions like «Открывает игру» unbuilt); FI-4 the music-edit «✎» button is unnamed. The menu-invoked islands (char sheets, doc viewer, xlsx, LLM setup, table host, event types) and `DetailPanel` content were pinned offscreen only — their live check awaits a real-mouse re-audit (FI-5); the audit also recorded a non-accessibility startup bug in the first-run calendar wizard (FI-6).

Before a session — the app has no data-directory override, so isolation is by convention:

- games live in `<repo>/games/<name>/` (`infrastructure/db/game_manager.py:_resolve_games_dir`) and the LLM config is the real `~/.nri_manager/llm_config.json`;
- create and touch only a throwaway game (name it `qa-<date>`); never open or delete an existing catalog row — opening a legacy flat `games/<name>.db` migrates the user's file in place;
- never press the AI-generation buttons: they hit the real endpoint with the real key;
- stop the app when done (`pkill -if "app.main"` — the process is `Python -m app.main`, so a case-sensitive pattern misses it) — nothing is lost, there is no session state.

Scenarios, on request; report findings in Russian under `docs/qa/<date>-<scenario>.md`:

1. `window-layout` — open the launcher, the main window, EventDialog, an entity card and the character-sheet editor; for each, record position/size from `screenshot`, check overlaps, clipped text, missing margins, and that no strip of the OS palette leaks around a QML island (the pixel contract pinned offscreen by `tests/ui/test_theme_grab.py`).
2. `theme-on-real-display` — flip «Светлая тема» in the launcher and re-check both themes on the real palette and Retina backing store, including native menus and dialogs.
3. `small-text-readability` — `zoom` each dense area (timeline ladder, detail panel, sheet fields) at 2 px/pt and report labels that are unreadable, elided or truncated.
4. `checklist-walkthrough` — walk `docs/functional-checklist.md` end to end as a user would, in a `qa-<date>` game, marking each item visible / reachable / confusing from the outside.
5. `accessibility-audit` — `get_app_state` every screen; check every interactive element carries a role+name addressable without coordinates, stock text controls carry a name equal to their visible text (the live-only half of the 4.2 contract), and the tree matches the island source except at the four fixed limits; a deviation gets a follow-up item and a real new limit is added to the list above in the same change — silently growing the list is a defect.
6. `native-focus-repro` — reproduce reports that only appear with real windows: menu-bar actions, focus lost to a native popup, modal dialogs blocking the main window, second-window behaviour.

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
