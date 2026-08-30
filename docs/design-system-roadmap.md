# Дорожная карта: дизайн-система

Два эпика подряд, не параллельно: сначала токены на текущем QtWidgets, потом перенос presentation в QML. QML не стартует, пока эпик W не влит.

Источник правды для цвета/типа/отступа — один набор semantic tokens. Из него: QSS (мастер) и CSS (HTML игрока D1). Не два независимых скина.

QML как «дизайн-система с нуля» отклонено как первый шаг. Канвас чар-листа (`QGraphicsView`) в эпике W не переписываем.

## Куски (порядок)

| # | Кусок | Эпик | Что это | Статус |
|---|---|---|---|---|
| 1 | **W1** | W | JSON-токены → генерация QSS + CSS; MainWindow + 1 диалог + HTML fill; dark/light | влито (эпик W не закрыт) |
| 2 | **W2** | W | Каталог wrapper-виджетов (кнопка, поле, карточка, панель) и перевод остального chrome. Канвас не трогать | W2a реализован + ревью-фиксы, приёмка (полный offscreen-pytest) зелёная — ждёт коммита/мержа и архивации change; W2b — следующий change |
| 3 | **W3** | W | Визуальная шкала событий (дорожки), не `QListWidget`. Widgets + токены W1 | не начато |
| 4 | **Q1** | Q | Каркас QML: Qt Quick Controls, биндинги к существующим VM, тесты, PyInstaller. Оболочка; канвас ещё Widgets | не начато |
| 5 | **Q2** | Q | Chrome в QML (то, что закрыл W2). Новые экраны без Python-layout | не начато |
| 6 | **Q3** | Q | Канвас листа в Qt Quick. Последний кусок, без него эпик Q не закрыт | не начато |

```
W1 → W2 → W3 → Q1 → Q2 → Q3
```

W3 не блокирует смысл W1/W2: после W1 можно влить W2, W3 — когда шкала нужна в продукте, но **до Q1**. Q1 не начинать, пока W1–W3 не влиты (или W3 явно вычеркнут отдельным решением).

**W1** (grill закрыт): `app/presentation/theme/tokens.json` — semantic, каждый токен `{light, dark}`; цвет + spacing/radius/type (имена — propose). Генератор Python в памяти при старте и смене темы; QSS/CSS не коммитить. Тема в `~/.nri_manager/ui.json`; default **dark**; нет/битый preference → dark; битые токены → лог + палитра ОС, тумблер no-op. Поверхности: QSS на `centralWidget` + `menuBar` (+ statusbar) и корень **GameLauncherDialog** — не на весь `QMainWindow` (иначе parented-диалоги наследуют скин). Тумблер: меню MainWindow + лаунчер. D1: динамический `/app.css`, `:root` из токенов, `var()` только landing/toolbar/status; бумага листа без theme-var; открытые вкладки не пушим. `tokens.json` в PyInstaller `datas`. Приёмка: смена токена меняет лаунчер, chrome MainWindow и CSS chrome игрока без трёх копий цветов. Тесты: генератор light/dark; round-trip `ui.json`; смена stylesheet; `/app.css` с `:root`; бумага без theme-var; E2E `grab()` + пиксель = hex токена (не golden PNG). Нет каталога контролов, нет QML, нет новой шкалы.

**W2:** тонкие обёртки над QtWidgets, читают токены. Не копировать Material/Fluent. Миграция экранов кусками внутри W2. **Остаток после W1:** все диалоги кроме лаунчера; тултипы (`QToolTip` — top-level попо-ап, chrome-QSS до него не достаёт, нужен app-wide лист); inline hex (`#2d5a88`, LLM green/red, `#888`, …); не заменять title/`setStyleSheet` лаунчера на обёртки в W1. Канвас и `QGraphicsProxyWidget` полей — вне скоупа. HTML игрока не дублирует виджеты: только те же токены в CSS.

**W2 (W2a `add-widget-catalog-chrome-mechanics-w2a` — реализован, приёмка: полный offscreen-прогон зелёный; change ещё не заархивирован/не влит):** механика и каталог сделаны — роли через dynamic property `uiRole` (+ модификаторы `uiRoleSize`/`uiRoleItalic`) вместо objectName-селекторов; `app/presentation/theme/catalog.py`: `attach_theme(root)` (одна точка подключения экрана), `set_role`, фабрики `title`/`hint`; роли title/hint/field/list/card/status-ok/status-error; app-wide лист только для top-level попапов (`QToolTip`, `QMenu`, combo-лист, календарь, `_MentionPopup` + `MentionPopupListView`) — в канвас ничего не течёт, и лист переставляется на `QApplication` только при изменении текста (`setStyleSheet` перепомптит всё дерево процесса; безусловный push давал ×6 деградацию полных прогонов); +3 обязательных токена (`color.status.ok`, `font.size.lg/xl`); hover/pressed — производная accent (`accent_rgba`). Пилоты: `MonthSettingsDialog`, `WorldSnapshotWidget` (ушли `#888/#999/#2d5a88`), mention-попап без inline-QSS; e2e AI-кнопки проверяют маркер `aiState` (`ai_state_is()`), а не rgba-подстроки. **W2b (следующий change):** миграция остальных ~12 экранов/виджетов, `_MENTION_STYLE`, AI-цвета, палитрные селекторы (`palette(mid/highlight)`) остального chrome, **+ мёртвые в W2a токены `color.rating.low/high` и `color.font.family.mono` — заводятся вместе с читающим кодом** (`rating_to_color`, mono-блоки).

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
