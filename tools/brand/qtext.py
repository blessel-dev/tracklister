"""Text outlines with Qt (offscreen): HarfBuzz shaping and GPOS kerning for the Inter wordmark.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QGuiApplication, QImage,  # noqa: E402
                           QPainter, QPainterPath, QTransform)

from common import ASSETS  # noqa: E402

_app = None
_families: dict[str, str] = {}


def app():
    global _app
    if _app is None:
        _app = QGuiApplication.instance() or QGuiApplication([])
    return _app


def font(file_name: str, px: float) -> QFont:
    app()
    if file_name not in _families:
        fid = QFontDatabase.addApplicationFont(str(ASSETS / "fonts" / file_name))
        if fid < 0:
            raise RuntimeError(f"cannot load {file_name}")
        _families[file_name] = QFontDatabase.applicationFontFamilies(fid)[0]
    f = QFont(_families[file_name])
    # weight comes from the static file itself; pick the style that file provides
    styles = QFontDatabase.styles(_families[file_name])
    stem = file_name.rsplit("-", 1)[-1].removesuffix(".ttf")
    if stem in styles:
        f.setStyleName(stem)
    f.setPixelSize(max(1, int(round(px))))
    f.setKerning(True)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def text_path(file_name: str, px: float, text: str, letter_spacing_pct: float = 100.0) -> QPainterPath:
    """Outline of `text` with its baseline at y=0 and pen start at x=0, in px for size `px`.
    Rendered at 64x the size and scaled down, so fractional sizes stay exact."""
    k = 64.0
    f = font(file_name, px * k)
    if letter_spacing_pct != 100.0:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, letter_spacing_pct)
    p = QPainterPath()
    p.addText(QPointF(0, 0), f, text)
    return QTransform.fromScale(1 / k, 1 / k).map(p)


def path_alpha(path: QPainterPath, w: int, h: int, dx: float, dy: float) -> np.ndarray:
    """Antialiased coverage (0..1) of `path` translated by (dx, dy) on a w x h canvas."""
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    qp = QPainter(img)
    qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    qp.setPen(Qt.PenStyle.NoPen)
    qp.setBrush(QBrush(QColor(255, 255, 255, 255)))
    qp.translate(dx, dy)
    qp.drawPath(path)
    qp.end()
    buf = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())
    return buf[:, : w * 4].reshape(h, w, 4)[..., 3].astype(np.float64) / 255.0
