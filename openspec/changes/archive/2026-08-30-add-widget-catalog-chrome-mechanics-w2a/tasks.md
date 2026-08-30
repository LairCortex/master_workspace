## 1. Токены и компилятор

- [x] 1.1 Добавить в `app/presentation/theme/tokens.json` читаемые токены (`color.status.ok`, `font.size.lg`, `font.size.xl`) с парами light/dark и внести их в `REQUIRED_TOKEN_KEYS` в `compiler.py`; `color.rating.low/high` и `color.font.family.mono` в куске не заводятся (ревью: читателя нет → мёртвый обязательный токен) и перенесены в W2b; проверить `python -m pytest tests/presentation/test_theme_compile.py` (валидный файл грузится)

- [x] 1.2 Написать падающий тест «удаление любого обязательного токена (включая новый каталожный) делает набор невалидным целиком» и сделать его зелёным (валидатор уже проходит по `REQUIRED_TOKEN_KEYS` — убедиться, что новые ключи покрыты параметризацией); `python -m pytest tests/presentation/test_theme_compile.py -k required`

- [x] 1.3 Переписать `compile_qss()` на `[uiRole="chrome"]`/`[uiRole="menu"]`-селекторы вместо `#themeChrome`/`#themeMenu`, добавив правила ролей каталога: `[uiRole="title"]` (`font.size.lg`/bold, `[uiRoleSize="xl"]` → `font.size.xl`), `[uiRole="hint"]` (`color.fg.muted`, `[uiRoleItalic]` → italic), `[uiRole="field"]`, `[uiRole="list"]` (surface/border/padding + `::item:selected` → accent/accent.fg), `[uiRole="card"]` (surface/border/radius), `[uiRole="status-ok"]` → `color.status.ok`, `[uiRole="status-error"]` → `color.danger`; правила button оставить под `[uiRole="chrome"]`, добавив hover/pressed; тесты генераторов light/dark в `test_theme_compile.py` зелёные

- [x] 1.4 Вынести правила top-level попапов (`QToolTip`, `QMenu`, `QComboBox QAbstractItemView`, `QCalendarWidget`, `_MentionPopup` + `MentionPopupListView`) в новую функцию `compile_popup_qss(tokens, theme)`; `QMenu` убрать из chrome-листа; правила `QMenu::item:hover` нет (наведённый пункт уже `:selected`, hover-слой размывал accent-выделение — ревью); юнит-тест: popup-лист содержит правила для всех категорий, chrome-лист — не содержит `QToolTip`; `test_theme_compile.py` зелёные

- [x] 1.5 Добавить helper `accent_rgba(tokens, theme, alpha)` (hex токена → `rgba(r, g, b, a)`) и применить для hover/pressed/selected-выделения; тест: значение совпадает с ожидаемым rgba из accent-токена обеих тем

- [x] 1.6 Перевести `game_launcher_dialog.py` и `main_window.py` с objectName-механизма на роли (`attach_theme`/`set_role`, objectName оставить где он идентификатор, не стиль); существующие `test_theme_apply.py` + сборка приложения (`QT_QPA_PLATFORM=offscreen python -m pytest`) зелёные

## 2. Runtime: app-wide popup-лист

- [x] 2.1 В `ThemeRuntime` добавить `attach_app(app)` (weakref на `QApplication`) и постановку `compile_popup_qss` в `apply()`: лист пересобирается при `set_theme()`, при невалидных токенах — пустая строка (off-skin); при отсутствии app (тесты без QApplication) — no-op; юнит-тесты в `test_theme_apply.py`

- [x] 2.1.1 (ревью) Дедуплицировать постановку листа: `apply()` сравнивает собранный popup-лист с `app.styleSheet()` (и QSS с `widget.styleSheet()`) и не вызывает `setStyleSheet` без изменения текста; тесты: повторный `apply()` — один push, смена темы и внешняя замена листа — push снова, unchanged QSS не перестилизует зарегистрированный виджет

- [x] 2.2 Передать `QApplication` в runtime из `Application.__init__` (`app/main.py`); проверить ручным запуском `QT_QPA_PLATFORM=offscreen python -m app.main` (не падает) + полный pytest зелёный. Ревью: безусловный push листа давал ×6 деградацию и зависание полного offscreen-прогона — после 2.1.1 A/B `tests/ui/test_char_sheets_wiring.py` вернулся к базовой линии (23.8 с → 9.3 с)

## 3. Каталог виджетов

- [x] 3.1 Создать `app/presentation/theme/catalog.py`: `attach_theme(widget)` (роль chrome/menu + `unpolish/polish` + `ThemeRuntime.register`), `set_role(widget, role, *, size=None, italic=False)`, фабрики `title(text, *, size="md")`, `hint(text, *, italic=False)`; докстринги в стиле соседних модулей; smoke-тесты (свойства выставлены, повторный `attach_theme` идемпотентен) в новом `tests/presentation/test_theme_catalog.py`

- [x] 3.2 Regression-тест «вложенный виджет без роли правилами не перекрашен» и «подключённый экран live-перекрашивается через `set_theme()` без пересоздания виджетов» (grab пикселя до/после); зелёные в `test_theme_catalog.py`

## 4. Пилоты

- [x] 4.1 `month_settings_dialog.py`: подключить корень через `attach_theme`, hint-лейблы через фабрику `hint()` (курсивный модификатор), удалить inline `color: #888`; E2E-пиксель: hint == `color.fg.muted` текущей темы, край диалога == токен фона (не палитра ОС) — тест в `tests/presentation/` по образцу лаунчер-пиксельного теста W1

- [x] 4.1.1 (ревью) Вернуть зазор 6px под hint в `MonthSettingsDialog` (`HINT_BOTTOM_GAP`, правка layout, а не универсального hint-правила) — он был в inline-стиле до каталога; пиксельный тест пинит расстояние hint → первое поле

- [x] 4.2 `world_snapshot_widget.py`: `attach_theme`, title `md` из токенов, «Показать» — обычная chrome-кнопка (удалить `#2d5a88`/hover), дерево и `stats`-лейбл — роли `list`/`hint` (вместо `#999` и `font-size: 11px`), императивные `palette()` в chrome убрать; пиксельные E2E: кнопка == `color.accent`, заголовок == `color.fg.primary` при `font.size.lg`; зелёные в обеих темах

- [x] 4.3 Для `_MentionPopup` ввести именованный класс списка (`MentionPopupListView(QListWidget)`) и удалить его inline-таблицу стилей — оформление берёт popup-лист; пиксельный E2E: элемент списка выделен → `color.accent`, фон попапа == `color.bg.surface`; зелёный offscreen-тест

- [x] 4.3.1 (ревью) Закрыть и фон **контейнера** попапа: правило `_MentionPopup` в popup-листе + `WA_StyledBackground` на контейнере; пиксельный E2E снимает полосу под списком (там список не заполняет попап → была палитра ОС)

## 5. Тестовые маркеры AI-кнопки

- [x] 5.1 В `ai_assist_button.py` выставить маркер `setProperty(AI_STATE_PROPERTY, AI_STATE_ACTIVE/AI_STATE_DISABLED)` и единственный способ его прочитать — `ai_state_is()`. `QObject::testProperty` protected и PySide6 его не экспортирует (`hasattr(QWidget, 'testProperty') == False`), поэтому формулировка «+ testProperty» реализована эквивалентной проверкой в хелпере: маркер объявлен среди dynamic properties и равен значению. Перевести e2e-тесты, которые grep-ают rgba-подстроки, на маркер + пинить согласованность маркера и стиля во всех ветках `EntityGenerateButton`; pytest зелёный; сами цвета rgba в этом куске не менять (миграция — W2b)

## 6. Документация и приёмка

- [x] 6.1 Обновить `docs/CHANGELOG.md` (пометка: эпик W открыт, W2b — следующий change, раздел «Исправлено (ревью W2a)») и строку/абзац W2 в `docs/design-system-roadmap.md` (механика/каталог сделаны в W2a; статус — «реализован, ждёт коммита/мержа и архивации», не «влито»); `QT_QPA_PLATFORM=offscreen python -m pytest` полностью зелёный (1795 passed) — итоговая приёмка куска

- [x] 6.2 (ревью)Страж обязательных токенов: тест «каждый `REQUIRED_TOKEN_KEYS` реально читается» (значение входит в собранный QSS либо в `var()` тела `app.css`) — мёртвый токен больше не пройдёт
