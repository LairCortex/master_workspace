"""D&D module infrastructure layer.

The dataset file storage under ``~/.nri_manager/datasets/`` and the
``LssDatasetsClient`` over the app-wide ``httpx.AsyncClient`` join this
package in group 3 of add-dnd-module-foundation. Network traffic goes
through the shared client only; the storage path comes from
``app.infrastructure.paths`` (the one source of the config home).
"""
