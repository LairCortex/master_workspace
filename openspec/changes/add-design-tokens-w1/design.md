## Context

См. `proposal.md`. Grill: `docs/design-system-roadmap.md` (W1). Сейчас нет QSS-файла: палитра ОС + hex в виджетах и статике `table_host/web/app.css` (`FileResponse` / `add_static`). LLM-конфиг уже глобальный (`~/.nri_manager/llm_config.json`); календарь — `game_settings`. Лаунчер — `QDialog` до выбора игры. Спеки: `ui-theme`, `character-sheet-host`.

## Goals / Non-Goals

**Goals:**

- Один JSON → QSS (Qt chrome) и CSS (`:root` + var на landing/toolbar/status).
- Тема переживает рестарт; стол отдаёт CSS текущей темы мастера на GET.
- Не протечь QSS в parented-диалоги.

**Non-Goals:**

- Обёртки контролов, скины остальных окон, QApplication.setStyleSheet на всё приложение.
- CSS variables внутри QSS (Qt ненадёжен) — в QSS литералы из токенов.

## Decisions

### D1. Формат `tokens.json`

Объект: ключ semantic-роли → `{ "light": "<css-value>", "dark": "<css-value>" }`. Без слоя primitives (grill Q3=B).

Минимум W1 (имена фиксируем здесь; hex можно подкрутить при apply, имена — нет):

| ключ | роль |
|---|---|
| `color.bg.canvas` | фон chrome |
| `color.bg.surface` | панели / landing |
| `color.fg.primary` | основной текст |
| `color.fg.muted` | вторичный текст |
| `color.border` | рамки chrome |
| `color.accent` | акцент кнопок chrome |
| `color.accent.fg` | текст на акценте |
| `color.danger` | `#status.error` на вебе |
| `space.xs` / `space.sm` / `space.md` | отступы |
| `radius.sm` | скругление |
| `font.size.md` | кегль chrome |
| `font.weight.bold` | жирный |

CSS custom property: точка → дефис, префикс `--` (`color.bg.canvas` → `--color-bg-canvas`). Бумага листа: литералы в `app.css` (`#fff`, рамки полей), не `var(--color-bg-canvas)`.

Альтернатива `{light:{...}, dark:{...}}` с дублированием ключей — отвергнута (легко разъехаться имена).

### D2. Генератор в памяти

Python читает JSON и собирает две строки: QSS (литералы) и CSS (`:root { … }` + тело `app.css`). Вызов при старте и при смене темы. Не коммитить выход, не писать на диск (не портить бандл).

Альтернатива: шаблоны `.qss.tpl` — второй исходник. CI-codegen — дубли в git.

### D3. Preference `ui.json`

`~/.nri_manager/ui.json`, поле `theme`: `"dark"` | `"light"`. Менеджер по образцу `LlmConfigManager` (отдельный файл, `chmod 0600` при записи). Нет файла / битый JSON / не-UTF-8 байты / неизвестное значение → `"dark"` (`UnicodeDecodeError` — subclass `ValueError`, ловится вместе с `json.JSONDecodeError`; иначе бинарный файл роняет старт). Имена тем — один источник: `app/domain/theme.py` (`THEMES`, `DEFAULT_THEME`), его импортируют и preference, и компилятор токенов (иначе разъедутся в W2). Не смешивать с `llm_config.json`.

Рантайм читает preference **один раз** при старте и держит значение в памяти: `qss()`/`css()` вызываются на каждую перекраску и на каждый `GET /app.css`, менять его может только `set_theme()`.

Тесты monkeypatch пути, как `tmp_llm_config`; корневой `tests/conftest.py` автофикстурой редиректит `CONFIG_FILE` в `tmp_path` и сбрасывает process-wide синглтон, чтобы тесты не трогали реальный `~/.nri_manager/ui.json`.

### D4. Куда вешать QSS

Не `QMainWindow.setStyleSheet` и не `QApplication.setStyleSheet`.

- Лаунчер: внутренний `QWidget` (`objectName` `themeChrome`) на весь layout; `setStyleSheet` только на него. `QMessageBox`/`QInputDialog` с parent=диалог — не потомки `themeChrome`. Внешний `QVBoxLayout` диалога — отступы 0: дефолтные 11 px показали бы палитру ОС рамкой вокруг chrome (grab-тест пикселя внутри chrome этого не видит, поэтому приёмка меряет и угол `dlg.grab()`).
- MainWindow: `setStyleSheet` на `centralWidget()` (`themeChrome`) и на `menuBar()` (`themeMenu`). Statusbar — если появится. Селекторы вида `QWidget#themeChrome QPushButton`, не `QMainWindow QPushButton`.
- `QToolTip` в QSS нет: тултип — top-level попо-ап без родителя-потомка chrome, правило не сработало бы никогда. Тултипы — W2 (нужен app-wide лист).

Inline `setStyleSheet` title лаунчера в W1 не переводим на обёртки (остаток W2).

Альтернатива: сбрасывать stylesheet на каждом `QDialog` — скрытый W2.

### D5. Тумблер

Лаунчер: `QPushButton` с подписью-переключателем («Светлая тема»/«Тёмная тема») на chrome. MainWindow: меню «Настройки» — checkable `QAction` «Светлая тема», галка = светлая активна. Оба пишут `ui.json` и зовут один `apply` на зарегистрированные chrome-виджеты.

Состояние обоих переключателей синхронизируется подпиской на рантайм (`add_listener`, слабая — D10), а не опросом: лаунчер живёт поверх уже открытого MainWindow (`Сменить игру`), и смена темы в лаунчере обязана пересинхронизировать галку меню (и наоборот). Checkable-действие при клике меняет свой чек само — при no-op (D7) хендлер обязан вернуть состояние обратно, иначе галка врёт.

### D6. D1 `GET /app.css`

`index.html` линкует `/app.css`, не `/static/app.css`. Хендлер: скомпилированный `:root` текущей темы + содержимое исходного `app.css` (var только у `#landing`, `#toolbar`, `#status.error` и связанных chrome-правил). `add_static` для JS остаётся. Исходный `app.css` в репозитории — с `var()`, без запечённой темы.

Исходник `app.css` не должен оставаться вторым (мёртвым) исходником: явный маршрут `/static/app.css` зарегистрирован до `add_static` и отдаёт тот же собранный CSS, иначе по старому URL кто угодно получит chrome без цветов (неразрешённые `var()`).

Рантайм в хост **инжектится** (`create_table_host_app(theme=...)`); фолбэка «взять process-wide синглтон» нет — он молча читал бы реальный `~/.nri_manager/ui.json` владельца процесса. Без рантайма — `500`.

Хендлер берёт CSS из того же theme-runtime, что Qt (не второй компилятор). Стол без игры не отдаёт fill, но тема всё равно глобальная — если HTTP поднят, CSS = текущий preference.

Альтернатива: инлайн в HTML — хуже кэша; перезапись файла на диске — ломает frozen.

### D7. Битые токены

Загрузка JSON: отсутствие ключа / не объект `{light,dark}` / файл не читается (нет, не-UTF-8) → невалидно целиком. Лог + флаг; `apply` no-op; тумблер не пишет осмысленный QSS (preference писать можно, но визуал не меняется, пока токены снова валидны — проще: тумблер no-op и не пишет, как grill). Grill: тумблер no-op.

Веб-сторона (не grill-илась, фиксируем решение здесь): `css()` при невалидных токенах возвращает **пустое** тело — тело `app.css` с неразрешёнными `var()` было бы «таблицей стилей без цветов», то есть тем же half-broken выводом, которого D7 избегает на Qt-стороне.

### D10. Жизненный цикл реестра рантайма

`ThemeRuntime` — process-wide синглтон, переживающий диалоги; `GameLauncherDialog` пересоздаётся на каждую смену игры. Поэтому реестр chrome-виджетов хранит **слабые** ссылки (`weakref`) + `unregister`, а мёртвые записи вычищаются на `apply()` (`registered` — публичный срез живых). Сильные ссылки держали бы каждый закрытый лаунчер живым и перекрашиваемым. Подписчики смены темы — тоже слабые (`weakref.WeakMethod` для bound-методов).

Альтернатива — явный `closeEvent`/`deleteLater`-хук в каждом окне: больше мест забыть, и окно всё равно живёт ровно столько, сколько на него есть ссылка.

### D8. Frozen

`nri_manager.spec` `datas`: `app/presentation/theme/tokens.json` → тот же относительный путь. Чтение: `Path(__file__).parent / "tokens.json"` (как пресеты/шрифты в `_MEIPASS`).

### D9. Тесты grab

Offscreen: показать chrome-виджет, `processEvents`, `grab()`, пиксель внутри `themeChrome` → `QColor` равен hex `color.bg.canvas` текущей темы. Light и dark. Без PNG-эталонов. Допуск 0: токены — непрозрачный hex.

## Risks / Trade-offs

- [Offscreen grab пустой/чёрный] → в тесте `show()` + `qtbot.waitExposed`; если платформа врёт — падать явно, не ослаблять до «stylesheet содержит hex» как единственную проверку UI (генератор уже покрыт отдельно).
- [Часть MainWindow (search/timeline) с собственным hex] → W1 красит контейнер; локальные stylesheet потомков могут перекрыть. Не чистить в W1.
- [Игрок с тёмным chrome и белой бумагой] → намеренный контракт, не баг.

## Migration Plan

Нет миграции БД. Старые инсталлы без `ui.json` → dark. Откат: удалить apply QSS, вернуть статику `/static/app.css` (потеря var).

## Open Questions

Нет.
