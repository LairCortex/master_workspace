## Context

См. `proposal.md`. Применять после A1, A-playable, A-editor и B. Макет — JSON v2 как у шаблона; новая таблица не нужна. Спеки: `character-sheet-preset`, `character-sheet-editor`.

## Goals / Non-Goals

**Goals:**

- Пресет = файл макета в бандле + id/имя/license_text в коде каталога.
- `create_from_preset` = `CharacterSheetService.create` с уже собранным `pages` JSON, не отдельная таблица.
- Лицензия — обычный `label`; после копии мастер может её стереть (нет типа «замок»).

**Non-Goals:**

- Импорт JSON шаблона пользователем (вынесен из эпика редактора).
- Живая связь бандл↔игра, авто-вставка в новую игру.
- Макеты C2+ и новые типы полей.

## Decisions

### D1. Файлы в бандле

Каталог `app/presentation/views/character_sheet/presets/`:

- `fate_core.json` — `SheetTemplate` v2 (одна страница, portrait).
- `mork_borg.json` — то же.
- `catalog.py` — `Preset(id, title, license_text, json_name)`.

`nri_manager.spec` `datas` включает оба JSON пресетов явным списком файлов (рядом с шрифтом A1; каталогом не копируем, чтобы `__pycache__` не попал в бандль — модули каталога так или иначе в PYZ). Чтение через `importlib.resources` / путь рядом с пакетом, не HTTP. Тест `tests/test_spec_presets_bundle.py` держит `datas` в синхроне с каталогом (риск «PyInstaller не упаковал JSON»).

Альтернатива: захардкодить геометрию в Python — отвергнута (макет правят как JSON, тесты сравнивают с файлом).

Исключение слоёв (зафиксировано, чтобы не ловить заново в ревью): `CharacterSheetService` (application) импортирует `PresetCatalog` из `app/presentation/views/character_sheet/presets/` — обратно относительно AGENTS.md. Разрешено намеренно: каталог не знает Qt (чистые dataclass + pathlib), и его расположение в `presets/` рядом с бандл-файлами экономит второй путь к JSON.

### D2. Стабильные id в файле, копия as-is

Поля в JSON имеют постоянные uuid. INSERT копирует `pages` без перегенерации id. Два шаблона Fate в одной игре могут иметь одинаковые field id — join B идёт через `template_id`.

Альтернатива: новые uuid при копии — лишняя сложность, тесты состава всё равно смотрят подписи/`type`.

### D3. Геометрия

Координаты задаются в JSON (pt, origin сверху, clamp в A4). Apply рисует макет в Design и сохраняет JSON; в репозиторий кладётся результат, не скрин Anima. Сетка 4 pt можно включить при рисовании, в пресет флаг snap не пишется.

Кегль лицензии = кегль соседних подписей пресета (не мельче). Длинный CC BY / 3PP — широкий label, перенос в рамке (A1 wrap).

### D4. Сервис

`PresetCatalog.list()` → два элемента, порядок: Fate Core, Mörk Borg.

`CharacterSheetService.create_from_preset(preset_id, name)`: load JSON, unique name, INSERT как `create` с готовым `pages`. Конфликт имени — та же ошибка, что `create`.

Не `update_pages` бандла.

### D5. Диалог

С вкладки «Шаблоны»: `QDialog` — список (два `QListWidget` item), `QPlainTextEdit` read-only для `license_text`, `QLineEdit` имени. Смена пункта списка меняет лицензию и подставляет title в имя, если имя ещё равно предыдущему title (или всегда подставлять title при смене, пока пользователь не правил имя: **при смене пресета подставлять title, если поле пустое или совпадает с title другого пресета**).

OK → `create_from_preset` → закрыть диалог → открыть Design (правила грязного Design как у «открыть шаблон»).

Cancel → ничего.

### D6. Состав полей (имена в JSON `content` у label / default у input)

Fate: label+input пары. Навыки — 18 number, default `""`. Стресс — checkbox default false. Портрет — image `image_id` null.

Mörk Borg: 2 omen checkbox; HP два number; четыре характеристики number без min/max (отрицательные в MB допустимы).

Русские строки подписей — в JSON, не в Qt `tr` (макет уезжает в игру как есть).

## Risks / Trade-offs

- [Лицензию сотрут в Design] → бандл и диалог остаются источником; копия в игре — снимок, как решили.
- [18 навыков не влезут] → две колонки мелким кеглем; тесты проверяют наличие полей, не пиксельный макет.
- [PyInstaller не упаковал JSON] → тест/проверка `datas`; без файлов диалог пустой — неприемлемо, упаковка обязательна.

## Migration Plan

1. После влитого B. `create_all` не трогаем.
2. Откат приложения: JSON в бандле просто не используется; копии в `game.db` остаются шаблонами v2.
3. Новых пресетов в этот change не добавляем.

## Open Questions

Нет.
