## Why

Вторая и последняя пачка R3 переводит `llm_setup` и `event_types` на QML-острова, завершая перенос шести тонких диалогов Q2a2 после пачки 1. Она сохраняет существующие сервисные и публичные контракты, добавляя недостающие библиотечные примитивы для парольного ввода и закрытой палитры типов событий.

## What Changes

- `LlmSetupDialog` и `EventTypesDialog` становятся QML-островами в прежних `QDialog`-фасадах; widgets-вёрстки удаляются целиком без флагов и запасных реализаций.
- Острова получают только тонкие sync-VM `llmSetupVm` / `eventTypesVm` и `islandPalette`; QML лишь эмитит запросы, а внешний сервис, HTTP-клиент, `_run` и `check_connection` остаются на фасаде.
- Публичные Python API обоих фасадов сохраняются 1:1.
- `ThemeField` получает режим password/echo, а новый `ThemeSwatch` отображает только цвета `color.chart.1…8`; оба получают пиксельную приёмку.
- Страницы LLM строятся через model/`Repeater` непосредственно из Python `FIELD_CONFIG`; второго списка полей в QML не появляется.
- LLM-сохранение использует `finish_saving`; пока идёт сохранение, Esc/закрытие блокируются.
- Редактирование типов событий остаётся write-through: без Save и подтверждения при закрытии.
- Каждый остров получает семантическую приёмку через `objectName` и один тест live-retheme.

## Capabilities

### New Capabilities

_(нет)_

### Modified Capabilities

- `qml-shell`: перечень QML-островов расширяется диалогами настройки LLM и типов событий, с фиксированными context names, фасадной границей и правилами приёмки.
- `qml-components`: `ThemeField` получает password/echo, библиотека получает `ThemeSwatch` на `color.chart.1…8` и пиксельную приёмку обоих.
- `llm-configuration`: форма настройки переносится на остров без изменения полей и сетевого поведения; поля выводятся из `FIELD_CONFIG`, сохранение завершается через `finish_saving`, закрытие блокируется во время save.
- `event-types`: диалог управления типами переносится на остров и сохраняет немедленное write-through-редактирование без Save/confirm.

## Impact

- `app/presentation/views/llm_setup_dialog.py`, `event_types_dialog.py`: сохраняемые фасады QML-островов, удаление widgets-layout.
- `app/presentation/viewmodels/`: тонкие sync-VM для двух диалогов.
- `app/presentation/qml/`: два root-файла островов; `nri/components/ThemeField.qml`, новый `ThemeSwatch.qml`, `qmldir`.
- `nri_manager.spec`: поставка новых QML-файлов.
- Тесты компонентов, VM, фасадов и островов мигрируются TDD; roadmap и changelog в этом planning change не изменяются.
