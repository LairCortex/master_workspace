"""D&D module application layer.

The module services (``ModuleSettingsService``, ``DatasetLibraryService``,
``DatasetValidatorService`` — groups 2–4 of add-dnd-module-foundation) join
this package. Like the kernel's application layer it stays Qt-free and, per
the architecture-integrity spec, it never imports ``app.presentation`` or a
database session — persistence arrives as repositories or services built by
the composition (guard-pinned since task 1.3).
"""
