# Design: nri-0012-qml-accessibility

## Context

Motivation — в proposal.md. Здесь — фактическая база и технические границы.

Механика проверена пробами на этом окружении (PySide6 6.10.2, macOS, `munim-computer-use` 0.4.3):

- **Ф1.** Произвольный `QQuickItem` с `Accessible.role/name` появляется в дереве и в `QAccessible.queryAccessibleInterface`; без attached — отсутствует.
- **Ф2.** `Accessible.onPressAction` обязателен: AXPress без обработчика — молчаливый no-op (tool сообщает успех, `onClicked` не вызывается). С обработчиком действие срабатывает; `actionInterface.actionNames() == ['Press','SetFocus','Press']`.
- **Ф3.** Слоты разделены: формат выдачи — `Роль "имя" value=...`. У `TextField` значение автоматически в value, имя освобождено.
- **Ф4.** `Accessible.name` usage-site переопределяет угаданное имя; при заданном name дерево показывает только его; `Accessible.description` доступен через `queryAccessibleInterface().text(QAccessible.Description)` (offscreen) и `AXDescription` (живой inspect), но не выводится tool'ом при непустом name.
- **Ф5.** Обычная `Text` без attached в живом дереве отсутствует; `Accessible.role: Accessible.NoRole` оставляет безымянный `AXStaticText` (мусор); `Accessible.ignored: true` скрывает — не требуется.
- **Ф6.** Оффскрин: `queryAccessibleInterface(root) is None` (нет обхода дерева от корня), но точечно по объекту с attached интерфейс читается; `doAction('Press'/'SetFocus')` дёргает QML-обработчики.
- **Ф7.** У `TextField/SpinBox/TextArea/TabButton/ThemeButton(Button)/ThemeCheckBox` имя из текста уже отдаётся штатно — пере-аннотация запрещена.

Тестовая инфраструктура: QQuickWidget + objectName-хелперы (`tests/presentation/qml_helpers.py`), offscreen — конвенция CI.

## Goals / Non-Goals

**Goals:**
- Каждое действие мышью на QML-элементах имеет accessibility-эквивалент (одиночная активация/фокус); координатный путь остаётся только для 4 пределов из спеков.
- Правила слотов и запрет NoRole/пере-аннотации зафиксированы тестами и доками.

**Non-Goals:**
- value для кастомных Item (value-моста `QAccessible.installFactory` нет — follow-up NRI-0013).
- озвучка/VoiceOver UX, перевод строк, изменения мышиного поведения, попапы дат и tooltip HTML.
- pixel/темизация — accessibility не должна влиять на рендер.

## Decisions

**D1. Аннотирование у корня элемента.** `Accessible.role/name/description` + обработчики вешаются на корень интерактивного Item (не на внутренние Text/MouseArea) — интерфейс привязан к Item (Ф1), вложенные слои сами не участвуют.

**D2. Роль задаёт компонент, name/description — usage-site.** Роль — свойство природы (RowItem строка — пункт списка всегда, а имя динамично в списке), задаётся внутри библиотечного компонента вместе с `onPressAction` (компонент знает свои сигналы); имя и описание — attached `Accessible.name: "..."` в точке применения, где виден соседний label/tooltip. Альтернатива «всё из usage-site» отвергнута: роль, забытая в одной точке, молча ломает контракт.

**D3. press = element action.** Для двойно-кликовых элементов (строки списка, строки шкалы, карточки панели, строки снимка мира) `onPressAction` эмитит activate (`activateRequested`/двойной клик), НЕ выбор — в accessibility нет двойного press, «выбрать без открытия» для обзора лишнее (обзор кликает один раз). Для одиночно-кликовых — тот же обработчик, что и клик. Одиночный клик user'а не меняется; тесты проверяют, что одинарный клик не открывает.

**D4. name.** Строковая константа в точке применения (или биндинг `modelData.label` там, где label уже биндинг); для штатных Button/TabButton/CheckBox name не задаётся (Ф7). У `RowItem` name по умолчанию = `rowText.text` внутри компонента — переопределение только когда у строки появляется описание.

**D5. description точечно.** «Открывает игру/карточку/изображение/сущность», «Выбор цвета», «Выбор даты», «Открыть редактирование» — только где смысл нажатия не выводится из имени; кнопки с текстом-глаголом не дублируют. Описание проверяется оффскрин через `text(QAccessible.Description)` (Ф4).

**D6. Текстовый ввод без value-слота.** У `MentionField` (Ctrl) и инлайн-редактора чар-листа — роль `EditableText` и `onSetFocusAction` на `forceActiveFocus()` текстового слоя. Читаемость набранного в дереве остаётся пределом №2.

**D7. SheetCanvas.** Делегаты/поля холста аннотируются у корня делегата: `role` по типу (текст/число/дата → EditableText, чекбокс → CheckBox, картинка → Button, «прочее» → Button), pressAction — существующие ветки `onPressDesign/onFillPress` по текущему режиму без новой логики (Q10 B).

**D8. Тесты.** Новый шаблон: `queryAccessibleInterface` по объекту (`qml_helpers` + `QAccessible`), проверка role/name/description, `doAction("Press"/"SetFocus")` вызывает ожидаемый обработчик/сигнал; по файлу на остров в `tests/presentation/`; плюс единый guard-тест «штатный контрол имеет ровно один интерфейс, name из text» на выборке Button/CheckBox. Мусорных Text в дереве нет — проверять нечего, guard на NoRole в QML-исходниках (grep-тест `Accessible.role: Accessible.NoRole` → 0), т.к. оффскрин мусор не виден.

**D9. Чего запрещаем.** `Accessible.role: Accessible.NoRole`, `Accessible.ignored`, name на штатных текстовых контролах, `Accessible.value` (property не существует — Ф3), аннотации декоративных слоёв, трогать `Text`/`TitleText`/`HintText`.

## Карта аннотаций

### Компоненты (роль + обработчики внутри)

| Компонент | Роль | pressAction | дополнительно |
|---|---|---|---|
| `RowItem` | ListItem | emit `activateRequested()` | name по умолчанию = `rowText.text` |
| `ThemeSwatch` | RadioButton | существующий клик (checked=true; emit clicked) | property `accessibleName` («Цвет палитры №N»); `Accessible.checked` |
| `MentionField` | EditableText | — | name/description usage-site; `onSetFocusAction` → `forceActiveFocus()` plain-слоя |
| чип упоминания | Link | существующий клик (emit mentionClicked) | name = текст чипа; описание «Открывает упомянутую сущность» (или от хоста) |

### Строки списков (usage-site)

| Остров/строка | name | description |
|---|---|---|
| Лаунчер, строка игры | строка строки (`modelData.name + " (" + modifiedLabel + ")"`) | «Открывает игру» |
| Поиск, строка результата | `modelData.label/текст строки` | «Переходит к сущности» |
| TypesEditor, строка типа | `modelData.name` | «Выбирает тип» |
| SheetEditor rail/Template, Instance | `railDelegate/templateRow.label` | «Выбирает/открывает лист» |
| SheetFill rail | имя страницы | «Открывает страницу» |
| Preset rail | `modelData.label` | — |
| Timeline строка | `rowText.text` | «Открывает событие» |
| DetailPanel строка | `rowText.text` (caption) | «Открывает карточку» |
| Карточка сущности, связанные RowItem | `modelData.name` | «Открывает сущность» |
| EventTypes строка | `modelData.name` | «Выбирает тип события» |
| RelatedSection строка | (через RowItem по умолчанию) | «Выбирает сущность» |
| WorldSnapshot строка | `modelData.displayText` | «Переходит к сущности»; заголовок секции — Button «Развернуть/свернуть раздел» |

### Текстовые контролы/поля/кнопки без имени (usage-site; поля и иконки; текстовые кнопки не трогаем)

| Файл | Точка | name |
|---|---|---|
| SearchBarRoot:53 | searchInput | «Поиск по всем сущностям» |
| LlmSetupRoot:68/78/87/135 | endpoint/model/key/world | «Endpoint», «Модель», «Ключ API», «Описание мира» |
| LlmSetupRoot:181 | репитер fieldPrompt_<type>_<name> | `modelData.label` |
| SheetEditorRoot | как в инвентаре: 125 «Ориентация страницы», 289 «Переименование страницы», 325/334 «Вверх»/«Вниз», 344 «Удалить страницу», 354 «Добавить страницу», 472 X/Y/W/H, 496 «Кегль», 517 «Текст поля», 552 «Число», 570/588 «Минимум»/«Максимум», 646 «Новая опция», 666/671 «Поднять/Опустить опцию», 685 «Значение по умолчанию» |
| SheetFillRoot:206/221/266 | fillTextInput/fillTextarea/fillDropdown | «Значение поля», «Значение поля (многострочно)», «Значение из списка» |
| SheetPresetRoot:140/167 | licenseView/nameField | «Текст лицензии», «Имя листа» |
| EventDialogRoot:34/50/67/92/109/124 | имя/даты/тип/mention | «Название события», «Дата начала», «Дата конца», «Тип события», «Характеристики», «Предыстория» |
| EventDialogRoot:41/100/115/130/142 | AI-кнопки + swatch | «Сгенерировать: <fieldLabel>» (у 142 — «Сгенерировать: Событие» через заполненный `fieldLabel: "Событие"`), swatch: «Цвет типа события» |
| EventTypesRoot:161/179/209/216 | name/swatch/up/down | «Название типа события», «Цвет палитры №`<index>`», «Поднять тип», «Опустить тип» |
| EntityCardRoot | name/даты/рейтинг/checkbox/music/mention/open-sheet + AI | «Название», «Дата начала», «Дата конца», «Рейтинг», чекбокс (text штатно), «Ссылка на музыку», mention по label, «Открыть чар-лист» (text штатно — не трогаем) |
| DocViewerRoot:22 | docText | «Текст документа» |
| ImageViewerRoot | (кнопки текстовые) | — |
| XlsxImportRoot:48/60 | formatArea/pathField | «Требования к формату файла», «Путь к файлу .xlsx» |
| LauncherRoot / SheetListRoot | (текстовые кнопки + RowItem) | — |
| TimelineRoot:195 | addButton «+» | «Добавить событие» (+ tooltip уже есть) |

### SheetCanvas (карта ролей)

поле-текст/многострочный/число/дата → EditableText; checkbox → CheckBox (name=label поля); картинка → Button (description «Открыть изображение»); header/разделитель → не аннотируется. press → одиночный клик текущего режима (design: выбрать; fill: открыть редактор / toggle чекбокса / открыть подбор файла). name поля = label из модели (fallback — тип); инлайн-редактор (штатный TextField) — name «Редактирование поля», фокус штатно.

## Risks / Trade-offs

- **Обработчик press эмитит activate напрямую** — у RowItem в лаунчере активация без предварительного select возможна и штатно (двойной клик). Осознанно.
- **Qt-обновления могут добавить name из placeholder** — guard-тест D8 это заметит (name сменится с константы на placeholder, тест упадёт).
- **Делегат живёт при скролле ListView** — name биндинг следует модели; в тестах делегаты материализуются через `grab()` (текущий паттерн).
- **description не выводит tool** — проверка живым аудитом (raw `AXDescription`), оффскрин тест проверяет слот.
- **Роль ListItem не даёт double-press** — осознанно D3 (обзор открывает одним нажатием).
- Coverage гейт: QML-строки не Python; тесты-гарды новые, строк приложения не меняют — гейт 100% не двигается.

## Migration Plan

Аддитивные QML-правки + тесты + доки; ни схем, ни форматов; откат — git revert изменения.

## Open Questions

(нет)
