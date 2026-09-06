## 1. Characterization and red contracts

- [x] 1.1 Add characterization tests for `EntityCardDialog` ctor/`entity_type`, public signals/properties/methods, `populate()`→`get_data()` result shape for every `_FIELD_SPECS` type, proxy ordering, relations, image id and character-sheet availability; verify the focused tests pass against the predecessor state.
- [x] 1.2 Add red QML-island tests for one `EntityCardRoot.qml`, deterministic `objectName` controls, exact base/extra/image/related composition for every type and absence of character branching in QML; verify the focused tests fail before the root/VM exist.
- [x] 1.3 Add red lifecycle tests proving Save emits once without a valid gate, does not accept early, `finish_saving(False)` preserves data and re-enables Save, `finish_saving(True)` accepts once, and save/generation close guards block Escape/X/Cancel; verify they fail before the new lifecycle.

## 2. Python VM and stable proxies

- [x] 2.1 Implement the thin entity-card VM/model from `_FIELD_SPECS` and `_RELATED_CONFIG`, with stable field/relation hosts, `hasImage` and character-sheet availability but no type matrix in QML; verify tasks 1.1–1.2 tests pass for model composition and proxy identity.
- [x] 2.2 Reuse R6 MentionField/AI/related proxy contracts so `get_mention_edits()`, `get_ai_buttons()`, `get_entity_button()`, mention results/clicks and relation create/select/open/remove remain wiring-compatible; verify focused wiring/proxy tests pass unchanged.
- [x] 2.3 Implement `saveRequested`/compatible `saved(dict)`, `finish_saving`, combined `_saving`/AI save lock and close guard without field validation; verify task 1.3 tests pass.

## 3. EntityCardRoot island

- [x] 3.1 Implement the single `EntityCardRoot.qml` from `nri.components`: common fields, `Repeater` from Python field specs, data-driven image/related visibility, dynamic deterministic object names and no `entityType === "character"` branch; verify task 1.2 type-composition tests pass.
- [x] 3.2 Add the island-local tokenized Basic `SpinBox` with range 1–20, `ThemeDateField` start/end plus «Бессрочно», and `MentionField` for common/extra text; verify rating/date/mention round-trip tests pass and QML source contains no literal hex or JS color derivation.
- [x] 3.3 Add related tabs/picker actions, R6 AI controls, footer actions and conditional character-sheet button; verify create/open/remove relation flows, AI states, default Save and `open_character_sheet_requested` retain 1:1 semantics.

## 4. Native image and URL bridges

- [x] 4.1 Add red tests for 280×280 placeholder/preview, valid and invalid file picks, `image_picked`/`set_stored_image_id`, clear, unsaved preview viewer fallback and provider-key cleanup across two dialogs; verify they fail before bridge integration.
- [x] 4.2 Integrate the R3 image provider with QML `Image` + `MouseArea`, native `QFileDialog`/warning/`ImageViewerDialog`, and cleanup in `done()`; verify task 4.1 tests pass without temp files or bytes copied into QML properties.
- [x] 4.3 Add red tests for music link/edit toggling and Python-side URL opening, then implement the facade bridge with `QDesktopServices`; verify QML never opens the external URL directly and focused tests pass.

## 5. Facade migration and legacy removal

- [x] 5.1 Replace the widgets layout inside the existing `EntityCardDialog` with one shared-engine `QQuickWidget`, `entityCardVm`/`islandPalette` context and deferred teardown while preserving ctor and public API 1:1; verify characterization, wiring and dialog tests pass.
- [x] 5.2 Migrate existing entity-card, mention, AI, related, image, date and save-error tests to real-island `objectName` interaction while preserving tested behavior; verify each focused suite passes.
- [x] 5.3 Redirect every remaining production consumer to R4–R6 QML components/proxies, then delete `mention_text_edit.py`, `related_section.py`, `ai_assist_button.py`, `clickable_label.py` and `custom_date_edit.py` while keeping the mention popup module, `_CustomCalendar` and date popup bridges; verify imports and focused tests pass.
- [x] 5.4 Add a grep invariant for removed class definitions/imports/files, forbidden character branching in `EntityCardRoot.qml`, and preservation of allowed popup bridges; verify the invariant test passes and fails against representative forbidden fixtures/patterns.

## 6. Acceptance

- [x] 6.1 Add one live-retheme test on a populated/scrolled card and verify text, relation selection, focus/scroll and shared-engine identity survive theme switching; do not duplicate predecessor component pixel tests.
- [x] 6.2 Add `EntityCardRoot.qml` to PyInstaller/bundle expectations and extend the no-chrome-hex QML scan; verify bundle and source-invariant tests pass.
- [x] 6.3 Add regression coverage that storage markers remain hidden in the editor while accepted copy-out and raw `LIKE`/detail debt is unchanged; verify focused mention/search/detail tests pass.
- [x] 6.4 Run `QT_QPA_PLATFORM=offscreen python -m pytest` and verify the complete suite and 100% Python line-coverage gate pass.
