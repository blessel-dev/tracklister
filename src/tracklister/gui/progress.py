"""The Estado cell of a running row: icon, text and a flat progress bar (1.0.1, R11).

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

The text always carries the state and the number («Descargando 63 %», «Descargando 25,9 MB»,
«Buscando…»): it is also the accessible text, so the bar is decorative and colour is never the only
signal. The bar is flat (accent fill on a surface track, 1 px line_strong border, radius 0, no gradient
and no glow); the accent reaches at least 3:1 against the track and every cell background in both themes
(tests/gui/test_progress.py measures it from tokens.json). An indeterminate bar is a short segment
whose position depends on the clock: the Descarga page repaints only those cells, about 10 times a
second, and only while a run is going.
"""
from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPen
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from tracklister.gui.models import BAR_BUSY, BAR_NONE, BAR_VALUE, PROGRESS_ROLE, ProgressView
from tracklister.gui.theme import ThemeManager, mono_font

BAR_W, BAR_H = 64, 8                 # outer size, border included
BAR_PAD = 8                          # space on the right of the bar and between the text and the bar
SEGMENT = 0.3                        # share of the bar the moving segment covers
PERIOD_S = 1.4                       # one sweep of the moving segment


def bar_rect(cell: QRect) -> QRect:
    """Where the bar goes in a cell: right-aligned, vertically centred, whole pixels."""
    x = cell.right() - BAR_PAD - BAR_W + 1
    y = cell.top() + (cell.height() - BAR_H) // 2
    return QRect(x, y, BAR_W, BAR_H)


def fill_rect(bar: QRect, view: ProgressView, now: float) -> QRect | None:
    """The filled part inside the 1 px border: the fraction of a determinate bar, or the moving segment."""
    inner = bar.adjusted(1, 1, -1, -1)
    if view.bar == BAR_VALUE:
        w = int(round(inner.width() * max(0.0, min(1.0, view.fraction or 0.0))))
        return QRect(inner.left(), inner.top(), w, inner.height()) if w > 0 else None
    if view.bar == BAR_BUSY:
        seg = max(4, int(inner.width() * SEGMENT))
        phase = (now % PERIOD_S) / PERIOD_S                      # 0..1, then back: a ping-pong sweep
        pos = phase * 2 if phase < 0.5 else 2 - phase * 2
        x = inner.left() + int(round((inner.width() - seg) * pos))
        return QRect(x, inner.top(), seg, inner.height())
    return None


class StateDelegate(QStyledItemDelegate):
    """Paints the Estado cell of a row in flight; any other cell is painted as always."""

    def __init__(self, themes: ThemeManager, parent=None, clock: Callable[[], float] = time.monotonic):
        super().__init__(parent)
        self.themes = themes
        self.clock = clock

    def paint(self, painter, option, index) -> None:
        view = index.data(PROGRESS_ROLE)
        if not isinstance(view, ProgressView):
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""                                           # background, focus and icon only
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        theme = self.themes.theme
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        cell = option.rect
        bar = bar_rect(cell) if view.bar != BAR_NONE else None
        right = (bar.left() - BAR_PAD) if bar is not None else (cell.right() - BAR_PAD)
        text_rect.setRight(min(text_rect.right(), right))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        color = theme.qcolor("on_selection") if selected else (QColor(fg) if fg is not None
                                                                else theme.qcolor("ink"))
        painter.save()
        painter.setClipRect(cell)
        painter.setPen(color)
        label_font, num_font = opt.font, mono_font(theme, "sm")
        lfm, nfm = QFontMetrics(label_font), QFontMetrics(num_font)
        number = view.number
        num_w = nfm.horizontalAdvance(number) if number else 0
        space = lfm.horizontalAdvance(" ") if number else 0
        label_w = max(0, text_rect.width() - num_w - space)
        label = lfm.elidedText(view.label, Qt.TextElideMode.ElideRight, label_w)
        align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        painter.setFont(label_font)
        painter.drawText(text_rect, int(align), label)
        if number:
            x = text_rect.left() + lfm.horizontalAdvance(label) + space
            painter.setFont(num_font)
            painter.drawText(QRect(x, text_rect.top(), max(0, text_rect.right() - x + 1), text_rect.height()),
                             int(align), number)
        if bar is not None:
            painter.fillRect(bar, theme.qcolor("surface"))
            fill = fill_rect(bar, view, self.clock())
            if fill is not None:
                painter.fillRect(fill, theme.qcolor("accent"))
            pen = QPen(theme.qcolor("line_strong"))
            pen.setWidth(1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(bar.adjusted(0, 0, -1, -1))
        painter.restore()
