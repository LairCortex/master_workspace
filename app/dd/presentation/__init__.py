"""D&D module presentation layer.

The «Датасеты D&D…» sheet (contract ``modal-sheets``) and the module's view
models join this package in group 5 of add-dnd-module-foundation. The same
DB boundary as the kernel's presentation holds here: no AsyncSession, no ORM
models, no transaction finishes — data flows through the module services.
"""
