"""
widgets/todo_item.py —— 单条待办

统一后的外观：
  · 左侧自绘圆形勾选（未完成空心 / 完成蓝底白勾）
  · 标题（完成时灰色 + 删除线）
  · 提醒时间做成小胶囊贴在标题下方，过期变暖色
  · 右侧置顶 / 删除图标按钮，悬停才变蓝 / 变红
  · 置顶项用极浅蓝底 + 蓝色描边，不影响阅读
  · 双击整行编辑
"""

from __future__ import annotations

import html
import time
from datetime import datetime

from PyQt6.QtCore import QPoint, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from theme import C
from repeat import REPEAT_LABELS
from ui_icons import IconButton
from widgets.controls import CheckCircle, RemindChip, repolish, ui_font

DRAG_HOLD_MS = 200          # 按住多久算「要拖动排序」，短于这个时间松手算普通点击
DRAG_MOVE_MS = 120          # 已经按住这么久再滑动，也算要拖动


def _is_overdue(remind_at: str | None) -> bool:
    if not remind_at:
        return False
    try:
        return datetime.strptime(remind_at, "%Y-%m-%d %H:%M") < datetime.now()
    except ValueError:
        return False


def fmt_remind(s: str | None) -> str:
    """把 '2026-11-08 08:45' 转成 '11月8日 08:45'"""
    if not s:
        return ""
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
        return f"{dt.month}月{dt.day}日 {dt.strftime('%H:%M')}"
    except ValueError:
        return s


def fmt_remind_chip(remind_at: str | None, repeat: str = "none") -> str:
    """时间胶囊上的文案：时间 + 重复标记，如 `11月9日 09:00 · 工作日`"""
    text = fmt_remind(remind_at)
    if not text:
        return ""
    label = REPEAT_LABELS.get(repeat or "none", "")
    if repeat and repeat != "none" and label:
        return f"{text} · {label}"
    return text


class TodoItem(QFrame):
    """一条待办。构造时传入 todo dict，所有状态变化通过信号外发。"""

    toggled = pyqtSignal(str)        # todo_id（完成态切换）
    pinned = pyqtSignal(str)         # todo_id
    removed = pyqtSignal(str)        # todo_id
    edited = pyqtSignal(str)         # todo_id（双击整行）
    remindClicked = pyqtSignal(str)  # todo_id（点击提醒胶囊）
    dragBegin = pyqtSignal(str)      # 长按到点，进入拖动排序
    dragMoved = pyqtSignal(QPoint)   # 拖动中的鼠标全局坐标
    dragEnd = pyqtSignal(str)        # 松手，结束拖动

    def __init__(self, todo: dict, parent=None, store=None):
        super().__init__(parent)
        self.todo = todo
        self.store = store
        self.setObjectName("TodoItem")
        self._chip: RemindChip | None = None
        self._press_pos: QPoint | None = None
        self._press_at = 0.0
        self._dragging = False

        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(DRAG_HOLD_MS)
        self._hold.timeout.connect(self._start_drag)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 10, 10)
        root.setSpacing(10)

        # ---- 勾选 ----
        self.check = CheckCircle(done=bool(todo.get("done")), size=22, parent=self)
        self.check.clicked.connect(lambda: self.toggled.emit(self.todo["id"]))
        root.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)

        # ---- 标题 / 提醒 ----
        body = QVBoxLayout()
        body.setContentsMargins(0, 1, 0, 0)
        body.setSpacing(6)
        self.body = body

        # 标题和两个图标按钮排在同一行：按钮贴第一行文字，不再按整行高度居中。
        # 这样下面那行（时间胶囊）就能用满整条宽度，不必给按钮列让出一竖条。
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(0)

        self.title = QLabel(todo.get("title", ""), self)
        self.title.setObjectName("TodoText")
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.title.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        head.addWidget(self.title, 1)
        head.addSpacing(4)

        self.btn_pin = IconButton(
            "pin", color=C.INK_3, hover=C.INK_2, checked_color=C.PRIMARY,
            size=24, icon_size=14, checkable=True, tooltip="置顶",
        )
        self.btn_pin.clicked.connect(lambda: self.pinned.emit(self.todo["id"]))
        head.addWidget(self.btn_pin, 0, Qt.AlignmentFlag.AlignTop)

        self.btn_del = IconButton(
            "trash", color=C.INK_3, hover=C.DANGER,
            size=24, icon_size=16, tooltip="删除",
        )
        self.btn_del.setProperty("kind", "danger")
        self.btn_del.clicked.connect(lambda: self.removed.emit(self.todo["id"]))
        head.addWidget(self.btn_del, 0, Qt.AlignmentFlag.AlignTop)

        body.addLayout(head)
        root.addLayout(body, 1)

        self._refresh()

    # ------------------------------------------------------------------ 状态
    def _apply_title_font(self, done: bool):
        self.title.setFont(ui_font(14, strike=done))

    def _rebuild_chip(self):
        if self._chip is not None:
            self.body.removeWidget(self._chip)
            self._chip.deleteLater()
            self._chip = None
        remind = self.todo.get("remind_at")
        if not remind:
            return
        chip = RemindChip(
            fmt_remind_chip(remind, self.todo.get("repeat") or "none"),
            overdue=_is_overdue(remind),
            parent=self,
        )
        chip.clicked.connect(lambda: self.remindClicked.emit(self.todo["id"]))
        self.body.addWidget(chip, 0, Qt.AlignmentFlag.AlignLeft)
        self._chip = chip

    def _refresh(self):
        done = bool(self.todo.get("done"))
        pinned = bool(self.todo.get("pinned"))

        self.check.setDone(done)
        self._apply_title_font(done)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setProperty("done", done)
        self.setProperty("pinned", pinned)
        self.title.setProperty("done", done)
        repolish(self)
        repolish(self.title)

        self.btn_pin.setChecked(pinned)

        if self._chip is None:
            self._rebuild_chip()

    def update_todo(self, todo: dict):
        """外部数据变化后，只更新本 item 的显示，不重建整个列表。"""
        self.todo = todo
        self.title.setText(todo.get("title", ""))
        if self._chip is not None:
            self.body.removeWidget(self._chip)
            self._chip.deleteLater()
            self._chip = None
        self._refresh()

    # ------------------------------------------------------------------ 查找高亮
    def highlight_match(self, keyword: str):
        """把标题里命中的关键词用主题色高亮标出。"""
        self._set_title_highlight(keyword)

    def clear_highlight(self):
        self.title.setText(self.todo.get("title", ""))

    def _set_title_highlight(self, keyword: str):
        title = self.todo.get("title", "")
        q = (keyword or "").strip().lower()
        if not q:
            self.title.setText(title)
            return
        idx = title.lower().find(q)
        if idx < 0:
            self.title.setText(title)
            return
        before = html.escape(title[:idx])
        hit = html.escape(title[idx:idx + len(q)])
        after = html.escape(title[idx + len(q):])
        self.title.setText(
            f'{before}<span style="color:{C.PRIMARY};'
            f'background-color:{C.PRIMARY_SOFT};">{hit}</span>{after}'
        )

    # ------------------------------------------------------------------ 交互
    # 长按（380ms）不动 → 进入拖动排序；短按 / 一按就动 = 普通点击 / 双击编辑
    def _start_drag(self):
        if self._press_pos is None:
            return
        self._dragging = True
        self.setProperty("dragging", True)
        repolish(self)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        # 启动排序时，取消窗口拖动，避免两个拖动同时进行
        win = self.window()
        if hasattr(win, '_win_drag'):
            win._win_drag = None
        self.dragBegin.emit(self.todo["id"])
        self.dragMoved.emit(self.mapToGlobal(self.rect().center()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._press_at = time.monotonic()
            self._hold.start()
            # 不调用 event.accept()，让事件冒泡到 card，触发窗口拖动
            # 长按超过 200ms 后再启动排序，同时阻止冒泡
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is None:
            return
        if self._dragging:
            self.dragMoved.emit(event.globalPosition().toPoint())
            event.accept()
            return
        moved = (event.globalPosition().toPoint() - self._press_pos).manhattanLength()
        if moved > 8:          # 按住已经够久再滑，也算要拖动；一按就滑才是普通点击
            if time.monotonic() - self._press_at >= DRAG_MOVE_MS / 1000:
                self._start_drag()
                self.dragMoved.emit(event.globalPosition().toPoint())
                event.accept()
                return
            self._hold.stop()
            self._press_pos = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._hold.stop()
        was_dragging = self._dragging
        self._press_pos = None
        if was_dragging:
            self._dragging = False
            self.setProperty("dragging", False)
            repolish(self)
            self.unsetCursor()
            self.dragEnd.emit(self.todo["id"])
            event.accept()                # 拖完这一下不当成点击，也别冒泡去拖窗口
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.edited.emit(self.todo["id"])
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """右键：直接复制整个标题到剪贴板"""
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.todo.get("title", ""))
