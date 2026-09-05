# Proposal: Переезд канваса чар-листа и окон редактора/заполнения в QML-острова (Q3b)

## Why

Последний кусок эпика Q: канвас чар-листа (`QGraphicsView`, 1280 строк) остаётся единственным widgets-экраном приложения и последней отговоркой «потом» для QML. Пока он нативный, эпик Q не закрыт, а инлайн-редактирование полей навсегда привязано к `QGraphicsProxyWidget` — ровно тому механизму, ради обхода которого Q-эпик и задумывался.

## What Changes

- Канвас чар-листа (лента страниц, 9 типов полей, сетка привязки, зум/прокрутка, резинка-выделение, drag/resize, инлайн-редактирование) переезжает в QML-остров; `QGraphicsView`-реализация `canvas.py`, палитра, рейка, панели свойств editor/fill удаляются целиком (флага/второй копии нет — прецедент Q1/Q2.5a/Q3a).
- Окна Design (`CharacterSheetEditorDialog`) и Заполнения (`CharacterSheetFillDialog`) остаются `QDialog`-обёртками с нативными рамкой/Esc/меню «Правка»; всё содержимое под меню — QML-остров (палитра, рейка страниц, канвас, панель свойств). **Публичные API фасадов сохраняется 1:1** (`saved`, `binding_changed`, `view_model`, `load/load_instance`, `save`, `set_name`, `export_pdf`, `force_close`, `set_read_only`, грязный `closeEvent`) — `app/main.py` меняется только точкой импорта модуля.
- Одно покрытие на оба окна: общий QML-компонент канваса с режимами design/fill/read-only (прецедент одного класса `CharacterSheetCanvas` с `fill_mode`/duck-VM). Режим read-only просмотра мастера (D1) — тот же остров без права ввода.
- **Инлайн-редактирование полей становится нативным QML-редактированием** — `QGraphicsProxyWidget` в приложении не остаётся нигде; исключение proxy-полей из инвариантов каталога W2 снимается.
- Наполнение канваса — списочная модель полей из VM (роли id/type/page/x/y/w/h/содержимое) поверх неизменного qt-нулевого домена `character_sheet.py`; геометрия (clamp в страницу, snap, перенос между страницами) остаётся в VM, в QML нет второй реализации; изображения полей — через провайдер `image://`, привязанный к ImageStore.
- Поведение не меняется ни на пункт: спек `character-sheet-editor` и `character-sheet-instance` — чек-лист приёмки, не правятся; веб-вьювер стола (`character-sheet-host`), PDF (`character-sheet-pdf`), сервисы и БД не трогаются.
- Системные попапы остаются нативными (`QFileDialog` PDF/изображений, `QMessageBox` подтверждений, `QInputDialog` привязки персонажа); выбор опции дропдауна-поля — нативная `QMenu` по мосту из QML (правило системных меню островов).
- `.spec` получает новые qml-файлы (datas); шрифт листа остаётся Python-регистрацией (`register_sheet_font()`).

## Capabilities

### New Capabilities

_(нет — наблюдаемое поведение чар-листов описано неизменными спеками `character-sheet-editor`/`character-sheet-instance`; меняется способ поставки)._

### Modified Capabilities

- `qml-shell`: «QML-каркас приложения» — канвас чар-листа становится островом (снимается из перечня widgets-экранов; mention-edit остаётся); «Питание QML-списков списочной моделью» — модель полей канваса как потребитель того же правила; инлайн-правки полей — нативные QML-редакторы, без прокси-виджетов.

## Impact

- Удаляются: `app/presentation/views/character_sheet/canvas.py`, `palette.py`, `page_rail.py`, `properties_panel.py`, класс `FillPropertiesPanel` из `fill_dialog.py`.
- Фасады: `editor_dialog.py`, `fill_dialog.py` — те же имена/API, внутри `QDialog` + `QQuickWidget`.
- VM: `character_sheet_viewmodel.py` / `character_sheet_fill_viewmodel.py` — дописываются (списочная модель полей, sync-инвайкейблы для QML), контракты существующих property/сигналов/methods не меняются.
- QML: `app/presentation/qml/SheetCanvas.qml` (+делегаты/рейка/палитры), `SheetEditorRoot.qml`, `SheetFillRoot.qml`; `qml/engine.py` — image-провайдер; файл регистрации шрифта переезжает из удаляемого `canvas.py` в остров.
- `app/main.py` — только импорт; `nri_manager.spec` (datas qml); тесты: `test_character_sheet_canvas.py` переписывается на островную адресацию (`walk_items`/`objectName`), соседние dialog/e2e-тесты перенацеливаются; шрифтовой/бандл/pixel-инварианты (`test_no_chrome_hex`) сохраняются.
- Домен `character_sheet.py`, instance/PDF-домен, сервисы, репозитории, БД, веб-вьювер — без изменений.
