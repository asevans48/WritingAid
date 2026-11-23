"""Make every part of the project file keep fields it does not recognise
(piece 0.4).

The top level of the project file (``WriterProject``) already keeps unknown
fields. Without this, a field a newer version of the app adds inside a
chapter, a character, a novella or any other nested part would be dropped
the moment this version saved the project.

``keep_unknown_fields(WriterProject)`` walks every model reachable from the
project and sets ``extra="allow"`` on it, rebuilding children before
parents. Models that already set ``extra`` are left alone. A file with no
unknown fields saves exactly as before.
"""

from __future__ import annotations

import inspect
import typing
from typing import List, Set, Type

from pydantic import BaseModel


def _models_in(annotation) -> List[Type[BaseModel]]:
    out: List[Type[BaseModel]] = []
    if typing.get_origin(annotation) is not None:
        for arg in typing.get_args(annotation):
            out.extend(_models_in(arg))
    elif inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        out.append(annotation)
    return out


def reachable_models(root: Type[BaseModel]) -> List[Type[BaseModel]]:
    """Every model reachable from ``root``, children before parents."""
    order: List[Type[BaseModel]] = []
    seen: Set[type] = set()

    def visit(cls: Type[BaseModel]) -> None:
        if cls in seen:
            return
        seen.add(cls)
        for field in cls.model_fields.values():
            for child in _models_in(field.annotation):
                visit(child)
        order.append(cls)

    visit(root)
    return order


def keep_unknown_fields(root: Type[BaseModel]) -> List[str]:
    """Switch every reachable model to keep unknown fields. Returns the
    names of the models changed."""
    changed: List[str] = []
    for cls in reachable_models(root):
        if cls.model_config.get("extra") is None:
            cls.model_config = {**cls.model_config, "extra": "allow"}
            changed.append(cls.__name__)
    # Rebuild children first, so each parent's schema embeds the new ones.
    for cls in reachable_models(root):
        cls.model_rebuild(force=True)
    return changed
