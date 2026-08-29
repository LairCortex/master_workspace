## Context

См. `proposal.md`. Канвас уже в pt, origin сверху, шрифт DejaVu в `app/presentation/views/character_sheet/fonts/`. ImageStore отдаёт `original_file_path` / `preview_file_path`. QPdfWriter рисует, но не делает AcroForm — без новой библиотеки Q9=1 неисполним.

Спеки: `character-sheet-pdf`, `character-sheet-editor`. Схема и `schema_version` не меняются.

## Goals / Non-Goals

**Goals:**

- Чистая функция «макет + байты картинок → файл PDF» без Qt и без сессии.
- Design только собирает картинки, показывает пикер и ошибку I/O.
- Тесты читают страницы и поля через pypdf, без Acrobat.

**Non-Goals:**

- Печать, импорт, хост, экземпляр, общий рендер с HTML D1.
- Побитовое совпадение хрома виджетов с Qt.

## Decisions

### D1. reportlab runtime, pypdf в dev

`reportlab.pdfgen.canvas.Canvas` + `canvas.acroform` (textfield / checkbox / choice). Шрифт: `TTFont` из того же DejaVuSans.ttf. pypdf только в `[project.optional-dependencies] dev` для `PdfReader.get_fields()` / числа страниц.

Альтернативы: QPdfWriter (нет формы); чистый pypdf (слабый drawing); Qt-фон + поля поверх — два пайплайна и растр.

`hiddenimports`: `reportlab`, `reportlab.pdfgen`, `reportlab.pdfbase`, `reportlab.pdfbase.ttfonts`. Шрифт уже в `datas`.

### D2. Координаты

ReportLab `bottomup=1`. Для поля `(x, y, w, h)` канваса (origin сверху):

`y_pdf = page_h - y - h`, `x_pdf = x`.

`page_w` / `page_h` — те же `PAGE_WIDTH_PT` / `PAGE_HEIGHT_PT` с учётом ориентации (альбом — swap). `pagesize=(page_w, page_h)`. Зазор ленты не рисуем: `showPage()` на каждую страницу шаблона.

### D3. Слои

На странице: сначала рисунок (label, rect, line, image) в порядке массива; затем виджеты. Виджеты всегда выше рисунка и получают клик в Acrobat. Рамки text/textarea/number/dropdown не дублировать рисунком — их даёт виджет.

| тип | API | флаги / детали |
|---|---|---|
| text, number | `acroform.textfield` | `maxlen` ≥ 4096 (дефолт reportlab 100 мало); number = строка `content` |
| textarea | `textfield` | `fieldFlags="multiline"`, тот же `maxlen` |
| checkbox | `acroform.checkbox` | `checked=(content == "true")`; размер — `min(w,h)` если API без произвольного rect |
| dropdown | `acroform.choice` | `fieldFlags="combo"` без `edit`; `options=field.options`; `value=content` если он в опциях, иначе пусто |
| label | `drawString` + clip | `font_size` поля |
| rect | `rect(..., stroke=1, fill=0)` | |
| line | `line` | ширина > высоты → горизонт по середине меньшей стороны |
| image | `drawImage` или `rect` | см. D4 |

Имя виджета = `field.id` (uuid hex). `/NeedAppearances` включить, чтобы Preview/Acrobat показали value до первого клика.

### D4. Картинки

Экспорт синхронный. Design до вызова читает байты: сначала original, иначе preview; нет файла / IOError → ключа в карте нет. Рендер: нет байт или `drawImage` падает → пустая рамка, остальные поля пишутся.

### D5. Слои кода

`app/domain/character_sheet_pdf.py`: `write_sheet_pdf(template, dest: Path | BinaryIO, images: Mapping[int, bytes]) -> None`. Без Qt.

`CharacterSheetEditorDialog`: кнопка у `save_button`; `QFileDialog.getSaveFileName` (`*.pdf`, suggested=`{name}.pdf`); отмена → выход; `run_locked` только на чтение ImageStore; запись файла вне сессии. `OSError` → `QMessageBox`. Успех — без `QDesktopServices`.

Альтернатива «сервис в application/» — лишний слой: нет БД.

### D6. Тесты

`tests/domain/test_character_sheet_pdf.py`: временный Path, `PdfReader` — число страниц, имена/значения полей, отсутствие поля у label/image, альбом `mediabox`, битый image_id не валит файл.

`tests/presentation/test_character_sheet_editor_dialog.py`: кнопка есть; отмена пикера (mock) не зовёт write.

Без сети. Offscreen как остальные UI.

## Risks / Trade-offs

- [Хром Acrobat ≠ Qt] → принято на гриле.
- [macOS Preview криво рисует choice/checkbox] → NeedAppearances; приёмка — pypdf + Acrobat где есть, Preview не блокер.
- [checkbox API без точного w×h] → поле может быть меньше рамки Design.
- [Cyrillic в виджете] → тот же DejaVu в `fontName` виджета; если reportlab не принимает TTF в acroform — fallback Helvetica только для виджетов, подписи всё равно DejaVu (зафиксировать тестом кириллицы в label; виджет — отдельный тест value).
- [Частичный файл при падении mid-write] → писать во tempfile в том же каталоге и `replace`; если нельзя — сообщение об ошибке.

## Migration Plan

1. `pip install -e ".[dev]"` после правок `pyproject.toml` / spec.
2. Откат: кнопка и зависимость; данные игр не менялись.
3. Roadmap: P = этот change; CHANGELOG — экспорт PDF, снять P из «незавершено» если других фич эпика нет (телефон/AP остаются незавершёнными).

## Open Questions

Нет.
