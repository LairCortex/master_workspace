"""Application package.

NRI-0016 (AB7, design V7): ``__version__`` is the single in-code source of
the version the UI shows («О приложении → Версия X.Y.Z»); it is pinned to
``pyproject.toml`` by ``tests/test_version_consistency.py``. Packaging places
(``nri_manager.spec``, ``docs/CHANGELOG.md``) stay release-time syncs.
"""

__version__ = "0.17.2"
