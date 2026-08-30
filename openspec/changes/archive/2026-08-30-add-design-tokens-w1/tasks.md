# Tasks: add-design-tokens-w1

TDD. `QT_QPA_PLATFORM=offscreen python -m pytest`. Без внешней сети. Wrappers, остальные диалоги, канвас, QML, live-push темы — не делать.

## 1. Токены и генератор

- [x] 1.1 Тесты: разбор `tokens.json` (все ключи D1); light и dark QSS содержат разные `color.bg.canvas`; CSS `:root` с `--color-bg-canvas`; отсутствие файла / дырявый JSON → невалидно. Проверка: `tests/presentation/test_theme_compile.py` красные до 1.2.
- [x] 1.2 `app/presentation/theme/tokens.json` + компилятор в памяти (D1, D2, D7). Проверка: тесты 1.1 зелёные.

## 2. Preference

- [x] 2.1 Тесты: нет файла → dark; round-trip light; битый JSON → dark; запись `chmod 0600` (как LLM, POSIX). Проверка: `tests/infrastructure/test_ui_prefs.py` красные до 2.2.
- [x] 2.2 Менеджер `~/.nri_manager/ui.json` (D3), не `llm_config.json`. Проверка: тесты 2.1 зелёные.

## 3. Apply QSS на chrome

- [x] 3.1 Тесты: `QApplication.styleSheet()` и `MainWindow.styleSheet()` пустые; QSS на `themeChrome` / `menuBar`; QDialog с parent=MainWindow без этого QSS на себе. Проверка: `tests/presentation/test_theme_apply.py` красные до 3.2.
- [x] 3.2 Контейнер `themeChrome` в лаунчере; apply на centralWidget + menuBar MainWindow (D4). Проверка: тесты 3.1 зелёные.
- [x] 3.3 Тесты тумблера: лаунчер и меню «Настройки» пишут preference и меняют QSS; битые токены → тумблер no-op. Проверка: красные до 3.4.
- [x] 3.4 Wiring тумблера + apply при старте (D5, D7). Проверка: тесты 3.3 зелёные.

## 4. D1 CSS

- [x] 4.1 Тесты: `GET /` ссылается на `/app.css`; `GET /app.css` содержит `:root` текущей темы и `var(--` у landing/toolbar/status; `.page` без `var(--color-bg-canvas)`; смена темы → новый ответ без WS. Проверка: `tests/infrastructure/test_table_host_http.py` (доп. кейсы) красные до 4.2.
- [x] 4.2 Хендлер `/app.css`, `index.html`, `app.css` на var chrome (D6). Проверка: тесты 4.1 зелёные.

## 5. Бандл и grab

- [x] 5.1 Тест: `nri_manager.spec` `datas` содержит `app/presentation/theme/tokens.json`. Проверка: красный до правки spec, затем зелёный (D8).
- [x] 5.2 E2E: `grab()` `themeChrome` лаунчера и MainWindow, пиксель = hex `color.bg.canvas` dark и light (D9). Проверка: `tests/ui/test_theme_grab.py` зелёный offscreen.

## 6. Интеграция

- [x] 6.1 `QT_QPA_PLATFORM=offscreen python -m pytest` — весь набор зелёный.
- [x] 6.2 `docs/CHANGELOG.md`; в `docs/design-system-roadmap.md` W1 = влито (эпик W не закрыт). Проверка: `openspec validate add-design-tokens-w1 --strict`.

## 7. Ревью W1 (спека ↔ код ↔ CI-гейты)

- [x] 7.1 Тесты красные: не-UTF-8 `ui.json` → dark и старт без исключения; не-UTF-8 `tokens.json` → токены невалидны целиком; бинарный/отсутствующий `app.css` → пустой CSS; чек-пункт главного окна не отстаёт от тумблера лаунчера (и наоборот); мёртвый виджет выпадает из реестра; `GET /static/app.css` = собранный CSS; `/app.css` без инжектированного рантайма → 500; grab угла лаунчера = фон chrome. Проверка: красные до 7.2.
- [x] 7.2 Нечитаемое (в т.ч. побайтово битое) не роняет старт: `load()` → `except (OSError, ValueError)`, `load_tokens()` и `css()` → `+ UnicodeDecodeError`. Имена тем — один источник `app/domain/theme.py`. Проверка: 7.1 зелёные.
- [x] 7.3 Жизненный цикл рантайма: реестр chrome — слабые ссылки + `unregister` + `registered` (D10); подписка переключателей на смену темы; тема кэшируется в памяти вместо чтения `ui.json` на каждый `qss()`/`css()`. Проверка: тесты реестра/подписки зелёные.
- [x] 7.4 Хост: `/static/app.css` зарегистрирован до `add_static` и отдаёт собранный CSS; фолбэк «взять process-wide синглтон» убран → 500 без инжектированного рантайма; `css()` пуст при невалидных токенах. Проверка: тесты хоста зелёные.
- [x] 7.5 Нулевые внешние отступы лаунчера: grab угла диалога = hex токена фона (полосы палитры ОС нет). Мёртвое `QToolTip`-правило убрано из компилятора (D4). Проверка: grab-приёмка зелёная.
- [x] 7.6 Тестовая изоляция: автофикстура в `tests/conftest.py` редиректит `CONFIG_FILE` в `tmp_path` и сбрасывает синглтон; `main()` не лезет в приватное (`GameLauncherDialog(theme=...)` из явного `get_default_theme()`). Проверка: `pytest --cov=app` → 100% (гейт CI Run 1), `ruff check`, `openspec validate add-design-tokens-w1 --strict`.
