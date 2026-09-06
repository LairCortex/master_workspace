## 1. ThemeTextArea (TDD)

- [x] 1.1 Красный пиксельный тест `ThemeTextArea` (фон/рамка = hex field-токена, обе темы + off-skin без выдуманного hex, без golden PNG) по образцу `ThemeField`; `python -m pytest` на этот файл красный.
- [x] 1.2 `ThemeTextArea.qml` + запись в `qmldir`; `readOnly` для format/doc; тест 1.1 зелёный.

## 2. Provider и VM (TDD)

- [x] 2.1 Красный юнит: in-memory `image://dialog/<key>` — отдача `QPixmap` по ключу, сброс ключа, второй viewer не видит pixmap первого; без диска.
- [x] 2.2 Регистрация провайдера один раз на shared engine рядом с `image://sheet` (не расширять sheet); тест 2.1 зелёный.
- [x] 2.3 Красные юниты четырёх sync-VM (`monthSettingsVm`/`xlsxImportVm`/`imageViewerVm`/`docViewerVm`): 12 имён+reset+saved; path/progress/`import_requested`; image source key; doc `text`. Сервисы не в VM.
- [x] 2.4 Реализация VM; тесты 2.3 зелёные.

## 3. Острова и фасады (TDD)

- [x] 3.1 Красные objectName-контракты четырёх root (`walk_items`): month 12 полей+Save/Reset (`defaultButton`=Save); xlsx format (`ThemeTextArea`)+path+browse+progress+Ok (`defaultButton`); image Image+Close; doc `ThemeTextArea` без кнопок.
- [x] 3.2 `MonthSettingsRoot.qml` / `XlsxImportRoot.qml` / `ImageViewerRoot.qml` / `DocViewerRoot.qml` из `nri.components`; цвета только палитра; progress xlsx в острове, не в библиотеке; тесты 3.1 зелёные.
- [x] 3.3 Красная миграция существующих тестов: `test_custom_months.py` (MonthSettingsDialog), `test_xlsx_import_dialog.py`, `test_image_viewer.py`, `_DocViewerDialog` (`test_views.py`, `test_w2b_offskin_gaps.py`) — адресация `objectName`/`walk_items`, смыслы 1:1 (month `saved`+`accept()`; xlsx FileDialog/MessageBox на фасаде; image original→preview→текст, ctor 1:1; doc `.open()`, missing.md). e2e `test_e2e_import.py` остаётся на классе фасада.
- [x] 3.4 Фасады-острова: публичный Python API 1:1; context D1; deferred `setSource(QUrl())`; `views/doc_viewer_dialog.py` + реэкспорт `_DocViewerDialog` из `main_window`; pixmap key в `open`/`exec`, сброс в `done()`; `main.py` не трогать; Enter D7.
- [x] 3.5 Удалить widgets-вёрстку четырёх диалогов без флага; тесты 3.3 зелёные; grep полей/лейаутов старых диалогов чистый.

## 4. Приёмка

- [x] 4.1 Снять month-grab с острова в `test_theme_grab.py`; по одному live-retheme на остров; `test_no_chrome_hex` на новых qml.
- [x] 4.2 `nri_manager.spec` datas: `ThemeTextArea.qml` + четыре root; бандл-тест qml проходит.
- [x] 4.3 `docs/CHANGELOG.md`; `docs/design-system-roadmap.md`: пачка 1 R3 реализована, пачка 2 (llm+types) впереди.
- [x] 4.4 `python -m pytest` зелёный, coverage-гейт Python 100%.
