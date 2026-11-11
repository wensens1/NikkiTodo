"""
widgets/pet_window.py —— 桌宠窗口（悬浮状态）157 x 225

  · 无边框 + 全透明 + 立绘铺满 + 按住拖动 / 轻点切回主窗口
  · 提醒气泡是独立的置顶小窗（不是子控件），所以不会被桌宠窗口裁掉；
    位置始终贴着桌宠，桌宠移动 / 隐藏时一起跟随。
  · 气泡的圆角、配色、按钮、字体与主窗口、对话框共用同一套 theme。
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from theme import C, FONT_FAMILY, font_ratio
from ui_icons import IconButton, icon
from ui_utils import CHAR_STAND, GrayTextLabel, add_shadow, round_menu
from widgets.controls import icon_label
from widgets.todo_item import fmt_remind

PET_W, PET_H = 157, 225      # 基准尺寸（100%）：高度沿用 225，宽度按新立绘 697x1000 的比例
LONG_PRESS_MS = 100          # 按住多久算"要拖动"，短于这个时间松手算点击
BUBBLE_SHADOW = 8               # 气泡窗口给投影留的白边
BUBBLE_GAP = 10                 # 相邻气泡卡片之间的视觉间距（窗口实际会重叠掉白边）
GLYPH_SIZE = 38                 # 缩小后那颗小星星的点击区
GLYPH_GAP = 8                   # 相邻缩小图标的竖向间距
DOCK_MARGIN = 8                 # 桌宠收进任务栏后，右下角气泡 / 图标离屏幕边的距离

PET_SCALE_MIN = 0.3             # 滚轮能缩到的最小比例（约 47 x 68）
PET_SCALE_STEP = 0.055          # 滚轮一格缩放多少（按当前比例等比）

# ---- 角色中心锚点（基准尺寸下）----
# 立绘铺满窗口，人物整体（含尾巴）居中，视觉重心就是窗口中心。
PET_CHAR_CX = PET_W // 2     # 78
PET_CHAR_CY = PET_H // 2     # 112


def pet_size(scale: float = 1.0) -> tuple[int, int]:
    """按缩放比例算桌宠窗口尺寸（宽高等比于基准）"""
    return max(1, round(PET_W * scale)), max(1, round(PET_H * scale))


def pet_anchor(scale: float = 1.0) -> tuple[int, int]:
    """桌宠窗口内的角色中心：立绘铺满窗口，等于窗口中心"""
    w, h = pet_size(scale)
    return w // 2, h // 2


# --------------------------------------------------------------------------- #
#  提醒气泡（独立置顶小窗）
# --------------------------------------------------------------------------- #
class SnoozeField(QWidget):
    """「稍后 N 分钟」按钮 + 时长下拉

    点按钮主体 = 按当前时长稍后提醒；点右侧小箭头 = 选 10 分钟 / 30 分钟 / 1 小时。
    交互参照时间胶囊（主体点动作、箭头点列表），但不支持双击自定义。
    """

    triggered = pyqtSignal(int)          # 点主体：稍后多少分钟
    minutesChanged = pyqtSignal(int)     # 从下拉里换了时长

    OPTIONS = (("10 分钟", 10), ("30 分钟", 30), ("1 小时", 60))

    def __init__(self, parent=None):
        super().__init__(parent)
        self._minutes = 10
        self.setFixedHeight(30)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.btn = QPushButton("稍后 10 分钟", self)
        self.btn.setObjectName("BtnGhostSmall")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setFixedHeight(30)
        self.btn.clicked.connect(lambda: self.triggered.emit(self._minutes))
        lay.addWidget(self.btn)

        self.arrow = IconButton(
            "chevron_down", color=C.INK_3, hover=C.INK,
            size=(16, 30), icon_size=11, tooltip="选择稍后时长", parent=self,
        )
        self.arrow.clicked.connect(self.open_menu)
        lay.addWidget(self.arrow)

    @staticmethod
    def label(minutes: int) -> str:
        if minutes >= 60 and minutes % 60 == 0:
            return f"稍后 {minutes // 60} 小时"
        return f"稍后 {minutes} 分钟"

    def minutes(self) -> int:
        return self._minutes

    def set_minutes(self, minutes: int, notify: bool = False):
        self._minutes = max(1, int(minutes))
        self.btn.setText(self.label(self._minutes))
        if notify:
            self.minutesChanged.emit(self._minutes)

    def open_menu(self):
        """下拉用和时间框同一套圆角弹层（PopupCard + TimeList），不用系统菜单样式"""
        popup = self._popup()
        current = self.option_text(self._minutes)
        options = [t for t, _ in self.OPTIONS]
        popup.open_for(options, current, self.arrow, self)

    def option_text(self, minutes: int) -> str:
        for text, value in self.OPTIONS:
            if value == minutes:
                return text
        return f"{minutes} 分钟"

    def _popup(self):
        if getattr(self, "_popup_ref", None) is None:
            from widgets.dialogs import _TimePopup     # 延迟导入，避开循环引用

            popup = _TimePopup(self.window())
            popup.picked.connect(self._on_picked)
            self._popup_ref = popup
        return self._popup_ref

    def _on_picked(self, text: str):
        for option, value in self.OPTIONS:
            if option == text:
                self.set_minutes(value, notify=True)
                return


class ReminderBubble(QWidget):
    snoozed = pyqtSignal(int)            # 稍后提醒（分钟数）
    completed = pyqtSignal()
    dismissed = pyqtSignal()
    minimized = pyqtSignal()             # 缩小成桌宠旁的小提醒图标
    minutesChanged = pyqtSignal(int)     # 用户换了稍后时长
    contextRequested = pyqtSignal(QPoint)  # 卡片上右键（全局坐标），弹和星星同一套菜单

    def __init__(self, store=None):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.store = store
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("待办提醒")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            BUBBLE_SHADOW, BUBBLE_SHADOW, BUBBLE_SHADOW, BUBBLE_SHADOW
        )
        outer.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("Bubble")
        add_shadow(self.card, blur=22, dy=0, alpha=55)
        outer.addWidget(self.card)

        body = QVBoxLayout(self.card)
        body.setContentsMargins(16, 14, 16, 14)
        body.setSpacing(10)
        self.body = body

        # 顶行：铃铛 + 说明 + 缩小 + 关闭
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(2)
        top.addWidget(icon_label("bell", C.PRIMARY, 14))
        kicker = QLabel("待办提醒", self.card)
        kicker.setObjectName("BubbleKicker")
        top.addWidget(kicker)
        top.addStretch(1)

        # 缩小：与 × 同一套线宽（SVG stroke 1.8）、同一图标尺寸，只是把线画短一点对齐 ×
        self.btn_min = IconButton(
            "minimize", color=C.INK_3, hover=C.INK,
            size=22, icon_size=12, tooltip="缩小到桌宠旁", parent=self.card,
        )
        self.btn_min.clicked.connect(self._on_minimize)
        top.addWidget(self.btn_min)

        self.btn_dismiss = IconButton(
            "close", color=C.INK_3, hover=C.INK,
            size=22, icon_size=12, tooltip="关闭", parent=self.card,
        )
        self.btn_dismiss.clicked.connect(self._on_dismiss)
        top.addWidget(self.btn_dismiss)
        body.addLayout(top)

        # 标题
        self.title = QLabel("", self.card)
        self.title.setObjectName("BubbleTitle")
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self.title)

        # 时间
        time_row = QHBoxLayout()
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.setSpacing(5)
        time_row.addWidget(icon_label("clock", C.INK_3, 12))
        self.time_label = GrayTextLabel("", C.INK_3, self.card)
        self.time_label.setObjectName("BubbleTime")
        self.time_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        f = QFont(FONT_FAMILY)
        f.setPixelSize(max(9, round(11 * font_ratio())))
        self.time_label.setFont(f)
        time_row.addWidget(self.time_label)
        time_row.addStretch(1)
        body.addLayout(time_row)

        body.addSpacing(2)

        # 操作
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)

        self.snooze = SnoozeField(self.card)
        self.snooze.triggered.connect(self._on_snooze)
        self.snooze.minutesChanged.connect(self._on_minutes_changed)
        actions.addWidget(self.snooze)

        self.btn_done = self._action_button("完成", "BtnPrimarySmall")
        self.btn_done.clicked.connect(self._on_done)
        actions.addWidget(self.btn_done)
        body.addLayout(actions)

        # ---- 拖拽脱离：按住卡片空白处拖动，卡片脱离桌宠绑定，停在自由位置 ----
        self._detached = False        # 是否已被手动拖离（不再跟随桌宠排布）
        self._dragging = False
        self._drag_moved = False
        self._drag_offset = QPoint()
        self._press_global = QPoint()

        self._card_width = 280
        self._fit()
        self._wire_context_menu()

    def _wire_context_menu(self):
        """卡片任意位置右键都弹同一套菜单

        卡片里全是 QLabel / QPushButton，它们的默认右键行为要么吃掉事件、
        要么给系统菜单。统一改成 CustomContextMenu，把事件转成自己的信号。
        """
        for w in [self] + self.findChildren(QWidget):
            if w.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu:
                continue
            w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            w.customContextMenuRequested.connect(self._on_context_menu)

    def _on_context_menu(self, pos: QPoint) -> None:
        sender = self.sender()
        gp = sender.mapToGlobal(pos) if isinstance(sender, QWidget) else self.mapToGlobal(pos)
        self.contextRequested.emit(gp)

    def _action_button(self, text: str, object_name: str):
        from PyQt6.QtWidgets import QPushButton

        btn = QPushButton(text, self.card)
        btn.setObjectName(object_name)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(30)
        return btn

    # ------------------------------------------------------------------ 内容
    def show_for(self, todo: dict, minutes: int | None = None):
        self.title.setText(todo.get("title") or "待办提醒")
        remind = todo.get("remind_at")
        self.time_label.setText(
            f"提醒时间 · {fmt_remind(remind)}" if remind else "提醒时间 · 现在"
        )
        if minutes is not None:
            self.snooze.set_minutes(minutes)
        self._fit()
        self.show()
        self.raise_()

    def _apply_metrics(self):
        """卡片的内边距 / 行距跟着字号档位一起缩放

        字大了留白跟着放大、字小了收紧，卡片才会明显"涨"起来；
        只让标题自己的行高变化的话，大字号和小字号看着几乎一样高。
        """
        r = font_ratio()
        px = max(12, round(16 * r))
        py = max(10, round(14 * r))
        self.body.setContentsMargins(px, py, px, py)
        self.body.setSpacing(max(7, round(10 * r)))

    def _fit(self):
        # 每次换提醒都要重新按标题高度收紧一次：先放开窗口自身的固定尺寸，
        # 否则外层布局会把 card 撑回上一次的高度，adjustSize 算不出真实内容高度
        self._apply_metrics()
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16_777_215, 16_777_215)
        self.card.setMinimumHeight(0)
        self.card.setMaximumHeight(16_777_215)
        self.card.setFixedWidth(self._card_width)
        self.title.setMinimumHeight(0)
        self.title.setMaximumHeight(16_777_215)
        self.card.layout().activate()

        # 标题是自动换行的，字号越大行数越多。QLabel 的 sizeHint 是"按它理想的宽度"
        # 算出来的，布局却按卡片里的实际宽度给它高度 —— 大字号下就会少一行被裁掉。
        # 这里按卡片里的可用宽度（卡片宽减左右内边距）重新问一次要多少高度，直接钉死。
        margins = self.card.layout().contentsMargins()
        avail_w = self._card_width - margins.left() - margins.right()
        need = self.title.heightForWidth(avail_w)
        if need > 0:
            self.title.setFixedHeight(need)
        self.card.layout().activate()

        self.card.adjustSize()
        height = self.card.height()
        self.card.setFixedHeight(height)
        self.setFixedSize(
            self._card_width + BUBBLE_SHADOW * 2,
            height + BUBBLE_SHADOW * 2,
        )

    # ------------------------------------------------------------------ 位置
    def place(self, pet_geo: QRect, avail: QRect):
        """单个气泡的兜底摆放（多气泡时由 PetWindow 统一排布）"""
        x = pet_geo.x() - self.width() - 4
        if x < avail.left():
            x = pet_geo.x() + PET_W + 4
        y = pet_geo.y() + 16
        x = max(avail.left(), min(x, avail.right() - self.width() + 1))
        y = max(avail.top(), min(y, avail.bottom() - self.height() + 1))
        self.move(x, y)

    def refresh_font(self):
        """字号档位换了：按新字号重新量一次高度

        高度是按旧字号算好再钉死的，光靠 QSS 换字体不会自己变高 ——
        字号调大之后必须重新量，不然标题又被裁。
        """
        self.title.setMinimumHeight(0)
        self.title.setMaximumHeight(16_777_215)
        self._fit()
        self.update()

    # ------------------------------------------------------------------ 拖拽脱离
    def _clamp_pos(self, pos: QPoint) -> tuple[int, int]:
        avail = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        x = max(avail.left(), min(pos.x(), avail.right() - self.width() + 1))
        y = max(avail.top(), min(pos.y(), avail.bottom() - self.height() + 1))
        return x, y

    def mousePressEvent(self, event):
        # 标题 / 时间是可选中文字、按钮自己消费事件，冒泡到这里的就是卡片空白区域
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_moved = False
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            gp = event.globalPosition().toPoint()
            # 小位移不算拖动，避免点一下就把卡片带跑
            if not self._drag_moved and (
                abs(gp.x() - self._press_global.x()) <= 3
                and abs(gp.y() - self._press_global.y()) <= 3
            ):
                return
            self._drag_moved = True
            self._detached = True
            self.move(*self._clamp_pos(gp - self._drag_offset))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------ 交互
    def _on_dismiss(self):
        self.dismissed.emit()

    def _on_snooze(self, minutes: int | None = None):
        self.snoozed.emit(int(minutes if minutes is not None else self.snooze.minutes()))

    def _on_minutes_changed(self, minutes: int):
        # 记住这次选的时长，所有气泡同步
        if self.store is not None:
            self.store.set_setting("snooze_minutes", int(minutes))
        self.minutesChanged.emit(int(minutes))

    def _on_done(self):
        self.completed.emit()

    def _on_minimize(self):
        self.minimized.emit()


# --------------------------------------------------------------------------- #
#  缩小后的提醒图标（贴着桌宠的小星星）
# --------------------------------------------------------------------------- #
def _sparkle_path(center: QPointF, r: float, k: float = 0.17) -> QPainterPath:
    """四角星（twinkle）轮廓：尖角在外、四条边向内收，和立绘上的小星星同款"""
    cx, cy = center.x(), center.y()
    kk = r * k
    path = QPainterPath(QPointF(cx, cy - r))
    path.quadTo(QPointF(cx + kk, cy - kk), QPointF(cx + r, cy))
    path.quadTo(QPointF(cx + kk, cy + kk), QPointF(cx, cy + r))
    path.quadTo(QPointF(cx - kk, cy + kk), QPointF(cx - r, cy))
    path.quadTo(QPointF(cx - kk, cy - kk), QPointF(cx, cy - r))
    return path


class MiniReminder(QWidget):
    """气泡缩小后贴在桌宠旁边的小图标（独立置顶小窗，不占桌宠窗口尺寸）"""

    activated = pyqtSignal()       # 左键单击：还原成气泡
    menuRequested = pyqtSignal()   # 右键单击：弹菜单（打开 / 缩小 / 关闭）

    def __init__(self, parent=None):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(GLYPH_SIZE, GLYPH_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False

    # ------------------------------------------------------------------ 内容
    def set_title(self, text: str) -> None:
        self.setToolTip((text or "待办提醒").strip() or "待办提醒")

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        center = self.rect().center()
        d = float(min(self.width(), self.height()))

        # 外圈柔光：悬停时更亮一点，说明"这里能点"
        glow = QColor(C.PRIMARY)
        glow.setAlpha(92 if self._hover else 52)
        grad = QRadialGradient(QPointF(center), d / 2.0)
        grad.setColorAt(0.0, glow)
        grad.setColorAt(0.55, glow)
        clear = QColor(C.PRIMARY)
        clear.setAlpha(0)
        grad.setColorAt(1.0, clear)
        p.fillRect(self.rect(), QBrush(grad))

        r = d / 2.0 - 8.0
        body = QColor(C.PRIMARY_HOVER if self._hover else C.PRIMARY)
        p.fillPath(_sparkle_path(QPointF(center), r), body)

        # 内部提亮：星心留一点浅色，贴合立绘上那颗星星的发光感
        inner = QColor(C.PRIMARY_SOFT)
        inner.setAlpha(215)
        p.fillPath(_sparkle_path(QPointF(center), r * 0.52, 0.22), inner)
        p.end()

    # ------------------------------------------------------------------ 鼠标
    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        # 右键单击这颗星星 → 交给桌宠那边弹菜单；左键留给「还原成气泡」
        if event.button() == Qt.MouseButton.RightButton:
            self.menuRequested.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.activated.emit()
        super().mouseReleaseEvent(event)


# --------------------------------------------------------------------------- #
#  桌宠
# --------------------------------------------------------------------------- #
class PetWindow(QWidget):
    """桌宠状态：150x225 全透明窗口"""

    enterWindowMode = pyqtSignal()          # 轻点桌宠 → 展开主窗口
    snoozeRequested = pyqtSignal(str, int)  # 稍后提醒（todo id, 分钟数）
    doneRequested = pyqtSignal(str)         # 勾选完成（todo id）
    minimizeToTray = pyqtSignal()           # 右键「最小化」→ 收进任务栏
    quitRequested = pyqtSignal()            # 右键「退出」

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._press_global = QPoint()
        self._win_start = QPoint()
        self._dragging = False
        self._drag_moved = False
        self._long_ready = False
        self._char_pm = QPixmap()
        self._mode = "pet"              # pet / window / tray：提醒贴谁、要不要收进右下角

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setWindowTitle("维尔汀桌宠")

        # ---- 立绘 ----
        self.char = QLabel(self)
        self.char.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
        self.char.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._load_char()
        # 闭眼素材（hover 眨眼用）
        self._char_pm_closed = QPixmap()
        self._load_closed_eyes()
        self._blink_timer = QTimer(self)
        self._blink_timer.setSingleShot(True)
        self._blink_timer.setInterval(150)  # 闭眼保持 150ms
        self._blink_timer.timeout.connect(self._blink_step)
        self._eyes_closed = False

        # ---- 尺寸（滚轮可缩放，比例记在设置里）----
        self._scale = self._load_scale()
        self._apply_scale()

        # ---- 提醒气泡：每个提醒一个气泡，多个同时到期时按列排布 ----
        self.bubbles: dict[str, ReminderBubble] = {}
        # ---- 缩小后的图标：点「缩小」后就留一颗星星贴在桌宠旁边 ----
        self.glyphs: dict[str, MiniReminder] = {}
        self._seq: list[str] = []       # 排布顺序：越小越靠前，图标永远在所有气泡之上

        self._long_timer = QTimer(self)
        self._long_timer.setSingleShot(True)
        self._long_timer.setInterval(LONG_PRESS_MS)
        self._long_timer.timeout.connect(self._on_long_press)

        self._restore_pos()

    # ------------------------------------------------------------------ 尺寸
    @property
    def pet_scale(self) -> float:
        return self._scale

    def _load_scale(self) -> float:
        try:
            s = float(self.store.get_setting("pet_scale", 1.0) or 1.0)
        except (TypeError, ValueError):
            s = 1.0
        return max(PET_SCALE_MIN, min(s, self._max_scale()))

    def _max_scale(self) -> float:
        """上限就是桌面：放大到整块可用桌面刚好放得下"""
        avail = self._screen_rect()
        fit = min(avail.width() / float(PET_W), avail.height() / float(PET_H))
        return max(1.0, fit)

    def _apply_scale(self):
        w, h = pet_size(self._scale)
        self.setFixedSize(w, h)
        self.char.setGeometry(0, 0, w, h)
        self._scale_char()

    def _scale_char(self):
        if self._char_pm.isNull():
            return
        self.char.setPixmap(
            self._char_pm.scaled(
                self.width(), self.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _load_closed_eyes(self):
        """加载闭眼素材"""
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "assets" / "pet_closed_eyes.png"
        self._char_pm_closed = QPixmap(str(p))

    def _show_closed_eyes(self):
        """切换到闭眼图片"""
        if self._char_pm_closed.isNull():
            return
        self.char.setPixmap(
            self._char_pm_closed.scaled(
                self.width(), self.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _open_eyes(self):
        """切回睁眼图片"""
        self._scale_char()

    def _blink_step(self):
        """眨眼循环：闭眼 150ms → 睁眼，睁眼停 2500ms 后再闭眼"""
        if getattr(self, "_eyes_closed", False):
            # 当前是闭眼 → 睁眼，2500ms 后再闭眼
            self._open_eyes()
            self._eyes_closed = False
            self._blink_timer.setInterval(2500)
        else:
            # 当前是睁眼 → 闭眼，150ms 后睁眼
            self._show_closed_eyes()
            self._eyes_closed = True
            self._blink_timer.setInterval(150)
        self._blink_timer.start()

    def enterEvent(self, event):
        """鼠标 hover 到桌宠上：等 600ms 后开始循环眨眼"""
        if self._mode == "pet":  # 只有桌宠状态才眨眼
            self._eyes_closed = False
            self._blink_timer.setInterval(600)  # 先等 600ms 再第一次眨眼
            self._blink_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开：停止循环，切回睁眼"""
        self._blink_timer.stop()
        self._eyes_closed = False
        self._open_eyes()
        super().leaveEvent(event)

    def set_pet_scale(self, scale: float):
        """滚轮缩放：底边中点不动，免得越滚越跑"""
        scale = max(PET_SCALE_MIN, min(float(scale), self._max_scale()))
        if abs(scale - self._scale) < 0.01:
            return
        old = self.geometry()
        self._scale = scale
        self._apply_scale()
        x = old.x() + (old.width() - self.width()) // 2
        y = old.y() + (old.height() - self.height())
        self.move(*self._clamp(x, y))
        self.store.set_setting("pet_scale", round(scale, 3))
        self._relayout_bubbles()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if not delta:
            return
        steps = delta / 120.0
        self.set_pet_scale(self._scale * (1.0 + PET_SCALE_STEP * steps))
        event.accept()

    # ------------------------------------------------------------------ 立绘
    def _load_char(self):
        self._char_pm = QPixmap(CHAR_STAND)
        if self._char_pm.isNull():
            self.char.setText("立绘缺失\n请放 assets/char_stand.png")
            self.char.setObjectName("EmptyHint")
            return
        self._scale_char()

    # ------------------------------------------------------------------ 提醒
    def show_reminder(self, todo: dict):
        """一条待办一个气泡；同一个待办重复提醒只更新原气泡"""
        tid = str(todo.get("id") or "")
        if not tid:
            return
        # 之前被缩小的，再提醒时先还原成气泡（避免图标和气泡同时存在）
        if tid in self.glyphs:
            self.restore_reminder(tid)
        minutes = int(self.store.get_setting("snooze_minutes", 10) or 10)
        b = self.bubbles.get(tid)
        if b is None:
            b = ReminderBubble(self.store)
            b.snoozed.connect(lambda m, t=tid: self._on_snooze(t, m))
            b.completed.connect(lambda t=tid: self._on_done(t))
            b.dismissed.connect(lambda t=tid: self.hide_reminder(t))
            b.minimized.connect(lambda t=tid: self.minimize_reminder(t))
            b.minutesChanged.connect(self._on_minutes_changed)
            b.contextRequested.connect(lambda p, t=tid: self.show_reminder_menu(t, p))
            self.bubbles[tid] = b
            if tid not in self._seq:
                self._seq.append(tid)
            # 新气泡用当前默认时长
            b.show_for(todo, minutes)
        else:
            # 已经开着的气泡保留自己选的时长，不跟着全局默认走
            b.show_for(todo)
        self._relayout_bubbles()

    def hide_reminder(self, tid: str | None = None):
        """tid 为空表示全部关掉（桌宠隐藏时用）"""
        if tid is None:
            for b in self.bubbles.values():
                b.hide()
            for g in self.glyphs.values():
                g.hide()
                g.deleteLater()
            self.bubbles.clear()
            self.glyphs.clear()
            self._seq.clear()
            return
        b = self.bubbles.pop(tid, None)
        if b is not None:
            b.hide()
            b.deleteLater()
        g = self.glyphs.pop(tid, None)
        if g is not None:
            g.hide()
            g.deleteLater()
        if tid in self._seq:
            self._seq.remove(tid)
        self._relayout_bubbles()

    def visible_bubbles(self) -> list[ReminderBubble]:
        return [b for b in self.bubbles.values() if b.isVisible()]

    # ------------------------------------------------------------- 缩小 / 还原
    def minimize_reminder(self, tid: str) -> None:
        """气泡收成桌宠旁边的一颗小星星；原来的气泡只隐藏不销毁，稍后时长等状态都留着"""
        b = self.bubbles.get(tid)
        if b is None:
            return
        g = self.glyphs.get(tid)
        if g is None:
            g = MiniReminder()
            g.activated.connect(lambda t=tid: self.restore_reminder(t))
            g.menuRequested.connect(lambda t=tid: self.show_glyph_menu(t))
            self.glyphs[tid] = g
        g.set_title(b.title.text())
        b._detached = False  # 收成星星后再还原，卡片重新贴回桌宠身边，不记自由位置
        b.hide()
        g.show()
        g.raise_()
        self._promote(tid)
        self._relayout_bubbles()

    def restore_reminder(self, tid: str) -> None:
        """点小星星 → 图标消失、气泡回来，并排到所有气泡的最前面（仍在图标下面）"""
        g = self.glyphs.pop(tid, None)
        if g is not None:
            g.hide()
            g.deleteLater()
        b = self.bubbles.get(tid)
        if b is None:
            self._relayout_bubbles()
            return
        self._promote(tid)
        b.show()
        b.raise_()
        self._relayout_bubbles()

    def minimize_all(self) -> None:
        """一键缩小：所有还开着的提醒气泡都收成桌宠旁边的小星星"""
        for tid, b in list(self.bubbles.items()):
            if tid in self.glyphs or not b.isVisible():
                continue
            self.minimize_reminder(tid)
        self._relayout_bubbles()

    def restore_all(self) -> None:
        """一键打开：所有收起的小星星都展开回气泡"""
        for tid in list(self.glyphs):
            self.restore_reminder(tid)
        self._relayout_bubbles()

    def _reminder_menu(self) -> tuple[QMenu, object, object, object, object]:
        """提醒右键菜单（气泡和星星共用）：
        一键打开 / 一键缩小 / 关闭此提醒 / 关闭目前所有提醒
        """
        menu = QMenu(self)
        menu.setObjectName("PetMenu")
        round_menu(menu)
        act_open = menu.addAction(icon("inbox", C.INK_2, 15), "一键打开")
        act_min = menu.addAction(icon("chevron_down", C.INK_2, 15), "一键缩小")
        menu.addSeparator()
        act_close = menu.addAction(icon("close", C.INK_2, 15), "关闭此提醒")
        act_close_all = menu.addAction(icon("trash", C.INK_2, 15), "关闭目前所有提醒")
        return menu, act_open, act_min, act_close, act_close_all

    # 老名字保留：测试和别处还在按名字调
    _glyph_menu = _reminder_menu

    def _menu_pos(self, pos: QPoint, menu: QMenu) -> QPoint:
        """菜单夹在屏幕可用区里，别跑到屏幕外"""
        avail = self._screen_rect()
        hint = menu.sizeHint()
        x = max(avail.left(), min(pos.x(), avail.right() + 1 - hint.width()))
        y = max(avail.top(), min(pos.y(), avail.bottom() + 1 - hint.height()))
        return QPoint(int(x), int(y))

    def show_reminder_menu(self, tid: str, pos: QPoint) -> None:
        """气泡或星星上右键：在哪张卡片上点，就在哪儿弹这套四项菜单"""
        menu, act_open, act_min, act_close, act_close_all = self._reminder_menu()
        chosen = menu.exec(self._menu_pos(pos, menu))
        if chosen is act_open:
            self.restore_all()
        elif chosen is act_min:
            self.minimize_all()
        elif chosen is act_close:
            self.hide_reminder(tid)
        elif chosen is act_close_all:
            self.hide_reminder()

    def show_glyph_menu(self, tid: str) -> None:
        """右键单击小星星：菜单弹在星星下方"""
        g = self.glyphs.get(tid)
        anchor = g.pos() if g is not None else self.pos()
        self.show_reminder_menu(tid, QPoint(anchor.x(), anchor.y() + GLYPH_SIZE + 2))

    def _promote(self, tid: str) -> None:
        """把某条提到序列最前：图标段永远在前，所以还原的气泡会落在图标下面、气泡组最上面"""
        if tid in self._seq:
            self._seq.remove(tid)
        self._seq.insert(0, tid)

    def _ordered_tids(self) -> list[str]:
        known = [t for t in self._seq if t in self.glyphs or t in self.bubbles]
        rest = [t for t in list(self.glyphs) + list(self.bubbles) if t not in known]
        return known + rest

    @staticmethod
    def _step_after(kind: int, h: int) -> int:
        """下一项的窗口顶边相对当前顶边的位移：图标之间留 GLYPH_GAP，气泡之间按 BUBBLE_GAP 吃掉白边"""
        if kind == 0:
            return h + GLYPH_GAP
        return max(24, h + BUBBLE_GAP - BUBBLE_SHADOW * 2)

    def _col_height(self, items: list, step_after) -> int:
        """一列叠起来的真实总高：每项的高度 + 项与项之间的净间距

        step_after 给的是"下一项顶边相对上皮顶边"的位移，减去上皮高度才是净间距
        （气泡之间会吃掉投影白边，间距是负的）。
        """
        if not items:
            return 0
        total = items[0][2]
        for i in range(1, len(items)):
            pk, ph = items[i - 1][0], items[i - 1][2]
            total += (step_after(pk, ph) - ph) + items[i][2]
        return total

    def _pack_cols(self, items: list, capacity: int, step_after) -> int:
        """这些项从上往下叠，要几列才装得下"""
        cols = 1
        cur: list = []
        for item in items:
            if cur and self._col_height(cur + [item], step_after) > capacity:
                cols += 1
                cur = [item]
            else:
                cur.append(item)
        return cols

    def _shrink_to_fit(self, order, glyphs, bubbles, capacity: int, ncols: int, step_after) -> bool:
        """屏幕上放不下时，按顺序把第 1 张、第 2 张…气泡收成小星星腾地方

        星星只有 38px 高，比一整张卡片省得多。收完这一轮会自己再排一次，
        还放不下就接着收下一张，直到塞得进为止。
        返回 True 表示已经收过，调用方别再排了（重排已经在里面做完）。
        """
        if getattr(self, "_shrink_guard", False) or not bubbles:
            return False
        items = [(0, g, GLYPH_SIZE) for g in glyphs] + [(1, b, b.height()) for b in bubbles]
        if self._pack_cols(items, capacity, step_after) <= ncols \
                and max((it[2] for it in items), default=0) <= capacity:
            return False

        tids = [
            t for t in order
            if t in self.bubbles and t not in self.glyphs
            and not self.bubbles[t]._detached
        ]
        sim = list(items)
        k = 0
        while k < len(tids):
            if self._pack_cols(sim, capacity, step_after) <= ncols \
                    and max((it[2] for it in sim), default=0) <= capacity:
                break
            idx = next((i for i, it in enumerate(sim) if it[0] == 1), None)
            if idx is None:
                break
            sim[idx] = (0, None, GLYPH_SIZE)
            k += 1
        if k == 0:
            return False

        self._shrink_guard = True
        try:
            for tid in tids[:k]:
                self.minimize_reminder(tid)
        finally:
            self._shrink_guard = False
        self._relayout_bubbles()
        return True

    def _relayout_bubbles(self):
        """提醒的排布：

        · 桌宠在场：缩小图标贴着桌宠竖排，跟着桌宠走，展开的气泡接着往下排；
        · 主窗口形态：提醒先收起来，等桌宠回来再贴回它身边；
        · 桌宠和窗口都没有（都收进任务栏）：全部挪到桌面右下角，从下往上一个个排。
        """
        order = self._ordered_tids()
        glyphs: list[MiniReminder] = [self.glyphs[t] for t in order if t in self.glyphs]
        # 气泡只算"还没收成星星"的：收起来的那条由星星代表
        all_bubbles: list[ReminderBubble] = [
            self.bubbles[t] for t in order if t in self.bubbles and t not in self.glyphs
        ]
        # 被手动拖离的卡片停在自由位置，不跟着桌宠重新排布
        detached = [b for b in all_bubbles if b._detached]
        bubbles: list[ReminderBubble] = [b for b in all_bubbles if not b._detached]
        if not glyphs and not all_bubbles:
            return

        if self._mode == "window":
            for w in list(glyphs) + list(all_bubbles):
                w.hide()
            return
        if self._mode == "tray":
            for g in glyphs:
                g.show()
            for b in all_bubbles:
                b.show()
            self._dock_reminders(glyphs, all_bubbles)
            return
        if not self.isVisible():
            # 切形态的中间态（桌宠还没 show 出来）：先收着，别闪到右下角
            for w in list(glyphs) + list(all_bubbles):
                w.hide()
            return

        # 桌宠在场：该显示的显示出来，再贴到它身边；拖离的卡片只保持原位
        for g in glyphs:
            g.show()
        for b in all_bubbles:
            b.show()

        geo = self.frameGeometry()
        avail = self._screen_rect()
        w = max([b.width() for b in bubbles], default=GLYPH_SIZE)
        usable_top = avail.top() + 8
        usable_bottom = avail.bottom() + 1

        step_after = self._step_after
        step_x = max(40, w + BUBBLE_GAP - BUBBLE_SHADOW * 2)

        # 候选列：优先桌宠左侧，其次右侧；左侧逐列向外
        cols: list[int] = []
        x = geo.x() - w - 4
        while x >= avail.left():
            cols.append(x)
            x -= step_x
        x = geo.x() + geo.width() + 4
        while x + w <= avail.right() + 1:
            cols.append(x)
            x += step_x
        if not cols:
            cols = [max(avail.left(), min(geo.x() - w - 4, avail.right() - w + 1))]
        # 只保留一个列宽都能放下的
        cols = [c for c in cols if c + w <= avail.right() + 1] or cols[:1]

        # 屏幕就这么多地方：先按顺序把放不下的气泡收成小星星，收完再排
        if self._shrink_to_fit(order, glyphs, bubbles, usable_bottom - usable_top,
                               len(cols), step_after):
            return

        # (kind, 控件, 高)：0 = 缩小图标，1 = 气泡
        items: list[tuple[int, QWidget, int]] = []
        items += [(0, g, GLYPH_SIZE) for g in glyphs]
        items += [(1, b, b.height()) for b in bubbles]

        # 按"一列能装几个"分组（用真实总高判断，气泡之间吃掉白边后间距是负的）
        groups: list[list[tuple[int, QWidget, int]]] = [[]]
        capacity = usable_bottom - usable_top
        for item in items:
            if groups[-1] and self._col_height(groups[-1] + [item], step_after) > capacity:
                groups.append([])
            groups[-1].append(item)
        if not groups[-1]:
            groups.pop()

        y_anchor = max(usable_top, min(geo.y() + 16, usable_bottom))
        for gi, group in enumerate(groups):
            col_x = cols[min(gi, len(cols) - 1)]
            total = self._col_height(group, step_after)
            y = max(usable_top, min(y_anchor, usable_bottom - total))
            prev_kind = prev_h = 0
            for i, (kind, obj, h) in enumerate(group):
                if i:
                    y += step_after(prev_kind, prev_h)
                x = col_x
                if kind == 0:
                    # 小星星贴向桌宠那一侧：左列靠右边缘，右列靠左边缘
                    x = col_x + (w - GLYPH_SIZE) if col_x <= geo.x() else col_x
                obj.move(int(x), int(y))
                prev_kind, prev_h = kind, h

    def _dock_reminders(self, glyphs: list[MiniReminder], bubbles: list[ReminderBubble]):
        """桌宠不在（收进任务栏）时的排布：右下角贴边，星星在最下，气泡一个个往上叠。

        放不下整屏时向左开新列，避免跑到屏幕外。
        """
        avail = self._screen_rect()
        right = avail.right() + 1 - DOCK_MARGIN          # 右对齐基准（窗口右边缘）
        bottom = avail.bottom() + 1 - DOCK_MARGIN        # 从下往上排的起点
        top = avail.top() + 8
        w = max([b.width() for b in bubbles], default=GLYPH_SIZE)

        # 右下角这块地方也有限：放不下照样按顺序收成小星星
        col_w = max(1, w - BUBBLE_SHADOW * 2 + BUBBLE_GAP)
        ncols = max(1, int((right - avail.left()) // col_w))
        if self._shrink_to_fit(self._ordered_tids(), glyphs, bubbles,
                               bottom - top, ncols, self._step_after):
            return

        # ---- 小星星：右下角往上叠 ----
        icon_x = right - GLYPH_SIZE
        y_bottom = bottom
        for g in glyphs:
            y = y_bottom - GLYPH_SIZE
            if y < top:                                   # 一列放满就向左挪一列
                icon_x = max(avail.left(), icon_x - GLYPH_SIZE - 6)
                y_bottom = bottom
                y = y_bottom - GLYPH_SIZE
            g.move(int(icon_x), int(y))
            y_bottom = y - GLYPH_GAP
        icons_top = y_bottom + GLYPH_GAP if glyphs else bottom

        # ---- 气泡：星星上面接着往上排 ----
        base = (icons_top - BUBBLE_GAP) if glyphs else bottom
        x_b = right - w
        y_bottom = base
        for b in bubbles:
            h = b.height()
            y = y_bottom - h
            if y < top:                                   # 放满了就向左开新列（不越出桌面左边缘）
                x_b = max(avail.left(), x_b - (w - BUBBLE_SHADOW * 2 + BUBBLE_GAP))
                y_bottom = bottom
                y = y_bottom - h
            b.move(int(x_b), int(y))
            y_bottom = y + BUBBLE_SHADOW * 2 - BUBBLE_GAP

    def _on_done(self, tid: str):
        self.doneRequested.emit(tid)
        self.hide_reminder(tid)

    def _on_snooze(self, tid: str, minutes: int | None = None):
        self.snoozeRequested.emit(tid, int(minutes or 10))
        self.hide_reminder(tid)

    def _on_minutes_changed(self, minutes: int):
        """只影响这条气泡；新时长已写进设置，之后新弹出的默认用它"""
        self._relayout_bubbles()

    # ------------------------------------------------------------------ 位置
    def set_reminder_mode(self, mode: str):
        """pet：贴桌宠；window：先收起（等回桌宠再现）；tray：右下角从下往上"""
        self._mode = mode
        self._relayout_bubbles()

    def _screen_rect(self) -> QRect:
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _restore_pos(self):
        pos = self.store.get_setting("pet_pos")
        avail = self._screen_rect()
        if pos and isinstance(pos, (list, tuple)) and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
        else:
            x = avail.right() - self.width() - 24
            y = avail.bottom() - self.height() - 24
        self.move(*self._clamp(x, y))

    def _clamp(self, x: int, y: int) -> tuple[int, int]:
        avail = self._screen_rect()
        x = max(avail.left(), min(x, avail.right() - self.width() + 1))
        y = max(avail.top(), min(y, avail.bottom() - self.height() + 1))
        return x, y

    def hideEvent(self, event):
        # 桌宠收进任务栏 / 切到主窗口：提醒先按当前模式重排（窗口模式会先收起来）
        super().hideEvent(event)
        self._relayout_bubbles()

    def showEvent(self, event):
        # 桌宠回来后，之前开着的气泡 / 缩小图标重新贴回桌宠身边
        super().showEvent(event)
        self._relayout_bubbles()
        # 显示后抬回置顶层，避免层级回落
        self.raise_()

    def event(self, ev):
        # 字号档位一改，全局 QSS 会重新贴一遍样式，这里跟着把气泡的高度重量一次：
        # 气泡高度是按旧字号钉死的，不重量就会「字变大、卡片没变高」，标题被裁。
        if ev.type() == QEvent.Type.StyleChange \
                and (getattr(self, "bubbles", None) or getattr(self, "glyphs", None)):
            QTimer.singleShot(0, self._reflow_after_style_change)
        return super().event(ev)

    def _reflow_after_style_change(self):
        for b in list(getattr(self, "bubbles", {}).values()):
            b.refresh_font()
        for g in list(getattr(self, "glyphs", {}).values()):
            g.update()
        if getattr(self, "bubbles", None) or getattr(self, "glyphs", None):
            self._relayout_bubbles()

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.bubbles or self.glyphs:
            self._relayout_bubbles()

    # ------------------------------------------------------------------ 鼠标
    def _pet_menu(self) -> tuple[QMenu, object, object, object]:
        """桌宠右键菜单：最小化到任务栏 / 显示待办窗口 / 退出"""
        menu = QMenu(self)
        menu.setObjectName("PetMenu")
        round_menu(menu)
        act_min = menu.addAction(icon("chevron_down", C.INK_2, 15), "最小化到任务栏")
        act_win = menu.addAction(icon("inbox", C.INK_2, 15), "显示待办窗口")
        menu.addSeparator()
        act_quit = menu.addAction(icon("close", C.INK_2, 15), "退出")
        return menu, act_min, act_win, act_quit

    def contextMenuEvent(self, event):
        menu, act_min, act_win, act_quit = self._pet_menu()
        chosen = menu.exec(event.globalPos())
        if chosen is act_min:
            self.minimizeToTray.emit()
        elif chosen is act_win:
            self.enterWindowMode.emit()
        elif chosen is act_quit:
            self.quitRequested.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._win_start = self.pos()
            self._dragging = True
            self._drag_moved = False
            self._long_ready = False
            self._long_timer.start()
        super().mousePressEvent(event)

    def _on_long_press(self):
        if self._dragging:
            self._long_ready = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if not self._dragging or not self._long_ready:
            return
        delta = event.globalPosition().toPoint() - self._press_global
        if not self._drag_moved and (abs(delta.x()) > 2 or abs(delta.y()) > 2):
            self._drag_moved = True
        self.move(*self._clamp(self._win_start.x() + delta.x(),
                               self._win_start.y() + delta.y()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._long_timer.stop()
        was_dragging = self._dragging
        self._dragging = False
        self.unsetCursor()

        if event.button() == Qt.MouseButton.LeftButton and was_dragging:
            if self._drag_moved:
                self.store.set_setting("pet_pos", [self.x(), self.y()])
            elif not self._long_ready:
                self.enterWindowMode.emit()
        super().mouseReleaseEvent(event)
