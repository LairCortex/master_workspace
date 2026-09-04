# Proposal: Переезд списка чар-листов и диалога пресета в QML-острова (Q3a)

## Why

Q3 (последний кусок эпика Q) — переезд чар-листов в QML. Диалоги списка и пресета — чистые формы без mention/AI, каталожный паттерн Q2a1 для них уже готов; их переезд отдельным куском снимает с Q3b (канвас) лишние экраны и переводит все non-canvas окна чар-листов на библиотеку компонентов.

## What Changes

- `CharacterSheetListDialog` и `CharacterSheetPresetDialog` переезжают в QML-острова внутри прежних `QDialog`-обёрток (рамка/Esc системные, Enter — в маркер `defaultButton`). **Widgets-вёрстка обоих диалогов удаляется целиком, флага/второй копии нет** (прецедент Q1/Q2.5a).
- Поведение не меняется ни на пункт: базовая линия — действующие спек `character-sheet-editor` (вкладки Шаблоны/Листы, create/open/rename/delete, правила «нельзя удалить открытый/имеющий листы», «создать лист = шаблон + имя → Fill») и `character-sheet-preset` (каталог пресетов, полный лицензионный текст, D5-подстановка имени, конфликт имени). Они остаются чек-листом приёмки и не правятся.
- Публичный API фасадов сохраняется 1:1 (сигналы `open_requested`/`open_instance_requested`/`renamed`/`instance_renamed`/`created`, методы `set_open_sheet_id`/`set_open_instance_id`/`set_seated_ids`, контракт `refresh()` «лок предоставляет вызывающий», свойство `preset_dialog`) — `app/main.py` меняется только импортом/атрибутом конструирования.
- В контекст острова — тонкие VM (`SheetListViewModel`: списочные модели строк шаблонов/листов, выбор, вкладка, флаги доступности; `SheetPresetViewModel`: пресеты, текст лицензии, имя с правилом подстановки). Сервисы и `run_locked` остаются Python-стороной; QML только sync-входы и `*Requested`-сигналы.
- Системные попапы сохраняются нативными: ввод имени (`QInputDialog.getText`), выбор шаблона при создании листа (`QInputDialog.getItem`), подтверждения удаления и ошибки (`QMessageBox`).
- Сборка/тесты: `.spec` получает новые qml-файлы (datas); тесты диалогов переписываются на адресацию QML (`objectName` + `walk_items`) с сохранением проверяемых смыслов (сигналы, вызовы сервисов, ложный `refresh`); `test_no_chrome_hex` покрывает новые qml.
- `docs/design-system-roadmap.md` и `docs/CHANGELOG.md` обновляются (эпик Q остаётся открытым — впереди Q3b).

## Capabilities

### New Capabilities

_(нет — наблюдаемое поведение диалогов описано неизменными спеками `character-sheet-editor`/`character-sheet-preset`; меняется способ поставки)._

### Modified Capabilities

- `qml-shell`: «QML-каркас приложения» — к перечню островов добавляются диалоги списка чар-листов и создания из пресета; формулировка «остальные диалоги — widgets» сужается до ещё не переведённых экранов (канвас чар-листа, mention-edit, диалоги события/карточки).

## Impact

- `app/presentation/views/character_sheet/list_dialog.py`, `preset_dialog.py` — становятся фасадами-островами (те же имена классов и публичный API); виджеты содержимого удаляются.
- `app/presentation/viewmodels/` — новые тонкие `SheetListViewModel` / `SheetPresetViewModel`.
- `app/presentation/qml/` — новые `SheetListRoot.qml`, `SheetPresetRoot.qml` (chrome — из `nri.components`).
- `app/main.py` — точка конструирования (импорт не меняется, имя класса сохранено); сигнальная проводка `renamed`/`open_*` — без правок.
- `nri_manager.spec` (datas + новые qml), `tests/presentation/test_character_sheet_list_dialog.py` / `test_character_sheet_preset_dialog.py` (перенос приёмки) , `tests/test_spec_qml_bundle*`; сервисы, репозитории, БД, канвас и editor/fill — без изменений.
