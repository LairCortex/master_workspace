## Context

См. proposal.md — Why. Четыре widgets-диалога без mention/AI в острове: `month_settings_dialog.py` (~106), `xlsx_import_dialog.py` (~201), `image_viewer_dialog.py` (~94), `_DocViewerDialog` в `main_window.py` (~67). Инфраструктура Q1/Q2a1/R1 на месте: общий движок, `nri.components`, `islandPalette`, `reset_qml_shell`, DPR=1. `image://sheet` резолвит байты ImageStore; viewer получает уже готовые `QPixmap` (в т.ч. несохранённый pick).

## Goals / Non-Goals

**Goals:**
- 1:1 UX четырёх диалогов на островах; widgets-вёрстка удалена без флага.
- `ThemeTextArea` в библиотеке с пиксельной приёмкой; потребители — xlsx format и doc-viewer.
- Публичные Python API фасадов 1:1 (wiring не переписывать); doc-viewer — отдельный модуль, `main.py` без правок.

**Non-Goals:**
- llm_setup, event_types (пачка 2 R3), `ThemeField` password, `ThemeSwatch`.
- R4 панели, `ThemeDateField`, mention-стек.
- Progress в библиотеке; запись pixmap viewer на диск.

## Decisions

### D1. Фасады-острова, имена VM в context уникальны

`QDialog` + `QQuickWidget` + общий engine, deferred `setSource(QUrl())` как лаунчер (диалоги переживают цикл). Context: `monthSettingsVm` / `xlsxImportVm` / `imageViewerVm` / `docViewerVm` + `islandPalette`. Голое `vm` запрещено (общий `rootContext`).

### D2. Тонкие sync-VM, async на фасаде/wiring

Month: 12 имён, reset, `saved`. Xlsx: format text, path, progress, `import_requested`; `QFileDialog`/`QMessageBox` — фасад. Doc: `text` из `Path.read_text` на фасаде при open. Image: не VM состояния картинки в JS — provider (D3).

### D3. In-memory `image://dialog/<key>` provider

Регистрация один раз на engine (рядом с `sheet`). Словарь key→`QPixmap` на GUI-потоке, синхронная отдача (байты уже в памяти, без DB). Ключ на `open`/`exec`, сброс в `done()`. Ctor `(original, preview)` без изменений. Альтернатива temp file отклонена (диск ради просмотра). Не расширять `image://sheet` (другой контракт — store id).

### D4. `ThemeTextArea` = field-токены, read-only флаг

Как `ThemeField`, многострочный `TextArea`; `readOnly` для format/doc. Off-skin — Basic/глобалы. Progress xlsx — `ProgressBar` в острове, цвет из `islandPalette`, не в qmldir.

### D5. Doc viewer — новый файл

`views/doc_viewer_dialog.py`, класс публично `DocViewerDialog` (или сохранить `_DocViewerDialog` как alias — **сохранить имя `_DocViewerDialog`**, чтобы тесты `main_window` не ломались: либо реэкспорт из `main_window`, либо правка импортов тестов). Решение: вынести класс как `DocViewerDialog`, в `main_window` `from ... import DocViewerDialog as _DocViewerDialog` если тесты ищут на модуле; проверить фактические импорты тестов и сохранить наблюдаемый API `MainWindow._show_readme`.

### D6. Тесты: TDD

Сначала красные тесты `ThemeTextArea` (hex обе темы, off-skin) и objectName-контракты островов; затем реализация. Существующие semantic-тесты четырёх диалогов переезжают на `objectName`/`walk_items`. Снять month pixel из `test_theme_grab.py`. Один live-retheme на остров. Бандл: `ThemeTextArea.qml` + четыре root. Гейт 100% покрытия Python.

### D7. Enter / defaultButton

Month/xlsx/image: маркер Save/Ok/Close как сейчас. Doc — без кнопок, Esc системный.

## Risks / Trade-offs

- [Provider живёт на общем движке] → ключ+сброс в `done()`; тест: второй viewer не видит pixmap первого.
- [QQuickWidget+QPixmap provider на GUI thread] → только sync in-memory, без `run_coroutine_threadsafe`.
- [Вынос doc-класса ломает `from main_window import _DocViewerDialog`] → реэкспорт или правка тестов в том же change.
- [Focus Tab в диалоге] → как Q3a, не контракт.

## Migration Plan

Один merge. Откат — revert. Пачка 2 R3 не зависит от progress-острова, зависит от `ThemeTextArea`.

## Open Questions

_(нет)_
