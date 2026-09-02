# Tasks: QML-каркас и пилот лаунчера (Q1)

> Порядок: каркас растёт снизу вверх (окружение → палитра → движок → VM → островок → сборка), каждая группа — падающие тесты сначала (TDD), затем зелёные. Приёмочные сценарии — из спеков `qml-shell`, `game-launcher`, `ui-theme` этого изменения.

## 1. Окружение и зависимости

- [x] 1.1 Поднять минимум PySide6 до `>=6.8` в `pyproject.toml`, обновить зависимости (`pip install -e ".[dev]"`) и прогнать `python -m pytest` — зелено
- [x] 1.2 В `tests/conftest.py` до первого импорта Qt выставить `QT_QUICK_BACKEND=software` (рядом с существующим порядковым комментарием), добавить смоук-тест: `QQuickWidget` с инлайн-QML (`Rectangle` заданного цвета) поднимается оффскрин и `grab()` даёт ожидаемый пиксель — тест зелёный локально; заодно фиксация факта работоспособности софтверного рендера (если `grab()` недоступен — включается запасной план спеки, решение фиксируется комментарием в conftest)

## 2. Мост токенов QmlPalette

- [x] 2.1 Падающие юниты `tests/presentation/test_qml_palette.py`: словарь палитры содержит ровно обязательные имена токенов `tokens.json`; производные (`accent_rgba`-аналоги hover/pressed/mention) присутствуют и совпадают с выводом компилятора QSS; при невалидном наборе токенов словарь пуст и изменений нет
- [x] 2.2 Реализовать `app/presentation/theme/qml_palette.py`: QObject с `Property(dict, notify=changed)`, подписка `ThemeRuntime.add_listener`, сборка словаря из компилятора; юниты 2.1 зелёные
- [x] 2.3 Юнит live-retheme: смена темы рантаймом → палитра эмитит `changed` и словарь содержит значения новой темы (обе темы, из валидной в валидную и валидные→невалидные при порче файла); зелёные

## 3. QML-движок приложения

- [x] 3.1 Падающий тест: после `Application.start()` существует ровно один `QQmlEngine`, импорт-путь включает `app/presentation/qml/`, стиль Controls = Basic (проверить `QQuickStyle.style()` до загрузки qml); импорт `qml-shell`-модуля в `conftest` не требуется
- [x] 3.2 Реализовать `app/presentation/qml/` (каталог) + точку каркаса (в `Application.start()`: `QQuickStyle.setStyle("Basic")`, создание движка, `addImportPath`, палитра в `contextProperties`); тест 3.1 зелёный; повторный вызов не создаёт второй движок (тест)

## 4. LauncherViewModel

- [x] 4.1 Падающие юниты `tests/presentation/test_launcher_viewmodel.py` (in-memory каталог через monkeypatch функций `game_manager`): `refresh()` заполняет `games` (имя, метка времени, путь; сортировка по времени изменения); `create(" Имя ")` обрезает, при коллизии бросает `FileExistsError` и состояние не меняет; `remove(path)` обновляет `games`; `import_(path)`/`archive_meta(path)` прокидывают `FileExistsError`/`ValueError` наружу; selection: `set_selected(index)`/`selected_path`, при сжатии списка выбор сбрасывается
- [x] 4.2 Реализовать `app/presentation/viewmodels/launcher_viewmodel.py` (QObject, property+Signal, синхронные методы поверх `game_manager`); юниты 4.1 зелёные; contract-тест: VM использует только sync-методы (проверка сигнатур — ни одного корутины)

## 5. QML-островок лаунчера

- [x] 5.1 `app/presentation/qml/LauncherRoot.qml`: заголовок-приглашение, `ListView` игр (строка `имя (дата_изменения)`, роль из палитры), ряд кнопок «Новая игра», «Импорт», «Удалить», «Открыть» (default), переключатель темы (подпись = тема-цель); у всех интерактивных элементов `objectName` (`gameList`, `newButton`, `importButton`, `deleteButton`, `openButton`, `themeToggleButton`); цвета/отступы — только из `palette`; smoke-падение: загрузка qml в `QQuickWidget` с test-палитрой даёт `status Ready` и все шесть `objectName` находятся
- [x] 5.2 Падающие e2e `tests/presentation/test_launcher_qml.py`: биндинг к списку VM (строки появляются/исчезают при обновлении VM без правок qml), выбор строки → `selected_path` VM, кнопка «Открыть» → сигнал острова с путём; тест «островок поверх реальной `LauncherViewModel` без правок VM» (доказательство контракта спеки)
- [x] 5.3 Пиксельная приёмка острова: пиксель фона = `color.bg.surface`, пиксель акцента кнопки = `color.accent` (обе темы; по конвенции grab+pixel, без golden); смена темы рантаймом → повторный grab равен новой теме без пересоздания острова; оф-скин (пустая палитра) — остров грузится, контролы базового вида, исключений нет

## 6. QDialog-обёртка и контроллер

- [x] 6.1 Падающие e2e контракта (перенос существующих сценариев на новый адрес): старт без выбора (Esc) → `selected_path is None`, сигнал не издан; выбор + Enter/«Открыть» → `game_selected(path)`, `accept()`; создание: `QInputDialog` (monkeypatch ответа) с пустым/отводом — no-op, коллизия — `QMessageBox.warning` и диалог открыт, успех — новая игра в списке и сразу `game_selected`; удаление: подтверждение с дефолтом «Нет», «Да» → удаление+refresh, лаунчер открыт; импорт: `QFileDialog`+подтверждение с метаданными, успех → refresh+`QMessageBox.information`, `FileExistsError`/`ValueError` → warning, лаунчер открыт; стартовая подпись переключателя темы и её синхронизация после чужой смены темы
- [x] 6.2 Перестроить `app/presentation/views/game_launcher_dialog.py`: QDialog-обёртка (тот же заголовок/min-size) + `QQuickWidget` с `LauncherRoot.qml` + VM в context объекта острова; контроллер-слушатель `*Requested` поднимает нативные попапы, зовёт VM, эмитит `game_selected`; удалить widgets-содержимое (список/кнопки/attach_theme содержимого); тесты 6.1 зелёные, `GameLauncherDialog(game_selected, selected_path)` контракт не изменился
- [x] 6.3 Правки потребителей в `app/main.py`: стартовый поток и `_on_switch_game` проходят как раньше (пройтись по существующим `tests/ui/` e2e: создание игры, открытие, переключение — зелёны без смены семантики); убрать QSS-подключение содержимого лаунчера (Spec ui-theme дельта: «Содержимое лаунчера не красится QSS»)
- [x] 6.4 Обновить/сохранить существующие тесты темы лаунчера в `tests/presentation/test_theme_apply.py` (переезд сценариев переключателя и лаунчера на палитру вместо QSS) — зелёные, включая сценарий ui-theme «Смена из главного окна при открытом лаунчере»

## 7. Инварианты и зачистка

- [x] 7.1 Расширить `tests/presentation/test_no_chrome_hex.py` (или параллельный тест) на `app/presentation/qml/**.qml`: ни hex-литералов, ни цветов вне палитры; оф-скин — именованные Qt-глобалы; зелёный
- [x] 7.2 Прогнать весь `python -m pytest` с гейтом 100%-покрытия — зелёный без новых дыр (весь новый Python-код покрыт)

## 8. Сборка (PyInstaller)

- [x] 8.1 Падающий тест `tests/test_spec_qml_bundle.py` по образцу `test_spec_theme_bundle.py`: `.spec` содержит qml-каталог в `datas` и hiddenimports `QtQuick`, `QtQuickControls2`, `QtQuickWidgets`/qml-плагины — по образцу существующего теста (парсинг spec-файла)
- [x] 8.2 Дополнить `nri_manager.spec` (`datas` — `app/presentation/qml`, hiddenimports Quick-модули; qml-плагины Qt проверить через хуки PyInstaller — факт фиксации в тесте/комментарии); тест 8.1 зелёный
- [x] 8.3 Локальная сборка `python build_app.py --clean` на текущей ОС и запуск бандла: лаунчер (QML) стартует и открывает игру — чек-лист прогона в тексте PR/коммита

## 9. Приёмка на трёх ОС

- [x] 9.1 CI-прогон (push): pytest на трёх ОС зелёные; зафиксировать, на каких ОС работает пиксельная приёмка (спека допускает деградацию до property-проверок не более чем на одной ОС); итоговый статус CI — до merge
- [x] 9.2 Ручная приёмка стартового потока на своей ОС (QML-лаунчер: список, создание, удаление, импорт, переключение темы живьём, переключение игры из главного окна) + запись в `docs/CHANGELOG.md` с пометкой «эпик Q, база» и обновление версии по конвенции (pyproject + spec plist + CHANGELOG)
