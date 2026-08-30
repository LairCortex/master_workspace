# Proposal: add-widget-catalog-chrome-mechanics-w2a

## Why

После W1 темизированы только лаунчер и chrome главного окна: все прочие диалоги и виджеты живут на палитре ОС, стили расползаются inline-шестами (`#2d5a88`, `#888`, `#999`, LLM green/red, rgba-синь AI-кнопки), а top-level попапы (тултипы, комбобоксы, календарь, mention-лист) недостижимы для chrome-QSS в принципе. W2 (roadmap: каталог wrapper-виджетов + перевод остального chrome) на этом куске закладывает механизм и каталог — без них миграция экранов (W2b) утонет в повторе стилей.

## What Changes

- Единый механизм ролей вместо objectName-селекторов: виджет получает `uiRole`-dynamic property (`chrome`, `menu`, `title`, `hint`, `field`, `list`, `card`, `status-ok`, `status-error`), QSS генерируется правилами по свойствам. Вспомогательная функция `attach_theme(widget|dialog)` регистрирует корень экрана в `ThemeRuntime` (live-смена темы сохраняется).
- App-wide QSS-лист строго для top-level попапов: `QToolTip`, `QMenu`, `QComboBox QAbstractItemView`, `QCalendarWidget`, `_MentionPopup` + `MentionPopupListView` (контейнер попапа и его список — двумя правилами, чтобы фон не расходился там, где список не заполняет попап). Хром-правила остаются под `[uiRole=chrome]`-поддеревом — в канвас и `QGraphicsProxyWidget`-поля ничего не проттекает. Лист переставляется на `QApplication` только при изменении текста: `QApplication.setStyleSheet` перепомптит всё живое дерево процесса.
- Каталог ролей + фабрики для частых однотипных мест (`title(+sizeModifier)`, `hint(+italic)`, `field`, `list`, `card`). Никаких subclass-обёрток и копирования Material/Fluent.
- +3 semantic-токена в `tokens.json` (все в `REQUIRED_TOKEN_KEYS`): `color.status.ok`, `font.size.lg`, `font.size.xl`. `color.rating.low/high` и `color.font.family.mono` из куска вынесены в W2b: в W2a их не читал ни один лист/CSS (ревью), а обязательный нечитаемый токен только ужесточает валидацию.
- Пилоты перевода на каталог: `month_settings_dialog`, `world_snapshot_widget` (title/hint/button→`color.accent`/list/tree/stats→токены; уход от `#2d5a88`, `#999`, `palette()` в их chrome).
- Разделители/hover переходят с `palette(mid)`/`palette(highlight)` на `color.border`/`color.accent` в пределах механизма и пилотов.
- **BREAKING (тесты):** e2e-селекторы AI-кнопки по rgba-подстрокам заменяются на динамический маркер `aiState` (`active`/`disabled`) + константы и хелпер `ai_state_is()` (эквивалент `QObject::testProperty`, который protected и PySide6 его не экспортирует). Сами состояния AI-кнопки мигрируют в W2b, маркеры готовятся здесь.

Не входит (W2b и вне): миграция остальных ~12 экранов/виджетов, mention text-color (`_MENTION_STYLE`), AI-кнопка целиком, character_sheet-диалоги, канвас и прокси-поля. Из попапов: пиксельный E2E — только mention-лист; tooltip/menu/calendar покрыты presence-тестами листа попапов.

## Capabilities

### New Capabilities

- `ui-widget-catalog`: каталог role-based обёрток/фабрик chrome-виджетов (title, hint, field, list, card, status), читающих семантические токены; контракт «стиль — из токенов, виджет — из фабрики/роли».

### Modified Capabilities

- `ui-theme`: область применения QSS расширяется — app-wide лист для top-level попапов; chrome-стили адресуются через `uiRole`-свойства вместо objectName; required-набор токенов дополняется тремя читаемыми ролями; тултипы перестают быть «палитрой ОС по design».

## Impact

- `app/presentation/theme/` — `tokens.json` (+3 токена), `compiler.py` (role-селекторы, popup-лист, alpha-производные accent, расширенный `REQUIRED_TOKEN_KEYS`), `runtime.py` (app-wide лист в `apply`/`set_theme`, dedupe по тексту листа).
- `app/presentation/` — новый module каталога (роль-хелперы/фабрики, `attach_theme`); пилоты: `month_settings_dialog.py`, `world_snapshot_widget.py`; мелкие правки `main_window.py`/`game_launcher_dialog.py` (objectName → role).
- Тесты: `tests/presentation/test_theme_compile.py`, `test_theme_apply.py` + новые (roles, popup-sheet, валидация токенов, пиксельные E2E пилотов и mention-попапа).
- PyInstaller `nri_manager.spec`: новых файлов нет (QSS компилируется в памяти) — пересинхронизации datas не требует.
- Визуально: button «Показать» становится token-accent (вместо синего), mentions/AI-цвета — contract W2b, не трогается.
