# Сторонние материалы и зависимости

Дата: 2026-10-14. Лицензии зависимостей взяты из установленных пакетов окружения `.venv`, а не из памяти или чужих списков: колонка «проверено» означает, что текст лицензии прочитан в дистрибутиве пакета.

Назначение файла: то, что нельзя забыть при распространении собранного приложения. Наш собственный выбор лицензий — [`LICENSE`](LICENSE) (код) и [`LICENSE.DATA.md`](LICENSE.DATA.md) (содержимое), обоснование — [`docs/licensing.md`](docs/licensing.md).

## 1. Прямые зависимости приложения

| Пакет | Лицензия | Правообладатель | Проверено |
|---|---|---|---|
| PySide6, shiboken6 | LGPL-3.0-only **или** GPL-2.0-only **или** GPL-3.0-only на выбор пользователя | The Qt Company Ltd и участники | метаданные пакета |
| SQLAlchemy | MIT | SQLAlchemy-авторы | метаданные пакета |
| alembic | MIT | Michael Bayer и участники | `LICENSE` пакета |
| qasync | BSD-2-Clause (условия 1–2, оговорок об именах нет) | Sam McCormack, Gerard Marull-Paretas, Mark Harviston, Arve Knudsen | `LICENSE` пакета |
| aiosqlite | MIT | Amethyst Reese | `LICENSE` пакета |
| openpyxl | MIT | участники openpyxl | метаданные пакета |
| httpx | BSD-3-Clause | Encode OSS Ltd | `LICENSE.md` пакета |
| aiohttp | Apache-2.0 (в метаданных «Apache-2.0 AND MIT» — MIT у входящих компонентов) | aiohttp-авторы | `LICENSE.txt` пакета |
| segno | BSD-3-Clause | Lars Heuer | `LICENSE` пакета |
| reportlab | BSD-лицензия ReportLab | ReportLab Inc. | `LICENSE` пакета |
| jsonschema | MIT | Julian Berman | `COPYING` пакета |
| referencing | MIT | Julian Berman | `COPYING` пакета |

## 2. Qt и требования LGPL (см. `docs/licensing.md`, §4.1)

Мы распространяем PySide6 по варианту **LGPL-3.0**. От поставки требуется:

1. текст GNU LGPL-3.0 рядом с приложением — лежит в `LICENSES/lgpl-3.0.txt` (копия из каталога SPDX, https://spdx.org/licenses/LGPL-3.0-only.html; канонический текст — https://www.gnu.org/licenses/lgpl-3.0.txt);
2. указание, какие именно библиотеки открыты по LGPL (PySide6, shiboken6 и Qt-библиотеки, которые они подтягивают), и где взять их исходники (https://download.qt.io/, https://code.qt.io/, https://pypi.org/project/PySide6/);
3. возможность заменить эти библиотеки в собранном приложении — она обеспечена каталожным форматом сборки, где Qt лежит отдельными файлами; переход на однофайловый архив это требование нарушит.

Текст GNU GPL-3.0 (третий вариант лицензии Qt) в поставку не вкладывается: мы на него не опираемся; ссылка — https://www.gnu.org/licenses/gpl-3.0.txt.

## 3. Инструменты разработки (в собранное приложение не входят)

pytest, pytest-qt, pytest-mock, pytest-asyncio, pytest-cov, ruff, pypdf — в основном MIT; у pytest-asyncio Apache-2.0. Обязанностей по распространению не создают, перечень приводится для полноты.

## 4. Сборка

| Инструмент | Лицензия | Комментарий |
|---|---|---|
| PyInstaller | GPL-2.0+ с особым исключением на собранные бинарники | исключение прямо разрешает распространять результат сборки под нашей лицензией |

## 5. Сторонние материалы в содержимом

| Материал | Лицензия | Где уведомление |
|---|---|---|
| Имена глифов и карта иконок Lucide (`app/domain/entity_registry.py`, `icons.js`) | ISC, © Lucide Icons and Contributors | этот файл + экран «О приложении» |
| Текст SRD 5.2.1 (справочник, датасеты, подсказки) | CC-BY-4.0, © Wizards of the Coast LLC | строка атрибуции ниже — в каждом датасете, в этом файле, в интерфейсе |
| Текст SRD 5.1 (датасет 2014 года) | CC-BY-4.0, © Wizards of the Coast LLC | формулировка SRD 5.1, подставить из соответствующего документа |
| Скачиваемые SRD-датасеты | CC-BY-4.0, © Wizards of the Coast LLC; поле `license` в файле | мы их не распространяем, скачивает пользователь |
| Схемы формата LSS (`app/dd/resources/schemas/`) | **не подтверждены** | см. `docs/licensing.md`, §7 В1 |
| Образцы подсказок (`app/dd/resources/generation/fewshot/`) | **происхождение не зафиксировано** | см. `docs/licensing.md`, §7 В2 |

### 5.1 Строка атрибуции SRD 5.2.1 (приводится дословно)

> This work includes material from the System Reference Document 5.2.1 ("SRD 5.2.1") by Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2.1 is licensed under the Creative Commons Attribution 4.0 International License, available at https://creativecommons.org/licenses/by/4.0/legalcode.

По условиям самого документа: никакой другой атрибуции Wizards и их материнской компании добавлять нельзя; о нашей работе допустимо написать «совместимо с пятой редакцией» («5E compatible»).

## 6. Товарные знаки

«D&D», «Dungeons & Dragons», логотипы и названия сеттингов — товарные знаки Hasbro и Wizards of the Coast. Ни лицензия на код, ни лицензия на содержимое прав на них не даёт; используется только описательное упоминание и формулировка о совместимости с пятой редакцией.
