## Why

The main window still mixes QtWidgets panels with the QML timeline island, leaving three high-use surfaces outside the shared QML component system. R4 moves the search bar, detail panel, and world snapshot together so their placement and public wiring remain stable while their chrome and reusable date/rating controls join the QML design system.

## What Changes

- Replace the `search_bar`, `detail_panel`, and `world_snapshot` widgets layouts with QML islands in one change, preserving their existing facade class names, public methods/signals, behavior, and MainWindow slots 1:1.
- Keep search above the native splitter; keep detail and snapshot inside the splitter without changing splitter stretch or minimum-width behavior.
- Expose only `searchBarVm`, `detailPanelVm`, or `worldSnapshotVm` plus `islandPalette` to each island; expose `tooltipBridge` only to snapshot.
- Feed snapshot through a flat `sectionHeader`/`entityRow` model; entity rows may emit selection, while event rows never emit `entity_clicked`.
- Add reusable `ThemeDateField` and tint-only `ThemeRatingCard` QML components.
- Add a Python single-date popup bridge backed by one `_CustomCalendar`, clamped to screen `availableGeometry`; leave the timeline range chip unchanged.
- Move `rating_to_color` from the detail panel into a neutral theme module for shared detail/snapshot use.
- Render detail images with QML `Image` + `MouseArea` while retaining `clickable_label.py` for later consumers.
- Remove obsolete snapshot title/button pixel grabs and delete the three widgets layouts without feature flags.
- Keep system popups native and cover the migration with red-first TDD tasks, component pixel tests, island semantic tests, and live-retheme tests.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `qml-shell`: Extend the island inventory and contracts to the three main panels, including placement, context/wiring, snapshot row semantics, native popup boundaries, and teardown/testing behavior.
- `qml-components`: Add the reusable themed single-date field and tint-only rating card with token-based and off-skin behavior.

## Impact

- Affects the three main-panel facades, their view models/models, QML roots and delegates, shared QML module registration, theme/date popup helpers, rating color helper location, MainWindow composition, PyInstaller QML data assertions, and presentation tests.
- Preserves public Python wiring APIs and native shell geometry; no database, service, domain-storage, or external dependency change is required.
