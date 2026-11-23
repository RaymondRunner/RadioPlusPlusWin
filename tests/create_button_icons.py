"""Regenerate simple white, transparent PNGs for recolorable button glyphs."""
import math
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
folder = Path(__file__).resolve().parents[1] / "resources" / "icons" / "default"
white = QColor("#ffffff")

for name in ("plus", "minus", "close", "gear"):
    image = QPixmap(64, 64)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(white, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    if name == "plus":
        painter.drawLine(14, 32, 50, 32)
        painter.drawLine(32, 14, 32, 50)
    elif name == "minus":
        painter.drawLine(14, 32, 50, 32)
    elif name == "close":
        painter.drawLine(17, 17, 47, 47)
        painter.drawLine(47, 17, 17, 47)
    else:
        for step in range(8):
            angle = step * math.pi / 4
            painter.drawLine(round(32 + 21 * math.cos(angle)),
                             round(32 + 21 * math.sin(angle)),
                             round(32 + 27 * math.cos(angle)),
                             round(32 + 27 * math.sin(angle)))
        painter.setPen(QPen(white, 7))
        painter.drawEllipse(14, 14, 36, 36)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(white)
        painter.drawEllipse(27, 27, 10, 10)
    painter.end()
    if not image.save(str(folder / f"{name}.png"), "PNG"):
        raise RuntimeError(f"Could not save {name}.png")
