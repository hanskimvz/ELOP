"""Simple latency histogram drawn with QPainter (matplotlib 없이)."""

from typing import List

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from ..stats import histogram, percentile


class HistogramWidget(QWidget):
    BINS = 60

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self._values: List[float] = []
        self._title = ""

    def clear(self, title: str = ""):
        self._values = []
        self._title = title
        self.update()

    def add(self, values: List[float]):
        self._values.extend(values)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        p.fillRect(self.rect(), pal.base())
        text_pen = QPen(pal.text().color())

        m_left, m_right, m_top, m_bottom = 50, 12, 24, 36
        plot = QRectF(m_left, m_top, self.width() - m_left - m_right,
                      self.height() - m_top - m_bottom)

        p.setPen(text_pen)
        p.drawText(QRectF(0, 2, self.width(), 20), Qt.AlignCenter,
                   "{}  (n={})".format(self._title, len(self._values)) if self._title
                   else "latency histogram (n={})".format(len(self._values)))

        if len(self._values) < 2:
            p.drawText(plot, Qt.AlignCenter, "데이터 없음")
            return

        # 꼬리 값 때문에 분포가 눌리지 않도록 p0.5 ~ p99.5 범위로 그림
        s = sorted(self._values)
        lo = percentile(s, 0.5)
        hi = percentile(s, 99.5)
        if hi <= lo:
            lo, hi = s[0], s[-1] + 1.0
        edges, counts = histogram(s, self.BINS, lo, hi)
        peak = max(counts) or 1

        bar_w = plot.width() / self.BINS
        bar_color = QColor(52, 120, 200)
        for i, c in enumerate(counts):
            h = plot.height() * c / peak
            p.fillRect(QRectF(plot.left() + i * bar_w, plot.bottom() - h,
                              max(bar_w - 1, 1), h), bar_color)

        p.setPen(text_pen)
        p.drawLine(plot.bottomLeft(), plot.bottomRight())
        p.drawLine(plot.bottomLeft(), plot.topLeft())
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            x = plot.left() + plot.width() * frac
            val = lo + (hi - lo) * frac
            p.drawText(QRectF(x - 40, plot.bottom() + 4, 80, 16), Qt.AlignHCenter,
                       "{:.0f}".format(val))
        p.drawText(QRectF(0, self.height() - 16, self.width(), 16), Qt.AlignCenter, "latency (us)")
        p.drawText(QRectF(0, plot.top() - 2, m_left - 6, 16), Qt.AlignRight, str(peak))
