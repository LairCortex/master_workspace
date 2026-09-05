## 1. Фиксация DPR и guard

- [x] 1.1 В `tests/conftest.py` у импорта (блок рядом с `QT_QUICK_BACKEND`) задать `QT_ENABLE_HIGHDPI_SCALING=0`, `QT_AUTO_SCREEN_SCALE_FACTOR=0`, `QT_SCREEN_SCALE_FACTORS=1`, `QT_SCALE_FACTOR=1` с комментарием why (детерминизм grab на Retina-хостах, приёмка spec ui-testing «Пиксельная приёмка при зафиксированном коэффициенте пикселей»); проверить: полный прогон зелёный на этой машине, прежние idiom'ы `_grab_scaled` не сломались
- [x] 1.2 В `tests/presentation/test_qml_shell_isolation.py` завести guard-тест: `QApplication.instance().devicePixelRatio() == 1` и grab виджета 64×64 даёт ровно 64 px по обеим осям (совмещает/заменяет захардкоженное предположение в `tests/test_qml_render_smoke.py:33`, если тот падает/проходит детерминированно); проверить: guard падает при ручном `QT_SCALE_FACTOR=2 python -m pytest tests/presentation/test_qml_shell_isolation.py -k device_pixel` и проходит в обычном прогоне

## 2. Детерминированный reset_qml_shell

- [x] 2.1 В `app/presentation/qml/engine.py` расширить `reset_qml_shell` по design D2 (условно при живом движке): `sendPostedEvents(None, DeferredDelete)` → `QTest.qWait(5)` → sweep top-level'ов `findChildren(QQuickWidget)`: `setSource(QUrl())` + `shiboken6.delete` → разрушение движка как раньше; докстринг фиксирует порядок «острова → движок» и причину (деструктор QQuickWidget обращается к движку); import'ы — только test-only-безопасные на месте использования
- [x] 2.2 Проверить регресс швов: прогнать семейства `tests/presentation/test_timeline_island.py`, `test_launcher_qml.py`, `test_character_sheet_*`, `test_qml_components.py`, `tests/test_qml_render_smoke.py` — падения вида SIGSEGV/RuntimeError в teardown отсутствуют, отложенные `_release_island` исполняются (тесты `qtbot.wait(20)`-пузы не сломаны)

## 3. Тесты изоляции (spec-сценарии)

- [x] 3.1 В `tests/presentation/test_qml_shell_isolation.py`: «Живой остров переживает сброс» — QQuickWidget на общем движке без close, ручной `reset_qml_shell()` в кадре теста → без исключения; `shiboken6.isValid(...)` объекта острова становится False; обращение к невалидной обёртке поднимает RuntimeError, а не рушит процесс
- [x] 3.2 Там же: «Отложенные релизы исполняются до смерти движка» — виджет с pending `deleteLater()` и диалог-оболочка с pending `singleShot(0, …)` освобождением переживают сброс без ошибок; после сброса C++-объекты уничтожены (`isValid` False / виджет скрыт+удалён), колбэк сработал при живом движке
- [x] 3.3 Там же: «Повторный setup после сброса» — после reset следующий `setup_qml_shell` даёт ровно один движок (count-assertion как в `test_qml_engine.py`), остров на новом движке рендерит и grab'ится

## 4. Приёмка детерминированности и финализация

- [x] 4.1 Три полных прогона подряд на этой машине (macOS/Retina, `QT_QPA_PLATFORM=offscreen`): `python -m pytest` без SIGSEGV, без «Object destroyed while…», без артефактов 2×128 против 64; счёт flake = 0
- [x] 4.2 Гейт покрытия: `python -m pytest --cov=app --cov-fail-under=100` — новые строки `reset_qml_shell` покрыты autouse-путём, исключений (`# pragma: no cover`) не добавлено
- [x] 4.3 В `docs/CHANGELOG.md` запись (эпик R открыт; R1 — врата островных тестов закрыты: детерминированный разрушительный порядок islands→engine→theme, DPR=1, guard) и в `docs/design-system-roadmap.md` статус куска R1 → «реализовано» по факту merge; `./ruff check app/ tests/` (если настроен как lint-gate — прогнать, иначе ruff job CI) зелёный
