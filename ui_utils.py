"""
ui_utils.py —— 通用绘图 / 资源小工具（两个窗口共用）
"""

import os
import sys

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import (
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
    qAlpha,
)
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QWidget
from PyQt6.QtGui import QColor
from PyQt6.QtCore import QEvent, QRect, QSize, Qt

from theme import C, R_CARD

BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.path.join(BASE_DIR, "assets")
CHAR_STAND = os.path.join(ASSET_DIR, "char_stand.png")
CHAR_LIE = os.path.join(ASSET_DIR, "char_lie.png")
APP_ICON_PNG = os.path.join(ASSET_DIR, "app_icon.png")


def pixmap_or_empty(path: str) -> QPixmap:
    pm = QPixmap(path)
    return pm  # 不存在时是空 QPixmap，调用方用 isNull() 判断后画占位


def rounded_pixmap(pm: QPixmap, w: int, h: int, radius: int | None = None) -> QPixmap:
    """把任意图片裁成圆角矩形（保持比例铺满裁切，不变形）"""
    if pm.isNull() or w <= 0 or h <= 0:
        return QPixmap()
    r = R_CARD if radius is None else radius
    scaled = pm.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(w, h)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), r, r)
    p.setClipPath(path)
    # 居中裁切
    p.drawPixmap(int((w - scaled.width()) / 2), int((h - scaled.height()) / 2), scaled)
    p.end()
    return out


def circular_pixmap(path: str, size: int, crop_ratio=None) -> QPixmap:
    """剪成圆形头像。

    crop_ratio：按原图比例先取一块区域再裁圆，例如 (0.12, 0.18, 0.88, 0.72) 只取头部；
    传 None 时用整张图居中裁切。
    """
    pm = pixmap_or_empty(path)
    if not pm.isNull() and crop_ratio:
        x0, y0, x1, y1 = crop_ratio
        pm = pm.copy(
            int(pm.width() * x0), int(pm.height() * y0),
            int(pm.width() * (x1 - x0)), int(pm.height() * (y1 - y0)),
        )
    if pm.isNull():
        out = QPixmap(size, size)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(C.LINE))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, size, size)
        p.end()
        return out
    return rounded_pixmap(pm, size, size, radius=size // 2)


def app_icon() -> QIcon:
    """托盘 / 窗口 / 任务栏图标：与 exe 图标同源（趴着的立绘裁成正方形）"""
    pm = pixmap_or_empty(APP_ICON_PNG)
    if not pm.isNull():
        return _multi_size_icon(pm)
    # 兼容旧结构：没有 app_icon.png 时退回角色脸部圆形
    pm = pixmap_or_empty(CHAR_LIE)
    if pm.isNull():
        pm = pixmap_or_empty(CHAR_STAND)
    if pm.isNull():
        icon = QPixmap(64, 64)
        icon.fill(QColor(C.NAVY))
        return QIcon(icon)
    w, h = pm.width(), pm.height()
    face = pm.copy(int(w * 0.12), int(h * 0.18), int(w * 0.76), int(h * 0.54))
    return _multi_size_icon(circular_pixmap_from(face, 256))


def _multi_size_icon(pm: QPixmap) -> QIcon:
    """把一张大图裁成多档尺寸，任务栏 / 托盘 / 标题栏都清晰"""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(
            pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)
        )
    return icon


def circular_pixmap_from(pm: QPixmap, size: int) -> QPixmap:
    if pm.isNull():
        return QPixmap()
    scaled = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(C.SURFACE))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(0, 0, size, size)
    p.setClipPath(_circle_path(size))
    p.drawPixmap(int((size - scaled.width()) / 2), int((size - scaled.height()) / 2), scaled)
    p.end()
    return out


def _circle_path(size: int) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QRectF(0, 0, size, size))
    return path


def add_shadow(widget, blur: int = 30, dx: int = 0, dy: int = 0, alpha: int = 55):
    """给卡片加软阴影（Qt 无 box-shadow，只能用 QGraphicsDropShadowEffect）"""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(dx, dy)
    eff.setColor(QColor(59, 42, 51, alpha))
    widget.setGraphicsEffect(eff)
    return eff


def round_menu(menu, margins: int = 0):
    """把 QMenu 变成真正圆角的弹出菜单。

    只写 QSS 的 border-radius 是不够的：菜单还是系统绘制的实心方框，
    四周会露出白色直角。这里关掉系统阴影、开透明底，让 QSS 画的圆角透出来。
    菜单项的内缩由 QSS 的 padding 控制，不需要额外包一层容器。
    """
    menu.setWindowFlags(
        menu.windowFlags()
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.NoDropShadowWindowHint
    )
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    if margins:
        menu.setStyleSheet(f"QMenu {{ padding: {margins}px; }}")
    return menu


class BottomFade(QWidget):
    """贴在滚动区底部的渐隐遮罩。

    滚动区会把列表按像素裁断，被裁到的那一行文字只剩顶部一行像素，
    在 125% 缩放下会显成一串彩色小点（ClearType 次像素色）。这里用一条
    从透明渐变到卡片底色的遮罩把它柔化掉。
    """

    FADE_H = 10

    def __init__(self, parent, color: str, height: int = FADE_H):
        super().__init__(parent)
        self._color = QColor(color)
        self.FADE_H = height
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        h = self.height()
        grad = QLinearGradient(0, 0, 0, h)
        # 顶部透明，最后两三个像素基本完全不透明——被裁剩的那一行文字正好落在这里
        for stop, alpha in ((0.0, 0), (0.5, 40), (0.75, 150), (0.9, 235), (1.0, 255)):
            c = QColor(self._color)
            c.setAlpha(alpha)
            grad.setColorAt(stop, c)
        p.fillRect(self.rect(), grad)


class GrayTextLabel(QLabel):
    """灰度抗锯齿文字标签。

    在 125% 显示缩放下，字号 ×1.25 会落到非整数设备像素，Windows 的
    ClearType 次像素渲染会把细笔画摊成“双线 + 左蓝右橙色边”。
    这里绕开系统渲染：先把文字用白色画到透明画布，只取它的 alpha 覆盖率，
    再用单一颜色重新填充，得到干净的灰度抗锯齿字形（没有彩色边）。
    """

    def __init__(self, text: str = "", color: str = C.INK, parent=None):
        super().__init__(text, parent)
        self._ink = QColor(color)
        self._img = None
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    # ---------------------------------------------------------------- 维护
    def setInk(self, color: str) -> None:
        self._ink = QColor(color)
        self._img = None
        self.update()

    def invalidate(self) -> None:
        self._img = None
        self.update()

    def setText(self, text: str) -> None:
        super().setText(text)
        self._img = None

    def setFont(self, font) -> None:
        super().setFont(font)
        self._img = None

    def resizeEvent(self, event) -> None:
        self._img = None
        super().resizeEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() in (
            QEvent.Type.FontChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.StyleChange,
        ):
            self._img = None
        super().changeEvent(event)

    def sizeHint(self):
        hint = super().sizeHint()
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self.text()) + 2, fm.height())

    # ---------------------------------------------------------------- 绘制
    def _build(self):
        dpr = self.devicePixelRatioF()
        w = max(1, int(self.width() * dpr))
        h = max(1, int(self.height() * dpr))
        mask = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        mask.fill(0)
        p = QPainter(mask)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font())
        p.drawText(
            QRect(0, 0, w, h),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.text(),
        )
        p.end()

        out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(0)
        r, g, b = self._ink.red(), self._ink.green(), self._ink.blue()
        for y in range(h):
            row = y * w
            for x in range(w):
                a = qAlpha(mask.pixel(x, y))
                if a:
                    out.setPixelColor(x, y, QColor(r, g, b, a))
        out.setDevicePixelRatio(dpr)
        self._img = out

    def paintEvent(self, event):
        dpr = self.devicePixelRatioF()
        try:
            if self._img is None or self._img.width() != max(1, int(self.width() * dpr)):
                self._build()
            p = QPainter(self)
            p.drawImage(0, 0, self._img)
            p.end()
        except Exception:
            # 自绘里抛异常会让 Qt 直接终止进程，这里退化成普通文字绘制兜底
            p = QPainter(self)
            p.setPen(self._ink)
            p.setFont(self.font())
            p.drawText(
                self.rect(),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                self.text(),
            )
            p.end()
