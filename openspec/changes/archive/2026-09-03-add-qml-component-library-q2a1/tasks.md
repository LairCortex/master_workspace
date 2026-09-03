## 1. Каркас модуля

- [x] 1.1 Создать `app/presentation/qml/nri/components/` с `qmldir` (`module nri.components`, записи типов по будущему списку) и smoke-qml, импортирующим модуль; проверить: `QQuickWidget` с общим движком загружает smoke-файл, `quick.errors()` пуст (тест в `tests/presentation/test_qml_components.py`).
- [x] 1.2 Перенести хелперы `token()`/`px()` из `LauncherRoot.qml` в `nri/components/tokens.js` (`.pragma library`, без состояния) со страховкой `typeof islandPalette`; проверить: smoke-тест резолвит токен при палитре и не бросает без палитры.

## 2. Компоненты библиотеки

- [x] 2.1 `ThemeButton.qml` — экстракция 1:1 из `LauncherRoot.ThemedButton` (свойство `accentBackground`, hover/pressed из `color.accent.hover/pressed`, `skinned`-флаг, оф-скин = `background.visible: false`); проверить: green позже группами 3–4 (поведение + пиксель).
- [x] 2.2 `ThemeField.qml` (TextField: bg `color.bg.canvas`, border `color.border`, border в фокусе `color.accent`; оф-скин — базовый Basic); проверить: группой 4 (пиксель/поведение).
- [x] 2.3 `ThemeCheckBox.qml` и `ThemeComboBox.qml` (индикатор/поле/выпадающий список по токенам; оф-скин — базовый Basic); проверить: группой 4.
- [x] 2.4 `TitleText.qml`/`HintText.qml` — роли title/hint теми же токенами шрифта/веса/цвета, что выдают фабрики `catalog.py`; проверить: пиксель exact-цвета внутри bounds текста обеими темами (группа 4).
- [x] 2.5 `CardPanel.qml` (bg/border/radius роли card) и `RowItem.qml` (строка списка из делегата лаунчера: selected → accent + accentFg); проверить: группой 4.

## 3. Лаунчер на библиотеке

- [x] 3.1 `LauncherRoot.qml`: `import nri.components`, удалить inline `ThemedButton` и делегат-разметку строки в пользу `ThemeButton`/`RowItem`, сохранить все `objectName`, `defaultButton`-маркер и сигнал `themeToggleRequested`; проверить: `python -m pytest tests/presentation/test_launcher_qml.py` зелёный без правок семантики тестов (включая islands-level pixel проверки).
- [x] 3.2 Убедиться, что Python-обёртка `GameLauncherDialog` не изменилась; проверить: `git diff` по `app/presentation/views/game_launcher_dialog.py` пуст, `test_launcher_viewmodel.py` зелёный.

## 4. Приёмка библиотеки

- [x] 4.1 Галерея `tests/presentation/qml_components_gallery.qml` (все компоненты с `objectName`) + загрузчик в `test_qml_components.py` на общем движке и оффскрин-backend (паттерн `qml_helpers.py`); проверить: smoke-загрузка `errors()` пуста.
- [x] 4.2 Пиксельные тесты по каждому темизируемому компоненту для обеих тем (фон/рамка/текст — совпадение с hex токена; текст — наличием exact-пикселя в bounds, без golden); проверить: тесты зелёны в обеих темах.
- [x] 4.3 Live-retheme галереи (переключение темы палитрой → пиксели новой темы без пересоздания острова); проверить: тест зелёный.
- [x] 4.4 Off-skin: пустые/битые токены и отдельный прогон вовсе без `islandPalette` в контексте — скина нет, `errors()` пуста, клик/ввод/фокус работают; проверить: оба теста зелёны.
- [x] 4.5 Расширить скан `tests/presentation/test_no_chrome_hex.py` на `tokens.js` (и прочие js библиотеки): ни hex, ни палитры ОС; planted-violation-тест для js; проверить: скан зелёный и не empty-guard.

## 5. Пакетирование

- [x] 5.1 `nri_manager.spec`: добавить в `datas` по образцу `LauncherRoot.qml` все файлы модуля (`qmldir`, каждый `*.qml`, `tokens.js`); проверить: бандл-тест ниже проходит на анализе spec-файла.
- [x] 5.2 Расширить `tests/test_spec_qml_bundle.py`: Presence `nri/components/qmldir` и файлов компонентов в ожидаемом бандл-дереве; проверить: тест зелёный.
- [x] 5.3 Локальная проверка сборки (`python build_app.py`) на текущей ОС и запуск собранного лаунчера/главного окна — QML-острова поднимаются из бандла (модуль резолвится); зафиксировать результат в PR-описании.

## 6. Контроль

- [x] 6.1 Полный прогон `QT_QPA_PLATFORM=offscreen python -m pytest` — всё зелёное, гейт 100%-покрытия Python-половины пройден.
- [x] 6.2 Запись в `docs/CHANGELOG.md` (Q2a1, эпик Q открыт; без миграций), обновление статусов `docs/design-system-roadmap.md` (путь каталога `nri/components/` и статус Q2a1) после мержа.
