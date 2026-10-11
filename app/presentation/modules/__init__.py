"""The core seam of game-system modules (add-dnd-module-foundation, design Д2).

The kernel knows exactly one thing about a game-system module: something
implementing :class:`~app.presentation.modules.protocol.GameSystemModule`
may exist in the composition and can be attached to the main window and the
connector or detached from them. Which concrete module (if any) the game
composes is decided by the composition point ``app/main.py`` alone — the
isolation guard ``tests/test_dd_module_isolation.py`` bars every other
kernel file from importing ``app.dd``.
"""
