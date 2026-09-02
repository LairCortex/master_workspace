# Приёмка Q1 на macOS (task 9.2, change `add-qml-shell-launcher-pilot-q1`)

ОС: macOS 26.5.2 arm64 (Apple Silicon), Python 3.12.10, PySide6 6.10.2, `QT_QPA_PLATFORM=offscreen`, `QT_QUICK_BACKEND=software`.
Дата: 2026-09-02. Метод: машинно-воспроизводимая приёмка стартового потока без интерактивных окон —
скриптовые сессии на **реальных объектах приложения** (offscreen), плюс вход `python -m app.main`
без правок, плюс уже зелёные e2e/suite-прогоны. Каталог игр, тему-_prefs_ и архив приёмка
держало во временных каталогах; реальные `games/` и `~/.nri_manager` не изменены (проверено md5/ls до и после).

Реальные объекты: `GameLauncherDialog` (QDialog-обёртка + живой `QQuickWidget` с `LauncherRoot.qml`),
`LauncherViewModel` поверх настоящего `game_manager` (файлы на диске), `ThemeRuntime` с настоящим `tokens.json`,
`Application` + `MainWindow`. Мокапами подменялись только модальные convenience-попапы
(`QInputDialog.getText` / `QMessageBox.*` / `QFileDialog.getOpenFileName`) — оффскрин-платформа
не может крутить живые модальные циклы; обработчики, VM, диалог и остров при этом настоящие.
Пиксельные проверки: `grab()` + hex токенов (обе темы), без golden.
Скрипт приёмки — одноразовый (offscreen, временные каталоги); шаги и вывод зафиксированы ниже, а класс-регресс
найденного дефекта осел в репозитории (`tests/presentation/test_views.py::TestGameLauncherDialog::test_real_island_click_open_survives_and_releases_island`).

## Чек-лист стартового потока — evidence

| # | Пункт | Как проверялось | Доказательство (вывод скрипта) |
|---|-------|-----------------|--------------------------------|
| 1 | Список | `GameLauncherDialog` на засечённом каталоге (`Альфа`, `Бета`), чтение QML-делегатов `gameRowText` живого острова | island `Ready`; строки `['Бета (2026-09-02 20:44)', 'Альфа (2026-09-02 20:44)']` — «имя (дата_изменения)», newest-first |
| 2 | Удаление | `QTest`-клик по QML-строке (selection → `vm.selected_path`), `QTest`-клик `deleteButton`, stub-ответ «Да» | каталог на диске без `Бета`, QML-список сжался до `['Альфа (… )']`, диалог остался открыт; подтверждение: `question[Удаление игры] default=No… «необратимо»` |
| 3 | Импорт | настоящий `export_game` → `.nri` вне каталога, `QTest`-клик `importButton`, stub-пикер + «Да» | `Импорт игры` подтверждение содержит имя/версию/дату меты, игра материализовалась (`ЭкспортДонор/game.db`), строка появилась в QML, `information` об успехе; диалог открыт |
| 4 | Тема живьём | `QTest`-клик `themeToggleButton` на живом диалоге, пиксели **того же** `QQuickWidget` до/после, обратно; prefs во tmp | dark→light: surface `(42,42,50)→(255,255,255)`, accent кнопки `(185,134,60)→(122,90,30)` = hex токенов, подпись переключателя = тема-цель, `rootObject` тот же (остров не пересоздан), prefs `{"theme":"light"}`; обратный клик — все пиксели обратно |
| 5 | Создание (+авто-открытие) | `QTest`-клик `newButton`, stub-ответ « Q1 Приёмка » | игра создана без пробелов `games/Q1 Приёмка/game.db`, `game_selected` издан, диалог `Accepted`; `Application.start()` на этом пути → заголовок `'НРИ Сценарий Менеджер — Q1 Приёмка'` |
| 6 | Переключение игры из главного окна | `switch_game_action.trigger()` из открытого `MainWindow`, лаунчер-на-окне: QML-выбор строки + клик `openButton` | заголовок нового окна `'НРИ Сценарий Менеджер — ЭкспортДонор'`, старое окно скрыто, список лаунчера `['Q1 Приёмка (…)','ЭкспортДонор (…)','Альфа (…)']` |
| 0 | Один движок на приложение | сравнение `Application._qml_engine` и движка острова стартового лаунчера | идентичны (`Application.qml_engine is launcher._engine` → True) |

Проходом подтверждены и ранее зелёные тематические e2e: `tests/presentation/test_theme_apply.py`
(включая ui-theme «Смена из главного окна при открытом лаунчере» — пиксельно, `test_main_window_toggle_repaints_open_launcher`),
`tests/ui/test_e2e_launcher.py` (создание/открытие/переключение), `tests/presentation/test_launcher_qml.py`
(пиксельная приёмка острова и live-retheme), `tests/test_qml_render_smoke.py` (software-рендер).

## Дефект, найденный приёмкой (исправлен в этом change)

**Симптом:** `QTest`/реальный клик по QML-кнопке, путь которой доходит до `accept()`
(«Открыть», даблклик строки, «Новая игра» → создать-и-открыть), завершался SIGABRT:
`Object … destroyed while one of its QML signal handlers is in progress … LauncherRoot.qml:229/202`.

**Причина:** `GameLauncherDialog.done()` синхронно звал `quick.setSource(QUrl())`, уничтожая QML-сцену
внутри стека собственного `onClicked`-обработчика острова. Тесты дефект не ловили, потому что все сценарии
эмитили `vm.*Requested` из Python (без стека QML-обработчика); QML-клики в тестах были только на изолированном
островке без диалога.

**Фикс:** освобождение острова отложено на следующий оборот цикла (`QTimer.singleShot(0, self, _release_island)`);
таймер с контекстом-диалогом не срабатывает после его гибели; семантика «остров освобождён, пока VM/палитра живы»
сохранена. Регресс: `TestGameLauncherDialog::test_real_island_click_open_survives_and_releases_island`
(реальный `QTest.mouseClick` + ожидание `quick.source().isEmpty()` — до фикса строка-ожидание была недостижима,
процесс умирал на клике). После фикса repro выживает (`selected_path` выставлен, `result == Accepted`).

## Реальный вход приложения (без правок)

`QT_QPA_PLATFORM=offscreen python -m app.main` с засеянной `games/q1-acc-seed/` — 15 с живой процесс
(лаунчер с QML-островом поднят; конструктор диалога assert'ит `status == Ready`), затем SIGTERM, rc=143.
stderr чист: только инфо `qt.qpa.fonts: Populating font family aliases took 37 ms …` (квирк оффскрин-окружения,
не приложение). stdout пуст. После: сид-игра удалена, `games/` = прежний снимок (`R.E.D.W.A.L.L/`, `супер дупер/`,
`супер дупер.db.bak-pre-migration`), `md5 ~/.nri_manager/ui.json` совпал до/после.

Примечание харнесса (не продукт): скриптовая сессия ставила `setQuitOnLastWindowClosed(False)` — между
accept лаунчера и показом первого `MainWindow` окно не видимо ни одного мгновения, и Qt-квит по
`lastWindowClosed` валил qasync-цикл; в реальном приложении промежуток закрыт модальным `exec()` лаунчера.
Часть взаимодействий 6-го шага доставлялась из `QTimer.singleShot`, чтобы `ensure_future` приложения
не входил в задачу посреди шага другой задачи (гард asyncio 3.12; живой клик приходит из OS-диспетчера, где гарда нет).

## Итоговые прогоны (macOS, после фикса)

- `QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q` → **2189 passed** (515 с), 0 failed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/ --cov=app` → те же 2189 passed; TOTAL **99.48%**
  (12547 stmts, 65 missing), гейт `fail_under=100` — **FAIL по pre-existing долгу**:
  `timeline_widget.py` 26, `wiring.py` 14, `timeline_rows.py` 7, `event_types_dialog.py` 7, `main.py` 4
  (строки 482, 485–487 — `git blame` = `deae72f7`, 2026-08-28, коммитленный код), `timeline_viewmodel.py` 3,
  `event_service.py` 3, `event_dialog.py` 1 = ровно 65; ни один из этих файлов change не трогает
  (`git diff --name-only` их не содержит). Новый код Q1 — 100%:
  `qml/__init__.py`, `qml/engine.py`, `theme/qml_palette.py`, `viewmodels/launcher_viewmodel.py`,
  `views/game_launcher_dialog.py` (104 stmts, 0 missing — фикс покрыт регрессом).
- Точечный набор приёмки (test_views launcher-класс + launcher_qml + theme_apply + e2e_launcher + render_smoke) — зелёный.

## Статус 9.1 (CI, три ОС) — вне этого сессии (нет push)

- CI-джоба `test` гоняет pytest **только на ubuntu-latest** (`.github/workflows/build.yml`); матрица трёх ОС
  (macos/windows/ubuntu) есть только для джобы `build`. «pytest на трёх ОС» текущим workflow не выполняется —
  нужно решение родител/ревьюеру: расширить матрицу test-джобы или переформулировать критерий приёмки.
- Ожидаемый цвет CI после push: **красный по гейту покрытия** по тем же 65 pre-existing строкам
  (локально на macOS воспроизведено: 99.48% < 100) — независимо от этого change.
- **Lint-джоба CI тоже падает на базе** (локально ruff 0.16.4: 21 ошибка — F401/E501/E741/E741 в коммитнутых
  файлах NRI-0009: `timeline_widget.py`, `event_types_dialog.py`, `test_timeline_*`, `test_event_types_*` и др.;
  каждый совпадает с `git diff --name-only` НЕ изменённым файлом). Файлы этого change — `ruff check` чистые.
  (CI ставит самый свежий ruff — точный набор может чуть отличаться, но baseline-файлы untouched.)
- Пиксельные QML-тесты: платформенных skip-условий в тестах нет (только два несвязанных POSIX-chmod skip
  в `test_ui_prefs`/`test_llm_config`); software-бэкенд+grab воспроизведены на macOS, на linux/windows — под
  подтверждением CI после push (запасной план спеки не активирован, решение зафиксировано комментарием в `tests/conftest.py`).
