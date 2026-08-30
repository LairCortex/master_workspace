# Дорожная карта: дизайн-система

Два эпика подряд, не параллельно: сначала токены на текущем QtWidgets, потом перенос presentation в QML. QML не стартует, пока эпик W не влит.

Источник правды для цвета/типа/отступа — один набор semantic tokens. Из него: QSS (мастер) и CSS (HTML игрока D1). Не два независимых скина.

QML как «дизайн-система с нуля» отклонено как первый шаг. Канвас чар-листа (`QGraphicsView`) в эпике W не переписываем.

## Куски (порядок)

| # | Кусок | Эпик | Что это | Статус |
|---|---|---|---|---|
| 1 | **W1** | W | JSON-токены → генерация QSS + CSS; MainWindow + 1 диалог + HTML fill; dark/light | влито (эпик W не закрыт) |
| 2 | **W2** | W | Каталог wrapper-виджетов (кнопка, поле, карточка, панель) и перевод остального chrome. Канвас не трогать | W2a влито (заархивирован); W2b реализован, приёмка offscreen-прогоном зелёная — ждёт коммита/мерджа; остаток W2 вычеркнут |
| 3 | **W3** | W | Визуальная шкала событий (дорожки), не `QListWidget`. Widgets + токены W1 | не начато |
| 4 | **Q1** | Q | Каркас QML: Qt Quick Controls, биндинги к существующим VM, тесты, PyInstaller. Оболочка; канвас ещё Widgets | не начато |
| 5 | **Q2** | Q | Chrome в QML (то, что закрыл W2). Новые экраны без Python-layout | не начато |
| 6 | **Q3** | Q | Канвас листа в Qt Quick. Последний кусок, без него эпик Q не закрыт | не начато |

```
W1 → W2 → W3 → Q1 → Q2 → Q3
```

W3 не блокирует смысл W1/W2: после W1 можно влить W2, W3 — когда шкала нужна в продукте, но **до Q1**. Q1 не начинать, пока W1–W3 не влиты (или W3 явно вычеркнут отдельным решением).

**W1** (grill закрыт): `app/presentation/theme/tokens.json` — semantic, каждый токен `{light, dark}`; цвет + spacing/radius/type (имена — propose). Генератор Python в памяти при старте и смене темы; QSS/CSS не коммитить. Тема в `~/.nri_manager/ui.json`; default **dark**; нет/битый preference → dark; битые токены → лог + палитра ОС, тумблер no-op. Поверхности: QSS на `centralWidget` + `menuBar` (+ statusbar) и корень **GameLauncherDialog** — не на весь `QMainWindow` (иначе parented-диалоги наследуют скин). Тумблер: меню MainWindow + лаунчер. D1: динамический `/app.css`, `:root` из токенов, `var()` только landing/toolbar/status; бумага листа без theme-var; открытые вкладки не пушим. `tokens.json` в PyInstaller `datas`. Приёмка: смена токена меняет лаунчер, chrome MainWindow и CSS chrome игрока без трёх копий цветов. Тесты: генератор light/dark; round-trip `ui.json`; смена stylesheet; `/app.css` с `:root`; бумага без theme-var; E2E `grab()` + пиксель = hex токена (не golden PNG). Нет каталога контролов, нет QML, нет новой шкалы.

**W2 (W2a влит, W2b ждёт мерджа):** тонкие обёртки над QtWidgets, читают токены. Не копировать Material/Fluent. Миграция экранов кусками внутри W2. ~~**Остаток после W1:** все диалоги кроме лаунчера; тултипы (`QToolTip` — top-level попо-ап, chrome-QSS до него не достаёт, нужен app-wide лист); inline hex (`#2d5a88`, LLM green/red, `#888`, …); не заменять title/`setStyleSheet` лаунчера на обёртки в W1.~~ Закрыто W2a+W2b. Канвас и `QGraphicsProxyWidget` полей — вне скоупа (остаётся вне). HTML игрока не дублирует виджеты: только те же токены в CSS.

**W2a (влито; change `add-widget-catalog-chrome-mechanics-w2a`, заархивирован):** механика и каталог — роли через dynamic property `uiRole` (+ модификаторы `uiRoleSize`/`uiRoleItalic`) вместо objectName-селекторов; `app/presentation/theme/catalog.py`: `attach_theme(root)` (одна точка подключения экрана), `set_role`, фабрики `title`/`hint`; роли title/hint/field/list/card/status-ok/status-error; app-wide лист только для top-level попапов (`QToolTip`, `QMenu`, combo-лист, календарь, `_MentionPopup` + `MentionPopupListView`); +3 обязательных токена; hover/pressed — производная accent (`accent_rgba`). Пилоты: `MonthSettingsDialog`, `WorldSnapshotWidget`; e2e AI-кнопки проверяют маркер `aiState`.

**W2b (реализован, ждёт коммита/мерджа; change `migrate-remaining-chrome-w2b`):** миграция остатка ~12 экранов/виджетов — обычные диалоги (llm_setup status-роли, event/xlsx mono-токен, image_viewer/entity_card card-роль, table_host), панели главного окна (detail_panel rating-концы из `color.rating.low/high`, timeline/search_bar list-роли и border-токен, `QSplitter::handle`, doc-viewer mono), character_sheet-диалоги (chrome форм, канвас и proxy-поля — не тронуты, пиксельный regression), mention inline-HTML и AI-кнопка — производные `color.accent` (`compiler.mention_style`, `accent_rgba`) + live-retheme через `attach_theme(on_retheme=…)` (панели) / `ThemeRuntime.add_listener` (`MentionTextEdit`) с сохранением каретки и чистоты `document().isModified()`; введены `font.family.mono`, `color.rating.low/high` (namespace обязателен: каждый ключ — CSS var web-игрока); оф-скин rating-карточки теряют тинт полностью (D7: выдуманный серый конец градиента не рисуется); инвариант зачистки — `tests/presentation/test_no_chrome_hex.py` (ни hex, ни `palette()` в chrome-коде кроме канвас-слоя). Accent-slip выделений — целевой вид, `color.selection` не заведён. Приёмка specs: смена `color.accent` меняет mention, AI-active, выделения и «Показать» без правок экранов (автотест, обе темы).

**W3:** Gantt-like дорожки событий. Не дерево snapshot и не «красивее список». Snapshot остаётся деревом, пока не будет отдельного куска (его нет на этой карте). Реализация на Widgets (`QGraphicsView` или аналог), стили из токенов.

**Q1:** второй UI-стек рядом с Widgets. Viewmodels не переписывать ради QML. `QQuickWidget`/окно — grill Q1. Сборка и pytest обязаны зеленеть на трёх ОС. Канвас, нативные меню/диалоги, mention-edit — ещё не QML, если Q1 это запретит явно.

**Q2:** остальной chrome. Q8.B (набросать экран без Python layout) — рабочий режим этого куска, не W.

**Q3:** порт канваса (лента A4, типы полей, Fill, Design). Поведение A-playable / A-editor / B / D1 master preview не режем. Пока Q3 не влит, QML-эпик незавершён.

## Зафиксированные рамки

- **Ценность** — одна палитра на мастере и игроке; потом смена тулкита, не наоборот.
- **W раньше Q.** Полный уход в QML включая канвас — эпик Q, не W.
- **Две поверхности:** десктоп + HTML D1. Телефон/софт-AP берут тот же CSS, что fill.
- **Не аргумент за QML:** текущие timeline и snapshot — список и дерево; «плотный IDE-layout» закрывается токенами и W2.
- **Не в этой карте:** карта мира вместо дерева snapshot; Figma-live preview; сторонний UI-kit.
- **Чар-листы** (A1–P) не открываем заново, кроме Q3 (тот же контракт, другой рендер).

## Как работать с куском

1. `/grill-me` этого куска (W1, W2, …).
2. `/opsx-propose` — только этот кусок.
3. `/opsx-apply` после ревью плана.

В `main` вливаем по кускам: в CHANGELOG пометка, если эпик ещё не закрыт.
