## Context

W1 (влито, `openspec/changes/archive/2026-08-30-add-design-tokens-w1/`): `tokens.json` → `compiler.compile_qss()` по objectName-селекторам (`themeChrome`/`themeMenu`), `ThemeRuntime.register()/apply()/set_theme()` (weakref-регистры), тема в `~/.nri_manager/ui.json`, CSS `/app.css`. `QApplication.setStyleSheet` не вызывается нигде; тултипы/попапы недостижимы скоупом W1. Остатки инвентаризованы (37 `setStyleSheet`, палитрные `palette(mid/highlight)`, чужие hex `#2d5a88/#5b9bd5/#2e7d32/#c62828/#888/#999`). Мотивация — proposal.md; контракты — specs (`ui-widget-catalog`, delta `ui-theme`).

Решения grill-сессии W2 (зафиксированы пользователем) детализированы ниже; дробление W2 → W2a (механика+каталог+пилоты) / W2b (остальное) — отдельными change'ами, этот — W2a.

## Goals / Non-Goals

**Goals:**
- Один механизм темы: role-property + `attach_theme` + app-wide popup-лист; live-перекрытие открытых подключённых экранов.
- Каталог ролей/фабрик поверх существующих QtWidgets без subclass-иерархий.
- +3 обязательных токена (только читаемые); ноль новых файлов-ресурсов (QSS компилируется в памяти).
- Пилоты month_settings/world_snapshot без inline-цветов; переписанные e2e-маркеры.

**Non-Goals:**
- Миграция остальных экранов, mention text-color (`_MENTION_STYLE`), AI-кнопка целиком, character_sheet-диалоги, search_bar/timeline/detail_panel/splitter — всё W2b.
- Канвас/прокси-поля, перекомпоновка layout, новый UI-kit, QML.
- Изменение формы попапов (только цвет/шрифт/рамка из токенов).

## Decisions

### D1. Роли через dynamic `uiRole`-property вместо objectName и subclass

QSS-правила компилируются на селекторах `[uiRole="..."]`: `attach_theme(w)` → `w.setProperty("uiRole", "chrome")` + `unpolish/polish` + `ThemeRuntime.register(w)`; вложенные роли ставит `set_role(w, role, **mods)` (модификаторы — отдельные свойства: `uiRoleSize="xl"`, `uiRoleItalic=true`). Фабрики `title(text, size=...)`, `hint(text, italic=False)` — тонкие функции, возвращающие стандартный `QLabel` с ролью: частые однотипные места (title 10×, hint 5×) без boilerplate.
*Alt:* subclass-обёртки (`ThemedButton`) — ломают composition с существующими составными виджетами (CustomDateEdit), и QSS subclass'а нельзя переиспользовать с чужими классами; objectName — W1-наследие, не масштабируется на модификаторы. Кнопка остаётся правилом `chrome QPushButton` (уже W1) с добавлением hover/pressed — отдельной роли нет.

### D2. App-wide лист: строго попапы

`ThemeRuntime` при `apply()/set_theme()` ставит на `QApplication` отдельный сгенерированный лист из правил: `QToolTip`, `QMenu`, `QComboBox QAbstractItemView`, `QCalendarWidget`, `_MentionPopup` + `MentionPopupListView` (именованные классы контейнера и списка, селектор по типу класса; Qt матчит и `_`-префикс — проверено пиксельным тестом). Лист ставится только если собранный текст отличается от того, что уже носит цель (`app.styleSheet()` / `widget.styleSheet()`): `QApplication.setStyleSheet` — это unpolish/polish всего живого дерева виджетов, и безусловный push на каждом `apply()` дал квадратичную деградацию полного offscreen-прогона (ревью W2a). Хром-правила — только под `[uiRole="chrome"]`. Выбор B из grill: минимум глобального скоупа — нулевой риск протечи в `QGraphicsProxyWidget`-поля канваса (QSS по class-селектору достал бы их); альтернатива A (весь базовый виджет-скин глобально) отклонена именно по этому критерию. Композиция: `QApplication` лист + registered-widget лист независимы, оба пересобираются при `set_theme()`.

### D3. Роли-vs-палитра ОС

`palette(mid)` → токен `color.border`, `palette(highlight)` → `color.accent`; императивный `palette().mid()` запрещён в chrome (в скоупе куска — пилоты + селекторы компилятора). Если accent-slip визуально подтвердится (пиксельный E2E выделения строки), решение «отдельный `color.selection`» принимается в W2b — токен заранее не заводим. `rating_to_color()` остаётся программной; концы градиента (`color.rating.low/high`) перенесены в W2b вместе с migrating-экраном `detail_panel` — в W2a их не читал бы ни один лист.

### D4. Новые токены только читаемые + строгая схема

`color.status.ok` (light `#2e7d32` family / dark светлее), `font.size.lg`=14px, `font.size.xl`=16px. Все добавляются в `REQUIRED_TOKEN_KEYS`: tokens.json — repo-ресурс в бандле, «опциональный с дефолтом» порождает вторые дефолты; отсутствие любого → вся тема невалидна (fallback W1: лог + палитра ОС + тумблер no-op). LLM-red маппится на существующий `color.danger`, не множим.
Правило-фильтр (ревью W2a): токен заводится тем же коммитом, что и правило/CSS, которое его читает — тест `test_every_required_token_is_read_by_a_generated_style` это пинит. `color.rating.low/high` и `color.font.family.mono` под него не прошли (читателей нет: `rating_to_color()` по-прежнему держит literals, mono-QFont — в немигрированных экранах
) и уехали в W2b.
*Alt:* `color.info`/`color.mention` для синих — отклонено (решение Q8=a): mention/AI уедут в accent в W2b.

### D5. Альфа-AI как производная accent

QSS-значение `rgba(r,g,b,a)` вычисляется из hex-токена `color.accent` — helper в компиляторе `accent_rgba(alpha)` разбирает hex сам (`_hex_rgb`), чтобы модуль компилятора оставался без Qt-импортов. Отдельных rgba-токенов нет. Правила `QMenu::item:hover` нет: наведённый пункт меню для Qt уже `:selected`, и hover-слой лишь размывал бы сплошное accent-выделение (ревью W2a). E2E-grep по rgba-подстрокам заменяется на маркер `aiState` + хелпер `ai_state_is()`: `QObject::testProperty` protected и PySide6 его не экспортирует, поэтому проверка (маркер объявлен + равен значению) живёт в одном хелпере (свойство ставит UI; цвета-маркеры из тестов уходят).

### D6. Миграция objectName → роли без big-bang

W1-объекты (`themeChrome`, `themeMenu`) переходят на `uiRole` в этом куске: компилятор эмитит правила по свойству; objectName остаётся только там, где нужен идентификатором (тесты), не стилем. Пилоты подключают `attach_theme` в `__init__`. Это точечная правка 2 существующих экранов + компилятора, не переписывание экранов.

## Risks / Trade-offs

- Селектор `[uiRole=...]` в Qt совпадает только с виджетом, у которого свойство реально установлено (не переносится на детей), поэтому роли ставятся точечно; mitigation: regression-тест «вложенный виджет без роли не перекрашен».
- Live-`polish` открытых диалогов может не подхватить кастомные paint (emoji-QFont в world_snapshot остаётся) — принято: шрифты контента (emoji, дерево канваса) токенами не стали.
- Ужесточение обязательных токенов: битый/старый файл → полное отключение темы. Приемлемо (repo-файл в бандле), покрыто тестом «вычеркнуть токен → невалиден».
- `QApplication.setStyleSheet` в редких случаях влияет на оформление system-native меню — наблюдаем в offscreen-тестах; при проблеме — откат правила `QMenu` из popup-листа (изолированная правка в компиляторе).
- Accent-slip (выделение строк accent) — фолбэк через отдельный токен в W2b.
- App-wide `setStyleSheet` — дорогой (перепомпчивание всего дерева): mitigated дедупликацией по тексту листа + тестами «повторный `apply()` не дёргает `setStyleSheet`». Оставшийся один push на смену темы — плата за живые top-level попапы (D2).

## Migration Plan

Порядок apply (детали в tasks): токены + компилятор (юниты зелёные) → catalog-модуль + `attach_theme` (юниты) → popup-лист + runtime (юниты) → пилоты + пиксельные E2E → e2e-маркеры/AI-маркер-хелпер → README/CHANGELOG (пометка: эпик W не закрыт, W2b не начат). Откат — revert change'а: сгенерированных артефактов в repo нет; бандл не меняется.

## Open Questions

- Имена фабрик/свойств модификаторов (`uiRoleSize` vs `uiTitleSize`) — чистая косметика, решается на apply по вкусу кодовой базы; на контракты не влияет.
