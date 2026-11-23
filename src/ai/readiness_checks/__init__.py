"""Readiness checks, one module per stage family (1.2a, Design §3).

Importing this package registers every check with ``src.ai.readiness``:
``structure.py`` (1.5), ``scene.py`` (1.6), ``line.py`` (1.2b, 1.3) and
``copyedit.py`` (1.2b, 1.4). ``opening.py`` (1.8) comes later.
"""

from src.ai.readiness_checks import copyedit, line, scene, structure  # noqa: F401
