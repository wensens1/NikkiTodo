"""
widgets/main_window.py —— 主窗口（窗口状态）

结构（全部尺寸由下面常量推导）：
  · 窗口 432 x 576，卡片 300 x 460，右侧 / 底部留 16px 给投影
  · 卡片左上角压着趴着的立绘（立绘是透明窗口的一部分）
  · 卡片左侧贴着一列白色标签页：待办 / 各个便签 / ＋（左边圆角，右边接在卡片上）
  · 卡片内：顶栏图标 → 时间日期 → 待办输入 → 列表 / 便签页 → 已完成折叠
  · 收成桌宠只走顶栏的缩小按钮；窗口贴着屏幕边/角时，桌宠也跟着贴那边/那个角

视觉全部来自 theme.py，本文件不写任何内联颜色。
"""

from __future__ import annotations

import html
import time
from datetime import datetime

from PyQt6.QtCore import (
    QEvent, QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, QSize, QTimer, Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from theme import C, app_qss, set_font_scale
from ui_icons import IconButton, icon
from ui_utils import CHAR_LIE, BottomFade, add_shadow, round_menu
from search import filter_notes, filter_todos
from widgets.controls import EmptyState, repolish
from widgets.dialogs import FindDialog, TodoEditDialog
from widgets.pet_window import PET_H, PET_W, pet_anchor, pet_size
from widgets.text_menu import TextContextMenu
from widgets.todo_item import TodoItem

# ---- 几何（改尺寸只改这里）----
WIN_W, WIN_H = 432, 576          # 窗口整体（含透明留白）
CARD_X, CARD_Y = 116, 100        # 卡片在窗口内的位置
CARD_W, CARD_H = 300, 460        # 卡片本体默认尺寸
CARD_RIGHT_GAP = 16
CARD_BOTTOM_GAP = 16
SIDE_W, SIDE_H = 78, 48          # 侧栏标签页
SIDE_X = CARD_X - SIDE_W + 1     # 右侧压进卡片 1px，去掉接缝（胶囊列在左边时）
SIDE_Y = 218
SIDE_BOTTOM_GAP = 22             # 侧栏最低点：卡片底部圆角(R_CARD=20)起点之上再让 2px
SIDE_TOP_MIN = CARD_Y + 24       # 侧栏最高点：卡片顶部圆角下缘再留 4px
CHAR_X, CHAR_Y = 136, 10         # 立绘位置：从 96 再右移 40px，落进卡片左上区
CHAR_W, CHAR_H = 132, 180        # 高度沿用 180，宽度按新立绘 441x600 的比例

# ---- 胶囊列左右翻转（贴左屏边会挡住胶囊，整列翻到卡片右边；挪开了再翻回来）----
SIDE_EXTRA_W = SIDE_W - 1        # 翻到右边时窗口要多出来的宽度（胶囊同样压进卡片 1px）
WIN_W_FLIP = WIN_W + SIDE_EXTRA_W   # 509：胶囊列翻到右边后的默认窗口宽度
FLIP_LOSE_PX = 6                 # 被屏幕边压掉这么多像素就翻面（留滞回，不会来回抖）
FLIP_BACK_PX = 24                # 翻回来要求原位腾出这么多空闲：6 翻出去、24 翻回来，中间 18px 不抖
SIDE_PEEK = 20                    # 抽屉收起时仍露在卡片外的宽度（约能看到胶囊圆角和一点粉底，不喧宾夺主）

# ---- 贴边判定（点缩小按钮时，桌宠跟着贴哪条边 / 哪个角）----
EDGE_TOUCH_PX = 2                # 可见内容离屏幕边这么近就算「贴着」（和贴边时窗口本身的位置容差一致）

# ---- 角色中心锚点（桌宠 ↔ 主窗口切换时两边的角色中心必须落在同一点）----
MAIN_CHAR_CX = CHAR_X + CHAR_W // 2   # 202：主窗口内角色中心 x
MAIN_CHAR_CY = CHAR_Y + CHAR_H // 2   # 100：主窗口内角色中心 y


def window_pos_for_pet(pet_x: int, pet_y: int, pet_scale: float = 1.0) -> tuple[int, int]:
    """桌宠位置 → 主窗口左上角（桌宠角色中心 = 主窗口角色中心）"""
    cx, cy = pet_anchor(pet_scale)
    return (
        int(pet_x + cx - MAIN_CHAR_CX),
        int(pet_y + cy - MAIN_CHAR_CY),
    )


def pet_pos_for_window(win_x: int, win_y: int, pet_scale: float = 1.0) -> tuple[int, int]:
    """主窗口左上角 → 桌宠位置（主窗口角色中心 = 桌宠角色中心）"""
    cx, cy = pet_anchor(pet_scale)
    return (
        int(win_x + MAIN_CHAR_CX - cx),
        int(win_y + MAIN_CHAR_CY - cy),
    )

WEEK_CN = "一二三四五六日"


# --------------------------------------------------------------------------- #
#  小部件
# --------------------------------------------------------------------------- #
NOTE_DRAG_HOLD_MS = 200     # 侧栏便签：按住多久算「要拖动换位」
NOTE_DRAG_MOVE_MS = 120     # 已经按住这么久再滑动，也算要拖动


class _NoteSideBtn(QPushButton):
    """侧栏便签按钮：单击切换，双击变输入框更名，长按拖动换位"""

    renamed = pyqtSignal(object)
    dragBegin = pyqtSignal(object)          # self
    dragMoved = pyqtSignal(object, QPoint)  # self, 鼠标全局坐标
    dragEnd = pyqtSignal(object)            # self

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_pos: QPoint | None = None
        self._press_at = 0.0
        self._dragging = False
        self._skip_release = False      # 双击改名之后的那次松手，不算单击
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(NOTE_DRAG_HOLD_MS)
        self._hold.timeout.connect(self._start_drag)

    def _start_drag(self):
        if self._press_pos is None:
            return
        self._dragging = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.dragBegin.emit(self)
        self.dragMoved.emit(self, self.mapToGlobal(self.rect().center()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._press_at = time.monotonic()
            self._hold.start()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is None:
            return
        if self._dragging:
            self.dragMoved.emit(self, event.globalPosition().toPoint())
            return
        moved = (event.globalPosition().toPoint() - self._press_pos).manhattanLength()
        if moved > 8:
            # 已经按住够久再滑，也算要拖动；一按就滑才是普通点击
            if time.monotonic() - self._press_at >= NOTE_DRAG_MOVE_MS / 1000:
                self._start_drag()
                self.dragMoved.emit(self, event.globalPosition().toPoint())
                return
            self._hold.stop()
            self._press_pos = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._hold.stop()
        self._press_pos = None
        if getattr(self, "_skip_release", False):
            self._skip_release = False
            self.setDown(False)
            event.accept()
            return
        if self._dragging:
            self._dragging = False
            self.unsetCursor()
            self.dragEnd.emit(self)
            event.accept()     # 拖完这一下不当成点击
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # 双击 = 原地改名：停掉长按计时，别让「按住不动」变成拖动
        self._hold.stop()
        self._press_pos = None
        self._skip_release = True     # 双击后的那次松手不要当成普通单击（否则会顺手切页）
        self.renamed.emit(self)
        event.accept()


class _SidePillEdit(QLineEdit):
    """侧栏便签原地改名：Enter 确认、Esc 取消、点别处也算确认"""

    cancelled = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _PlainPasteEdit(QTextEdit):
    """粘贴只取纯文本

    从网页 / Word / 微信里复制过来的文字，原样带着自己的字号、颜色、加粗，
    粘进白底的输入框就会出现"字是白的，看不见"这种事。统一只取纯文本，
    外部格式一律不带进来（拖放同理）。
    """

    def insertFromMimeData(self, source):
        if source is not None and source.hasText():
            self.insertPlainText(source.text())
            return
        super().insertFromMimeData(source)


class _TodoInput(_PlainPasteEdit):
    """Enter 创建待办，Ctrl+Enter 换行；焦点变化时通知外壳画蓝边"""

    submitted = pyqtSignal()
    focusChanged = pyqtSignal(bool)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.insertPlainText("\n")
                return
            self.submitted.emit()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focusChanged.emit(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focusChanged.emit(False)


class _InputHint(QFrame):
    """输入框上方悬浮提示：深色圆角小条 + 键帽"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InputHint")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 7, 12, 7)
        lay.setSpacing(6)

        for key, text in (("Enter", "添加"), ("Ctrl+Enter", "换行")):
            if lay.count():
                dot = QLabel("·", self)
                dot.setObjectName("HintDot")
                lay.addWidget(dot)
            key_label = QLabel(key, self)
            key_label.setObjectName("HintKey")
            lay.addWidget(key_label)
            text_label = QLabel(text, self)
            text_label.setObjectName("HintText")
            lay.addWidget(text_label)

        add_shadow(self, blur=18, dy=0, alpha=55)


class _Resizer(QWidget):
    """卡片右下角 / 右缘 / 下缘的缩放手柄

    角手柄固定在卡片右下角（胶囊列翻到卡片右边时也是这样，那列胶囊在卡片外面，
    不挡热区）；只有右缘那条细手柄在翻面时让位收起来，免得压住胶囊。
    """

    def __init__(self, target, mode="corner", parent=None):
        super().__init__(parent)
        self._target = target
        self._mode = mode
        self._origin = None
        self._start_size = None
        if mode == "corner":
            self.setFixedSize(28, 28)
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif mode == "right":
            self.setFixedSize(6, 100)
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setFixedSize(100, 6)
            self.setCursor(Qt.CursorShape.SizeVerCursor)

    def paintEvent(self, event):
        if self._mode != "corner":
            return
        from PyQt6.QtGui import QColor, QPainter, QPen

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(C.LINE_STRONG))
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for offset in (0, 5, 10):
            p.drawLine(
                self.width() - 8 - offset, self.height() - 6,
                self.width() - 6, self.height() - 8 - offset,
            )
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.globalPosition().toPoint()
            self._start_size = self._target.size()

    def mouseMoveEvent(self, event):
        if self._origin is None:
            return
        delta = event.globalPosition().toPoint() - self._origin
        w = self._start_size.width()
        h = self._start_size.height()
        # 最小尺寸跟着当前胶囊列在哪一侧变（翻到右边时窗口下限更宽）
        if self._mode in ("corner", "right"):
            w = max(self._target.minimumWidth(), w + delta.x())
        if self._mode in ("corner", "bottom"):
            h = max(self._target.minimumHeight(), h + delta.y())
        self._target.resize(w, h)

    def mouseReleaseEvent(self, event):
        self._origin = None


class _NoteScrollBar(QWidget):
    """便签视口右缘那条细指示条（独立子控件，才盖在胶囊上面）"""

    def __init__(self, view):
        super().__init__(view)
        self._view = view
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        v = self._view
        if not v._bar_visible or v._max_offset() <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.PRIMARY))
        h = v.height()
        track = h - 8
        thumb = max(22, int(track * (h / float(v._content_h))))
        y = 4 + int((track - thumb) * (v._offset / v._max_offset()))
        x = 1.0 if v._bar_on_right else self.width() - 4.0
        p.drawRoundedRect(QRectF(x, y, 3.0, thumb), 1.5, 1.5)
        p.end()


class _NoteView(QWidget):
    """便签胶囊的滚动视口：内容比视口高时用滚轮上下滚，右缘一条细指示条

    不用 QScrollArea：它的 viewport 会把子控件的 QSS 底色洗掉（胶囊会变透明）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._holder = None
        self._content_h = 0
        self._offset = 0.0
        self._bar_on_right = True
        self._bar_visible = True
        self._bar = _NoteScrollBar(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._bar_on_right:
            self._bar.setGeometry(self.width() - 5, 0, 5, self.height())
        else:
            self._bar.setGeometry(0, 0, 5, self.height())
        self._bar.raise_()

    def set_content(self, holder: QWidget | None, content_h: int = None):
        if holder is not None:
            self._holder = holder
        if content_h is not None:
            self._content_h = content_h
        self._offset = min(self._offset, float(self._max_offset()))
        self._apply()
        self._bar.raise_()          # holder 后加进来会盖住指示条，这里再抬一次
        self.update()
        self._bar.update()

    def _max_offset(self) -> int:
        return max(0, self._content_h - self.height())

    def _apply(self):
        if self._holder is not None:
            self._holder.move(0, -int(self._offset))

    def ensure_row_visible(self, row: int, row_h: int):
        if row < 0:
            return
        top = row * row_h
        bottom = top + row_h
        if top < self._offset:
            self._offset = float(top)
        elif bottom > self._offset + self.height():
            self._offset = float(bottom - self.height())
        self._offset = max(0.0, min(float(self._max_offset()), self._offset))
        self._apply()
        self.update()
        self._bar.update()

    def wheelEvent(self, event):
        if self._max_offset() <= 0:
            event.ignore()
            return
        dy = event.angleDelta().y()
        self._offset = max(
            0.0, min(float(self._max_offset()), self._offset - dy * 0.4)
        )
        self._apply()
        self.update()
        self._bar.update()
        event.accept()


# --------------------------------------------------------------------------- #
#  主窗口
# --------------------------------------------------------------------------- #
class MainWindow(QWidget):
    enterPetMode = pyqtSignal()
    hideToTray = pyqtSignal()       # 点 × 把窗口收进托盘：此时窗口和桌宠都不在，提醒该落右下角
    todoDoneChanged = pyqtSignal(str)  # 点完成/取消完成时发出，参数是 tid
    todoDeleted = pyqtSignal(str)       # 点删除时发出，参数是 tid

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._include_done = False
        self._edit_dialog_open = False
        self.current_note: dict | None = None
        self._note_rename_edit = None      # 正在原地改名的便签输入框（点空白就提交它）

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("NikkiTodo")
        self._side = "left"          # 胶囊列在哪一侧：left（默认）/ right（贴左屏边时翻过来）
        # 胶囊列抽屉：鼠标在卡片 / 胶囊列上时整列像抽屉一样拉出来，离开就整列缩进卡片
        self._pills_open = True
        self._pill_anim = None
        self._pill_timer = QTimer(self)
        self._pill_timer.setInterval(120)
        self._pill_timer.timeout.connect(self._poll_pill_hover)
        # 键盘焦点进侧栏时也把抽屉拉开（不然 Tab 切到被卡片压住的胶囊，看不出焦点在哪）
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_app_focus_changed)
        self._win_drag = None        # 卡片拖动状态：{press: 按下时全局坐标, xy: 按下时窗口位置, moved}
        # Ctrl+F 查找：待办页存命中的条目控件，便签页存命中的便签 dict
        self._find_matches: list = []
        self._find_index = -1
        self._find_dlg: FindDialog | None = None
        self._find_hl_item: TodoItem | None = None
        # 贴边自动缩小（可在设置里关掉）：贴边后鼠标移开自动收成桌宠，
        # 拖动过程中 / 拖手柄改大小都不会触发
        self._is_edge_touched = False
        self.setMinimumSize(WIN_W, WIN_H)
        self.resize(WIN_W, WIN_H)

        self._build_card()
        self._build_sidebar()
        self._build_char()
        self._build_resizers()
        self._bind_notes()
        self._restore_pos()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()
        # 全局拦截 Ctrl+F：焦点在待办输入框 / 便签正文里也能唤起查找条
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.refresh()

    # ------------------------------------------------------------------ 卡片
    def _build_card(self):
        self.card = QFrame(self)
        self.card.setObjectName("Card")
        self.card.setProperty("side", self._side)
        self.card.setGeometry(CARD_X, CARD_Y, CARD_W, CARD_H)
        add_shadow(self.card, blur=20, dy=0, alpha=38)
        self.card.installEventFilter(self)

        root = QVBoxLayout(self.card)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(0)

        # ---- 顶栏 ----
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(2)
        top_row.addStretch(1)

        self.btn_settings = IconButton(
            "settings", color=C.INK_2, hover=C.INK,
            size=28, icon_size=16, object_name="BtnTopBar",
            tooltip="设置", parent=self.card,
        )
        self.btn_min = IconButton(
            "minus", color=C.INK_2, hover=C.INK,
            size=28, icon_size=16, object_name="BtnTopBar",
            tooltip="收成桌宠", parent=self.card,
        )
        self.btn_close = IconButton(
            "close", color=C.INK_2, hover=C.DANGER,
            size=28, icon_size=16, object_name="BtnTopBar",
            tooltip="关闭", parent=self.card,
        )
        self.btn_close.setProperty("kind", "danger")
        self.btn_settings.clicked.connect(self.on_settings)
        self.btn_min.clicked.connect(self._minimize_to_pet)
        self.btn_close.clicked.connect(self.on_close)
        for b in (self.btn_settings, self.btn_min, self.btn_close):
            top_row.addWidget(b)
        root.addLayout(top_row)

        root.addSpacing(2)

        # ---- 时间 / 日期 / 待办数量（右对齐，避开左上角立绘）----
        clock_box = QVBoxLayout()
        clock_box.setContentsMargins(0, 0, 2, 0)
        clock_box.setSpacing(1)

        self.time_label = QLabel("--:--", self.card)
        self.time_label.setObjectName("TimeLabel")
        self.time_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        clock_box.addWidget(self.time_label)

        # 日期行：右边是日期
        date_row = QHBoxLayout()
        date_row.setContentsMargins(0, 0, 0, 0)
        date_row.setSpacing(8)
        date_row.addStretch(1)
        self.date_label = QLabel("", self.card)
        self.date_label.setObjectName("DateLabel")
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        date_row.addWidget(self.date_label, 0, Qt.AlignmentFlag.AlignVCenter)
        clock_box.addLayout(date_row)
        root.addLayout(clock_box)

        # 文字不接鼠标，按住时间区域也能拖窗口
        for w in (self.time_label, self.date_label):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        root.addSpacing(12)

        # ---- 待办输入 ----
        shell = QFrame(self.card)
        shell.setObjectName("InputShell")
        shell.setFixedHeight(46)
        self.input_shell = shell
        sh = QHBoxLayout(shell)
        sh.setContentsMargins(14, 0, 6, 0)
        sh.setSpacing(2)

        self.todo_input = _TodoInput(shell)
        self.todo_input.setObjectName("TodoInput")
        self.todo_input.setPlaceholderText("记一条待办…")
        self.todo_input.setFixedHeight(44)
        self.todo_input.document().setDocumentMargin(0)
        self.todo_input.submitted.connect(self.on_add_todo)
        self.todo_input.focusChanged.connect(self._on_input_focus)
        self.todo_input.textChanged.connect(self._hide_input_hint)
        sh.addWidget(self.todo_input, 1)

        self.bell_btn = IconButton(
            "bell", color=C.INK_3, hover=C.PRIMARY,
            size=32, icon_size=17, object_name="BellBtn",
            tooltip="带提醒时间新建", parent=shell,
        )
        self.bell_btn.clicked.connect(self.on_bell_new_todo)
        sh.addWidget(self.bell_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(shell)

        # 输入框悬停提示：放在输入框上方，避免被鼠标挡住
        self._input_hint = _InputHint(self)
        self._input_hint.hide()
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.setInterval(450)
        self._hint_timer.timeout.connect(self._show_input_hint)
        self.todo_input.installEventFilter(self)
        self.todo_input.viewport().installEventFilter(self)

        root.addSpacing(10)

        # ---- 内容页 ----
        self.pages = QStackedWidget(self.card)
        root.addWidget(self.pages, 1)

        # 待办页
        self.page_todo = QWidget(self.pages)
        tl = QVBoxLayout(self.page_todo)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)

        self.scroll = QScrollArea(self.page_todo)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.todo_holder = QWidget(self.scroll)
        self.todo_layout = QVBoxLayout(self.todo_holder)
        self.todo_layout.setContentsMargins(0, 0, 2, 0)
        self.todo_layout.setSpacing(8)
        self.scroll.setWidget(self.todo_holder)
        self.scroll.viewport().installEventFilter(self)
        self.todo_holder.installEventFilter(self)
        self.scroll.installEventFilter(self)
        tl.addWidget(self.scroll, 1)

        # 视口底边的渐隐：滚动区把列表按像素裁断时，被裁到的那行文字只剩顶部一行像素，
        # 在 125% 缩放下会显成一串彩色小点，这里用卡片底色把它柔化掉
        self.scroll_fade = BottomFade(self.scroll, C.BG)
        self.scroll_fade.hide()
        sb = self.scroll.verticalScrollBar()
        sb.valueChanged.connect(self._update_scroll_fade)
        sb.rangeChanged.connect(lambda *_: self._update_scroll_fade())

        tl.addSpacing(6)
        fold_row = QHBoxLayout()
        fold_row.setContentsMargins(0, 0, 0, 0)
        fold_row.setSpacing(8)
        self.btn_fold = QPushButton(self.page_todo)
        self.btn_fold.setObjectName("BtnFold")
        self.btn_fold.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fold.setFixedHeight(30)
        self.btn_fold.clicked.connect(self._on_toggle_done)
        fold_row.addStretch(1)
        fold_row.addWidget(self.btn_fold)
        self.btn_clear_done = QPushButton("清空已完成", self.page_todo)
        self.btn_clear_done.setObjectName("BtnFold")
        self.btn_clear_done.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_done.setFixedHeight(30)
        self.btn_clear_done.clicked.connect(self._on_clear_done)
        fold_row.addWidget(self.btn_clear_done)
        fold_row.addStretch(1)
        tl.addLayout(fold_row)

        # 便签页
        self.page_note = QWidget(self.pages)
        nl = QVBoxLayout(self.page_note)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(6)

        self.note_title = QLabel("", self.page_note)
        self.note_title.setObjectName("NoteTitle")
        nl.addWidget(self.note_title)

        nl.addSpacing(2)
        self.note_edit = _PlainPasteEdit(self.page_note)
        self.note_edit.setObjectName("NoteEdit")
        self.note_edit.setPlaceholderText("在这里写点什么…")
        nl.addWidget(self.note_edit, 1)

        # 便签正文的右键菜单：系统那条白框菜单换成自绘圆角浅粉菜单
        self.text_menu = TextContextMenu(self)
        self.note_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.note_edit.customContextMenuRequested.connect(self._show_note_text_menu)

        self.pages.addWidget(self.page_todo)
        self.pages.addWidget(self.page_note)
        self.pages.setCurrentIndex(0)

    def _on_input_focus(self, focused: bool):
        self.input_shell.setProperty("focused", focused)
        repolish(self.input_shell)
        if not focused:
            self._hide_input_hint()

    def _show_input_hint(self):
        if self.pages.currentIndex() != 0:
            return
        if self.todo_input.toPlainText().strip():
            return
        self._input_hint.setMinimumWidth(0)
        self._input_hint.setMaximumWidth(16777215)
        self._input_hint.adjustSize()
        # 关键：放在输入框上方，鼠标在下方输入框里不会挡住提示；
        # 宽度对齐输入框，避免日期文字从右侧露出来。
        hint_w = max(self.input_shell.width(), self._input_hint.sizeHint().width())
        self._input_hint.setFixedWidth(hint_w)
        pos = self.input_shell.mapTo(
            self, QPoint(0, -self._input_hint.height() - 6)
        )
        x = max(8, min(pos.x(), self.width() - hint_w - 12))
        y = max(self.card.y() + 4, pos.y())
        self._input_hint.move(x, y)
        self._input_hint.raise_()
        self._input_hint.show()

    def _hide_input_hint(self):
        if hasattr(self, "_hint_timer"):
            self._hint_timer.stop()
        if hasattr(self, "_input_hint"):
            self._input_hint.hide()

    # ------------------------------------------------------------------ 查找（Ctrl+F）
    def _ensure_find_dlg(self) -> FindDialog:
        if self._find_dlg is None:
            dlg = FindDialog(self)
            dlg.queryChanged.connect(self._on_find_text_changed)
            dlg.nextRequested.connect(self._find_next)
            dlg.prevRequested.connect(self._find_prev)
            dlg.closed.connect(self.close_find)
            self._find_dlg = dlg
        return self._find_dlg

    def open_find(self):
        """Ctrl+F 唤起查找弹窗：聚焦并全选已有词，立即按当前页搜索"""
        dlg = self._ensure_find_dlg()
        dlg.show()
        dlg.focus_input()
        self._on_find_text_changed()

    def close_find(self):
        if self._find_dlg is not None:
            self._find_dlg.hide()
        self._clear_find_matches()

    def _clear_find_matches(self):
        self._find_matches = []
        self._find_index = -1
        if self._find_hl_item is not None:
            self._find_hl_item.clear_highlight()
            self._find_hl_item = None
        if hasattr(self, "note_title"):
            self._update_note_header()

    def _set_find_count(self, text: str):
        if self._find_dlg is not None:
            self._find_dlg.set_count(text)

    def _on_find_text_changed(self):
        q = self._find_dlg.query().strip() if self._find_dlg else ""
        if not q:
            self._clear_find_matches()
            self._set_find_count("0/0")
            return
        self._search_all(q)

    def _search_all(self, q: str):
        for w in self._todo_widgets():
            w.clear_highlight()
        self._find_hl_item = None
        todo_matches = self._collect_todo_matches(q)
        note_matches = filter_notes(q, self.store.notes())
        # 全局查找：待办命中在前、便签命中在后，上一个/下一个跨类型翻
        self._find_matches = todo_matches + note_matches
        self._find_index = 0 if self._find_matches else -1
        self._locate_current()

    def _collect_todo_matches(self, q: str) -> list:
        all_todos = self.store.todos(include_done=True)
        hits = filter_todos(q, all_todos)
        widgets = {w.todo["id"]: w for w in self._todo_widgets()}
        # 命中项若落在已完成折叠区，先展开已完成再定位，避免「查到了却看不到」
        missing = [h["id"] for h in hits if h["id"] not in widgets]
        if missing and not self._include_done:
            self._include_done = True
            self.render_todos()
            widgets = {w.todo["id"]: w for w in self._todo_widgets()}
        return [widgets[h["id"]] for h in hits if h["id"] in widgets]

    def _step_find(self, delta: int):
        if not self._find_matches:
            return
        self._find_index = (self._find_index + delta) % len(self._find_matches)
        self._locate_current()

    def _locate_current(self):
        if not self._find_matches:
            self._set_find_count("0/0")
            return
        item = self._find_matches[self._find_index]
        if isinstance(item, TodoItem):
            self._locate_todo_current()
        else:
            self._locate_note_current()

    def _find_next(self):
        self._step_find(1)

    def _find_prev(self):
        self._step_find(-1)

    def _locate_todo_current(self):
        if not self._find_matches:
            self._set_find_count("0/0")
            return
        w = self._find_matches[self._find_index]
        self.scroll.ensureWidgetVisible(w)
        w.raise_()
        if self._find_hl_item is not None:
            self._find_hl_item.clear_highlight()
        self._find_hl_item = w
        query = self._find_dlg.query().strip() if self._find_dlg else ""
        w.highlight_match(query)
        self._set_find_count(f"{self._find_index + 1}/{len(self._find_matches)}")

    def _locate_note_current(self):
        if not self._find_matches:
            self._set_find_count("0/0")
            return
        if self._find_hl_item is not None:
            self._find_hl_item.clear_highlight()
            self._find_hl_item = None
        note = self._find_matches[self._find_index]
        if not isinstance(note, dict):
            return
        if self.current_note is None or self.current_note["id"] != note["id"]:
            self._switch_to_note(note["id"])
        query = self._find_dlg.query().strip() if self._find_dlg else ""
        self._select_note_match(query)
        self._set_note_title_highlight(query)
        self._set_find_count(f"{self._find_index + 1}/{len(self._find_matches)}")

    def _select_note_match(self, q: str):
        if not q:
            return
        doc = self.note_edit.document()
        cur = self.note_edit.textCursor()
        start = cur.selectionEnd() if cur.hasSelection() else cur.position()
        cur = doc.find(q, start)
        if cur.isNull():
            cur = doc.find(q)          # 末尾没找到就从头环回
        if not cur.isNull():
            self.note_edit.setTextCursor(cur)

    # ------------------------------------------------------------------ 侧栏
    def _build_sidebar(self):
        self.sidebar = QWidget(self)
        self.sidebar.setFixedWidth(SIDE_W)
        self.sidebar.setGeometry(SIDE_X, SIDE_Y, SIDE_W, SIDE_H)
        lay = QVBoxLayout(self.sidebar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.btn_tab_todo = QPushButton("待办", self.sidebar)
        self.btn_tab_todo.setObjectName("SidePill")
        self.btn_tab_todo.setProperty("side", self._side)
        self.btn_tab_todo.setCheckable(True)
        self.btn_tab_todo.setChecked(True)
        self.btn_tab_todo.setFixedSize(SIDE_W, SIDE_H)
        self.btn_tab_todo.setCursor(Qt.CursorShape.PointingHandCursor)
        add_shadow(self.btn_tab_todo, blur=14, dy=0, alpha=30)
        lay.addWidget(self.btn_tab_todo)

        # 便签列表放进一个自绘视口：便签多到放不下时用滚轮上下滚，
        # 右边缘画一条很细的指示条提示还有内容；不用 QScrollArea 是因为
        # 它自带的 viewport 会把子控件的 QSS 底色洗掉（胶囊会变透明）
        self.note_view = _NoteView(self.sidebar)

        self.note_buttons_holder = QWidget(self.note_view)
        self.note_buttons_layout = QVBoxLayout(self.note_buttons_holder)
        self.note_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.note_buttons_layout.setSpacing(10)
        self.note_view.set_content(self.note_buttons_holder)
        lay.addWidget(self.note_view)

        self.btn_add_note = IconButton(
            "plus", color=C.INK_3, hover=C.PRIMARY,
            size=(SIDE_W, SIDE_H), icon_size=18, object_name="SidePill",
            tooltip="新建便签", parent=self.sidebar,
        )
        self.btn_add_note.setProperty("side", self._side)
        add_shadow(self.btn_add_note, blur=14, dy=0, alpha=30)
        lay.addWidget(self.btn_add_note)

        self.btn_tab_todo.clicked.connect(self._switch_to_todo)
        self.btn_add_note.clicked.connect(self.on_new_note)

    def _switch_to_todo(self):
        self._flush_note()
        self._clear_find_matches()
        self.pages.setCurrentIndex(0)
        self.btn_tab_todo.setChecked(True)
        self._uncheck_note_buttons()
        # 点击待办胶囊后把焦点移到输入框，不然焦点留在侧栏按钮上，
        # 抽屉会一直拉开，和 hover 时鼠标移开就缩回的行为不一致
        if hasattr(self, "todo_input"):
            self.todo_input.setFocus(Qt.FocusReason.MouseFocusReason)

    def _uncheck_note_buttons(self):
        for i in range(self.note_buttons_layout.count()):
            w = self.note_buttons_layout.itemAt(i).widget()
            if isinstance(w, QPushButton):
                w.setChecked(False)

    def refresh_note_buttons(self):
        """根据 store.notes() 重建侧栏便签按钮，并让侧栏高度自适应"""
        while self.note_buttons_layout.count():
            item = self.note_buttons_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        notes = self.store.notes()
        current_id = self.current_note.get("id") if self.current_note else None
        on_todo_tab = self.pages.currentIndex() == 0
        for note in notes:
            full_title = note.get("title", "便签")
            btn = _NoteSideBtn(self.note_buttons_holder)
            btn.setObjectName("SidePill")
            btn.setProperty("side", self._side)
            btn.setCheckable(True)
            btn.setChecked((not on_todo_tab) and note["id"] == current_id)
            btn.setProperty("note_id", note["id"])
            btn.setFixedSize(SIDE_W, SIDE_H)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setText(self._elide(full_title, SIDE_W - 12, btn))
            add_shadow(btn, blur=14, dy=0, alpha=30)

            nid = note["id"]
            btn.clicked.connect(lambda checked=False, nid=nid: self._switch_to_note(nid))
            btn.renamed.connect(self._rename_inline)
            btn.dragBegin.connect(self._on_note_drag_begin)
            btn.dragMoved.connect(self._on_note_drag_move)
            btn.dragEnd.connect(self._on_note_drag_end)
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, nid=nid, btn=btn: self._note_context_menu(pos, nid, btn)
            )
            self.note_buttons_layout.addWidget(btn)

        # 侧栏高度按内容计算：放得下就自然铺开（间距 10），
        # 放不下先收间距（10 → 4），还放不下就在视口里滚动
        self._layout_note_view(notes)
        self._position_sidebar()

    def _layout_note_view(self, notes: list):
        """按便签数决定间距与可视高度；便签再多也不越出卡片圆角"""
        if not hasattr(self, "note_view"):
            return
        count = len(notes)
        view_h_available = (
            CARD_Y + self.card.height() - SIDE_BOTTOM_GAP
            - SIDE_TOP_MIN - 2 * SIDE_H - 20
        )
        sp = 10
        content_h = count * SIDE_H + max(0, count - 1) * sp
        if content_h > view_h_available:
            sp = 4
            content_h = count * SIDE_H + max(0, count - 1) * sp
        view_h = min(content_h, view_h_available)
        self.note_buttons_layout.setSpacing(sp)
        self.note_buttons_holder.setFixedWidth(SIDE_W)
        self.note_buttons_holder.setFixedHeight(int(content_h))
        self.note_view.setFixedHeight(int(view_h))
        self.note_view.set_content(self.note_buttons_holder, int(content_h))
        self.sidebar.setFixedHeight(int(2 * SIDE_H + 20 + view_h))

        # 选中的便签在视口里滚到看得见的位置
        current_id = self.current_note.get("id") if self.current_note else None
        idx = next((i for i, n in enumerate(notes) if n.get("id") == current_id), 0)
        self.note_view.ensure_row_visible(idx, SIDE_H + sp)
        self.sidebar.layout().activate()

    def _ensure_note_visible(self, nid: str):
        """选中的便签如果在视口外，滚到看得见"""
        if not hasattr(self, "note_view"):
            return
        notes = self.store.notes()
        idx = next((i for i, n in enumerate(notes) if n.get("id") == nid), 0)
        self.note_view.ensure_row_visible(
            idx, SIDE_H + self.note_buttons_layout.spacing()
        )

    def _side_right_gap(self) -> int:
        """窗口右缘留白：胶囊列在右边时要多留出整列胶囊的宽度"""
        if self._side == "right":
            return SIDE_EXTRA_W + CARD_RIGHT_GAP
        return CARD_RIGHT_GAP

    def _sidebar_x(self) -> int:
        """胶囊列左缘：贴卡片左边（默认）或贴卡片右边"""
        if self._side == "right":
            return CARD_X + self.card.width() - 1
        return SIDE_X

    # ---------------- 胶囊列抽屉（鼠标移开缩进卡片、hover 拉开）----------------
    def _sidebar_target_x(self, open: bool = True) -> int:
        """胶囊列左缘的目标 x：拉开时贴着卡片外沿，收起时缩进卡片但留一条边

        · 列在卡片左边：收起往右走 (SIDE_W - 1 - SIDE_PEEK)，右侧 SIDE_PEEK(20) 那一条
          露在卡片左缘外面，其余被卡片盖住
        · 列在卡片右边：收起往左走同距离，左边那条露在卡片右缘外面
        卡片宽度与窗口宽度都不动，所以收起只是这一列钻到卡片背后。
        """
        shut = SIDE_W - 1 - SIDE_PEEK
        if self._side == "right":
            base = CARD_X + self.card.width() - 1
            return base if open else base - shut
        return SIDE_X if open else SIDE_X + shut

    def _set_pills_open(self, flag: bool, animate: bool = True):
        """抽屉开合；animate=False 直接落位（resize / 翻面 / 首次显示时用）"""
        flag = bool(flag)
        changed = flag != self._pills_open
        self._pills_open = flag
        if not hasattr(self, "sidebar"):
            return
        # 抽屉收起时隐藏滚动条（只露出 20px，滚动条露出来也没用）
        if hasattr(self, "note_view"):
            self.note_view._bar_visible = flag
            self.note_view._bar.update()
        x = self._sidebar_target_x(open=flag)
        y = self.sidebar.y()
        if not animate:
            if self._pill_anim is not None:
                self._pill_anim.stop()
            self.sidebar.move(x, y)
            return
        if not changed:
            return
        if self._pill_anim is None:
            self._pill_anim = QPropertyAnimation(self.sidebar, b"pos", self)
            self._pill_anim.setDuration(220)
            self._pill_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._pill_anim.stop()
        self._pill_anim.setStartValue(QPoint(self.sidebar.x(), y))
        self._pill_anim.setEndValue(QPoint(x, y))
        self._pill_anim.start()

    def _pill_hover_rect(self) -> QRect:
        """鼠标落在这一块里就算「想拉开抽屉」：卡片本体 + 胶囊列展开时占的那一条

        收起后那一条是空的，但鼠标划到那里也能把它拉出来，等于隐形的拉手。
        窗口左/右那块真正的透明留白不算，鼠标路过不会把抽屉抖出来。
        """
        if not hasattr(self, "sidebar"):
            return self.rect()
        rect = QRect(self.card.geometry())
        side = QRect(self._sidebar_x(), self.sidebar.y(), SIDE_W, self.sidebar.height())
        return rect.united(side)

    def _focus_in_sidebar(self) -> bool:
        """键盘焦点是不是落在侧栏那一列上（含便签胶囊、「＋」、「待办」）"""
        if not hasattr(self, "sidebar"):
            return False
        w = QApplication.focusWidget()
        return w is not None and (w is self.sidebar or self.sidebar.isAncestorOf(w))

    def _pill_should_open(self) -> bool:
        """抽屉该不该开着：键盘焦点在侧栏里，或者鼠标落在判定区里（两条通路取或）

        焦点优先——收起时胶囊被卡片压住，Tab 切过去看不见焦点在哪，
        所以焦点一进来就把抽屉拉开，键盘和鼠标拿到的是同一种反馈。
        """
        if self._focus_in_sidebar():
            return True
        return self._pill_hover_rect().contains(self.mapFromGlobal(QCursor.pos()))

    def _on_app_focus_changed(self, old, now):
        """焦点一进侧栏立刻拉开，不等 120ms 轮询（键盘操作要即时反馈）

        焦点离开时也立刻重算一次：鼠标还在卡片上就继续开着，都走了才收。
        """
        if not self.isVisible() or not hasattr(self, "sidebar"):
            return
        if now is not None and (now is self.sidebar or self.sidebar.isAncestorOf(now)):
            self._set_pills_open(True)
            return
        self._set_pills_open(self._pill_should_open())

    def _poll_pill_hover(self, first: bool = False):
        """120ms 看一次鼠标与焦点：想拉开就拉开，都离开了就缩回去"""
        if not hasattr(self, "sidebar") or not self.isVisible():
            return
        self._set_pills_open(self._pill_should_open(), animate=not first)

    def _position_sidebar(self):
        """侧栏便签多到放不下时整体上移，但最高只到卡片圆角的下缘

        · 下界：最后一个胶囊仍在卡片内（卡片底边 - 22）
        · 上界：不超过卡片顶部圆角的下缘（SIDE_TOP_MIN）
        """
        if not hasattr(self, "sidebar"):
            return
        max_bottom = CARD_Y + self.card.height() - SIDE_BOTTOM_GAP
        y = min(SIDE_Y, max_bottom - self.sidebar.height())
        y = max(SIDE_TOP_MIN, y)
        x = self._sidebar_target_x(open=self._pills_open)
        if (self._pill_anim is not None
                and self._pill_anim.state() == QPropertyAnimation.State.Running):
            # 动画走着：只把终点挪到新位置，别把正在滑的那一列立刻拍到现在
            self._pill_anim.setEndValue(QPoint(x, y))
        else:
            self.sidebar.move(x, y)

    # ---------------- 胶囊列左右翻转 ----------------
    def _pill_buttons(self) -> list:
        """胶囊列里的所有按钮（待办 / 各便签 / ＋）"""
        out = []
        for name in ("btn_tab_todo", "btn_add_note"):
            w = getattr(self, name, None)
            if w is not None:
                out.append(w)
        if hasattr(self, "note_buttons_layout"):
            for i in range(self.note_buttons_layout.count()):
                w = self.note_buttons_layout.itemAt(i).widget()
                if isinstance(w, QPushButton):
                    out.append(w)
        return out

    def _apply_pill_side_style(self):
        """把当前的左右状态写给 QSS 认（卡片 + 每个胶囊）"""
        if hasattr(self, "card"):
            self.card.setProperty("side", self._side)
            repolish(self.card)
        for b in self._pill_buttons():
            b.setProperty("side", self._side)
            repolish(b)
        if hasattr(self, "note_buttons_holder"):
            for edit in self.note_buttons_holder.findChildren(QLineEdit):
                edit.setProperty("side", self._side)
                repolish(edit)

    def _set_pill_side(self, side: str):
        """把胶囊列整列翻到卡片另一侧：卡片宽度不变，只有窗口跟着加宽 / 收窄"""
        if side == self._side:
            return
        card_w = self.card.width()
        self._side = side
        self._apply_pill_side_style()

        gap = self._side_right_gap()
        min_w = CARD_X + CARD_W + gap
        self._apply_size_limits()
        # 窗口宽度 = 卡片左缘 + 卡片宽度 + 右留白：卡片和立绘原地不动，只有窗口外框变
        new_w = max(min_w, CARD_X + card_w + gap)
        if new_w != self.width():
            self.resize(new_w, self.height())
        self._position_sidebar()
        # 侧栏翻到右边时，滚动条翻到左侧（贴着卡片那一侧）
        if hasattr(self, "note_view"):
            self.note_view._bar_on_right = (side == "left")
            self.note_view.resizeEvent(None)
            self.note_view._bar.update()

    def _pill_fits_at(self, side: str, x: int, card_w: int, avail) -> bool:
        """翻过去之后这一列胶囊能不能整列落在屏幕里（不能就别翻，免得来回抖）"""
        if side == "right":
            left = x + CARD_X + card_w - 1
            return left >= avail.left() and left + SIDE_W <= avail.right() + 1
        left = x + SIDE_X
        return left >= avail.left() and left + SIDE_W <= avail.right() + 1

    def _sync_pill_side(self):
        """窗口贴到哪边、胶囊列该在哪边

        · 胶囊在左边：左边被屏幕压掉 ≥ FLIP_LOSE_PX → 翻到右边
        · 胶囊在右边：左边腾出 ≥ FLIP_BACK_PX 空闲 → 翻回左边（窗口跟着收窄）
        · 胶囊在右边但右边自己被压住（贴右屏边）→ 也翻回左边
        两个阈值一高一低，卡在临界点上小幅拖动不会来回翻。
        """
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None or not hasattr(self, "card"):
            return
        avail = screen.availableGeometry()
        x = self.x()
        card_w = self.card.width()
        if self._side == "left":
            lose = avail.left() - (x + SIDE_X)          # 左侧胶囊被左屏边压掉的像素
            if lose >= FLIP_LOSE_PX and self._pill_fits_at("right", x, card_w, avail):
                self._set_pill_side("right")
        else:
            pill_right = x + CARD_X + card_w - 1 + SIDE_W
            lose = pill_right - (avail.right() + 1)     # 右侧胶囊被右屏边压掉的像素
            free_left = (x + SIDE_X) - avail.left()     # 左边给胶囊腾出来的空闲
            back = lose >= FLIP_LOSE_PX or free_left >= FLIP_BACK_PX
            if back and self._pill_fits_at("left", x, card_w, avail):
                self._set_pill_side("left")

    # ---------------- 侧栏便签：长按拖动换位 ----------------
    def _note_widgets(self) -> list:
        out = []
        for i in range(self.note_buttons_layout.count()):
            w = self.note_buttons_layout.itemAt(i).widget()
            if isinstance(w, _NoteSideBtn):
                out.append(w)
        return out

    def _on_note_drag_begin(self, btn):
        self._note_drag_btn = btn

    def _on_note_drag_move(self, btn, gpos):
        items = self._note_widgets()
        if btn not in items:
            return
        cur = items.index(btn)
        target = 0
        for w in items:
            if w is btn:
                continue
            if w.mapToGlobal(w.rect().center()).y() < gpos.y():
                target += 1
        if target != cur:
            self.note_buttons_layout.removeWidget(btn)
            self.note_buttons_layout.insertWidget(target, btn)
            self.note_buttons_layout.activate()

    def _on_note_drag_end(self, btn):
        if getattr(self, "_note_drag_btn", None) is None:
            return
        self._note_drag_btn = None
        ids = [w.property("note_id") for w in self._note_widgets()]
        self.store.set_note_order([i for i in ids if i])
        self.refresh_note_buttons()

    def _elide(self, text: str, width: int, widget: QWidget) -> str:
        return widget.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width)

    def _rename_inline(self, btn):
        """双击便签按钮：原地变输入框。

        和电脑里改文件夹名一个手感：一进来就全选、直接敲字就是整体替换；
        回车确认，点别处也算确认，Esc 放弃。
        """
        idx = -1
        for i in range(self.note_buttons_layout.count()):
            if self.note_buttons_layout.itemAt(i).widget() is btn:
                idx = i
                break
        notes = self.store.notes()
        if idx < 0 or idx >= len(notes):
            return
        note = notes[idx]
        old_title = note.get("title", "")

        edit = _SidePillEdit(old_title, self.note_buttons_holder)
        edit.setObjectName("SidePillEdit")
        edit.setProperty("side", self._side)
        edit.setFixedSize(SIDE_W, SIDE_H)
        edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._note_rename_edit = edit

        # 顺序很重要：先换进布局并显示，之后 setFocus / selectAll 才作数
        # （原来先 setFocus 后 replaceWidget，输入框还没进界面，焦点落在旧按钮上，
        #   所以才要再点一次才能输入）
        self.note_buttons_layout.replaceWidget(btn, edit)
        btn.hide()
        edit.show()

        saved = [False]

        def finish(commit: bool):
            if saved[0]:
                return
            saved[0] = True
            self._note_rename_edit = None
            if commit:
                new = edit.text().strip()
                if new and new != old_title:
                    self.store.update_note(note["id"], title=new)
                if self.current_note and self.current_note["id"] == note["id"]:
                    self.current_note["title"] = new or old_title
                    self._update_note_header()
            edit.deleteLater()
            self.refresh_note_buttons()

        save = lambda: finish(True)        # noqa: E731  Enter / 失焦
        cancel = lambda: finish(False)     # noqa: E731  Esc

        def arm_focus():
            # 双击的第二次松手会落在新出现的输入框上，把全选冲掉；
            # 等这一轮鼠标事件走完，再把焦点和全选补上
            if saved[0] or not edit.isVisible():
                return
            edit.setFocus(Qt.FocusReason.MouseFocusReason)
            edit.selectAll()

        edit.returnPressed.connect(save)
        edit.editingFinished.connect(save)
        edit.cancelled.connect(cancel)
        QTimer.singleShot(0, arm_focus)

    def _note_context_menu(self, pos, nid: str, btn):
        menu = self._build_note_menu(nid, btn)
        action = menu.exec(btn.mapToGlobal(pos))
        menu.deleteLater()
        if action is None:
            return
        if action.objectName() == "ActOpenNote":
            self._switch_to_note(nid)
        elif action.objectName() == "ActRenameNote":
            self._rename_inline(btn)
        elif action.objectName() == "ActDeleteNote":
            self._delete_note(nid)

    def _delete_note(self, nid: str):
        """删便签：删的不是当前选中的，选中项必须留在原位；删的正是选中的，落到邻居"""
        old = self.store.notes()
        idx = next((i for i, n in enumerate(old) if n["id"] == nid), 0)
        was_current = bool(self.current_note and self.current_note["id"] == nid)
        if was_current:
            self.current_note = None
        self.store.delete_note(nid)
        notes = self.store.notes()
        if was_current:
            if notes:
                # 落到原位置上的那一条（删的是末尾就退到新的最后一条）
                self._switch_to_note(notes[min(idx, len(notes) - 1)]["id"])
            else:
                self.pages.setCurrentIndex(0)
                self.btn_tab_todo.setChecked(True)
        self.refresh_note_buttons()

    def _build_note_menu(self, nid: str, btn) -> QMenu:
        note = self.store.get_note(nid) or {}
        menu = QMenu(self)
        menu.setObjectName("NoteMenu")
        round_menu(menu)

        header = QWidget(menu)
        hl = QVBoxLayout(header)
        hl.setContentsMargins(12, 8, 12, 6)
        hl.setSpacing(1)
        kicker = QLabel("便签", header)
        kicker.setObjectName("MenuKicker")
        title = QLabel(self._elide(note.get("title", "便签"), 180, self.note_title), header)
        title.setObjectName("MenuTitle")
        hl.addWidget(kicker)
        hl.addWidget(title)

        header_action = QWidgetAction(menu)
        header_action.setDefaultWidget(header)
        header_action.setEnabled(False)
        menu.addAction(header_action)
        menu.addSeparator()

        act_open = menu.addAction(icon("note", C.INK_2, 15), "打开便签")
        act_open.setObjectName("ActOpenNote")
        act_rename = menu.addAction(icon("edit", C.INK_2, 15), "重命名")
        act_rename.setObjectName("ActRenameNote")
        menu.addSeparator()
        act_delete = menu.addAction(icon("trash", C.DANGER, 15), "删除此便签")
        act_delete.setObjectName("ActDeleteNote")
        return menu

    # ------------------------------------------------------------------ 立绘
    def _build_char(self):
        self.char = QLabel(self)
        self.char.setGeometry(CHAR_X, CHAR_Y, CHAR_W, CHAR_H)
        self.char.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self.char.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        pm = QPixmap(CHAR_LIE)
        if pm.isNull():
            self.char.setText("立绘缺失")
            self.char.setObjectName("EmptyHint")
        else:
            self.char.setPixmap(
                pm.scaled(
                    CHAR_W, CHAR_H,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.char.raise_()

    # ------------------------------------------------------------------ 缩放
    def _build_resizers(self):
        self._resizer = _Resizer(self, "corner", self.card)
        self._resizer_right = _Resizer(self, "right", self.card)
        self._resizer_bottom = _Resizer(self, "bottom", self.card)
        self._place_resizers(CARD_W, CARD_H)

    def _place_resizers(self, card_w: int, card_h: int):
        """缩放手柄的落点：角手柄一直在卡片右下角；胶囊列在右边时右缘细手柄让位收起来"""
        self._resizer.setGeometry(card_w - 32, card_h - 32, 28, 28)
        if self._side == "right":
            self._resizer_right.hide()
        else:
            self._resizer_right.setGeometry(card_w - 3, 48, 6, card_h - 96)
            self._resizer_right.show()
        self._resizer_bottom.setGeometry(48, card_h - 3, card_w - 96, 6)
        self._resizer.raise_()
        self._resizer_right.raise_()
        self._resizer_bottom.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 拖手柄改大小不算「贴边停住了」：缩放一发生就把贴边标志清掉，
        # 松手之后也不会因为刚才撑到过边上而自己收成桌宠
        self._is_edge_touched = False
        if getattr(self, "_input_hint", None) is not None and self._input_hint.isVisible():
            self._show_input_hint()
        if not hasattr(self, "_resizer"):
            return
        card_w = max(CARD_W, self.width() - CARD_X - self._side_right_gap())
        card_h = max(CARD_H, self.height() - CARD_Y - CARD_BOTTOM_GAP)
        self.card.setGeometry(CARD_X, CARD_Y, card_w, card_h)
        self._place_resizers(card_w, card_h)
        # 卡片高度变了：便签可视区跟着重算（拉长卡片就能多看见几颗）
        if hasattr(self, "note_view"):
            self._layout_note_view(self.store.notes())
        self._position_sidebar()

    def showEvent(self, event):
        super().showEvent(event)
        self.card.raise_()
        self.char.raise_()
        self._apply_size_limits()
        self._update_scroll_fade()
        # 上次关在屏幕左边（或从桌宠在左边展开）：先判一次胶囊列该在哪边
        self._sync_pill_side()
        # 抽屉：先按鼠标当前位置落位（鼠标不在卡片上就直接是收起态，别播一段动画）
        self._pills_open = True
        self._position_sidebar()
        self._poll_pill_hover(first=True)
        self._pill_timer.start()
        # 显示后抬回置顶层，避免被其他窗口抢占后层级回落
        self.raise_()

    def hideEvent(self, event):
        self._is_edge_touched = False
        self._pill_timer.stop()
        if self._pill_anim is not None:
            self._pill_anim.stop()
        self._hide_input_hint()
        super().hideEvent(event)

    def _visible_right(self) -> int:
        """窗口内可见内容（卡片，胶囊列在右边时再加上整列胶囊）离窗口左缘多远"""
        side = SIDE_EXTRA_W if self._side == "right" else 0
        return CARD_X + self.card.width() + side

    def _screen_for_point(self, x: int, y: int):
        """坐标落在哪块屏的可用区就返回哪块；找不到（副屏已拔 / 离屏）回退主屏。"""
        point = QPoint(x, y)
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().contains(point):
                return screen
        return self.screen() or QGuiApplication.primaryScreen()

    def _fit_on_screen(self, x: int, y: int) -> tuple[int, int]:
        """把窗口钳到坐标所属屏的可见区（卡片口径）；屏几何异常时回退主屏中心。

        可用区 = 屏幕去掉任务栏 / 停靠栏的那块，所以卡片最多贴住任务栏上沿，不会盖住它。
        """
        screen = self._screen_for_point(x, y)
        if screen is None:
            return x, y
        avail = screen.availableGeometry()
        if avail.width() <= 0 or avail.height() <= 0:
            avail = QGuiApplication.primaryScreen().availableGeometry()
        vis_bottom = CARD_Y + self.card.height()
        min_x = avail.left() - CARD_X
        max_x = avail.right() + 1 - self._visible_right()
        min_y = avail.top()
        max_y = avail.bottom() + 1 - vis_bottom
        nx = max(min_x, min(x, max_x))
        ny = max(min_y, min(y, max_y))
        # 兜底：屏过小导致卡片仍与可用区无交集，直接居中到这块屏，避免藏到屏外
        vl = nx + CARD_X
        vr = nx + self._visible_right()
        vb = ny + vis_bottom
        if vr <= avail.left() or vl > avail.right() or vb <= avail.top() or ny > avail.bottom():
            nx = avail.center().x() - self.width() // 2
            ny = avail.center().y() - self.height() // 2
        return nx, ny

    def _clamp_to_screen(self, x: int, y: int) -> tuple[int, int]:
        return self._fit_on_screen(x, y)

    def _apply_size_limits(self):
        """窗口最小 / 最大：卡片拉到最大也只是铺满屏幕可用区，超不过桌面更盖不住任务栏

        上限跟着窗口当前位置算（`card 右缘 = x + w - CARD_RIGHT_GAP`），所以停在屏幕右下角
        时窗口最多长到那两条边就停住，不会从右边 / 下边长出去。
        """
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None or not hasattr(self, "card"):
            return
        avail = screen.availableGeometry()
        min_w = CARD_X + CARD_W + self._side_right_gap()
        max_w = min(avail.width(), avail.right() + 1 - self.x() + CARD_RIGHT_GAP)
        max_w = max(min_w, max_w)
        max_h = min(
            avail.height(),
            avail.bottom() + 1 - self.y() + CARD_BOTTOM_GAP,
        )
        max_h = max(WIN_H, max_h)
        cache = (min_w, max_w, max_h)
        if cache == getattr(self, "_size_limit_cache", None):
            return
        self._size_limit_cache = cache
        self.setMinimumSize(min_w, WIN_H)
        self.setMaximumSize(max_w, max_h)

    def moveEvent(self, event):
        super().moveEvent(event)
        x, y = self.x(), self.y()
        nx, ny = self._clamp_to_screen(x, y)
        if (nx, ny) != (x, y):
            self.move(nx, ny)
            return
        # 位置变了，窗口能拉到多大也跟着变（贴着屏幕右下角时就长不过那两条边）
        self._apply_size_limits()

        # 贴着边还停住不动 1 秒才会收成桌宠（计时只由拖动松手、拖动过程驱动，见 _arm_edge_shrink）；
        # 拖手柄改大小、程序化移动都不会让它自己收走。
        # 贴到屏幕边、胶囊列要被压住时整列翻面（拖到另一侧再翻回来）
        self._sync_pill_side()

    def _edge_shrink_enabled(self) -> bool:
        """设置里「贴边自动缩小」开着没有（默认关：拖动 / 改大小都不该把窗口收走）"""
        try:
            return bool(self.store.get_setting("edge_shrink", False))
        except Exception:
            return False

    def _arm_edge_shrink(self):
        """窗口位置定下来后检测是否贴边：贴边就等鼠标移开，没贴边就清掉标志

        拖动中每次移动都会走这里重置，所以「拖着走」不会触发；
        拖手柄改大小只经过 resizeEvent（那里直接把标志清掉）；
        从桌宠展开 / 恢复位置这类程序化移动不经过这里，不会把自己收走。
        """
        if not self._edge_shrink_enabled():
            self._is_edge_touched = False
            return
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            self._is_edge_touched = False
            return
        avail = screen.availableGeometry()
        x, y = self.x(), self.y()
        vis_left = x + CARD_X
        vis_right = x + CARD_X + self.card.width()
        vis_top = y
        vis_bottom = y + CARD_Y + self.card.height()
        self._is_edge_touched = (
            vis_left <= avail.left() + EDGE_TOUCH_PX
            or vis_top <= avail.top() + EDGE_TOUCH_PX
            or vis_right >= avail.right() - EDGE_TOUCH_PX
            or vis_bottom >= avail.bottom() - EDGE_TOUCH_PX
        )

    def leaveEvent(self, event):
        """鼠标离开窗口：如果贴边了，就自动收成桌宠（有对话框或菜单打开时不触发）"""
        super().leaveEvent(event)
        # 有对话框打开时，不触发自动缩小
        from PyQt6.QtWidgets import QApplication
        for w in QApplication.topLevelWidgets():
            if w.isVisible() and w != self:
                cls_name = w.__class__.__name__
                if cls_name in ("SettingsDialog", "TodoEditDialog", "QMenu"):
                    return
        if getattr(self, "_is_edge_touched", False) and self._edge_shrink_enabled():
            if self._win_drag is None:
                self._minimize_to_pet()

    def _minimize_to_pet(self):
        """点缩小按钮（或贴边静置满 1 秒自动触发）：桌宠按角色中心原地出现；
        窗口贴着屏幕边 / 角时，桌宠也贴到那条边 / 那个角

        贴角判定按「可见内容（卡片 + 立绘）离屏幕边 ≤ EDGE_TOUCH_PX」，同时贴两条边就算贴角，
        四角的优先级按 左上 > 左下 > 右上 > 右下；只贴一条边时，另一轴仍然保持角色中心不动。
        """
        self._flush_note()
        self.store.set_setting("win_pos", [self.x(), self.y()])

        scale = self._pet_scale()
        pet_w, pet_h = pet_size(scale)
        pet_x, pet_y = pet_pos_for_window(self.x(), self.y(), scale)

        screen = self.screen() or QGuiApplication.primaryScreen()
        pet_corner = ""
        if screen is not None:
            avail = screen.availableGeometry()
            card_w = self.card.width()
            card_h = self.card.height()
            vis_left = self.x() + CARD_X
            vis_right = self.x() + CARD_X + card_w
            vis_top = self.y()
            vis_bottom = self.y() + CARD_Y + card_h
            touch_l = vis_left <= avail.left() + EDGE_TOUCH_PX
            touch_r = vis_right >= avail.right() - EDGE_TOUCH_PX
            touch_t = vis_top <= avail.top() + EDGE_TOUCH_PX
            touch_b = vis_bottom >= avail.bottom() - EDGE_TOUCH_PX

            if touch_t and touch_l:                       # 左上
                pet_x, pet_y = avail.left(), avail.top()
                pet_corner = "tl"
            elif touch_b and touch_l:                     # 左下
                pet_x, pet_y = avail.left(), avail.bottom() - pet_h + 1
                pet_corner = "bl"
            elif touch_t and touch_r:                     # 右上
                pet_x, pet_y = avail.right() - pet_w + 1, avail.top()
                pet_corner = "tr"
            elif touch_b and touch_r:                     # 右下
                pet_x, pet_y = avail.right() - pet_w + 1, avail.bottom() - pet_h + 1
                pet_corner = "br"
            else:
                # 只贴一条边：那一轴压到屏幕边，另一轴保持角色中心
                if touch_l:
                    pet_x = avail.left()
                elif touch_r:
                    pet_x = avail.right() - pet_w + 1
                if touch_t:
                    pet_y = avail.top()
                elif touch_b:
                    pet_y = avail.bottom() - pet_h + 1

        self.store.set_setting("pet_pos", [int(pet_x), int(pet_y)])
        self.store.set_setting("pet_corner", pet_corner)
        self.enterPetMode.emit()


    def _pet_scale(self) -> float:
        """桌宠当前缩放比例（存在设置里，滚轮调过就按新的算锚点）"""
        try:
            return float(self.store.get_setting("pet_scale", 1.0) or 1.0)
        except (TypeError, ValueError):
            return 1.0

    # ------------------------------------------------------------------ 便签
    def _bind_notes(self):
        if not self.store.notes():
            self.store.add_note(title="便签 1", content="")
        self.current_note = self.store.notes()[0]
        self._set_note_content(self.current_note)

        self._note_save_timer = QTimer(self)
        self._note_save_timer.setSingleShot(True)
        self._note_save_timer.setInterval(500)
        self._note_save_timer.timeout.connect(self._save_note)
        self.note_edit.textChanged.connect(lambda: self._note_save_timer.start())

        self.refresh_note_buttons()

    def _set_note_content(self, note: dict):
        self.note_edit.blockSignals(True)
        self.note_edit.setPlainText(note.get("content", ""))
        self.note_edit.blockSignals(False)
        self._update_note_header()

    def _update_note_header(self):
        title = (self.current_note or {}).get("title", "便签")
        self.note_title.setText(self._elide(title, 230, self.note_title))

    def _set_note_title_highlight(self, keyword: str):
        """便签标题里命中的关键词用主题色高亮标出。"""
        title = (self.current_note or {}).get("title", "便签")
        q = (keyword or "").strip().lower()
        if not q:
            self._update_note_header()
            return
        idx = title.lower().find(q)
        if idx < 0:
            self._update_note_header()
            return
        before = html.escape(title[:idx])
        hit = html.escape(title[idx:idx + len(q)])
        after = html.escape(title[idx + len(q):])
        self.note_title.setText(
            f'{before}<span style="color:{C.PRIMARY};'
            f'background-color:{C.PRIMARY_SOFT};">{hit}</span>{after}'
        )

    def _flush_note(self):
        if (
            hasattr(self, "_note_save_timer")
            and self._note_save_timer.isActive()
        ):
            self._note_save_timer.stop()
            self._save_note()

    def _save_note(self):
        if not self.current_note:
            return
        self.store.update_note(
            self.current_note["id"], content=self.note_edit.toPlainText()
        )

    def _show_note_text_menu(self, pos):
        """便签正文右键：光标先落到点击处（点在选区里则保留选区），再弹自绘菜单"""
        ed = self.note_edit
        at = ed.cursorForPosition(ed.viewport().mapFrom(ed, pos))
        cur = ed.textCursor()
        inside_sel = (
            cur.hasSelection()
            and cur.selectionStart() <= at.position() <= cur.selectionEnd()
        )
        if not inside_sel:
            ed.setTextCursor(at)
        self.text_menu.popup_at(ed.mapToGlobal(pos), ed)

    def _switch_to_note(self, nid: str):
        note = self.store.get_note(nid)
        if not note:
            return
        self._flush_note()
        self._hide_input_hint()
        self.current_note = note
        self.pages.setCurrentIndex(1)
        self._set_note_checked(nid)
        self._set_note_content(note)
        self._ensure_note_visible(nid)
        self.note_edit.setFocus()

    def _set_note_checked(self, nid: str):
        """只切换选中态，不重建按钮（否则双击重命名会被打断）"""
        self.btn_tab_todo.setChecked(False)
        for i in range(self.note_buttons_layout.count()):
            w = self.note_buttons_layout.itemAt(i).widget()
            if isinstance(w, QPushButton):
                w.setChecked(w.property("note_id") == nid)

    def on_new_note(self):
        self._flush_note()
        self._hide_input_hint()
        self._clear_find_matches()
        note = self.store.add_note(title=f"便签 {len(self.store.notes()) + 1}", content="")
        self.current_note = note
        self.pages.setCurrentIndex(1)
        self.btn_tab_todo.setChecked(False)
        self._set_note_content(note)
        self.refresh_note_buttons()
        self._ensure_note_visible(note["id"])
        self.note_edit.setFocus()

    # ------------------------------------------------------------------ 时钟
    def _update_clock(self):
        now = datetime.now()
        self.time_label.setText(now.strftime("%H:%M"))
        self.date_label.setText(f"{now.month}月{now.day}日 周{WEEK_CN[now.weekday()]}")

    # ------------------------------------------------------------------ 刷新
    def refresh(self):
        self._update_clock()
        self.render_todos()

    def _done_count(self) -> int:
        return sum(1 for t in self.store.data["todos"] if t.get("done"))

    def _update_fold_button(self):
        done_count = self._done_count()
        total_count = len(self.store.data["todos"])
        pending_count = total_count - done_count
        # 已完成折叠 + 清空已完成：有已完成的才显示
        if done_count == 0:
            self.btn_fold.setVisible(False)
            self.btn_clear_done.setVisible(False)
            return
        self.btn_fold.setVisible(True)
        self.btn_clear_done.setVisible(True)
        if self._include_done:
            self.btn_fold.setText("收起已完成")
            self.btn_fold.setIcon(icon("chevron_up", C.INK_3, 13))
        else:
            self.btn_fold.setText(f"已完成 {done_count} 项")
            self.btn_fold.setIcon(icon("chevron_down", C.INK_3, 13))
        self.btn_fold.setIconSize(QSize(13, 13))

    def _on_toggle_done(self):
        self._include_done = not self._include_done
        self.render_todos()

    def _on_clear_done(self):
        """清空所有已完成的待办"""
        self.store.data["todos"] = [t for t in self.store.data["todos"] if not t.get("done")]
        self.store.save()
        self._include_done = False
        self.render_todos()

    def render_todos(self):
        while self.todo_layout.count():
            item = self.todo_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        self._update_fold_button()

        todos = self.store.todos(include_done=self._include_done)
        if not todos:
            all_done = bool(self.store.data["todos"]) and self._done_count() == len(
                self.store.data["todos"]
            )
            if all_done:
                empty = EmptyState("今天的待办都完成啦", "点下方「已完成」可以回看", "check_circle")
            else:
                empty = EmptyState("还没有待办", "在上方输入框记一条吧", "inbox")
            self.todo_layout.addWidget(empty)
        else:
            for t in todos:
                item = TodoItem(t, self.todo_holder, store=self.store)
                item.toggled.connect(self._on_toggle)
                item.pinned.connect(self._on_pin)
                item.removed.connect(self._on_remove)
                item.edited.connect(self._on_edit)
                item.remindClicked.connect(self._on_remind_click)
                item.dragBegin.connect(self._on_todo_drag_begin)
                item.dragMoved.connect(self._on_todo_drag_move)
                item.dragEnd.connect(self._on_todo_drag_end)
                item.installEventFilter(self)
                self.todo_layout.addWidget(item)
        self.todo_layout.addStretch(1)

    # ------------------------------------------------------------------ 拖动排序
    def _todo_widgets(self) -> list:
        """当前列表里的待办条目（跳过末尾的弹簧）"""
        out = []
        for i in range(self.todo_layout.count()):
            w = self.todo_layout.itemAt(i).widget()
            if isinstance(w, TodoItem):
                out.append(w)
        return out

    def _on_todo_drag_begin(self, tid: str):
        self._drag_tid = tid

    def _on_todo_drag_move(self, gpos):
        """被拖的那条跟着鼠标换位：按其它条目的中心线算落点，一次可以跨好几条"""
        items = self._todo_widgets()
        me = next((w for w in items if w.todo["id"] == self._drag_tid), None)
        if me is None:
            return
        cur = items.index(me)
        y = gpos.y()
        # 其它条目里，中心线在鼠标上方的条数 = 应该插入的位置
        target = 0
        for w in items:
            if w is me:
                continue
            if w.mapToGlobal(w.rect().center()).y() < y:
                target += 1
        # 置顶的永远压在上面：拖置顶的只能花在置顶区里，拖普通的进不了置顶区
        pinned_n = sum(1 for w in items if w.todo.get("pinned"))
        if me.todo.get("pinned"):
            target = max(0, min(target, max(0, pinned_n - 1)))
        else:
            target = max(pinned_n, target)
        if target != cur:
            self.todo_layout.removeWidget(me)
            self.todo_layout.insertWidget(target, me)
            self.todo_layout.activate()   # 立刻重算几何，下一帧的位置才准

    def _on_todo_drag_end(self, tid: str):
        if getattr(self, "_drag_tid", None) is None:
            return
        self._drag_tid = None
        ids = [w.todo["id"] for w in self._todo_widgets()]
        self.store.set_todo_order(ids)
        if self.store.get_setting("sort_mode", "created") != "manual":
            self.store.set_setting("sort_mode", "manual")
        self.render_todos()

    # ------------------------------------------------------------------ 待办
    def on_add_todo(self):
        text = self.todo_input.toPlainText().strip()
        if not text:
            return
        self.store.add_todo(text)
        self.todo_input.clear()
        self.refresh()

    def on_bell_new_todo(self):
        title = self.todo_input.toPlainText().strip()
        dlg = TodoEditDialog(
            title=title,
            remind_at=None,
            parent=self,
            store=self.store,
            remind_enabled=True,
        )
        if not dlg.exec():
            return
        title, remind, repeat = dlg.result()
        if not title:
            return
        self.store.add_todo(title, remind_at=remind, repeat=repeat)
        self.todo_input.clear()
        self.refresh()

    def _on_toggle(self, tid: str):
        self.store.toggle_done(tid)
        self.todoDoneChanged.emit(tid)
        self.render_todos()

    def _on_pin(self, tid: str):
        self.store.toggle_pin(tid)
        self.render_todos()

    def _on_remove(self, tid: str):
        self.store.delete_todo(tid)
        self.todoDeleted.emit(tid)
        self.render_todos()

    def _on_edit(self, tid: str):
        QTimer.singleShot(120, lambda: self._do_edit(tid))

    def _on_remind_click(self, tid: str):
        # 点提醒胶囊是单击操作，立即打开，不用等双击判定
        QTimer.singleShot(0, lambda: self._do_edit(tid))

    def _do_edit(self, tid: str):
        # 双击整行和单击提醒胶囊都可能触发；同时只允许一个编辑窗
        if self._edit_dialog_open:
            return
        todo = self.store.get_todo(tid)
        if not todo:
            return
        dlg = TodoEditDialog(
            title=todo.get("title", ""),
            remind_at=todo.get("remind_at"),
            parent=self,
            store=self.store,
            repeat=todo.get("repeat") or "none",
            base_remind_at=todo.get("base_remind_at") or todo.get("remind_at"),
        )
        self._edit_dialog_open = True
        try:
            accepted = dlg.exec()
        finally:
            self._edit_dialog_open = False
        if not accepted:
            return
        title, remind, repeat = dlg.result()
        if not title:
            return
        # 编辑待办改的是原始周期锚点，同时同步到 remind_at
        self.store.update_todo(tid, title=title, remind_at=remind, base_remind_at=remind, repeat=repeat)
        for i in range(self.todo_layout.count()):
            w = self.todo_layout.itemAt(i).widget()
            if isinstance(w, TodoItem) and w.todo.get("id") == tid:
                w.update_todo(self.store.get_todo(tid))
                break

    # ------------------------------------------------------------------ 设置
    def on_settings(self):
        from widgets.dialogs import SettingsDialog

        dlg = SettingsDialog(
            self.store,
            self,
            on_font_preview=self.apply_font_scale,
            on_sort_preview=self.apply_sort_mode,
        )
        dlg.exec()
        v = dlg.values()
        self.store.set_setting("autostart", v["autostart"])
        self.store.set_setting("sort_mode", v["sort_mode"])
        self.store.set_setting("edge_shrink", v["edge_shrink"])
        # 关掉就立刻取消正在跑的贴边计时；打开则按当前位置重新判断要不要计时
        self._arm_edge_shrink()
        try:
            from main import AutoStart

            AutoStart.set_enabled(v["autostart"])
        except Exception:
            pass
        self.apply_font_scale(v["font_scale"])

    def apply_sort_mode(self, mode: str):
        self.store.set_setting("sort_mode", mode)
        self.render_todos()

    def apply_font_scale(self, scale: str):
        app = QApplication.instance()
        if app is not None:
            set_font_scale(scale)
            app.setStyleSheet(app_qss(scale))
        self._update_note_header()
        self.refresh_note_buttons()
        self.refresh()

    def flush_pending(self):
        """退出 / 收成桌宠前，把便签的防抖保存立刻落盘"""
        self._flush_note()

    def on_close(self):
        self.flush_pending()
        self.save_position()
        self._is_edge_touched = False
        self.hide()
        # 窗口收进托盘后桌宠也没有：提醒要改落右下角（由外层控制器接管状态）
        self.hideToTray.emit()

    def save_position(self):
        nx, ny = self._fit_on_screen(self.x(), self.y())
        if (nx, ny) != (self.x(), self.y()):
            self.move(nx, ny)
        self.store.set_setting("win_pos", [self.x(), self.y()])

    # ------------------------------------------------------------------ 拖动
    def _drag_window_to(self, gpos: QPoint):
        """按住卡片拖动：按全局坐标差移动窗口

        不用 windowHandle().startSystemMove()：那是系统自己的移动循环，拖动过程中
        程序里做的 resize 会被它压住，胶囊翻过去了窗口却要松手才变宽。自己算位移，
        moveEvent 里的翻面和加宽当场就生效。
        """
        d = self._win_drag
        if d is None:
            return
        delta = gpos - d["press"]
        if not d["moved"]:
            if abs(delta.x()) < 2 and abs(delta.y()) < 2:
                return
            d["moved"] = True
        target_x = d["xy"].x() + delta.x()
        target_y = d["xy"].y() + delta.y()
        # 边拖边夹：卡片 / 右态胶囊列不许出屏幕可用区，到边就停住（不用等 moveEvent 回弹）
        cx, cy = self._clamp_to_screen(target_x, target_y)
        self.move(cx, cy)
        # moveEvent 是异步派发的，等它再判翻面就会晚一帧（看着像「翻过去了窗口没长宽」）；
        # 这里 move() 之后 self.x() 已经是新值，当场判一次，翻面和加宽同帧落到窗口上
        self._sync_pill_side()
        # 拖动中每动一下都把贴边计时清零，所以拖着走不会触发自动缩小
        self._arm_edge_shrink()

    def eventFilter(self, obj, event):
        # Ctrl+F 全局唤起查找条（焦点在待办输入框 / 便签正文里同样生效）
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_F
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.open_find()
            event.accept()
            return True
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
            and self._find_dlg is not None
            and self._find_dlg.isVisible()
        ):
            self.close_find()
            event.accept()
            return True
        holder = getattr(self, "todo_holder", None)
        scroll = getattr(self, "scroll", None)
        input_widget = getattr(self, "todo_input", None)
        if input_widget is not None and (
            obj is input_widget or obj is input_widget.viewport()
        ):
            if event.type() == QEvent.Type.Enter:
                if self.pages.currentIndex() == 0 and not input_widget.toPlainText().strip():
                    self._hint_timer.start()
            elif event.type() == QEvent.Type.Leave:
                self._hide_input_hint()
            return super().eventFilter(obj, event)
        # 窗口拖动：card 和 TodoItem 都触发
        is_drag_target = (obj is self.card or isinstance(obj, TodoItem))
        if is_drag_target and event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._clear_text_selection()
            self._hide_input_hint()
            self._win_drag = {
                "press": event.globalPosition().toPoint(),
                "xy": QPoint(self.x(), self.y()),
                "moved": False,
            }
            # 不拦截事件，让 TodoItem 自己处理长按排序
            return False
        if is_drag_target and event.type() == QEvent.Type.MouseMove:
            if self._win_drag is not None:
                self._drag_window_to(event.globalPosition().toPoint())
                return False
        if is_drag_target and (
            event.type() == QEvent.Type.MouseButtonRelease
            or event.type() == QEvent.Type.UngrabMouse
        ):
            if self._win_drag is not None:
                self._win_drag = None
                self._arm_edge_shrink()
                if event.type() == QEvent.Type.MouseButtonRelease:
                    return False
        # 待办列表区域：清除文字选中（TodoItem 已在上面处理过）
        if not isinstance(obj, TodoItem) and (
            (holder is not None and obj is holder)
            or (scroll is not None and isinstance(scroll, QScrollArea) and obj is scroll.viewport())
        ):
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._clear_text_selection()
                return super().eventFilter(obj, event)
        if scroll is not None and obj is scroll and event.type() == QEvent.Type.Resize:
            self._update_scroll_fade()
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key.Key_F
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.open_find()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._clear_text_selection()
        super().mousePressEvent(event)

    # ------------------------------------------------------------------ 列表底边渐隐
    def _place_scroll_fade(self):
        fade = getattr(self, "scroll_fade", None)
        if fade is None:
            return
        vp = self.scroll.viewport().geometry()
        fade.setGeometry(vp.x(), vp.bottom() - fade.FADE_H + 1, vp.width(), fade.FADE_H)
        fade.raise_()

    def _update_scroll_fade(self):
        fade = getattr(self, "scroll_fade", None)
        if fade is None:
            return
        sb = self.scroll.verticalScrollBar()
        self._place_scroll_fade()
        # 已经滚到底就不需要遮罩，否则会盖住最后一项的下边缘
        fade.setVisible(sb.maximum() > 0 and sb.value() < sb.maximum())

    def _clear_text_selection(self):
        """点击空白处时取消输入框 / 便签里的文字选中和焦点"""
        for name in ("todo_input", "note_edit"):
            edit = getattr(self, name, None)
            if edit is None:
                continue
            cursor = edit.textCursor()
            if cursor.hasSelection():
                cursor.clearSelection()
                edit.setTextCursor(cursor)
            edit.clearFocus()
        # 正在改便签名：点空白就算确认（对齐电脑里改文件名的习惯）
        renaming = getattr(self, "_note_rename_edit", None)
        if renaming is not None:
            renaming.clearFocus()

    # ------------------------------------------------------------------ 位置
    def _restore_pos(self):
        pos = self.store.get_setting("win_pos")
        x = y = None
        if pos and isinstance(pos, (list, tuple)) and len(pos) == 2:
            try:
                x, y = int(pos[0]), int(pos[1])
            except (TypeError, ValueError):
                x = y = None
        if x is None or y is None:
            avail = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
            x = avail.center().x() - WIN_W // 2
            y = avail.center().y() - WIN_H // 2
        nx, ny = self._fit_on_screen(x, y)
        self.move(nx, ny)

    def closeEvent(self, event):
        self._flush_note()
        self.save_position()
        super().closeEvent(event)


# 供外部（main.py）换算位置
__all__ = ["MainWindow", "WIN_W", "WIN_H", "CARD_X", "CARD_Y", "CARD_W", "CARD_H"]
