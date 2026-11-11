"""
widgets/controls.py —— 可复用的自绘控件（全程序共用一套外观）

  · IconButton      —— 见 ui_icons.py
  · CheckCircle     —— 圆形勾选（替代 ☐ / ☑ 字符，跨字体都不变形）
  · Switch          —— 开关（设置里的开机自启）
  · SegmentedControl—— 分段选择（字体大小）
  · RemindChip      —— 提醒时间小胶囊（带时钟图标 / 过期配色）
  · EmptyState      —— 空列表插画 + 两行文案
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from theme import ANIM_FAST, C, font_px
from ui_icons import icon_pixmap


def ui_font(px: int, *, weight: QFont.Weight | None = None, strike: bool = False) -> QFont:
    """按当前字号档位生成字体（用于 QSS 无法表达的删除线等）"""
    f = QFont()
    f.setPixelSize(font_px(px))
    if weight is not None:
        f.setWeight(weight)
    f.setStrikeOut(strike)
    return f


def repolish(widget: QWidget) -> None:
    """动态属性变化后让 QSS 重新生效"""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def icon_label(name: str, color: str, size: int) -> QLabel:
    label = QLabel()
    label.setFixedSize(size, size)
    label.setPixmap(icon_pixmap(name, color, size))
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return label


# --------------------------------------------------------------------------- #
#  圆形勾选
# --------------------------------------------------------------------------- #
class CheckCircle(QAbstractButton):
    """20px 圆形勾选：未完成空心，悬停泛蓝，完成后蓝底白勾"""

    def __init__(self, done: bool = False, size: int = 22, parent=None):
        super().__init__(parent)
        self._done = done
        self._hover = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("标记完成")

    def setDone(self, done: bool):  # noqa: N802
        if self._done == done:
            return
        self._done = done
        self.update()

    def isDone(self) -> bool:  # noqa: N802
        return self._done

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 4
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

        if self._done:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C.PRIMARY))
            p.drawEllipse(rect)
            pen = QPen(QColor(C.WHITE))
            pen.setWidthF(2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            path = QPainterPath(QPointF(rect.left() + side * 0.27, rect.top() + side * 0.52))
            path.lineTo(rect.left() + side * 0.44, rect.top() + side * 0.69)
            path.lineTo(rect.left() + side * 0.75, rect.top() + side * 0.34)
            p.drawPath(path)
        else:
            if self._hover:
                p.setBrush(QColor(C.PRIMARY_SOFT))
            else:
                p.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(QColor(C.PRIMARY if self._hover else C.LINE_STRONG))
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.drawEllipse(rect.adjusted(0.8, 0.8, -0.8, -0.8))
        p.end()


# --------------------------------------------------------------------------- #
#  开关
# --------------------------------------------------------------------------- #
class Switch(QAbstractButton):
    """42x24 的滑动开关，选中为蓝色"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._offset = 3.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(ANIM_FAST)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _end_offset(self) -> float:
        return self.width() - 21.0 if self.isChecked() else 3.0

    def _animate(self, checked: bool):
        self._anim.stop()
        if not self.isVisible():
            # 初始化时直接落到正确位置，只在用户点击时才播放动画
            self._offset = self._end_offset()
            self.update()
            return
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(self._end_offset())
        self._anim.start()

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float):
        self._offset = float(value)
        self.update()

    offset = pyqtProperty(float, fget=get_offset, fset=set_offset)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0, 0, self.width(), self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.PRIMARY if self.isChecked() else C.LINE_STRONG))
        p.drawRoundedRect(track, track.height() / 2, track.height() / 2)

        # 旋钮
        knob = 18.0
        x = self._offset
        y = (self.height() - knob) / 2
        p.setBrush(QColor(0, 0, 0, 18))
        p.drawEllipse(QRectF(x + 0.4, y + 0.8, knob, knob))
        p.setBrush(QColor(C.WHITE))
        p.drawEllipse(QRectF(x, y, knob, knob))
        p.end()


# --------------------------------------------------------------------------- #
#  分段选择
# --------------------------------------------------------------------------- #
class SegmentedControl(QFrame):
    """白底灰槽的分段选择（微 / 小 / 中 / 大）"""

    changed = pyqtSignal(str)

    def __init__(self, options: list[str], current: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for name in options:
            btn = QPushButton(name, self)
            btn.setObjectName("SegBtn")
            btn.setCheckable(True)
            btn.setChecked(name == current)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._group.addButton(btn)
            lay.addWidget(btn)
            self._buttons[name] = btn
        self._group.buttonClicked.connect(lambda b: self.changed.emit(b.text()))

    def value(self) -> str:
        for name, btn in self._buttons.items():
            if btn.isChecked():
                return name
        return next(iter(self._buttons), "")

    def set_value(self, name: str):
        btn = self._buttons.get(name)
        if btn:
            btn.setChecked(True)


# --------------------------------------------------------------------------- #
#  提醒胶囊
# --------------------------------------------------------------------------- #
class RemindChip(QWidget):
    """提醒时间胶囊：时钟图标 + 文本，过期时变暖色

    整块都是可点击区域（内部图标 / 文字不接收鼠标），点击后由外层打开时间编辑。
    """

    clicked = pyqtSignal()

    def __init__(self, text: str, overdue: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("RemindChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setProperty("overdue", overdue)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 3, 9, 3)
        lay.setSpacing(4)
        color = C.WARN if overdue else C.REMIND_INK
        lay.addWidget(icon_label("clock", color, 13))

        self.text_label = QLabel(text, self)
        self.text_label.setObjectName("RemindChipText")
        self.text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.text_label)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._pressed = False

    def mousePressEvent(self, event):
        # 普通 QWidget 默认忽略鼠标按下，真实点击会冒泡到父级；
        # 这里必须显式 accept，才能稳定拿到 release 并触发 clicked。
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


# --------------------------------------------------------------------------- #
#  空状态
# --------------------------------------------------------------------------- #
class EmptyState(QWidget):
    """居中插画 + 标题 + 提示"""

    def __init__(self, title: str, hint: str, icon_name: str = "inbox", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 24, 20, 24)
        lay.setSpacing(8)
        lay.addStretch(1)

        self.icon = QLabel(self)
        self.icon.setPixmap(icon_pixmap(icon_name, C.LINE_STRONG, 44))
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.icon)

        self.title = QLabel(title, self)
        self.title.setObjectName("EmptyTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.title)

        self.hint = QLabel(hint, self)
        self.hint.setObjectName("EmptyHint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        lay.addStretch(1)

    def sizeHint(self) -> QSize:
        return QSize(220, 150)
