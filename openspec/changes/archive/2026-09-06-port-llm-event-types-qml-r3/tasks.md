## 1. Библиотечные компоненты (TDD)

- [x] 1.1 Добавить красный тест password/echo для `ThemeField`: маскирование при сохранённом text API, pixel background/border = field-токен в dark/light и off-skin без собственного hex; проверить, что целевой pytest падает до реализации.
- [x] 1.2 Реализовать password/echo property в `ThemeField` без изменения normal-mode и проверить, что тест 1.1 и существующие тесты `ThemeField` проходят.
- [x] 1.3 Добавить красный pixel/behavior suite `ThemeSwatch` для индексов 1…8: checkable state, pixel = `color.chart.1…8` в dark/light, нумерованный Qt-global off-skin, без arbitrary color/golden; проверить, что целевой pytest падает до реализации.
- [x] 1.4 Реализовать `ThemeSwatch.qml`, добавить его в `qmldir` и проверить, что тест 1.3 проходит для всех восьми индексов.

## 2. Тонкие sync-VM (TDD)

- [x] 2.1 Добавить красные unit-тесты `LlmSetupViewModel`: initial values, navigation/check/save state, `checkRequested`/`saveRequested`, password value и field-prompt model в порядке `FIELD_CONFIG` без внешнего service/http; проверить падение целевого pytest.
- [x] 2.2 Реализовать `LlmSetupViewModel` и адаптер model из `FIELD_CONFIG`, затем проверить зелёный тест 2.1 и точное восстановление `dict[str, dict[str, str]]`.
- [x] 2.3 Добавить красные unit-тесты `EventTypesViewModel`: rows/selection/button state и sync requests add/rename/recolor/move/remove без `event_service`/`_run`; проверить падение целевого pytest.
- [x] 2.4 Реализовать `EventTypesViewModel` и проверить зелёный тест 2.3, включая сохранение selected id при обновлении rows.

## 3. LLM-остров и фасад (TDD)

- [x] 3.1 Добавить красный `objectName`-контракт `LlmSetupRoot.qml`: connection/world/warnings, страницы и поля из model+`Repeater`, Back/Next/Save (`defaultButton`=Save), status/check и password echo; проверить падение island pytest до root-файла.
- [x] 3.2 Реализовать `LlmSetupRoot.qml` из `nri.components` с context `llmSetupVm` + `islandPalette`, без списка имён `FIELD_CONFIG` в QML, и проверить зелёный тест 3.1 плюс grep-инвариант отсутствия дублированных field names.
- [x] 3.3 Переписать существующие тесты `LlmSetupDialog` сначала как красную QML-адресацию, сохранив ctor, `saved`, `get_connection`, `get_world_prompt`, `get_field_prompts`, `page_count`, validation и check-status semantics; проверить, что suite падает до миграции фасада.
- [x] 3.4 Перевести `LlmSetupDialog` на общий-engine `QQuickWidget`, оставив `AppHttpClient`, `RemoteLlmProvider.check_connection`, async task и ошибки на фасаде; проверить зелёные тесты 3.3 и отсутствие service/http/provider в QML context.
- [x] 3.5 Зафиксировать красными тестами save lifecycle: повторный save блокирован, Esc/reject/close игнорируются до `finish_saving`, success принимает, failure показывает warning и оставляет диалог открытым; затем реализовать фасадный bridge и проверить зелёный целевой pytest.
- [x] 3.6 Удалить widgets-layout и `_FieldPromptsPage` LLM без флага/резервной реализации; проверить grep по `QFormLayout`/`QStackedWidget`/старым widget-полям в `llm_setup_dialog.py` и полный LLM dialog suite.

## 4. Event-types остров и фасад (TDD)

- [x] 4.1 Добавить красный `objectName`-контракт `EventTypesRoot.qml`: list/name, восемь `ThemeSwatch`, add/remove/up/down/Close и отсутствие Save/confirm; проверить падение island pytest до root-файла.
- [x] 4.2 Реализовать `EventTypesRoot.qml` из `nri.components` с context `eventTypesVm` + `islandPalette`, QML-only request emissions и swatch `Repeater` 1…8; проверить зелёный тест 4.1 и отсутствие service/async вызовов в QML.
- [x] 4.3 Переписать существующие тесты `EventTypesDialog` сначала как красную QML-адресацию, сохранив ctor, initial reload, `wait_idle`, `reload`, `type_names`, `types_changed`, default-name/next-color и selection semantics; проверить падение suite до миграции фасада.
- [x] 4.4 Перевести `EventTypesDialog` на общий-engine `QQuickWidget`, оставив `event_service`, `_run`, coroutine writes/reload и публичный API на фасаде; проверить зелёные тесты 4.3.
- [x] 4.5 Добавить/сохранить e2e-тесты немедленного write-through для rename/recolor/add/move/remove и закрытия без Save/confirm; проверить, что service-вызов и `types_changed` происходят после каждого действия, а close не откатывает состояние.
- [x] 4.6 Удалить widgets-layout, painter/swatch buttons и list controls диалога без флага, сохранив внешне используемые константы/helpers; проверить grep старых layout/control классов и полный event-types suite.

## 5. Темизация, lifecycle и поставка

- [x] 5.1 Добавить по одному красному live-retheme-тесту на остров: LLM сохраняет current page/введённые значения/password masking, types сохраняет selected id/order; реализовать palette bridge/lifecycle и проверить оба теста зелёными.
- [x] 5.2 Добавить оба root-файла и `ThemeSwatch.qml` в PyInstaller datas/qmldir ожидания; проверить целевым bundle-тестом наличие файлов и загрузку модулей без dev-окружения.
- [x] 5.3 Расширить `test_no_chrome_hex` на новые QML-файлы и проверить, что literal hex, OS palette и JS-derived colors отсутствуют, а off-skin использует только именованные Qt globals.
- [x] 5.4 Проверить deferred teardown обоих островов на общем engine тестом open/close/reopen без QML warnings, утечек context и создания второго engine.
- [x] 5.5 Запустить целевые suites компонентов, VM, LLM и event types с `QT_QPA_PLATFORM=offscreen`, затем `python -m pytest`; проверить зелёный полный прогон и Python coverage gate 100%.
