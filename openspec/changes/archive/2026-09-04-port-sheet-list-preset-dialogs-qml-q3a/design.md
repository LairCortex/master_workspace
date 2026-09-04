# Design: port-sheet-list-preset-dialogs-qml-q3a

## Context

`list_dialog.py` (499 строк): `QDialog` с `QTabWidget` (вкладки «Шаблоны»/«Листы»), два `QListWidget` (id строки в `UserRole`; метка листа — `«лист — шаблон»`), кнопки Создать/Создать из пресета…/Открыть/Переименовать/Удалить/Закрыть. Все потоки — корутины на qasync под сессионным локом (`run_locked`), имена спрашиваются `QInputDialog.getText` (`create_instance` — ещё и `getItem` выбора шаблона), фатальные шаги — `QMessageBox.question/warning/critical`. Публичный контракт фасада используется `app/main.py` и wiring: сигналы `open_requested/open_instance_requested/renamed/instance_renamed`, методы `set_open_sheet_id/set_open_instance_id/set_seated_ids`, async `refresh()` с контрактом «лок предоставляет вызывающий» (не реентерабелен!), свойство `preset_dialog`.

`preset_dialog.py` (182 строки): немодальный дочерний `QDialog`: список пресетов (`PresetCatalog().list()`), read-only `QPlainTextEdit` лицензии, `QLineEdit` имени; правило D5 — подстановка заголовка пресета в имя, только пока поле пусто или держит заголовок другого пресета (`.strip()`-сравнение); `created(int)`; конфликт имени — warning, диалог остаётся открытым.

Инфраструктура Q1/Q2a1 на месте: общий `QQmlEngine` (`qml/engine.py`) с палитрой токенов в его контексте, `nri.components` (ThemeButton/ThemeField/RowItem/CardPanel/…), tooltip-шим, `walk_items`-тесты, софт-бэкенд, бандл-tест `.spec`. Диалоги event/entity в Q2 не участвовали (MentionTextEdit) — эти два экрана чистые и едут первыми.

## Goals / Non-Goals

**Goals:**
- 1:1 перенос наблюдаемого поведения вкладок «Шаблоны/Листы» и пресет-потока в QML-острова; widgets-вёрстка удалена целиком, флага нет.
- Публичный API фасадов (`CharacterSheetListDialog`, `CharacterSheetPresetDialog`) сохранён — `main.py` и wiring не переписываются под новый контракт.
- Chrome только из библиотеки `nri.components` и палитры токенов; оф-скин — именованные Qt-глобалы.
- Системные попапы (`QInputDialog`/`QMessageBox`) остаются нативными вызовами Python-стороны.

**Non-Goals:**
- Переезд канваса/редакторов чар-листа (editor/fill/properties/palette/rail) — Q3b.
- Любые изменения сервисов, репозиториев, БД, `PresetCatalog`, публичных контрактов `character-sheet-editor`/`character-sheet-preset`.
- QML-аналоги `QInputDialog`/`QMessageBox`; переезд editor/fill; tooltip-шим новых контролов сверх уже библиотечного.

## Decisions

### D1. Фасады сохраняют имена и публичный API

Файлы `list_dialog.py`/`preset_dialog.py` остаются на месте и сохраняют имена классов, сигналы и методы; внутри `QDialog`-обёртки — один `QQuickWidget` по образцу лаунчера (SizeRootToView, `assert Ready`).

Контекст острова: VM экрана под островным именем (`sheetListVm`/`sheetPresetVm`), `islandPalette`, `tooltipBridge` (по потребности). Островные имена — вынужденные: у всех `QQuickWidget` общий `QQmlEngine`, его `rootContext()` разделяется виджетами, и plain `vm` перетёр бы биндинги лаунчера/шкалы на том же движке. `islandPalette` пушится диалог-owned `QmlPalette` (контракт лаунчера/timeline); в общий движок регистрируется только `palette`.

Освобождение сцены на закрытии расщепляется по жизненному циклу диалога: список использует лаунчерский отложенный `setSource(QUrl())` one-shot (диалог кэшируется в `main.py` и переживает цикл событий), а пресет с `WA_DeleteOnClose` освобождает сцену синхронно в `done()` — qasync выгружает `DeferredDelete` в своих колбэках, и «deleteLater + one-shot» даёт гонку: диалог умирает раньше таймера, освобождение не выполняется, деструктор `QQuickWidget` попадает в устаревший контекст (use-after-free). Механизм задокументирован комментариями в обоих файлах.

Альтернатива «новые имена + правка main.py» отклонена: contract-preservation дешевле диффа проводки.

### D2. `SheetListViewModel` — состояние, фасад — async-потоки

Тонкий `viewmodels/sheet_list_view_model.py`: две списочные модели строк (роли `id`/`label`; вкладка листов — готовые метки `«лист — шаблон»`), `currentTab`, selection-id по вкладкам, флаги `canOpen/canRename/canDelete/presetButtonVisible`, слоты выбора; кнопки QML эмитят `createRequested/presetRequested/openRequested/renameRequested/deleteRequested/closeRequested`. Все корутины (create/open/rename/delete/refresh с `run_locked`, обработкой `CharacterSheetError` и `QMessageBox`) переезжают в фасад почти буквально из текущих методов; VM после успеха обновляется Python-стороной (lock-контракт `refresh()` не меняется). `set_open_sheet_id`/`set_open_instance_id`/`set_seated_ids` фасада пробрасываются в VM и пересчитывают флаги.

### D3. `SheetPresetViewModel` — пресеты и правило D5 на Python

`viewmodels/sheet_preset_view_model.py`: плоский список пресетов (id/title), `selectedIndex`, `licenseText`, `nameText`; синхронный слот `selectPreset(index)` применяет подстановку ровно по D5 (пусто или `.strip()`-совпадение с чужим заголовком). QML при смене выделения зовёт `selectPreset`; кнопка «Создать» эмитит `createRequested` — фасад валидирует пустое имя (`QMessageBox.warning`), зовёт `create_from_preset` под локом, при успехе `created.emit(id)` + `accept()`, при `CharacterSheetError` — warning, диалог остаётся открытым. Подъём уже открытого диалога (`raise_/activateWindow`) — методы обёртки-`QDialog`, без изменений.

### D4. Вёрстка островов — библиотека, без self-made chrome

Списки — `ListView` с делегатом `RowItem` (объектные контракты `templateList`/`instanceList`/`presetList`), кнопки — `ThemeButton` (`createButton`/`openButton`/`renameButton`/`deleteButton`/`presetButton`/`closeButton`, в пресете — `okButton`/`cancelButton`), поле имени — `ThemeField nameField`, вкладки — `TabBar`+`StackLayout` (`tabTemplates`/`tabInstances`; видимость `presetButton` — только вкладка шаблонов). Лицензия — read-only прокручиваемая текстовая область (`selectByMouse`) поверх токенов поля. Цвета — только `islandPalette`; literal-hex запрещён (инвариант `test_no_chrome_hex` сканирует qml).

### D5. Enter — в маркер `defaultButton`, попапы нативные

Корневые qml-объекты выставляют свойство-маркер `defaultButton` (у списка — `openButton`, у пресета — `okButton`); keyPress Enter в обёртке передаётся кликом маркеру (контракт Q2a1-диалогов). Нативные `QInputDialog`/`QMessageBox` вызывает фасад в своих обработчиках — никакого QML-поповера вместо них; позиционировать относительно острова не нужно (системные окна модальны родителю).

### D6. Тесты

Существующие тесты диалогов (`test_character_sheet_list_dialog.py`, `test_character_sheet_preset_dialog.py`) сохраняют проверяемые смыслы (набор сигналов, ложный `refresh` не под локом-изнутри, правила отключения кнопок, D5-подстановка, конфликт имени, отмена каталога) и переписываются на адресацию QML (`walk_items`/`objectName`); мок `QInputDialog`/`QMessageBox` — тот же (фасад зовёт их по-прежнему). Юниты VM (модели/флаги/D5) добавляются. Бандл: datas `.spec` + новые qml-файлы, бандл-тест расширяется.

## Risks / Trade-offs

- [Focus/фокус-порядок в QQuickWidget в диалоге] — кнопочные потоки завязаны на клики и Enter-маркер, не на Tab-обход; регресс Tab-порядка принимается (не contract в текущих тестах).
- [Разнородные строковые метки листов (`лист — шаблон`)] — считаются Python-стороной при refresh (D2), QML не конкатенирует — второй реализации правил нет.
- [Двойная прокрутка (вкладка-скролл внутри QQuickWidget в QDialog)] — штатный паттерн шкалы/лаунчера; при регрессе колёсной эвент обрабатывается Control'ом списка, как везде.
- [Пиксельная приёмка] — библиотеке поэлементная пиксельная приёмка не дублируется (правило Q2a1); достаточно semantic-адресации + существующих пиксельных тестов палитры острова.

## Open Questions

_(нет)_
