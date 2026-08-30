# Proposal: add-design-tokens-w1

## Why

Цвета chrome мастера и HTML игрока (D1) живут копиями hex в виджетах и `app.css`. Смена палитры требует трёх правок и не даёт dark/light. W1 вводит один JSON semantic-токенов и проводит его до лаунчера, chrome MainWindow и CSS chrome стола — до каталога контролов и QML.

Кусок дорожной карты дизайн-системы; QML не входит. Grill W1 закрыт (`docs/design-system-roadmap.md`).

## What Changes

- Файл `app/presentation/theme/tokens.json` в репозитории (не `game.db`): semantic-токены, у каждого `light` и `dark`.
- Генерация QSS и CSS в памяти при старте и при смене темы; сгенерированные артефакты не коммитить.
- Предпочтение темы в `~/.nri_manager/ui.json`; по умолчанию **dark**.
- Тумблер dark/light в лаунчере и в меню MainWindow.
- QSS только на chrome-контейнеры лаунчера и MainWindow (`centralWidget` + `menuBar` ± statusbar), не на весь `QMainWindow`.
- D1: динамический `GET /app.css` с `:root` из токенов; `var()` только landing/toolbar/status; бумага листа без theme-var; открытые вкладки не пушим.
- `tokens.json` в PyInstaller `datas`.

Не входит: wrapper-виджеты (W2); остальные диалоги и снятие inline hex; канвас / `QGraphicsProxyWidget`; шкала событий (W3); QML; live-push темы в браузер.

## Capabilities

### New Capabilities

- `ui-theme`: semantic-токены, генерация QSS/CSS, глобальное dark/light, применение к лаунчеру и chrome MainWindow.

### Modified Capabilities

- `character-sheet-host`: отдача CSS chrome игрока из тех же токенов (бумага листа не тема).

## Impact

- Новый модуль темы в `presentation/` (+ preference рядом с паттерном `LlmConfigManager`, отдельный файл).
- `GameLauncherDialog`, `MainWindow`, `create_table_host_app` / статика `table_host/web`.
- `nri_manager.spec` `datas`; `docs/CHANGELOG.md`; статус W1 в `docs/design-system-roadmap.md`.
- Тесты: генератор, `ui.json`, stylesheet, `/app.css`; E2E `grab()` + пиксель = hex токена. Без golden PNG. Без внешней сети.
