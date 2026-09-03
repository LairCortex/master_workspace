# Proposal: add-qml-component-library-q2a1

## Why

Q1 поднял QML-каркас и пилот лаунчера, но компоненты лаунчера остались стилизованы inline в `LauncherRoot.qml`; Q1 прямо отложил qmldir-модуль («модульность — Q2»). Q2a2/Q2b переводят в QML ещё восемь экранов: без общей библиотеки каждый остров повторит стилизацию кнопки/поля/карточки — это «третья копия стилей» в qml, против которой вся карта. Q2a1 закрывает фундамент, на котором все последующие острова пишутся только поверх библиотеки.

## What Changes

- Вводится qmldir-библиотека компонентов `app/presentation/qml/nri/components/`, модуль `nri.components` (импорт через существующий `engine.addImportPath()`): `ThemeButton`, `ThemeField`, `ThemeCheckBox`, `ThemeComboBox`, `TitleText`, `HintText`, `CardPanel`, делегат-стиль строки списка; единый skinned/off-skin паттерн (скин — из `islandPalette`, оф-скин — только именованные Qt-глобалы, без hex и без палитры ОС).
- `ThemeButton` выносится из `LauncherRoot.qml` один-в-один по поведению; `LauncherRoot.qml` рефакторится на библиотеку без изменения внешнего вида, сигналов и objectName-контрактов (семантика тестов `test_launcher_qml.py` сохраняется, виджеты не возвращаются).
- Библиотека потребляет единственный источник токенов — `QmlPalette` (context property острова); производные цвета продолжают считаться Python-компилятором; никакого вычисления цвета в JS.
- PyInstaller-бандл дополняется поставкой qmldir-каталога модуля; бандл-тест по образцу `test_spec_theme_bundle.py` проверяет загрузку модуля из собранного дерева.
- Пиксельная приёмка (grab + пиксель = hex токена) переносится на компоненты библиотеки (обе темы + оф-скин); это единственное место pixel-тестов в Q2 (новым островам — семантика + live-retheme, по роадмапу; islands-level пиксельные проверки Q1 не ослабляются).
- Сканирование `test_no_chrome_hex` уже рекурсивно покрывает `app/presentation/qml/**/*.qml` — новые файлы библиотеки попадают автоматически; скан расширяется на js-файлы библиотеки (`tokens.js`).

## Capabilities

### New Capabilities

- `qml-components`: библиотека переиспользуемых QML-компонентов chrome — набор, контракт токенов, skinned/off-skin поведение, пиксельная приёмка компонентов.

### Modified Capabilities

- `qml-shell`: требование «Размещение qml-файлов и поставка» — qmldir-модуль больше не запрещён: библиотека поставляется как модуль через import-путь движка и включается в PyInstaller-бандл; direct-загрузка корневых файлов островов остаётся допустимой.

## Impact

- `app/presentation/qml/nri/components/` (новый каталог: qmldir + компоненты + `tokens.js`), `app/presentation/qml/LauncherRoot.qml` (рефактор на библиотеку), `app/presentation/qml/engine.py` (без изменений кода — существующий import-путь уже покрывает подкаталог; фиксируется тестом).
- `nri_manager.spec`: qml кладётся в datas поштучно (Q1) — добавить файлы модуля `nri/components/` (qmldir, qml, js) и расширить `tests/test_spec_qml_bundle.py`.
- Тесты: новые `tests/presentation/test_qml_components.py` (pixel/roles), расширение `tests/presentation/test_no_chrome_hex.py`, `test_launcher_qml.py` — без ослабления семантики.
- Follow-up'ы: все последующие Q2-экраны обязаны использовать библиотеку; менять `tokens.json` здесь не требуется (существующих токенов достаточно; имена — существующие ключи).
- W-слой (`catalog.py`, QSS) не трогается; widgets-код лаунчера не возвращается.
