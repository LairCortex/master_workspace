"""The built-in D&D module (add-dnd-module-foundation).

A game-system module lives behind the kernel seam
:class:`app.presentation.modules.protocol.GameSystemModule`: the composition
point ``app/main.py`` is the ONLY kernel file allowed to import this package
(guard ``tests/test_dd_module_isolation.py``), and only after the game's
public ``dnd_module`` flag read enabled and supported.

The package mirrors the kernel's layering (design Д3): ``domain`` holds the
dataset model and the check report, ``application`` the module services,
``infrastructure`` the file storage and the LSS network client,
``presentation`` the module's sheet and view models. The module core binds
to the kernel UI only through ``attach`` — never the other way around.
"""

from app.infrastructure.repositories.game_settings_repository import (
    DND_MODULE_DATA_VERSION,
)

#: The module's data format version, stored with the game's ``dnd_module``
#: flag (design Д1: a module version lives slower than app releases). A game
#: whose flag names a version ABOVE this number was written by a newer
#: module: the current composition opens it as ordinary without touching its
#: data (spec «Версия модуля и совместимость версий приложения»).
#: Since task 2.1 the number lives in the kernel's key registry — the
#: synchronous launcher and the composition both need it, and neither may
#: import this package (guard tests/test_dd_module_isolation.py); this is the
#: module's own name for the same single source (add-dnd-module-foundation
#: tasks 2.1/2.6).
MODULE_VERSION = DND_MODULE_DATA_VERSION
