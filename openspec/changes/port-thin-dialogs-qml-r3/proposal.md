# Proposal: Четыре тонких диалога Q2a2 на QML-острова (R3, пачка 1)

## Why

Эпик R закрывает оставшийся widgets-chrome. Первый change куска R3 переводит четыре диалога без mention/async-сервиса в острове (month_settings, xlsx_import, image_viewer, doc-viewer) и вводит `ThemeTextArea`, чтобы пачка 2 (llm + event_types) не копировала многострочное поле. R1 уже врата тестов; порядок карты — R3 до панелей и mention-стека.

## What Changes

- `MonthSettingsDialog`, `XlsxImportDialog`, `ImageViewerDialog` и вынесенный `DocViewerDialog` становятся QML-островами в прежних `QDialog`-обёртках (рамка/Esc системные, Enter — `defaultButton`). Widgets-вёрстка содержимого удаляется без флага/второй копии (прецедент Q1/Q3a).
- `_DocViewerDialog` выносится из `main_window.py` в `views/doc_viewer_dialog.py`; `MainWindow` только открывает. `main.py` не трогаем.
- В `nri.components` — `ThemeTextArea` (xlsx format, doc-viewer, дальше llm). Progress xlsx — Controls+токены **в острове**, не в библиотеку. Password/`ThemeSwatch` — пачка 2, не здесь.
- Image viewer: публичный ctor `(original, preview)` 1:1; показ через `image://` provider на общем движке (ключ на открытие, сброс в `done()`). Unsaved-preview без сущности сохраняется.
- Поведение UX 1:1: month `saved`+сразу `accept()`; xlsx `QFileDialog`/`QMessageBox` на фасаде, close после import — wiring; doc немодальный `.open()`; image Close/Esc и fallback original→preview→текст.
- Тонкие sync-VM; context `monthSettingsVm` / `xlsxImportVm` / `imageViewerVm` / `docViewerVm` + `islandPalette`. Сервисы не в QML.
- Приёмка: hex — `ThemeTextArea`; островам `objectName` + live-retheme. Month-grab с острова в `test_theme_grab` снимается (кроет `ThemeField`). `.spec` datas + новые qml.
- Roadmap/CHANGELOG: пачка 1 R3; пачка 2 (llm+types) не входит.

## Capabilities

### New Capabilities

_(нет)_

### Modified Capabilities

- `qml-shell`: в перечень островов — month settings, xlsx import, image viewer, doc viewer; сужается формулировка «остальные диалоги — widgets».
- `qml-components`: в библиотеку добавляется многострочное поле `ThemeTextArea` с пиксельной приёмкой.

## Impact

- `app/presentation/views/month_settings_dialog.py`, `xlsx_import_dialog.py`, `image_viewer_dialog.py` — фасады-острова; `doc_viewer_dialog.py` — новый файл; `main_window.py` — импорт.
- `app/presentation/viewmodels/` — четыре тонкие VM.
- `app/presentation/qml/` — четыре `*Root.qml`; `nri/components/ThemeTextArea.qml` + qmldir.
- Image provider на shared engine (регистрация рядом с `image://sheet`).
- `nri_manager.spec`, тесты перечисленных диалогов + `test_theme_grab.py` (снять month-grab) + бандл qml; wiring пяти диалогов без переписи сигналов.
- Не входит: llm_setup, event_types, панели R4, mention-стек, `ThemeDateField`.
