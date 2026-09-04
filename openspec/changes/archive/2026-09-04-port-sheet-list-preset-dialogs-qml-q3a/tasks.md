# Tasks: port-sheet-list-preset-dialogs-qml-q3a

## 1. View models (без QML)

- [x] 1.1 `app/presentation/viewmodels/sheet_list_view_model.py`: `SheetListViewModel` — две списочные модели строк (роли `id`/`label`), `currentTab`, selection-id по вкладкам, флаги `canOpen/canRename/canDelete/presetButtonVisible` (открытый/сидящий/листоимеющий шаблоны по `set_open_sheet_id`/`set_open_instance_id`/`set_seated_ids`); юниты: метки `«лист — шаблон»` считает Python, флаги по всем комбинациям блокировок.
- [x] 1.2 `app/presentation/viewmodels/sheet_preset_view_model.py`: `SheetPresetViewModel` — список пресетов (`PresetCatalog().list()`), `selectPreset(index)` с правилом D5 (подстановка только пока имя пусто или `.strip()`-совпадает с чужим заголовком), `licenseText`/`nameText`; юниты: D5-матрица (пусто/свой/чужой/пользовательское имя + обрамляющие пробелы), смена лицензии при смене выбора.

## 2. QML-острова

- [x] 2.1 `app/presentation/qml/SheetListRoot.qml`: `TabBar`+`StackLayout` (objectName `tabTemplates`/`tabInstances`), два `ListView` с делегатом `RowItem` (`templateList`/`instanceList`), ряд `ThemeButton` (`createButton`/`presetButton`/`openButton`/`renameButton`/`deleteButton`/`closeButton`), `defaultButton`-маркер на `openButton`, `*Requested`-сигналы корня, флаги VM на enabled/visible (`presetButton` — только вкладка шаблонов); цвета только из палитры острова, загрузка через `nri.components`; проверка: остров грузится в existing-тесте загрузки qml (walk_items на objectName).
- [x] 2.2 `app/presentation/qml/SheetPresetRoot.qml`: `presetList` (`RowItem`), read-only прокручиваемая лицензия (`selectByMouse`, объект `licenseView`), `nameField` (`ThemeField`), `okButton`/`cancelButton` (маркер `defaultButton` на `okButton`); смена выделения зовёт sync-слот `selectPreset`; проверка: остров грузится, делегаты адресуются.

## 3. Фасады

- [x] 3.1 `list_dialog.py` → фасад `CharacterSheetListDialog` прежнего публичного API (сигналы `open_requested`/`open_instance_requested`/`renamed`/`instance_renamed`, методы `set_open_sheet_id`/`set_open_instance_id`/`set_seated_ids`, `refresh()`, свойство `preset_dialog`): `QDialog`-обёртка + `QQuickWidget` по образцу лаунчера (отложенный teardown one-shot — диалог кэшируется в `main.py`), контекст `sheetListVm`/`islandPalette`; корутины create/open/rename/delete/refresh переносятся в фасад с сохранением `run_locked` и моков попапов; Enter обёртки — клик `defaultButton`; проверка: существующие смыслы тестов списка проходят через walk_items после миграции теста (п. 4.1).
- [x] 3.2 `preset_dialog.py` → фасад `CharacterSheetPresetDialog` (сигнал `created(int)`, немодальность, повторный вызов = `raise_/activateWindow`): контекст `sheetPresetVm`/`islandPalette`, освобождение сцены синхронно в `done()` (у dialog-owned `WA_DeleteOnClose` отложенный one-shot даёт гонку — см. D1); `createRequested` → валидация пустого имени (`QMessageBox.warning`), `create_from_preset` под локом, успех — `created.emit` + `accept`, конфликт — warning и остаться открытым; проверка: смыслы тестов пресета проходят после миграции (п. 4.2).
- [x] 3.3 Удаление widgets-вёрстки обоих диалогов без флага: в `app/presentation/views/character_sheet/` не остаётся QWidget-содержимого этих окон, импортов удалённых классов нет (`python -c "import app.main"` и grep-проверка); проверка: grep чистый, приложение стартует.

## 4. Приёмка

- [x] 4.1 Миграция `tests/presentation/test_character_sheet_list_dialog.py`: адресация через `walk_items`/`objectName`, смыслы 1:1 (набор сигналов, `refresh` без внутреннего `run_locked`, правила отключения кнопок, создание листа = getItem+getText → `open_instance_requested`, отмены попапов, ошибки `_show_error`); тесты зелёны.
- [x] 4.2 Миграция `tests/presentation/test_character_sheet_preset_dialog.py`: смыслы 1:1 (D5-подстановка через `selectPreset` и через остров, конфликт имени — диалог жив, пустое имя — warning, отмена — `created` без emit, `created(int)` при успехе); тесты зелёны.
- [x] 4.3 Инварианты и бандл: `test_no_chrome_hex` проходит на новых qml; `nri_manager.spec` datas пополнен `SheetListRoot.qml`/`SheetPresetRoot.qml`; бандл-тест qml-файлов проходит; пиксельная проверка токена доезжает до новых островов (формат `test_qml_*` pixel-ассертов, без golden).
- [x] 4.4 Полный `python -m pytest` зелёный (включая coverage-гейт Python-стороны); `docs/design-system-roadmap.md`: Q3a реализовано, эпик Q открыт (впереди Q3b); `docs/CHANGELOG.md` с пометкой незавершённости эпика.
