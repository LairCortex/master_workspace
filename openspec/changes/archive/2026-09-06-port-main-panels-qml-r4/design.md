## Context

See `proposal.md` for motivation. The native `MainWindow` already hosts the timeline as a `QQuickWidget`, but `SearchBar`, `DetailPanel`, and `WorldSnapshotWidget` still own widgets layouts. Search is a child above the native `QSplitter`; timeline, detail, and snapshot are its three children with equal stretch and minimum widths 220/280/280.

The panels already expose stable wiring surfaces. Search owns `search_requested`/`result_selected`; detail owns `show_event`/`clear`/`entity_clicked`; snapshot owns `snapshot_requested`/`populate`/`entity_clicked`. The migration must preserve those class-level surfaces because `Application` and `MainWindow` wiring are not being redesigned.

Snapshot currently derives a tree, rating tint, boldness, icon, tooltip, and stats in its view. Detail owns the same rating interpolation and widgets-only item cards. `CustomDateEdit` embeds `_CustomCalendar`; the timeline range popover separately owns two calendars and a low-screen fallback. R4 adds a separate one-date bridge without changing the timeline path.

## Goals / Non-Goals

**Goals:**

- Make all three panels full QML islands while retaining native shell placement and public facade APIs.
- Keep view/data derivation in Python and make QML roots declarative renderers of sync VM state.
- Add reusable date and rating primitives to `nri.components` with token/off-skin acceptance.
- Remove the old layouts atomically and preserve deterministic island teardown.

**Non-Goals:**

- Replacing `QMainWindow`, menu/status bar, `QSplitter`, system dialogs, or the timeline date-range chip.
- Cleaning raw mention storage in search, detail summaries, or snapshot tooltips.
- Migrating event/entity dialogs, `CustomDateEdit`, or `clickable_label.py`.
- Introducing feature flags, fallback widgets layouts, QML popup overlays, or a second rating implementation in JS.

## Decisions

### 1. One atomic R4 change with three stable facades

`SearchBar`, `DetailPanel`, and `WorldSnapshotWidget` remain the Python classes constructed by `MainWindow`. Each becomes a thin `QQuickWidget` facade using the shared engine and preserves its constructor shape and public signals/methods. `MainWindow` keeps search in `main_layout` before the splitter and keeps timeline/detail/snapshot as splitter children; existing minimum widths and all stretch factors remain unchanged.

The old widgets layouts are deleted in the same change, with no runtime flag or fallback copy. This prevents dual behavior and stale tests. Alternative: migrate panels independently. Rejected because detail and snapshot share the rating extraction and the R4 acceptance boundary is one coherent main-window slice.

### 2. Minimal, panel-specific context and 1:1 wiring

The roots are `SearchBarRoot.qml`, `DetailPanelRoot.qml`, and `WorldSnapshotRoot.qml`. Their context contracts are:

- search: `searchBarVm`, `islandPalette`
- detail: `detailPanelVm`, `islandPalette`
- snapshot: `worldSnapshotVm`, `islandPalette`, `tooltipBridge`

No repository, service, runtime, or facade object is exposed. The facade connects VM/root sync requests to its existing public signals and turns existing public calls into VM updates. Search reuses the existing search VM, adding only QML-facing model/state adapters if needed. Detail receives `show_event()` data through a thin detail VM; snapshot gets a new VM because its current model construction is embedded in the widget.

Alternative: expose each facade to QML. Rejected because it expands context beyond the established sync-VM contract and makes service/wiring boundaries harder to test.

### 3. Python-built models; QML only renders

Search publishes rows that distinguish non-clickable section headers from result rows. Empty input hides/empties the list; a completed search with no matches retains the current “Ничего не найдено” semantics. Debounce and explicit search keep the existing 300 ms/public-signal behavior.

Detail publishes title/date and four tab models in the existing order: organizations, characters, items, locations. Python builds each row’s name, summary, entity identity, image source, and rating tint. QML uses `TabBar` + `StackLayout`, a themed list, `ThemeRatingCard`, and `Image` + `MouseArea`. Row activation emits the same entity identity. Image activation calls the facade, which loads original/preview and executes `ImageViewerDialog` as before. `clickable_label.py` stays because R4 removes only these three layouts and R7 owns its final cleanup.

Snapshot publishes a flat list model with exactly `sectionHeader` and `entityRow` rows. Each row contains the render-ready roles required by the roadmap (`type`, `id`, `name`, `ratingHex`, `fontBold`, `tooltipHtml`, icon path/key plus display text/state). Expansion state is held in `WorldSnapshotViewModel`; `toggleSection` changes visibility/model rows and `select` routes only supported entity types. Event rows are display-only and never emit `entity_clicked`. Images/icons render at 24 px and have no viewer action. Buttons and stats/empty hints retain their current text and semantics.

Alternative: reproduce tree/model/rating/summary logic in QML. Rejected because it creates a second domain presentation implementation and violates the list-model boundary.

### 4. ThemeRatingCard is a tint primitive; rating math moves to theme

`rating_to_color` moves from `detail_panel.py` into a neutral module under `app/presentation/theme/` and remains the sole interpolation implementation for detail and snapshot. It clamps rating 1–20, interpolates `color.rating.low/high`, ramps alpha 80–220, and returns transparent when runtime/tokens are invalid.

`ThemeRatingCard.qml` receives the resulting color and paints only the tint surface inside normal card chrome. It does not know rating, endpoints, alpha, text, summary fields, or gradients. This keeps live retheme deterministic: Python refreshes model roles and QML bindings repaint.

Alternative: interpolate in QML. Rejected because it duplicates token derivation and would create the prohibited JS gradient.

### 5. ThemeDateField delegates one-date selection to a top-level Python bridge

`ThemeDateField.qml` exposes `isoDate`, `display`, and a click signal. It renders field chrome from library tokens and performs no calendar/date arithmetic.

`app/presentation/views/theme_date_popup.py` owns the single-date top-level popup. One popup instance contains one reused `_CustomCalendar`; each open refreshes custom month names, sets the current date, and maps the QML-reported global anchor rectangle. After `adjustSize()`, both axes are clamped to the selected screen’s `availableGeometry`. Selection is clamped to `0100-01-01…9999-12-31` using Python/date utilities, emitted once, and closes the popup. It does not use or copy `_DateWindowPopup._fit_low_screen`, which exists only to choose between the timeline popover’s two calendars.

The snapshot facade translates selected ISO/Python dates and display text. The timeline’s range chip, `_DateWindowPopup`, two-calendar behavior, captions, and low-screen fallback are untouched. `CustomDateEdit` remains for widgets consumers until R7.

Alternative: QML `Popup` or `Calendar`. Rejected because a popup can be clipped by the `QQuickWidget`, while custom month and bounds logic must stay Python-side.

### 6. Tooltip bridge belongs only to snapshot

Snapshot rows attach dynamic tooltip HTML through the existing `Nri.tooltip` declaration, with the existing `IslandTooltipBridge` injected only into that island. Search and detail receive no `tooltipBridge` context property and create no QML overlay. This keeps the bridge capability-scoped and preserves the system `QToolTip` styling.

### 7. Teardown, packaging, and acceptance follow existing island rules

Each facade registers with the shared shell lifecycle and clears its source using deferred `setSource(QUrl())` before destruction, matching the timeline island. New roots, delegates, `ThemeDateField.qml`, `ThemeRatingCard.qml`, and `qmldir` entries are covered by bundle assertions. The no-hex scan covers all new QML.

Tests are red-first. Python units cover rating helper, date-popup geometry/clamp, and all VM/model transforms. Real-island tests cover root `objectName` contracts, facade signals, row semantics, and live retheme without selection/scroll loss. Component tests compare pixels for both themes and off-skin without golden files. Old snapshot title/“Показать” grabs are removed because `TitleText`/`ThemeButton` already own those pixel contracts.

## Risks / Trade-offs

- [QML model role drift breaks delegates silently] → Define role constants centrally and assert complete model rows plus root loading in tests.
- [Popup geometry differs across screens/DPR] → Compute from global anchor after sizing, choose the screen at the anchor, clamp both axes to `availableGeometry`, and unit-test edge positions.
- [Facade compatibility regresses wiring] → Migrate existing facade tests before implementation and keep class/signature/signal assertions 1:1.
- [Live retheme leaves stale rating colors] → Recompute rating color roles from the neutral helper on palette change without rebuilding selection/scroll state.
- [Snapshot flattening changes event activation] → Encode event rows explicitly and test that selecting them never emits while entity rows still do.
- [Three islands increase shared-engine teardown pressure] → Use the established registration/deferred-source sequence and lifecycle regression tests from R1.

## Migration Plan

1. Add failing helper/component/VM tests, then implement neutral rating math, `ThemeDateField`, `ThemeRatingCard`, and the single-date popup bridge.
2. Add failing semantic contracts for each panel, then implement Python models, roots, and thin facades while keeping old public APIs.
3. Switch the three facades atomically, delete their widgets layouts without flags, and keep MainWindow geometry unchanged.
4. Update QML module/bundle assertions, remove obsolete snapshot grabs, run focused suites, then the full test suite and strict OpenSpec validation.

Rollback is a normal commit revert of the atomic change; no data/schema migration or persisted-state conversion is involved.
