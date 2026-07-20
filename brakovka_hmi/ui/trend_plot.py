from __future__ import annotations

from collections import deque
from time import monotonic

from PySide6.QtCore import QPointF, Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from brakovka_hmi.ui import theme as t


class DualTrendPlot(QWidget):
    """
    Sliding time-series: speed (m/min, left axis) and PID output (%, right axis).
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        window_s: float = 60.0,
        max_points: int = 600,
    ) -> None:
        super().__init__(parent)
        self._window_s = max(5.0, float(window_s))
        self._buf: deque[tuple[float, float, float]] = deque(maxlen=max(50, int(max_points)))
        self.setMinimumHeight(280)
        self.setObjectName("trendPlot")

    def clear(self) -> None:
        self._buf.clear()
        self.update()

    def push(self, speed_mpm: float, pid_out_pct: float) -> None:
        now = monotonic()
        self._buf.append((now, float(speed_mpm), float(pid_out_pct)))
        cut = now - self._window_s
        while self._buf and self._buf[0][0] < cut:
            self._buf.popleft()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        _ = event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(t.PANEL))

        margin_l, margin_r, margin_t, margin_b = 52, 52, 28, 28
        plot = QRectF(margin_l, margin_t, max(1, w - margin_l - margin_r), max(1, h - margin_t - margin_b))
        p.setPen(QPen(QColor(t.BORDER), 1))
        p.drawRect(plot)

        font = QFont(self.font())
        font.setPointSize(9)
        p.setFont(font)

        # Legend / live values
        if self._buf:
            _, sp, pct = self._buf[-1]
            legend = f"Скорость {sp:.1f} м/мин    PID {pct:.1f} %"
        else:
            legend = "Скорость — м/мин    PID — %"
        p.setPen(QColor(t.TEXT))
        p.drawText(QRectF(8, 4, w - 16, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, legend)

        if len(self._buf) < 2:
            p.setPen(QColor(t.TEXT_DIM))
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Ожидание данных…")
            return

        now = self._buf[-1][0]
        t0 = now - self._window_s
        speed_max = 10.0
        for _, s, _ in self._buf:
            if s > speed_max:
                speed_max = s
        speed_max = max(10.0, speed_max * 1.15)
        pct_max = 100.0

        # Grid
        p.setPen(QPen(QColor(t.BORDER), 1, Qt.PenStyle.DotLine))
        for i in range(1, 4):
            y = plot.top() + plot.height() * i / 4.0
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        # Left axis labels (speed)
        p.setPen(QColor(t.BORDER))
        for i in range(5):
            frac = i / 4.0
            y = plot.bottom() - plot.height() * frac
            val = speed_max * frac
            p.drawText(
                QRectF(0, y - 10, margin_l - 4, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{val:.0f}",
            )
        p.setPen(QColor(t.BORDER))
        p.drawText(QRectF(2, margin_t - 2, margin_l - 4, 16), Qt.AlignmentFlag.AlignLeft, "м/мин")

        # Right axis labels (PID %)
        p.setPen(QColor(t.ACCENT))
        for i in range(5):
            frac = i / 4.0
            y = plot.bottom() - plot.height() * frac
            val = pct_max * frac
            p.drawText(
                QRectF(plot.right() + 4, y - 10, margin_r - 6, 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{val:.0f}",
            )
        p.drawText(
            QRectF(plot.right() + 4, margin_t - 2, margin_r - 6, 16),
            Qt.AlignmentFlag.AlignLeft,
            "%",
        )

        def x_of(ts: float) -> float:
            return plot.left() + ((ts - t0) / self._window_s) * plot.width()

        def y_speed(v: float) -> float:
            return plot.bottom() - (max(0.0, v) / speed_max) * plot.height()

        def y_pct(v: float) -> float:
            return plot.bottom() - (max(0.0, min(100.0, v)) / pct_max) * plot.height()

        # Speed line
        pen_sp = QPen(QColor(t.BORDER), 2)
        p.setPen(pen_sp)
        prev = None
        for ts, sp, _ in self._buf:
            pt = QPointF(x_of(ts), y_speed(sp))
            if prev is not None:
                p.drawLine(prev, pt)
            prev = pt

        # PID % line
        pen_pid = QPen(QColor(t.ACCENT), 2)
        p.setPen(pen_pid)
        prev = None
        for ts, _, pct in self._buf:
            pt = QPointF(x_of(ts), y_pct(pct))
            if prev is not None:
                p.drawLine(prev, pt)
            prev = pt
