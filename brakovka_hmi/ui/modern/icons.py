from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPainterPath

from brakovka_hmi.ui.modern import theme as t

_ICON_CACHE: dict[tuple[str, str, int], QIcon] = {}


def _c(color: str) -> QColor:
    return QColor(color)


def icon(name: str, *, color: str = t.ACCENT, size: int = 24) -> QIcon:
    key = (name, color, size)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw(p, name, size, color)
    p.end()
    qicon = QIcon(pm)
    _ICON_CACHE[key] = qicon
    return qicon


def _draw(p: QPainter, name: str, size: int, color: str) -> None:
    fn = _DRAWERS.get(name, _draw_dot)
    fn(p, size, color)


def _pad(size: int, pct: float = 0.18) -> float:
    return size * pct


def _draw_dot(p: QPainter, size: int, color: str) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c(color))
    r = size * 0.2
    p.drawEllipse(size / 2 - r, size / 2 - r, r * 2, r * 2)


def _draw_home(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    path = QPainterPath()
    path.moveTo(size / 2, pad)
    path.lineTo(size - pad, size * 0.42)
    path.lineTo(size - pad, size - pad)
    path.lineTo(size * 0.62, size - pad)
    path.lineTo(size * 0.62, size * 0.58)
    path.lineTo(size * 0.38, size * 0.58)
    path.lineTo(size * 0.38, size - pad)
    path.lineTo(pad, size - pad)
    path.lineTo(pad, size * 0.42)
    path.closeSubpath()
    p.setPen(QPen(_c(color), max(1.4, size * 0.07), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _draw_roll(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    cx, cy = size / 2, size / 2
    r = size / 2 - pad
    p.setPen(QPen(_c(color), max(1.4, size * 0.07)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
    p.drawLine(int(cx - r * 0.55), int(cy), int(cx + r * 0.55), int(cy))


def _draw_settings(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    cx, cy = size / 2, size / 2
    r_outer = size / 2 - pad
    r_inner = r_outer * 0.42
    p.setPen(QPen(_c(color), max(1.3, size * 0.06)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for i in range(8):
        ang = i * 45
        p.save()
        p.translate(cx, cy)
        p.rotate(ang)
        p.drawLine(0, int(-r_outer * 0.55), 0, int(-r_outer))
        p.restore()
    p.drawEllipse(int(cx - r_outer), int(cy - r_outer), int(r_outer * 2), int(r_outer * 2))
    p.setBrush(_c(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(int(cx - r_inner), int(cy - r_inner), int(r_inner * 2), int(r_inner * 2))


def _draw_status(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    w = size - pad * 2
    h = (size - pad * 2) * 0.55
    y = pad + h * 0.35
    path = QPainterPath()
    path.moveTo(pad, y)
    path.lineTo(pad + w * 0.22, y)
    path.lineTo(pad + w * 0.35, pad)
    path.lineTo(pad + w * 0.52, size - pad)
    path.lineTo(pad + w * 0.68, size * 0.48)
    path.lineTo(size - pad, size * 0.48)
    p.setPen(QPen(_c(color), max(1.5, size * 0.08), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _draw_journal(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    w = size - pad * 2
    h = size - pad * 2
    p.setPen(QPen(_c(color), max(1.3, size * 0.06)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(int(pad), int(pad), int(w), int(h), 3, 3)
    lw = max(1.2, size * 0.06)
    p.setPen(QPen(_c(color), lw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i, frac in enumerate((0.28, 0.48, 0.68)):
        y = pad + h * frac
        x2 = size - pad - (0 if i == 2 else w * 0.25)
        p.drawLine(int(pad + w * 0.18), int(y), int(x2), int(y))


def _draw_play(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    path = QPainterPath()
    path.moveTo(pad, pad)
    path.lineTo(size - pad, size / 2)
    path.lineTo(pad, size - pad)
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c(color))
    p.drawPath(path)


def _draw_stop(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c(color))
    side = size - pad * 2
    p.drawRoundedRect(int(pad), int(pad), int(side), int(side), 3, 3)


def _draw_jog(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    p.setPen(QPen(_c(color), max(1.5, size * 0.08), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    y = size / 2
    p.drawLine(int(pad), int(y), int(size - pad), int(y))
    p.drawLine(int(size - pad - size * 0.14), int(y - size * 0.14), int(size - pad), int(y))
    p.drawLine(int(size - pad - size * 0.14), int(y + size * 0.14), int(size - pad), int(y))


def _draw_reverse(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    p.setPen(QPen(_c(color), max(1.5, size * 0.08), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    y = size / 2
    p.drawLine(int(size - pad), int(y), int(pad), int(y))
    p.drawLine(int(pad + size * 0.14), int(y - size * 0.14), int(pad), int(y))
    p.drawLine(int(pad + size * 0.14), int(y + size * 0.14), int(pad), int(y))


def _draw_reset(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    p.setPen(QPen(_c(color), max(1.4, size * 0.07), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = size / 2 - pad
    cx, cy = size / 2, size / 2
    p.drawArc(int(cx - r), int(cy - r), int(r * 2), int(r * 2), 45 * 16, 270 * 16)
    p.drawLine(int(cx + r * 0.55), int(pad + size * 0.08), int(cx + r * 0.85), int(pad))
    p.drawLine(int(cx + r * 0.55), int(pad + size * 0.08), int(cx + r * 0.35), int(pad + size * 0.22))


def _draw_save(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    w = size - pad * 2
    h = size - pad * 2
    p.setPen(QPen(_c(color), max(1.3, size * 0.06)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(int(pad), int(pad + h * 0.12), int(w), int(h * 0.88), 3, 3)
    p.drawRect(int(pad + w * 0.22), int(pad), int(w * 0.56), int(h * 0.22))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c(color))
    p.drawRect(int(pad + w * 0.28), int(pad + h * 0.45), int(w * 0.44), int(h * 0.12))


def _draw_speed(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    cx, cy = size / 2, size / 2
    r = size / 2 - pad
    p.setPen(QPen(_c(color), max(1.3, size * 0.06)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(int(cx - r), int(cy - r), int(r * 2), int(r * 2), 30 * 16, 300 * 16)
    p.setPen(QPen(_c(color), max(1.6, size * 0.08), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(int(cx), int(cy), int(cx + r * 0.55), int(cy - r * 0.35))


def _draw_diameter(p: QPainter, size: int, color: str) -> None:
    _draw_roll(p, size, color)


def _draw_length(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    p.setPen(QPen(_c(color), max(1.5, size * 0.08), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    y = size / 2
    p.drawLine(int(pad), int(y), int(size - pad), int(y))
    for x in (pad, size - pad):
        p.drawLine(int(x), int(y - size * 0.12), int(x), int(y + size * 0.12))


def _draw_target(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    cx, cy = size / 2, size / 2
    p.setPen(QPen(_c(color), max(1.3, size * 0.06)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for scale in (1.0, 0.62, 0.28):
        r = (size / 2 - pad) * scale
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))


def _draw_motor(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    p.setPen(QPen(_c(color), max(1.3, size * 0.06)))
    p.setBrush(_c(color))
    cx, cy = size / 2, size / 2
    r = size / 2 - pad
    p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
    p.setBrush(_c(t.BG))
    r2 = r * 0.35
    p.drawEllipse(int(cx - r2), int(cy - r2), int(r2 * 2), int(r2 * 2))


def _draw_brake(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    p.setPen(QPen(_c(color), max(1.4, size * 0.07)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(int(pad), int(pad), int(size - pad * 2), int(size - pad * 2))
    p.drawLine(int(size * 0.32), int(size * 0.68), int(size * 0.68), int(size * 0.32))


def _draw_freq(p: QPainter, size: int, color: str) -> None:
    _draw_status(p, size, color)


def _draw_tension(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    p.setPen(QPen(_c(color), max(1.4, size * 0.07), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(int(pad), int(size * 0.25), int(pad), int(size - pad))
    p.drawLine(int(size - pad), int(size * 0.25), int(size - pad), int(size - pad))
    y = size * 0.62
    path = QPainterPath()
    path.moveTo(pad, y)
    path.quadTo(size / 2, size - pad, size - pad, y)
    p.drawPath(path)


def _draw_encoder(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    step = (size - pad * 2) / 4
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c(color))
    for i in range(5):
        h = size * (0.22 + (i % 3) * 0.12)
        x = pad + i * step
        p.drawRoundedRect(int(x), int(size - pad - h), int(step * 0.55), int(h), 2, 2)


def _draw_pid(p: QPainter, size: int, color: str) -> None:
    _draw_settings(p, size, color)


def _draw_service(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    p.setPen(QPen(_c(color), max(1.3, size * 0.06)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(int(pad), int(pad), int(size - pad * 2), int(size - pad * 2), 4, 4)
    p.drawLine(int(pad + size * 0.2), int(pad + size * 0.35), int(size - pad - size * 0.2), int(pad + size * 0.35))
    p.drawLine(int(pad + size * 0.2), int(size * 0.52), int(size - pad - size * 0.35), int(size * 0.52))
    p.drawLine(int(pad + size * 0.2), int(size - pad - size * 0.28), int(size - pad - size * 0.5), int(size - pad - size * 0.28))


def _draw_calibrate(p: QPainter, size: int, color: str) -> None:
    _draw_diameter(p, size, color)


def _draw_refresh(p: QPainter, size: int, color: str) -> None:
    _draw_reset(p, size, color)


def _draw_filter(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    p.setPen(QPen(_c(color), max(1.3, size * 0.06)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(size / 2, pad)
    path.lineTo(size - pad, pad + size * 0.32)
    path.lineTo(size / 2, size - pad)
    path.lineTo(pad, pad + size * 0.32)
    path.closeSubpath()
    p.drawPath(path)


def _draw_warning(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    path = QPainterPath()
    path.moveTo(size / 2, pad)
    path.lineTo(size - pad, size - pad)
    path.lineTo(pad, size - pad)
    path.closeSubpath()
    p.setPen(QPen(_c(color), max(1.3, size * 0.06)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.setPen(QPen(_c(color), max(1.6, size * 0.08), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(int(size / 2), int(size * 0.42), int(size / 2), int(size * 0.62))
    p.drawPoint(int(size / 2), int(size * 0.72))


def _draw_check(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    p.setPen(QPen(_c(color), max(1.8, size * 0.09), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawLine(int(pad), int(size * 0.52), int(size * 0.38), int(size - pad))
    p.drawLine(int(size * 0.38), int(size - pad), int(size - pad), int(pad + size * 0.12))


def _draw_connection(p: QPainter, size: int, color: str) -> None:
    pad = _pad(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c(color))
    p.drawEllipse(int(pad), int(pad), int(size - pad * 2), int(size - pad * 2))


def _draw_back(p: QPainter, size: int, color: str) -> None:
    _draw_reverse(p, size, color)


_DRAWERS = {
    "home": _draw_home,
    "roll": _draw_roll,
    "settings": _draw_settings,
    "status": _draw_status,
    "journal": _draw_journal,
    "play": _draw_play,
    "stop": _draw_stop,
    "jog": _draw_jog,
    "reverse": _draw_reverse,
    "reset": _draw_reset,
    "save": _draw_save,
    "speed": _draw_speed,
    "diameter": _draw_diameter,
    "length": _draw_length,
    "target": _draw_target,
    "motor": _draw_motor,
    "brake": _draw_brake,
    "freq": _draw_freq,
    "tension": _draw_tension,
    "encoder": _draw_encoder,
    "pid": _draw_pid,
    "service": _draw_service,
    "calibrate": _draw_calibrate,
    "refresh": _draw_refresh,
    "filter": _draw_filter,
    "warning": _draw_warning,
    "check": _draw_check,
    "connection": _draw_connection,
    "back": _draw_back,
}


def icon_size(size: int = 24) -> QSize:
    return QSize(size, size)
