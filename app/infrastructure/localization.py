"""Русский язык системного оперения Qt (NRI-0014, spec interface-language, L1).

Qt рисует стандартные кнопки диалогов и файловые панели сам — их языком
управляет единственный :class:`QTranslator`, загружаемый из комплектного
``qtbase_ru.qm``:

* путь берётся из ``QLibraryInfo(TranslationsPath)`` — на dev-машине это
  ``PySide6/Qt/translations`` внутри колеса, в собранном ``.app`` — папка с
  тем же адресом (``datas`` в ``nri_manager.spec`` резолвит её тем же
  механизмом), поэтому dev и сборка говорят одинаково;
* язык фиксирован на ``ru`` именем каталога: языковые настройки ОС
  пользователя в выборе не участвуют.

Единственная точка вызова — ``main()`` сразу после создания ``QApplication``
и до первого окна; тестовая сессия воспроизводит это состояние session-фикстурой
в ``tests/conftest.py``. Установщик идемпотентен: повторный вызов возвращает
уже установленный переводчик и не заводит второго (пин в
``tests/test_interface_language.py``).

Отсутствие ``.qm`` (нештатная установка колеса/сборки) оставляет Qt-оперение
английским — деградацию ловят текстовые пины того же тестового файла, а не
молчаливый дрейф от спеки.
"""
from __future__ import annotations

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtWidgets import QApplication

#: the one translator of the process (set by install_russian_localization below)
_RU_TRANSLATOR: QTranslator | None = None


def install_russian_localization(app: QApplication) -> QTranslator:
    """Install the Russian standard-elements catalog once per process.

    Called right after the ``QApplication`` exists and before the first
    window (composition root ``app/main.py``, mirrored by the test session
    fixture). Idempotent: a second call hands back the same translator
    without installing anything new.
    """
    global _RU_TRANSLATOR
    if _RU_TRANSLATOR is None:
        translator = QTranslator(app)
        translator.load(
            "qtbase_ru",
            QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
        )
        app.installTranslator(translator)
        _RU_TRANSLATOR = translator
    return _RU_TRANSLATOR
