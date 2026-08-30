# Design: add-event-timeline-tracks-w3

## Context

Текущий таймлайн — `TimelineWidget(QWidget)` c `QListWidget` (`app/presentation/views/timeline_widget.py`): items `"start — end\nname"`, сигнал `event_selected(int row)`, фильтр-шапка (`CustomDateEdit` ×2, apply/clear, "+"-меню). `TimelineViewModel` держит `_all_events`/`events`, клиентский `filter_by_dates`, `select_event(index)`. Wiring (`app/application/wiring.py`) связан с рядом: selection→detail (по индексу), dblclick→edit, search→`window.timeline_widget.list_widget.setCurrentRow(i)`. Домен `Event`: `start_date: date`, `end_date: date | None`, без типов/времени суток. Тема: `attach_theme(root, on_retheme=…)` (QSS-роли) + `ThemeRuntime.tokens`/`add_listener` для рисования вне QSS (паттерны W2b: `compiler.mention_style`, `accent_rgba`). Инвариант зачистки: `tests/presentation/test_no_chrome_hex.py`. Гantt-решения зафиксированы grill-сессией W3.

## Goals / Non-Goals

**Goals:**
- Gantt-полотно: полоса на событие, упаковка коллизий в дорожки, линейная шкала по дням, ось по игровым месяцам.
- Qt-независимое ядро геометрии (полностью юнит-тестируемое) + тонкий QWidget-рендер.
- Id-контракт выбора; все существующие E2E зелёные после переписывания хелперов.
- Полная живая ре-тема; ноль hex/palette() в новом коде.

**Non-Goals:**
- Зум, горизонтальный скролл, drag-редактирование дат, дорожки по сущностям/типам, сжатие пустых периодов, day/night-модель, изменения домена/репозиториев, world_snapshot, канвас чар-листа.

## Decisions

### D1. Кастомный `QWidget` + `QPainter` вместо `QGraphicsView`
Сотни полос, нет трансформаций/перетаскивания; hit-test — перебор rect'ов. `QGraphicsScene` (как канвас чар-листа) — лишний state-machine и item-overhead для статичного вида, а также тянет proxy-виджеты, которые нам не нужны. Альтернатива QScintilla-подобные/QListView delegate — не дают произвольной геометрии полос.

### D2. Чистое ядро `app/presentation/views/track_layout.py`
Dataclass-only/typing-only модуль (никаких Qt-импортов): вход — `[(event_id, start, end|None)]` + ширина/высота вьюпорта + метрики (min_h, max_h, lane_gap, axis_h, min_bar_w, padding); выход — rect'ы полос (x0,x1,y,h, метки обрезания текста), число дорожек, высота скролла, hit-test точка→event_id (верхняя по порядку отрисовки полоса, см. Risks), расписание подписей. QWidget (`TimelineCanvas`) только: paintEvent, mouse{Press,DoubleClick}→сигналы, wheelEvent (верт. скролл), tooltip, listener ре-темы. Причина: вся сложная математика (упаковка, клампы, скос идущих) тестится без QApplication и без grab().
- Упаковка: сортировка `(start_date, id)`, greedy first-fit по дорожкам (line-sweep с окончанием последней полосы дорожки). Детерминировано при неизменном входе.
- Ось: `x(date) = padding + (date − range_start).days / total_days * inner_w` (разность дат — `timedelta`, `.days`; `.toordinal()` был бы ошибкой); идущие: x1 = правый край inner, плюс скос (полигон) как маркер.
- Высота дорожки: `h = clamp((viewport_h − axis_h) / N − gap, MIN_H, MAX_H)`; переполнение при MIN_H → `scroll_y` ∈ [0, `content_h − (viewport_h − axis_h)`] — прокручивается только область дорожек, ось (`axis_h`) закреплена и в высотах, и в hit-test.
- Шаг вертикального скролла: один нотч колеса (`angleDelta` = 120 единиц) = ровно одна строка дорожки (`lane_h + lane_gap`); сырой `angleDelta` (120 px) прыгал бы на 5–8 дорожек.
- Кэш: канвас переиспользует план и замеры подписей по ключу (версия набора событий, размер вьюпорта, шрифт) — `paintEvent`/`wheelEvent`/hover не переупаковывают дорожки и не пересоздают `QFontMetrics` на каждый кадр. Смена набора id (`set_events`) дополнительно отматывает `scroll_y` в 0; перезагрузка того же набора позицию чтения сохраняет.

### D3. Id-контракт вместо row
`TimelineCanvas.event_selected(event_id: int)`, `event_double_clicked(event_id: int)`; `TimelineViewModel.select_event_by_id(id)` (+ сигнал `selected_event_changed` без изменений semantics). Wiring: selection по id ищет в `vm.events`; search-jump → `select_event_by_id` + `canvas.scroll_to_event(id)`. Альтернатива «оставить row как position-in-list» — отвергнута: в Gantt нет линейного порядка, синхронизация с detail-панелью на id честнее (решение grill R1-Q5).

### D4. Colors: только производные токенов, новых токенов нет
Полоса unselected: заливка `color.accent` с низкой альфой + border `color.border`/accent-производная; hover — средняя альфа; selected — solid `color.accent`, текст подписи `color.accent.fg`; фон/сетка — `color.bg.surface`/`color.border`; подписи оси — `color.fg.muted`. Ре-тема: панель через `attach_theme(..., on_retheme=…)` (шапка) + `ThemeRuntime.add_listener` на canvas (пересчёт QColor из `runtime.tokens`, `update()`). Паттерны уже обкатаны в W2b (`mention_style`, `accent_rgba`). Хелпер альфы — расширить существующий `accent_rgba`-механизм в compiler/theme, не плодить второй. Альтернатива новые `color.track.*` токены — отвергнута: namespace каждого ключа = CSS-переменная web-игрока, выдуманные роли не заводятся (правило ui-theme «обязательный токен без читателя»).
- Оф-скин (нет runtime либо токен не парсится в hex): выводить нечего, поэтому канвас красит именованными Qt-глобалами (`gray`/`black`/`white`) — это не цвет приложения и не `palette()` ОС, hex по-прежнему не появляется. Сценарий зафиксирован в спеке («Вне скина»).

### D5. Прогрессивная детализация подписей
Подпись рисуется iff `bar_w >= text_w + inset` и `lane_h >= MIN_TEXT_H`; иначе полоса остаётся без подписи. `QToolTip` (название + `format_game_date` диапазона; «—» для открытого конца) показывается при наведении на ЛЮБУЮ полосу, а не только на полосу без подписи: подпись не содержит дат, и подсказка остаётся единственным способом увидеть диапазон, не открывая карточку.Это сознательное расширение формулировки «иначе — tooltip» (ревью W3, п.4); spec-сценарий «Tooltip при нехватке места» остаётся импликацией. repaint планируем только при смене наведённой полосы. QToolTip уже покрыт app-wide popup-листом W2a.

### D6. Ось игровых месяцев
Пересечение диапазона с границами месяцев игрового календаря (месяцы/года из `date_utils`, имена из-game settings); тики — вертикальные hairline по всей высоте области полос. Дневных/недельных тиков нет.
- Тик — только настоящая дата «первое число месяца» внутри диапазона. Старт диапазона НЕ подписывается и не получает hairline (это край шкалы, а не календарная граница; ревью W3, п.2); интервал короче месяца остаётся без подписей.
- Прогрессивная детализация — только клиппингом подписей (соседние метки не перекрываются: при нехватке места следующая пропускается), hairline при этом остаётся на каждом тике. Отдельного шага тиков (`tick_months`) нет: канвас всегда вызывал дефолт, параметр жил только в юнитах и был удалён как мёртвый.

### D7. Точка встраивания — та же панель
`timeline_widget.py` сохраняет имя `TimelineWidget`, шапку и все add/filter-сигналы; внутри `QListWidget` → `TimelineCanvas`. Main window, minWidth и сплиттер не меняются. Меньше правок в wiring/тестах, change остаётся «один экран».

### D8. Тестовая пирамида
- unit (без Qt): упаковка/клампы/min-width/идущие/hit/scroll — `tests/presentation/test_track_layout.py`;
- widget: клик/dblclick→id-сигналы, tooltip, hint пустого состояния, autoscroll — `test_views.py` + новые кейсы;
- pixel-приёмка (grab-пиксель = ожидаемый QColor из токенов, обе темы; смена `color.accent` → новый цвет полос) — по образцу W1/W2b e2e;
- E2E: `tests/ui/helpers.py` — клик по полосе через canvas (маппинг id→центр rect из track_layout), все существующие E2E остаются зелёными;
- инвариант: `test_no_chrome_hex.py` на новый файл; 100% line coverage сохраняется.

## Risks / Trade-offs

- [Длинные кампании: сутки < 1 px, полосы сливаются] → принято grill-решением: min-ширина 10 px + фильтр-дата как «зум»; риск Cosmetic, tooltip/HIT остаются корректными.
- [front-most hit при пересечении полос] → между дорожками rect'ы не пересекаются (разные y). ВНУТРИ дорожки first-fit разводит только даты: расширение короткой полосы до `min_bar_w` может надвинуть её на соседа. Порядок отрисовки — `(start, id)`, поэтому hit-test идёт по списку с конца и отдаёт верхнюю (видимую) полосу — то же, что видит пользователь; сложных приоритетов по-прежнему нет.
- [Утечка hex в «производные» цвета при спешке] → пиксель-приёмка + `test_no_chrome_hex` ловят на CI.
- [E2E-хелперы завязаны на координаты] → хелпер получает координаты из того же `track_layout` (не магические числа); сломается детектируется юнит-тестами.
- [Двойное хранение выбранного id (VM + canvas)] → canvas только рендерит выбранный из VM; source of truth — VM, canvas `set_selected(id)` идемпотентен.

## Migration Plan

Один PR в `main` (по кускам roadmap). Внутри: сначала `track_layout` + юниты → canvas → VM/wiring → тесты/E2E → инварианты + CHANGELOG («эпик W: W3 влит») + roadmap (строка W3 → «влито»). Откат — revert PR'а, правок схемы БД нет.
- Статус: «влито» в roadmap/CHANGELOG фиксируется только фактом коммита/мерджа. Пока изменения лежат в рабочем дереве, статус — «реализован, ждёт коммита/мерджа» (ревью W3, п.10).
