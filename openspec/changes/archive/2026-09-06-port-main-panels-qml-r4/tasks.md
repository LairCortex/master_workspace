## 1. Theme primitives and single-date bridge (TDD)

- [x] 1.1 Add failing unit tests for neutral `rating_to_color`: 1/20 endpoints, clamp, 80…220 alpha interpolation, light/dark token values, invalid/off-skin transparency; run the focused test and verify it is red.
- [x] 1.2 Move `rating_to_color` from `detail_panel.py` to a neutral `app/presentation/theme/` module, update detail/snapshot imports, and verify tests from 1.1 are green with no second interpolation implementation.
- [x] 1.3 Add failing real-QML pixel tests for `ThemeDateField` and tint-only `ThemeRatingCard`: both themes, field background/border, supplied rating tint, off-skin behavior, no golden PNG; run the focused component test and verify it is red.
- [x] 1.4 Implement `ThemeDateField.qml` (`isoDate`, `display`, `clicked`) and `ThemeRatingCard.qml` (surface tint only), register both in `qmldir`, and verify tests from 1.3 are green and QML contains no date/rating calculations or literal hex.
- [x] 1.5 Add failing unit tests for `theme_date_popup.py`: exactly one `_CustomCalendar`, refreshed custom months, current-date prefill, `0100-01-01…9999-12-31` clamp, one selection emit, and x/y placement inside mocked `availableGeometry`; verify the focused test is red.
- [x] 1.6 Implement the reusable top-level single-date popup bridge and verify tests from 1.5 are green; add a regression assertion that `timeline_date_popup.py`, its two calendars, `_fit_low_screen`, and range-chip behavior are unchanged.

## 2. Search island (TDD)

- [x] 2.1 Add failing search VM/model tests for 300 ms debounce inputs, explicit search, empty query/list, no-match row, non-clickable section headers, result type/id/date text, and selection; verify the focused test is red.
- [x] 2.2 Implement the QML-facing search rows/state on the existing search VM without services in context and verify tests from 2.1 are green.
- [x] 2.3 Add failing real-island tests for `SearchBarRoot.qml`: root/input/button/list and row `objectName` contracts, context limited to `searchBarVm` + `islandPalette`, no `tooltipBridge`, `search_requested`/`result_selected` semantics, and live-retheme without selection/scroll loss; verify red.
- [x] 2.4 Implement `SearchBarRoot.qml` from `nri.components` and convert `SearchBar` to a shared-engine thin facade with its class/constructor/public signals preserved; verify tests from 2.3 and migrated existing search tests are green.

## 3. Detail island (TDD)

- [x] 3.1 Add failing detail VM/model tests for `show_event`/`clear`, title/date, the four tabs in existing order, summary text, entity identities, image source, and neutral-helper rating tint recomputation on retheme; verify red.
- [x] 3.2 Implement the thin detail VM/models and verify tests from 3.1 are green, with summary/rating/image derivation only in Python.
- [x] 3.3 Add failing real-island/facade tests for `DetailPanelRoot.qml`: `TabBar`/`StackLayout`, list rows, `ThemeRatingCard`, `Image` + `MouseArea`, entity activation, image click opening `ImageViewerDialog.exec()`, context limited to `detailPanelVm` + `islandPalette`, no `tooltipBridge`, and live-retheme preserving tab/scroll; verify red.
- [x] 3.4 Implement `DetailPanelRoot.qml` and convert `DetailPanel` to a shared-engine thin facade preserving `show_event`/`clear`/`entity_clicked`; keep `clickable_label.py`; verify tests from 3.3 and migrated detail tests are green.

## 4. World snapshot island (TDD)

- [x] 4.1 Add failing `WorldSnapshotViewModel` tests for `populate`, empty/date/all states, stats text, expanded-section persistence, and a flat model containing only `sectionHeader`/`entityRow` with type/id/name/ratingHex/fontBold/tooltipHtml/icon roles; verify red.
- [x] 4.2 Extend the failing snapshot tests for ordering, 24 px icon data, rating≥15 boldness, `toggleSection`, supported entity selection, and the invariant that event rows never emit selection; verify all new tests are red.
- [x] 4.3 Implement the snapshot VM/model in Python using the neutral rating helper and existing formatting/image utilities; verify tests from 4.1–4.2 are green and no tree/rating/tooltip rules are duplicated in QML.
- [x] 4.4 Add failing real-island/facade tests for `WorldSnapshotRoot.qml`: title/date/actions/list/stats `objectName`, `ThemeDateField`, “Показать”/“Сброс”/“Показать всё”, section toggling, entity click, event no-emit, non-clickable 24 px icons, context `worldSnapshotVm` + `islandPalette` + `tooltipBridge`, native tooltip shim, and live-retheme preserving expansion/scroll; verify red.
- [x] 4.5 Implement `WorldSnapshotRoot.qml` and delegates from `nri.components`, connect the single-date popup and existing tooltip bridge, and convert `WorldSnapshotWidget` to a shared-engine thin facade preserving `snapshot_requested`/`populate`/`entity_clicked`; verify tests from 4.4 and migrated snapshot tests are green.

## 5. Shell migration and deletion (TDD)

- [x] 5.1 Add failing MainWindow integration assertions that search remains above the splitter, timeline/detail/snapshot remain its three children, minimum widths stay 220/280/280, stretch factors stay 1/1/1, and all three facade class/public wiring contracts remain 1:1; verify red before removing layouts.
- [x] 5.2 Register all three islands in the shared lifecycle with deferred `setSource(QUrl())` teardown and verify R1 multi-island/reset tests plus 5.1 are green.
- [x] 5.3 Delete the widgets layouts and widget-only helpers from `search_bar.py`, `detail_panel.py`, and `world_snapshot_widget.py` without feature flags; verify grep finds no old `QLineEdit`/`QListWidget`/`QTreeWidget` panel layout construction while `clickable_label.py`, `CustomDateEdit`, system popups, and timeline date-chip code remain.
- [x] 5.4 Migrate existing panel tests to QML `objectName`/model addressing and verify their prior behavioral assertions pass with unchanged wiring.

## 6. Acceptance and packaging

- [x] 6.1 Remove obsolete snapshot title/“Показать” island grab checks, keep their `TitleText`/`ThemeButton` component coverage, and verify component pixel tests plus one live-retheme test per new island pass.
- [x] 6.2 Extend `test_no_chrome_hex` and PyInstaller bundle assertions for both components, three roots, and delegates; verify no new QML hex/OS-palette usage and all QML files/qmldir entries are bundled.
- [x] 6.3 Update `docs/CHANGELOG.md` and `docs/design-system-roadmap.md` only during apply to record R4 implementation, and verify both describe search above splitter, detail/snapshot in splitter, and R2 as next.
- [x] 6.4 Run all focused presentation suites, then `QT_QPA_PLATFORM=offscreen python -m pytest`; verify the full suite and Python 100% coverage gate are green.
- [x] 6.5 Run `openspec validate port-main-panels-qml-r4 --strict` and verify the implemented change still satisfies both MODIFIED capability deltas.
