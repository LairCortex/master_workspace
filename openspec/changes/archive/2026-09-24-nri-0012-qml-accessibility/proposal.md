# Proposal: nri-0012-qml-accessibility

## Why

Дерево accessibility, которое читает компьютерный обзор (`munim-computer-use`), полностью слеп к кастомным QML-элементам: строки списков (игры, сущности), события на временной шкале, панель деталей, снимок мира, карточка сущности, холст чар-листа, переключатель цвета и упоминания отсутствуют в дереве целиком, а стандартные контролы вне текстовых кнопок показаны без имени. Любой сценарий computer-use вынужден кликать по координатам (зависимость от переднего плана, нечитаемость элементов), что зафиксировано в AGENTS.md как известный пробел.

## What Changes

- Все интерактивные элементы QML-островов и компонентов получают `Accessible.role`/`Accessible.name`; кликабельные кастомные `Item` — `Accessible.onPressAction`, чтобы нажатие по element_id действительно срабатывало (проверено пробами: без обработчика AXPress — молчаливый no-op).
- `Accessible.name` = короткая подпись у полей/кнопок-обёрток (usage-site), содержимое — у строк списков; `value` отдают штатные контролы (`TextField`, `SpinBox`), для кастомных `Item` слота value нет — это зафиксированный предел.
- `Accessible.description` точечно ("что делает нажатие") — для пользователя/VoiceOver через `AXDescription`; в выдаче computer-use не отображается, это не контракт.
- Запрещён `Accessible.role: Accessible.NoRole` (создаёт безымянный узел-мусор); обычные `Text` не трогаются (в живом дереве их нет).
- MentionField и инлайн-редактор чар-листа: роль `EditableText` + `Accessible.onSetFocusAction` → фокус внутреннего `TextEdit` (набор текста после пресса).
- pytest-оффскрин закрепляет по `objectName`: роль/имя/содержимое и `QAccessible actionInterface.doAction("Press"/"SetFocus")` вызывает ожидаемый обработчик.
- AGENTS.md: список «what tree does NOT expose» заменяется списком из четырёх известных пределов; обновляются `docs/functional-checklist.md` и `docs/CHANGELOG.md`.

## Capabilities

### New Capabilities
- `qml-accessibility`: дерево доступности QML-островов — discoverability и pressability каждого интерактивного элемента, правила name/value/description, оффскрин-пин тестами, зафиксированные пределы координатности.

### Modified Capabilities
- `qml-components`: `RowItem`, `ThemeSwatch`, `MentionField` обязаны предоставлять accessibility-обёртку (роль/имя/press/focus) поверх существующих сигналов, без изменения видимого поведения для мыши.

## Impact

- QML: правки в `app/presentation/qml/` (9 файлов аудита + иконки/поля во всех оставшихся островах: SearchBar, LlmSetup, SheetEditor-тулбар, Timeline addButton, дата-чипы и т.п. — полная таблица usage-site в design.md).
- Тесты: новые оффскрин-тесты по тестам/острову в `tests/presentation/` (QML-строки — покрытие линий Python не затрагивает, гейт 100% не двигается).
- Доки: `AGENTS.md` (блок computer-use: контракты дерева + пределы), `docs/functional-checklist.md`, `docs/CHANGELOG.md`.
- Видимое мышью поведение, модели, схемы БД и форматы файлов не меняются; follow-up за пределами изменения — value-мост `QAccessible.installFactory` (NRI-0013, только записать в tasks как отметку).
