# Tasks: nri-0017-accessibility-completers

Все правки — оффскрин-пины из паттерна NRI-0012 (`queryAccessibleInterface`, `actionInterface().doAction("Press")`); живые проверки — только финальный `accessibility-audit`.

## 1. `ThemeDateField` (FI-1=M3, M2)

- [x] 1.1 `nri/components/ThemeDateField.qml`: `Accessible.role: Button`, `onPressAction` → существующий обработчик открытия попапа; `minimumWidth` по свойству `worstCaseText` (хосты/форматтер передают наихудшую форму активной календарь-даты; fallback-наихудшая маска в компоненте), elide остаётся запасным. Убрать usage-site «роль на role-less Control» где есть — имя остаётся на usage-site. Проверить: `test_theme_date_field_accessibility.py` — интерфейс/role/name не пустой; Press дёргает сигнал открытия (мок-хост); `implicitWidth` ≥ измеренного `worstCaseText`; `git diff` usage-site — только удалённые мёртвые аннотации.

## 2. Табы и пресеты (B1, B3)

- [x] 2.1 `ThemeTabButton`/`SheetListRoot` табы: проверить и (при необходимости) починить Press-контракт вкладки (`doAction("Press")` → смена `currentIndex`/VM). Проверить: `test_sheet_list_accessibility.py` (расширение) — Press вкладка «Листы» → смена; имена вкладок штатные.
- [x] 2.2 `SheetPresetRoot.qml:109`: слушать `activateRequested` (принятие), `selectedRequested` — только выделение; греп-обход остальных `selectedRequested`-слушателей на ту же размолвку. Проверить: тест — Press строки = принятие пресета (окно closedAccepted); одиночная мышь = только выделение (регрессия существующих).
- [x] 2.3 Проекция ListItem (FI-2): минимальная проба починки роли на живой проекции (сырое дерево offscreen+live-режим прогона); при неудаче — новый поименованный пункт «пределов» в AGENTS (с формулировкой «cocoa-проекция теряет List-роль, press работает») в этом же изменении. Проверить: итог либо зелёный live-прогон (в QA-отчёте), либо расширенный список пределов; незадокументированного расхождения не осталось (решение фиксируется в `docs/qa/<date>-accessibility-audit.md`).

## 3. «Правка» редактора и Fill (B2)

- [x] 3.1 `editor_dialog.py:131-160`: удалить `QMenuBar`/`setMenuBar`; `SheetEditorRoot.qml`: action-row «Отменить/Повторить/Копировать/Вставить/Дублировать» (текстовые `ThemeButton`, привязка к существующему command/VM-слою), хоткеи — существующие QAction/shortcuts на диалоге остаются. Проверить: тест — пять кнопок видны, Press «Отменить» = команда отмены (счётчик VM); `Ctrl+Z` работает (key-event тест); grab-контракт редактора переснят; QMenuBar больше нет (`git diff`).
- [x] 3.2 `fill_dialog.py:124-143`: то же для «Отменить/Повторить» (read-only — row скрыт, как прежний `.hide()`). Проверить: editable — кнопки+хоткеи делают undo/Fill (тест); read-only — row невидим (тест состояния).

## 4. Описания строк и ✎ (FI-3, FI-4=CR2)

- [x] 4.1 `RowItem.qml`: строковое свойство `accessibleDescription` → `Accessible.description`; usage-site лаунчера — «Открывает игру». Проверить: тест — описание через `text(QAccessible.Description)`; guard-тест конвенций NRI-0012 остаётся зелёным (описания не в запретах); карта AGENTS «description»-блок дополнен «Открывает игру» (совмещаем с фактическим набором — расхождений с картой design.md не остаётся).
- [x] 4.2 `EntityCardRoot.qml` музыка-«✎»: `Accessible.name: "Изменить ссылку на музыку"` (role уже Button). Проверить: accessibility-ассерт имени в существующем карточном наборе.

## 5. Посадки — закрепляющий AX-пин (TB3, поведение из П3)

- [x] 5.1 `tests/ui/test_table_host_seats_accessibility.py`: чекбокс строки посадки — `doAction("Press")` → ожидаемый `seat()`/`drop_seat()` на мок-хосте; повторная Press — обратный переход; `_seating_loading` гард не создаёт эхо-вызовов.
- [x] 5.2 Временная подмена: пин выполняет тот же путь, что клик мышью (общий обработчик 0016 — не новая логика). Проверить: счётчик обработчика = 1 Press.

## 6. Гейт, документация, живой контур

- [x] 6.1 `QT_QPA_PLATFORM=offscreen python -m pytest` зелёные, гейт 100 %.
- [x] 6.2 Документация: AGENTS.md (описание-слот RowItem, список пределов по итогам 2.3, карта «description» набора), `functional-checklist` (дата открыта прессом, правки редактора видны, пресеты выбираются активацией), `CHANGELOG`; П4 и статус закрытия карты в `docs/design-review-roadmap.md` (все четыре пакета — финальные статусы). Проверить: карта↔доки↔спики без расхождений.
- [x] 6.3 Живой `accessibility-audit` (computer-use, throwaway `qa-<date>`, AI не трогать): снять `get_app_state` главного окна/карточек/списка чар-листов/пресетов/редактора/Fill/попапов дат; сверить каждый интерактив и четыре/пять пределов; raw `AXDescription` описаний; дата-поле живо (имя+открытие), ListItem-итог из 2.3; дописка во все QA-отчёты серии (FI, B, CR/TB-строки). Проверить: реестр FI-1…FI-4, B1-B3, CR2, TB3-пин — закрыты или оформлены как задокументированный предел/отдельный follow-up с ключом.
- [x] 6.4 Финал: сверка дельты↔тестов; `openspec validate nri-0017-accessibility-completers --strict`; commit по запросу пользователя.
