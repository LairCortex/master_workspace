## Context

См. proposal.md — Why. Это пачка 2 R3 после `port-thin-dialogs-qml-r3`: на widgets остаются `LlmSetupDialog` (~430 строк) и `EventTypesDialog` (~365 строк). Оба уже имеют требуемое поведение: LLM ждёт `finish_saving` и глушит закрытие при `_saving`; types пишет через сервис немедленно. Инфраструктура общего QML-движка, `nri.components`, `islandPalette` и детерминированных island-тестов R1 уже существует; пачка 1 добавляет `ThemeTextArea`.

## Goals / Non-Goals

**Goals:**

- Сохранить UX и публичные Python API обоих `QDialog`-фасадов 1:1, заменив только содержимое на QML.
- Держать async, сервисы и HTTP на Python-стороне; QML — отображение и запросы.
- Завершить библиотечные примитивы R3: password/echo у `ThemeField`, `ThemeSwatch` на восьми chart-токенах.
- Исключить вторую декларацию LLM field prompts: строки генерируются из `FIELD_CONFIG`.

**Non-Goals:**

- Изменение формата `LlmConfig`, provider/retry/error semantics, `LlmService`, `EventService`, БД или wiring.
- Диалоги события/карточки, mention-стек, панели R4 и любые следующие куски R.
- Произвольный colorpicker, QML-owned async, новый QML engine или feature flag.
- Правки roadmap, changelog, app-кода или тестов на стадии planning.

## Decisions

### D1. Два прежних фасада владеют островами

`LlmSetupDialog` и `EventTypesDialog` остаются `QDialog` с теми же ctor, сигналами, методами и test seams. Каждый создаёт `QQuickWidget` на общем engine и загружает свой root с deferred teardown по принятому island-паттерну. Context properties уникальны: `llmSetupVm` / `eventTypesVm` + `islandPalette`; голое `vm` запрещено на общем root context.

Widgets-layout каждого диалога удаляется в этом change целиком, без флага. Альтернатива параллельной widgets-версии отклонена как мёртвый второй UI и источник расхождения поведения.

### D2. VM — тонкое синхронное зеркало, фасад — граница эффектов

`LlmSetupViewModel` хранит текущую страницу, connection values, world prompt, field-prompt model, check/save state и синхронные `*Requested`-сигналы. QML не создаёт provider и не вызывает coroutine. Фасад сохраняет `AppHttpClient`, создание `RemoteLlmProvider`, `check_connection`, `_run`/task scheduling, отображаемые ошибки и эмит `saved`; существующий внешний caller продолжает завершать save через `finish_saving(success)`.

`EventTypesViewModel` зеркалит строки, selected id и доступность действий. Add/rename/recolor/move/remove эмитят синхронные запросы; фасад сохраняет `event_service`, инъецированный `_run`, coroutine-операции, reload, `wait_idle`, `reload`, `types_changed` и `type_names`. VM не владеет репозиторием или event service.

Альтернатива async slots в QML/Python VM отклонена: она меняет принятый shell-контракт и усложняет qasync ownership.

### D3. LLM field pages строятся только из `FIELD_CONFIG`

Python адаптирует `FIELD_CONFIG` в модель строк с entity type/label, field name/label, placeholder и value. `LlmSetupRoot.qml` использует model + `Repeater` для страниц entity и их полей; имена `event/name/...` не перечисляются в QML. Connection, world и warnings остаются отдельными фиксированными страницами, потому что они не являются field prompts.

Модель возвращает значения фасаду без изменения структуры `dict[str, dict[str, str]]`; `get_connection`, `get_world_prompt`, `get_field_prompts` и `page_count` сохраняют наблюдаемую семантику. Альтернатива JS-массива отклонена как вторая копия schema.

### D4. Save/check state LLM управляется фасадом

`checkRequested` блокирует кнопку, фасад выполняет текущий `RemoteLlmProvider.check_connection()` и синхронно отражает neutral/ok/error status обратно в VM. `saveRequested` валидирует endpoint/model на Python-фасаде, ставит `_saving`, блокирует повторный запрос и эмитит прежний `saved`.

До `finish_saving` фасадные `reject()` и `closeEvent()` продолжают игнорировать Esc/close; VM одновременно выключает navigation/save controls. `finish_saving(True)` принимает диалог, `finish_saving(False)` снимает lock и показывает прежнее предупреждение, оставляя диалог открытым. QML не решает, закрывать ли окно.

### D5. Компоненты password/echo и chart swatch

`ThemeField` получает property, напрямую выбирающее echo mode базового `TextField`, не меняя прежний text API и default normal mode. `ThemeSwatch` — checkable библиотечный control с `colorIndex` 1..8; цвет читается только как соответствующее плоское свойство `islandPalette` для `color.chart.1…8`. Skinned-режим не рисует hex/JS-производные; off-skin использует только именованные Qt global colors и номер индекса.

Остров types создаёт восемь `ThemeSwatch` через `Repeater`, поэтому набор палитры также не дублируется вручную. Произвольный QColor/colorpicker и перенос старого `QPixmap` painter в QML отклонены.

### D6. Event types сохраняет write-through и test seams

Выбор строки только отражается в VM. Rename по завершению редактирования, swatch click, add, remove и up/down сразу отправляют запрос фасаду. Фасад выполняет существующую service-операцию, reload с сохранением/очисткой selection по прежним правилам и эмитит `types_changed`. Кнопка Close лишь принимает диалог; Save, dirty state, rollback и confirm не вводятся.

Public API сохраняется 1:1: ctor `(event_service, run=None, parent=None, theme=None)`, `types_changed`, `wait_idle()`, `reload()`, `type_names()` и наблюдаемая немедленная загрузка. Константы, используемые другими экранами (`NO_TYPE_TEXT` и договорённые palette helpers), не удаляются без проверки ссылок.

### D7. Приёмка разделена между библиотекой и островами

Сначала красные тесты. Библиотечный suite проверяет password masking и pixel field background/border, а также `ThemeSwatch` pixel = `color.chart.1…8` для dark/light и off-skin без выдуманного hex. Островные suites проверяют все интерактивные controls через стабильные `objectName`, поведение 1:1 и по одному live-retheme на остров: LLM сохраняет page/values, types — selection/order. Golden PNG нет.

`test_no_chrome_hex` охватывает оба root и новый компонент. Bundle-тест проверяет root-файлы, `ThemeSwatch.qml` и обновлённый `qmldir`/datas.

## Risks / Trade-offs

- [Field model может изменить порядок страниц/полей] → строить её напрямую в insertion order `FIELD_CONFIG`; контракт зафиксировать unit- и island-тестами.
- [Двойной save/check request при быстрых кликах] → фасадный `_saving` и check-state остаются авторитетными; controls следуют VM, фасад повторно защищает вход.
- [Write-through reload теряет selection] → сохранять id для rename/recolor/move и явно очищать после remove, как текущий фасад; live-retheme не пересобирает модель.
- [Context collision на общем engine] → только уникальные `llmSetupVm`/`eventTypesVm`, lifecycle очистки по общему island-паттерну.
- [Старые тесты обращаются к widgets-полям] → мигрировать их на `objectName`/VM, сохраняя проверяемые смыслы и публичные test seams.
- [Off-skin swatch теряет различимость цветов] → нумерованный Qt-global fallback сохраняет идентичность индекса без собственного цвета.

## Migration Plan

Один merge для пачки 2 R3: сначала библиотечные primitives, затем VM/фасады и оба острова, после чего удалить widgets-layout и обновить bundle. Схема данных и migration БД не требуются. Откат — revert change; runtime flag и параллельная реализация не создаются.

## Open Questions

_(нет)_
