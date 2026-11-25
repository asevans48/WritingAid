"""The one small chart in the scene outline (piece 7.3).

Every scene of the manuscript, left to right, chapter by chapter. Without
a model: a bar for each scene's length (the chapter shown in colour, the
rest grey) and a line for its share of dialogue. With tension from 7.2
(``plan_match.set_tension_source``): the line is tension instead.

Drawn into a ``QImage`` that the issue list's page shows as
``<img src='wa-chart:…'>`` (``ChapterIssues.loadResource``). Colours from
``PALETTE``.
"""

from __future__ import annotations

from typing import List, Sequence

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen

from src.ui.ui_kit import PALETTE

HEIGHT = 64
SCENE_GAP = 1.0
CHAPTER_GAP = 4.0


def render(points: Sequence, current_chapter_id: str, width: int, ratio: float = 2.0) -> QImage:
    """The chart for ``points`` (``plan_match.ScenePoint``), ``width`` px wide."""
    width = max(120, int(width))
    img = QImage(int(width * ratio), int(HEIGHT * ratio), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(ratio)
    img.fill(QColor(PALETTE["surface"]))
    if not points:
        return img
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    chapters = len({pt.chapter_id for pt in points})
    room = width - CHAPTER_GAP * (chapters - 1) - SCENE_GAP * (len(points) - chapters)
    bar = max(1.0, room / len(points))
    top, bottom = 4.0, HEIGHT - 4.0
    most = max(pt.words for pt in points) or 1
    tension = any(pt.tension is not None for pt in points)
    x, prev = 0.0, None
    line: List[QPointF] = []
    for pt in points:
        if prev is not None:
            x += CHAPTER_GAP if pt.chapter_id != prev else SCENE_GAP
        prev = pt.chapter_id
        h = (bottom - top) * pt.words / most
        colour = PALETTE["primary"] if pt.chapter_id == current_chapter_id else PALETTE["border_strong"]
        if tension:
            colour = PALETTE["primary_border"] if pt.chapter_id == current_chapter_id \
                else PALETTE["border"]
        p.fillRect(QRectF(x, bottom - h, bar, h), QColor(colour))
        value = pt.tension if tension else pt.dialogue_share
        if value is not None:
            line.append(QPointF(x + bar / 2, bottom - (bottom - top) * max(0.0, min(1.0, value))))
        x += bar
    p.setPen(QPen(QColor(PALETTE["border_strong"]), 1))
    p.drawLine(QPointF(0, bottom), QPointF(width, bottom))
    if line:
        pen = QPen(QColor(PALETTE["error_ink"] if tension else PALETTE["accent_ink"]), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        if len(line) > 1:
            p.drawPolyline(line)
        else:
            p.drawPoint(line[0])
    p.end()
    return img
