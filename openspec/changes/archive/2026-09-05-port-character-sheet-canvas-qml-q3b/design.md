# Design: port-character-sheet-canvas-qml-q3b

## Context

`canvas.py` (1280 строк): `QGraphicsView` вертикальной ленты A4; координаты сцены = пункты страницы; поля — `SheetFieldItem` (paint-ветки по 9 типам), зум 25–400 % Ctrl-колесом с якорем, fit-width при открытии; drag/resize/рамка-выделение/ручки — ручная диспетчеризация mouse-событий; инлайн-правка — `QGraphicsProxyWidget` (QLineEdit/QPlainTextEdit) с единым буфером VM; дропдаун в fill — `QMenu`; шрифт DejaVu Sans регистрируется при импорте модуля; цвета canvas — фиксированные константы «бумаги» (не темизуются, W2b D5).

`editor_dialog.py` (437): QDialog с меню «Правка» (undo/redo/paste…, StandardKey), палитра + рейка + canvas + панель свойств; PDF через доменный экспорт; сохранение под `run_locked` с `QMessageBox`; грязный `closeEvent`. `fill_dialog.py` (496): рейка navigation-only + canvas + `FillPropertiesPanel`; привязка персонажа `QInputDialog`; `set_read_only` — режим просмотра мастера. Публичные API фасадов (`saved`/`binding_changed`, `view_model`, `load*`, `save`, `set_name`, `export_pdf`, `force_close`, `set_read_only`, `closeEvent`) использует `app/main.py`.

Обе VM — чистые QObject-конtracts: place/move/resize/remove, drag_move*/commit_drag*/relocate_field, gestures (begin/end), selection/copy/paste/duplicate(z-visible_center), pages/orientation/z-order/undo/redo/snap; fill — те же duck-входы + set_text/set_number/set_dropdown/set_image/clear_image/apply_remote_value. Домен `character_sheet.py` — qt-нулевые `page_origin`/`scene_to_page`/`page_size`, clamp/snap живут в VM. Инфраструктура Q2.5a: модели-питание, tooltip-шим, walk_items, бандл-tест; `register_sheet_font` — глобальная регистрация шрифта.

## Goals / Non-Goals

**Goals:**
- 1:1 перенос наблюдаемого поведения канваса и окон Design/Заполнения (включая read-only просмотр мастера) в QML; `QGraphicsView`/`QGraphicsProxyWidget`-механика удалена целиком.
- Публичные API фасадов `CharacterSheetEditorDialog`/`CharacterSheetFillDialog` сохранены — `main.py` меняется точечно; VM не переписываются (дописываются: модель полей + invokables).
- Одно покрытие design/fill/read-only (прецедент общего `CharacterSheetCanvas`), геометрию/клампы/снап считает VM — в QML нет второй реализации.
- Правила приёмки — неизменные спекы `character-sheet-editor`/`character-sheet-instance`.

**Non-Goals:**
- Список чар-листов и пресет (готовы, Q3a); mention-edit/диалоги события и карточки (заблокированы, Qx).
- Изменения поведения: новые типы полей, правки в PDF/экспорт, новые попапы вместо системных.
- Правки домена/сервисов/репозиториев/БД, веб-вьювера стола (`character-sheet-host`).

## Decisions

### D1. Фасады окон: тот же API, нативное меню, остров под ним

`editor_dialog.py`/`fill_dialog.py` остаются на месте, классы/сигналы/методы прежние; внутри `QDialog` — `QMenuBar` («Правка», StandardKey как сейчас) + один `QQuickWidget` (SizeRootToView, deferred teardown). Слоты фасада (PDF/изображения `QFileDialog`, сохранения с `run_locked`+`QMessageBox`, bind/unbind `QInputDialog`, подтверждения грязного закрытия и удаления страницы) переносятся почти буквально. Enter обёртки — клик маркеру `defaultButton` («Сохранить») только когда остров не израсходовал Enter (инлайн-правка поля приоритетна). Альтернатива «QML-меню» отклонена правилом шелла.

### D2. Один QML-компонент канваса на все режимы

`app/presentation/qml/SheetCanvas.qml` — лента страниц + поля + жесты + инлайн, режим `mode: "design"|"fill"|"readonly"` (прецедент одного класса с `fill_mode`). `SheetEditorRoot.qml`/`SheetFillRoot.qml` — композиция канваса с палитрой, рейкой, панелью свойств; `SheetFieldDelegate` (внутри SheetCanvas) — ветки рендера по типу, порядок делегатов = z-порядок страницы (позже — выше, совпадает с семантикой Repeater).

### D3. Лента/зум — владение представлением в QML

Flickable + контейнер страниц с `scale`; pt↔px через transform контента (координаты полей QML-влокальные = пункты, VM получает пункты напрямую). Константы 25–400 %/шаг 1.15/fit-width при первом показе и смене ориентации — свойства вида, живут в QML они же никогда не были доменными правилами. `visible_page_changed` → `vm.set_current_page`, `scroll_to_page(index)`/`visible_page_center(index)` — invokables/вывод QML (панель рейки и paste питаются через те же каналы, что сейчас).

### D4. Модель полей поверх домена

`SheetFieldModel(QAbstractListModel)` в пакете VM (роль-набор: id/type/page/x/y/w/h/fontSize/content-для-рендера/imageKey/optionsCount/disabled): строится по `template` VM и обновляется инкрементально существующими сигналами VM (field_added→insertRow, field_removed→removeRow, geometry/content/props→dataChanged ролей, pages/orientation/template→reset). Один экземпляр обслуживает и design, и fill: fill читает готовое отображаемое значение через display-инвокабл VM (доменный `resolve_display` не дублируется). Копий полей в QML нет (spec-сценарий «Поля канваса идут из модели»).

### D5. Жесты — тонкие вызовы существующих sync-входов VM

Палитра инструмента → `set_tool`; клик по листу → `place` с пунктами точки клика (зажим в страницу считает VM; клик по рейке/зазору не ставит — путь палитры не задействован); одиночный выбор — клик (`select`/Shift+клик `toggle_select`); рамка — прямоугольник на view-слое, по отпускании `select_ids(пересечённые, additive=Shift)`; перенос набора — `begin_gesture/drag_move_selection/commit_drag_selection` (перенос между страницами решает VM); ресайз — `begin_gesture/resize/end_gesture`; dblclick в design открывает инлайн; в fill — клик чекбокса `toggle_checkbox`, дропдаун — сигнал facade-мосту: `QMenu` нативная в глобальных координатах поля (запрет QML-меню), выбор → `set_dropdown`; Del/Backspace — `remove_selection`; Esc — `select(None)`; Ctrl+колесо — якорный зум локально (D3). Привязка/Shift-override — `set_snap_override` при жесте, как сейчас.

### D6. Инлайн-редактирование — QML-редактор внутри поля

Пока `inline_field_id` задан, в делегате поля активен `TextField`/многострочный редактор (тот же шрифт/кегль, переносы/обрезка по ветке типа): live text → `set_content`; Enter/Ctrl+Enter/Esc → `commit_inline`/`cancel_inline`; числа — коммит по Enter `apply_number` с откатом при reject. Единый буфер — VM (панель свойств и остров читают/пишут одно и то же поле VM; рассинхрон исключён копий нет). `QGraphicsProxyWidget` удажается из проекта вместе с исключением proxy-полей из каталога W2 (обновление инвариантного теста).

### D7. Шрифт и изображения — Python-половина

`register_sheet_font()` переезжает из удаляемого `canvas.py` в модуль python-стороны острова (тот же `QFontDatabase.addApplicationFont` once-per-application; вызов до загрузки островов); путь к TTF и datas `.spec` не меняются. Изображения полей — `QQuickImageProvider` (`image://sheet/<imageId>`, идемпотентная регистрация на движок), читающий ImageStore текущей игры; асинхронность загрузки даёт QML Image (ручной QPixmap-кэш canvas не наследуется).

### D8. Сцена канваса остаётся нетемизируемой

Бумага/зазор/рамки/выделение/сетка/ручки — фиксированные константы вида (переезжают в `SheetCanvas.qml` из canvas.py 1:1); это та же разрешённая зона нетемизируемого слоя канваса: инвариант `test_no_chrome_hex` сканирует qml, исключение канвас-слоя переносится на новый файл с той же мотивировкой. Chrome островов (палитра, рейка, панель свойств, кнопки) — только `nri.components` + палитра токенов, оф-скин — именованные глобалы (паттерн Q2a1).

### D9. Формы редактирования в QML — через те же VM-входы

Палитра типов (включая «pointer»), рейка страниц (имя, добавить/удалить/↑↓, инлайн-переименование → `rename_page`; navigation-only в fill), комбо ориентации (`set_orientation`), панель свойств (ветки: content/кегль/границы числа/опции `set_options`/галка дефолта чекбокса; image — «Выбрать…/Очистить» → сигналы фасаду на `QFileDialog`). Значения/активность только из VM-свойств; async остаётся в фасаде.

### D10. Тесты

`test_character_sheet_canvas.py` переписывается на остров (walk_items + координатные клики через масштаб, те же проверяемые смыслы: лента/зум/drag/рамка/handles/инлайн/тип-рендеры/шрифт); тесты editor/fill диалогов перенацеливаются на QML-адресацию (смыслы сигналов/сохранений/привязок не меняются); e2e чар-листов — по образцу timeline-проб; бандл-test `.spec` с новыми qml; пиксельная приёмка: константы бумаги (canvas) + токен chrome (острова), golden нет; VM/домен-тесты не разъезжаются (контракты не менялись).

## Risks / Trade-offs

- [Тяжёлые жесты внутри QQuickWidget в диалоге (zoom anchor, rubber band на scaled-контент)] — вся математика на item-локальных координатах (transform тулkit'а), зум — тот же viewport-анкор что в timeline; приёмка координатными тестами.
- [Перенос между страницами перетаскиванием через gap] — остаётся на VM (`drag_move_selection`/`commit_drag_selection` знают gap/страницы — проверка существующими VM-юнитами, а не новым QML-кодом).
- [Разъезд live-редактирования при смене inline-поля QQuickFocus] — коммит-при-переходе даёт сам VM-контракт (`commit_inline`/`cancel_inline` при открытии другого поля, поведение текущего canvas).
- [Двойная ветка «нетемизируемой» бумаги в qml] — единственный файл-исключение `test_no_chrome_hex`; расширение перечня исключений запрещено (тот же инвариант, что W2b).

## Open Questions

_(нет)_
