"""Readiness checks, one module per stage family (1.2a, Design §3).

Importing this package registers every check with ``src.ai.readiness``.
Later pieces add ``line.py`` checks (1.3), ``copyedit.py`` (1.4),
``structure.py`` (1.5), ``scene.py`` (1.6) and ``opening.py`` (1.8).
"""

from src.ai.readiness_checks import copyedit, line  # noqa: F401
