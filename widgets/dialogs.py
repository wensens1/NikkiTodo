"""
widgets/dialogs.py —— 待办编辑 / 提醒时间 / 设置

两个弹窗都继承 BaseDialog，因此圆角、投影、标题栏、按钮区完全一致；
日历、时间下拉、开关、分段选择也都来自同一套 QSS 规范。
"""

from __future__ import annotations

import time
from datetime import datetime

from PyQt6.QtCore import (
    QDate,
    QEvent,
    QPoint,
    QRectF,
    QRegularExpression,
    QSize,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QRegularExpressionValidator,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCalendarWidget,
    QComboBox,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from theme import C, font_px
from repeat import REPEAT_LABELS
from ui_icons import IconButton, icon
from ui_utils import add_shadow, round_menu
from widgets.controls import SegmentedControl, Switch, icon_label, repolish
from widgets.dialog_base import BaseDialog


# --------------------------------------------------------------------------- #
#  日历：把默认的方块选中改成圆形（和勾选圈同一套视觉）
# --------------------------------------------------------------------------- #
class _DayDelegate(QStyledItemDelegate):
    def __init__(self, calendar: QCalendarWidget, parent=None):
        super().__init__(parent)
        self._cal = calendar

    def _date_for(self, index) -> QDate:
        # 模型第 0 行是星期表头，日期从第 1 行开始
        first = QDate(self._cal.yearShown(), self._cal.monthShown(), 1)
        first_dow = self._cal.firstDayOfWeek().value
        offset = (first.dayOfWeek() - first_dow) % 7
        return first.addDays((index.row() - 1) * 7 + index.column() - offset)

    def paint(self, painter: QPainter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 星期表头：统一成浅冷灰底，避免 Fusion 默认的暖灰
        if index.row() == 0:
            painter.fillRect(opt.rect, QColor(C.BG_SOFT))
            header_font = QFont(opt.font)
            header_font.setPixelSize(font_px(11))
            painter.setFont(header_font)
            brush = index.data(Qt.ItemDataRole.ForegroundRole)
            color = QColor(brush.color()) if isinstance(brush, QBrush) else QColor(C.INK_3)
            painter.setPen(color)
            painter.drawText(opt.rect, Qt.AlignmentFlag.AlignCenter, text)
            painter.restore()
            return

        side = min(opt.rect.width(), opt.rect.height()) - 6
        circle = QRectF(
            opt.rect.center().x() - side / 2 + 0.5,
            opt.rect.center().y() - side / 2 + 0.5,
            side,
            side,
        )

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(C.PRIMARY))
            painter.drawEllipse(circle)
        elif self._date_for(index) == QDate.currentDate():
            pen = QPen(QColor(C.PRIMARY))
            pen.setWidthF(1.2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(circle.adjusted(0.8, 0.8, -0.8, -0.8))

        if selected:
            color = QColor(C.WHITE)
        else:
            brush = index.data(Qt.ItemDataRole.ForegroundRole)
            color = QColor(brush.color()) if isinstance(brush, QBrush) else QColor(
                opt.palette.color(opt.palette.ColorRole.Text)
            )

        painter.setFont(opt.font)
        painter.setPen(color)
        painter.drawText(opt.rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


# --------------------------------------------------------------------------- #
#  小部件
# --------------------------------------------------------------------------- #
class _TimePopup(QFrame):
    """时间选择弹层：自绘圆角卡片 + 列表，外观与菜单 / 卡片完全一致"""

    picked = pyqtSignal(str)
    ROW_H = 30                      # 与 QSS 里 QListWidget#TimeList::item 的 height 一致
    PAD = 6                         # 与 QSS 里 TimeList 的 padding 一致
    VISIBLE_ROWS = 8
    SHADOW = 14

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.SHADOW, self.SHADOW, self.SHADOW, self.SHADOW)
        outer.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("PopupCard")
        add_shadow(self.card, blur=28, dy=0, alpha=50)
        outer.addWidget(self.card)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.list = QListWidget(self.card)
        self.list.setObjectName("TimeList")
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.itemClicked.connect(self._on_clicked)
        self.list.itemActivated.connect(self._on_clicked)
        lay.addWidget(self.list)

    def open_for(
        self,
        options: list[str],
        current: str,
        anchor: QWidget,
        align: QWidget | None = None,
    ):
        """anchor 决定弹层贴哪一行的下方，align 决定左右对齐谁。

        时间胶囊这类「外壳里还嵌着图标 + 输入框 + 箭头」的控件，如果按内部的
        输入框对齐，弹层会整体右移半格；所以外壳宽度和左边缘要单独传进来。
        """
        self.list.clear()
        self.list.addItems(options)
        matches = self.list.findItems(current, Qt.MatchFlag.MatchExactly)
        row = self.list.row(matches[0]) if matches else 0
        self.list.setCurrentRow(row)

        field = align or anchor
        rows = min(len(options), self.VISIBLE_ROWS)
        card_w = max(field.width(), 150)
        # 高度必须正好是 N 行整数倍 + 内边距 + 卡片 1px 框：多出来的零头会把
        # 下一行裁成半行，125% 缩放下就成了「一排彩色小点」
        card_h = rows * self.ROW_H + self.PAD * 2 + 2
        self.card.setFixedSize(card_w, card_h)
        self.setFixedSize(card_w + self.SHADOW * 2, card_h + self.SHADOW * 2)

        below = field.mapToGlobal(QPoint(0, field.height() + 2))
        avail = field.screen().availableGeometry()
        x = below.x()
        y = below.y()
        # 弹层比外壳宽时改成右对齐，免得整块往右探出去
        if card_w > field.width():
            x = field.mapToGlobal(QPoint(field.width(), 0)).x() - card_w
        if y + card_h > avail.bottom():
            y = field.mapToGlobal(QPoint(0, 0)).y() - card_h - 2
        x = max(avail.left(), min(x, avail.right() - card_w + 1))
        y = max(avail.top(), min(y, avail.bottom() - card_h + 1))

        self.move(x - self.SHADOW, y - self.SHADOW)
        self.show()
        self.raise_()
        self.list.scrollToItem(
            self.list.item(row), QAbstractItemView.ScrollHint.PositionAtCenter
        )
        self.list.setFocus()

    def _on_clicked(self, item):
        self.picked.emit(item.text())
        self.hide()


class _RepeatCombo(QComboBox):
    """重复选择：外壳沿用 QComboBox#Field，弹层换成自绘圆角卡片

    原生下拉弹的是直角白框独立窗口，和本程序的圆角弹层 / 菜单不是一套；
    这里跟 _TimeCombo 一样绕开原生弹层，改用 _TimePopup。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup: _TimePopup | None = None

    def showPopup(self):
        if not self.count():
            return
        if self._popup is None:
            self._popup = _TimePopup(self.window())
            self._popup.picked.connect(self._on_picked)
        options = [self.itemText(i) for i in range(self.count())]
        self._popup.open_for(options, self.currentText(), self)

    def hidePopup(self):
        if self._popup is not None:
            self._popup.hide()
        super().hidePopup()

    def _on_picked(self, text: str):
        idx = self.findText(text)
        if idx >= 0:
            self.setCurrentIndex(idx)
        self.hidePopup()


_TIME_RE = QRegularExpression(r"\d{0,2}:\d{0,2}")

def _parse_time_text(text: str | None) -> str | None:
    """把 7:5 / 07:05 / 7：05 统一成 07:05；非法返回 None"""
    text = (text or "").strip().replace("：", ":")
    parts = text.split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


class _TimeEdit(QLineEdit):
    """HH:MM 固定格式的时间输入框，四个数字各自独立编辑

    · 冒号是格式的一部分，删不掉、改不了，光标走到它会自动跳过
    · 第 1 位只能 0–2；第 1 位是 0/1 时第 2 位 0–9，是 2 时第 2 位只能 0–3
    · 第 3 位只能 0–5，第 4 位 0–9
    · 每次只选中一位数字，输完自动前进到下一个可编辑位
    """

    _SLOTS = (0, 1, 3, 4)            # 可编辑位在文本里的下标（2 是冒号）
    _NEXT = {0: 1, 1: 3, 3: 4, 4: 0}
    _PREV = {1: 0, 3: 1, 4: 3, 0: 4}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hour = 0
        self._minute = 0
        self._slot = 0               # 当前编辑位（0/1/3/4）
        self._applying = False
        self._suppress_selection = True   # 初始化/程序化设置时不自动选中
        self._range_slots: list[int] = []   # 多选连续输入时的位列表
        self._range_idx = 0
        self._click_count = 0
        self._last_click_at = 0.0
        self._drag_anchor = -1
        self.setAcceptDrops(False)
        self.setDragEnabled(False)
        # 兜底：任何绕过按键处理的路径把文本改坏了，都会在下一次心跳里恢复成 HH:MM
        self._guard = QTimer(self)
        self._guard.setInterval(400)
        self._guard.timeout.connect(self._ensure_format)
        self._guard.start()
        self.setMaxLength(5)
        # 只读：文本只能由本类写入，任何原生编辑路径（拖放/右键菜单/撤销/输入法）
        # 都不可能改动框里的内容和那个冒号；键盘输入全部走下面的 keyPressEvent
        self.setReadOnly(True)
        # 只收数字：中文输入法开着时也不让它介入，否则拼音/候选窗会打断输入
        self.setInputMethodHints(
            Qt.InputMethodHint.ImhDigitsOnly | Qt.InputMethodHint.ImhNoPredictiveText
        )
        # setText 不是虚函数，外部（QComboBox 内部）改文本只能靠 textChanged 同步
        self.textChanged.connect(self._on_text_changed)
        self._apply()

    # ---------------------------------------------------------------- 内部
    def _apply(self):
        text = f"{self._hour:02d}:{self._minute:02d}"
        if self.text() != text:
            self._applying = True
            QLineEdit.setText(self, text)
            self._applying = False
        if self._suppress_selection:
            # 初始化/程序化设置时不选中，光标放末尾
            QLineEdit.setCursorPosition(self, len(text))
            return
        if self._range_slots:
            # 多选输入时保持整段高亮，用户能看出在改哪几位
            start = min(self._range_slots)
            end = max(self._range_slots) + 1
            QLineEdit.setCursorPosition(self, end)
            QLineEdit.setSelection(self, start, end - start)
            return
        if self._slot not in self._SLOTS:
            self._slot = 0
        QLineEdit.setCursorPosition(self, self._slot)
        QLineEdit.setSelection(self, self._slot, 1)

    def _on_text_changed(self, text: str):
        if self._applying:
            return
        self._range_slots = []
        parsed = _parse_time_text(text)
        if parsed is None:
            self._apply()        # 外部塞了不合规的文本：还原
            return
        self._hour = int(parsed[:2])
        self._minute = int(parsed[3:])
        self._apply()

    def _ensure_format(self):
        """兜底校验：文本一旦不是 HH:MM 就按内部状态重写"""
        if not self.isVisible() or not self.hasFocus():
            return
        if self.text() != f"{self._hour:02d}:{self._minute:02d}":
            self._apply()

    # ---------------------------------------------------------------- 位
    def _slot_for_caret(self, caret: int) -> int:
        if caret <= 1:
            return 0 if caret <= 0 else 1
        if caret == 2:
            return 3             # 点在冒号上算分钟十位
        return 4 if caret >= 4 else 3

    def _slot_value(self, slot: int) -> int:
        if slot == 0:
            return self._hour // 10
        if slot == 1:
            return self._hour % 10
        if slot == 3:
            return self._minute // 10
        return self._minute % 10

    def _slot_limit(self, slot: int) -> int:
        if slot == 0:
            return 2
        if slot == 1:
            return 3 if self._hour // 10 == 2 else 9
        if slot == 3:
            return 5
        return 9

    def _set_slot_value(self, slot: int, value: int):
        value = max(0, min(int(value), self._slot_limit(slot)))
        h_t, h_u = self._hour // 10, self._hour % 10
        m_t, m_u = self._minute // 10, self._minute % 10
        if slot == 0:
            h_t = value
            if h_t == 2 and h_u > 3:
                h_u = 3
        elif slot == 1:
            h_u = value
        elif slot == 3:
            m_t = value
        else:
            m_u = value
        self._hour = h_t * 10 + h_u
        self._minute = m_t * 10 + m_u

    def select_at(self, caret_pos: int):
        """按光标位置选中某一个数字位"""
        self._range_slots = []
        self._slot = self._slot_for_caret(caret_pos)
        self._apply()

    def select_range(self, caret_pos: int):
        """双击用：选中光标所在的那一段（小时两位 / 分钟两位）"""
        self._range_slots = []
        if self._slot_for_caret(caret_pos) <= 1:
            self._slot = 0
            start = 0
        else:
            self._slot = 3
            start = 3
        QLineEdit.setCursorPosition(self, start + 2)
        QLineEdit.setSelection(self, start, 2)

    def select_all_slots(self):
        """三击用：整段时间全选"""
        self._range_slots = []
        self._slot = 0
        QLineEdit.setCursorPosition(self, 5)
        QLineEdit.setSelection(self, 0, 5)

    def _selected_slots(self) -> list[int]:
        if not self.hasSelectedText():
            return []
        start = self.selectionStart()
        end = start + len(self.selectedText())
        return [s for s in self._SLOTS if start <= s < end]

    def _digit(self, d: int):
        slots = self._selected_slots()
        if len(slots) > 1 and len(slots) > len(self._range_slots):
            # 第一次在多选范围内输入：从最左边一位开始依次填
            self._range_slots = slots
            self._range_idx = 0
        if self._range_slots:
            slot = self._range_slots[min(self._range_idx, len(self._range_slots) - 1)]
            self._set_slot_value(slot, d)
            self._range_idx += 1
            if self._range_idx >= len(self._range_slots):
                last = self._range_slots[-1]
                self._range_slots = []
                self._range_idx = 0
                self._slot = self._NEXT[last]
            else:
                self._slot = self._range_slots[self._range_idx]
            self._apply()
            return
        self._set_slot_value(self._slot, d)
        self._slot = self._NEXT[self._slot]
        self._apply()

    def _step(self, delta: int):
        limit = self._slot_limit(self._slot)
        value = self._slot_value(self._slot) + delta
        if value > limit:
            value = 0
        elif value < 0:
            value = limit
        self._set_slot_value(self._slot, value)
        self._apply()

    # ---------------------------------------------------------------- 事件
    def keyPressEvent(self, event):
        key = event.key()
        text = event.text()
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_A:
                self.select_all_slots()
                event.accept()
                return
            if key == Qt.Key.Key_C:
                QApplication.clipboard().setText(self.text())
                event.accept()
                return
            if key == Qt.Key.Key_X:
                QApplication.clipboard().setText(self.text())
                self._hour = 0
                self._minute = 0
                self._range_slots = []
                self._slot = 0
                self._apply()
                event.accept()
                return
            if key == Qt.Key.Key_V:
                parsed = _parse_time_text(QApplication.clipboard().text())
                if parsed is not None:
                    self._hour = int(parsed[:2])
                    self._minute = int(parsed[3:])
                self._apply()
                event.accept()
                return
            # 撤销 / 重做等一律不让它改动文本
            self._apply()
            event.accept()
            return
        if text and text.isdigit():
            self._digit(int(text))
            event.accept()
            return
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            slots = self._selected_slots()
            if len(slots) > 1:
                # 选了几位就一起清 0（例如后两位一起清零）
                for s in slots:
                    self._slot = s
                    self._set_slot_value(s, 0)
                self._range_slots = []
                self._slot = slots[0]
            else:
                self._range_slots = []
                self._set_slot_value(self._slot, 0)
            self._apply()
            event.accept()
            return
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._range_slots = []
            self._slot = self._PREV[self._slot] if key == Qt.Key.Key_Left else self._NEXT[self._slot]
            self._apply()
            event.accept()
            return
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._step(1 if key == Qt.Key.Key_Up else -1)
            event.accept()
            return
        if text == ":" or key == Qt.Key.Key_Colon:
            self._slot = self._NEXT[self._slot]
            self._apply()
            event.accept()
            return
        if key in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Tab,
            Qt.Key.Key_Backtab,
            Qt.Key.Key_Escape,
        ):
            super().keyPressEvent(event)
            return
        event.accept()          # 其它字符一律不进输入框

    def keyReleaseEvent(self, event):
        super().keyReleaseEvent(event)
        self._ensure_format()   # 松手立刻校验，不等到心跳

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._suppress_selection = False   # 用户首次点击后开始正常选中
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        now = time.monotonic()
        if now - self._last_click_at < 0.5:
            self._click_count += 1
        else:
            self._click_count = 1
        self._last_click_at = now

        super().mousePressEvent(event)          # 原生定位光标，并保留拖选能力
        self._drag_anchor = self.cursorPositionAt(event.position().toPoint())
        if self._click_count >= 3:
            self._drag_anchor = -1
            self.select_all_slots()             # 连点三次 = 整段全选
            event.accept()
            return
        if not self.hasSelectedText():
            self.select_at(self.cursorPosition())
        event.accept()

    def mouseMoveEvent(self, event):
        # 按住拖出任意范围（比如一次选中后三位）
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._drag_anchor < 0:
            super().mouseMoveEvent(event)
            return
        cur = self.cursorPositionAt(event.position().toPoint())
        cur = max(0, min(cur, 5))
        start, end = min(self._drag_anchor, cur), max(self._drag_anchor, cur)
        start = max(0, min(start, 4))
        end = max(0, min(end, 4))
        self._range_slots = []
        QLineEdit.setCursorPosition(self, end + 1)
        QLineEdit.setSelection(self, start, end - start + 1)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_anchor = -1
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._click_count = 2
        self._last_click_at = time.monotonic()
        # 双击 = 选中所在那一段（小时两位 / 分钟两位），可直接输两位数
        self.select_range(self.cursorPositionAt(event.position().toPoint()))
        event.accept()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._range_slots = []
        # 不要自动选中第一位，光标放在末尾，用户想改哪位点哪
        QLineEdit.setCursorPosition(self, len(self.text()))

    def insertFromMimeData(self, source):
        parsed = _parse_time_text(source.text())
        if parsed is not None:
            QLineEdit.setText(self, parsed)

    def dropEvent(self, event):
        # 不接拖放的文本，格式只能靠键盘改
        event.accept()

    def contextMenuEvent(self, event):
        # 原生菜单里的“删除 / 剪切 / 撤销 / 粘贴”会绕过按键处理改动文本，直接不弹
        event.accept()

    def inputMethodEvent(self, event):
        # 时间框只认键盘数字，输入法组合输入（拼音、候选窗）一律不介入
        event.accept()


class _TimeCombo(QComboBox):
    """时间选择：可下拉选 15 分钟刻度，也可以直接输入任意时间

    输入框始终可编辑：单击定位光标、双击选中整段后直接改；
    下拉箭头仍然打开统一风格的 15 分钟列表。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup: _TimePopup | None = None
        self._last_valid = "09:00"
        self._popup_align: QWidget | None = None
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setCompleter(None)
        edit = _TimeEdit(self)
        self.setLineEdit(edit)
        edit.editingFinished.connect(self.commit_time)
        edit.returnPressed.connect(self.commit_time)
        self.currentTextChanged.connect(self._remember_time)

    def _in_dropdown(self, pos) -> bool:
        # 下拉箭头已经独立成右侧的小按钮，输入框区域全部用于编辑
        return False

    def focusInEvent(self, event):
        # 焦点落到 combo 本体时要转给内部输入框，否则敲键盘进不来
        super().focusInEvent(event)
        edit = self.lineEdit()
        if edit is not None and not edit.hasFocus():
            edit.setFocus(Qt.FocusReason.TabFocusReason)

    def keyPressEvent(self, event):
        edit = self.lineEdit()
        if edit is not None and not edit.hasFocus():
            edit.setFocus(Qt.FocusReason.OtherFocusReason)
            edit.keyPressEvent(event)
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # 点输入区域 = 进入编辑，不弹列表；只有点右侧箭头才展开
        if event.button() == Qt.MouseButton.LeftButton and not self._in_dropdown(
            event.position()
        ):
            edit = self.lineEdit()
            edit.setFocus(Qt.FocusReason.MouseFocusReason)
            edit.select_at(
                edit.cursorPositionAt(edit.mapFrom(self, event.position().toPoint()))
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._in_dropdown(
            event.position()
        ):
            edit = self.lineEdit()
            edit.setFocus(Qt.FocusReason.MouseFocusReason)
            edit.select_range(
                edit.cursorPositionAt(edit.mapFrom(self, event.position().toPoint()))
            )
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _remember_time(self, text: str):
        normalized = _parse_time_text(text)
        if normalized is not None:
            self._last_valid = normalized

    def commit_time(self):
        """把输入框内容规范化（非法时回到上一次有效值）"""
        normalized = _parse_time_text(self.currentText())
        if normalized is None:
            normalized = self._last_valid
        if self.findText(normalized) < 0:
            index = self.count()
            for i in range(self.count()):
                if self.itemText(i) > normalized:
                    index = i
                    break
            self.insertItem(index, normalized)
        self.setCurrentText(normalized)
        self._last_valid = normalized

    def set_popup_align(self, widget: QWidget):
        """弹层左右对齐的参照：时间胶囊是「时钟图标 + 输入框 + 箭头」的外壳，
        只按输入框对齐会整体右移，所以由调用方把外壳传进来。"""
        self._popup_align = widget

    def showPopup(self):
        # 打开列表前先把正在输入的内容落成合法时间
        self.commit_time()
        if self._popup is not None and self._popup.isVisible():
            self._popup.hide()
            return
        if self._popup is None:
            self._popup = _TimePopup(self.window())
            self._popup.picked.connect(self._on_picked)
        options = [self.itemText(i) for i in range(self.count())]
        self._popup.open_for(options, self.currentText(), self, self._popup_align)

    def hidePopup(self):
        if self._popup is not None:
            self._popup.hide()
        super().hidePopup()

    def _on_picked(self, text: str):
        self.setCurrentText(text)
        self._last_valid = text
        self.hidePopup()


class _TitleEdit(QTextEdit):
    """事项输入：Enter 保存，Ctrl+Enter 换行"""

    submitted = pyqtSignal()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # 焦点移走时取消选中，不然点其他地方后文字还高亮着
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.insertPlainText("\n")
                return
            self.submitted.emit()
            return
        super().keyPressEvent(event)


def _time_options() -> list[str]:
    return [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)]


# --------------------------------------------------------------------------- #
#  编辑待办 / 提醒时间
# --------------------------------------------------------------------------- #
class TodoEditDialog(BaseDialog):
    def __init__(
        self,
        title: str = "",
        remind_at: str | None = None,
        parent=None,
        store=None,
        remind_enabled: bool | None = None,
        repeat: str = "none",
        base_remind_at: str | None = None,
    ):
        initial_on = bool(remind_at) if remind_enabled is None else bool(remind_enabled)
        super().__init__("编辑待办" if remind_at or title else "新建待办", parent, width=380)
        self.store = store
        self._base_remind_at = base_remind_at or remind_at
        self.body.setSpacing(12)
        # 底部边距加大，防止重复下拉框被切
        self.body.setContentsMargins(22, 18, 22, 32)

        # ---- 事项内容 ----
        self.title_edit = _TitleEdit(self.card)
        self.title_edit.setObjectName("Field")
        self.title_edit.setPlaceholderText("写点什么…  Enter 保存，Ctrl+Enter 换行")
        self.title_edit.setPlainText(title)
        self.title_edit.setFixedHeight(112)
        self.title_edit.submitted.connect(self._on_ok)
        self.title_edit.textChanged.connect(self._sync_save_state)
        self.body.addWidget(self.title_edit)

        # ---- 提醒时间：开关 + 可折叠的日期 / 时间 ----
        remind_row = QHBoxLayout()
        remind_row.setContentsMargins(0, 0, 0, 0)
        remind_row.setSpacing(8)
        remind_row.addWidget(self._field_label("提醒时间"))
        remind_row.addStretch(1)
        self.remind_switch = Switch(self.card)
        self.remind_switch.setChecked(initial_on)
        self.remind_switch.toggled.connect(self._on_remind_toggled)
        remind_row.addWidget(self.remind_switch)
        self.body.addLayout(remind_row)

        self.remind_box = QWidget(self.card)
        rb = QVBoxLayout(self.remind_box)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(10)

        cal_card = QFrame(self.remind_box)
        cal_card.setObjectName("CalendarCard")
        cal_lay = QVBoxLayout(cal_card)
        cal_lay.setContentsMargins(8, 6, 8, 6)
        cal_lay.setSpacing(4)

        self.cal = QCalendarWidget(cal_card)
        self.cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.cal.setHorizontalHeaderFormat(
            QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
        )
        self.cal.setGridVisible(False)
        self.cal.setNavigationBarVisible(False)
        self.cal.setFixedHeight(220)
        self._build_calendar_header(cal_lay)
        self._style_weekend()
        self._install_day_delegate()
        self.cal.currentPageChanged.connect(self._on_page_changed)
        cal_lay.addWidget(self.cal)
        rb.addWidget(cal_card)

        time_row = QHBoxLayout()
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.setSpacing(10)

        time_shell = QFrame(self.remind_box)
        time_shell.setObjectName("TimeShell")
        time_shell.setFixedSize(162, 42)
        self.time_shell = time_shell
        sh = QHBoxLayout(time_shell)
        sh.setContentsMargins(10, 0, 4, 0)
        sh.setSpacing(4)
        sh.addWidget(icon_label("clock", C.PRIMARY, 15))

        self.time_combo = _TimeCombo(time_shell)
        self.time_combo.setObjectName("TimeComboFlat")
        # objectName 是在 QComboBox 初始化之后才设置的，需要重新 polish 一次，
        # 否则原生白色边框和下拉箭头会残留。
        repolish(self.time_combo)
        repolish(self.time_combo.lineEdit())
        self.time_combo.addItems(_time_options())
        self.time_combo.setFixedHeight(36)
        self.time_combo.set_popup_align(time_shell)
        self.time_combo.lineEdit().installEventFilter(self)
        sh.addWidget(self.time_combo, 1)

        self.time_drop = IconButton(
            "chevron_down", color=C.INK_3, hover=C.PRIMARY,
            size=26, icon_size=14, tooltip="选择时间", parent=time_shell,
        )
        self.time_drop.clicked.connect(self.time_combo.showPopup)
        sh.addWidget(self.time_drop)
        time_row.addWidget(time_shell)

        time_row.addStretch(1)
        rb.addLayout(time_row)

        # ---- 重复：不重复 / 每日 / 每周 / 每月 / 每年 / 工作日 ----
        repeat_row = QHBoxLayout()
        repeat_row.setContentsMargins(0, 0, 0, 0)
        repeat_row.setSpacing(10)
        repeat_row.addWidget(self._field_label("重复"))
        self.repeat_combo = _RepeatCombo(self.remind_box)
        self.repeat_combo.setObjectName("Field")
        for key, label in REPEAT_LABELS.items():
            self.repeat_combo.addItem(label, key)
        self.repeat_combo.setFixedHeight(36)
        self.repeat_combo.setMinimumWidth(132)
        self.repeat_combo.setToolTip("选了重复，到点没完成会自动顺到下一次；完成了第二天再给一条")
        repolish(self.repeat_combo)
        repeat_row.addWidget(self.repeat_combo, 1)
        rb.addLayout(repeat_row)

        # 重复锚点时间说明（base_remind_at）
        self.anchor_label = QLabel("", self.remind_box)
        self.anchor_label.setObjectName("SectionHint")
        self.anchor_label.setWordWrap(True)
        rb.addWidget(self.anchor_label)

        # 日历、时间选择器、重复下拉框变化时，实时更新说明文字
        self.cal.selectionChanged.connect(self._update_anchor_label)
        self.time_combo.currentTextChanged.connect(lambda _: self._update_anchor_label())
        self.repeat_combo.currentIndexChanged.connect(self._update_anchor_label)
        self.remind_switch.toggled.connect(self._update_anchor_label)

        # 重复行下面留空，防止下拉框底部圆角被切
        rb.addSpacing(12)

        self.body.addWidget(self.remind_box)
        self.remind_box.setVisible(initial_on)

        # ---- 底部 ----
        self.btn_ok, _, _ = self.add_footer(primary_text="保存", ghost_text="取消")
        self.btn_ok.clicked.connect(self._on_ok)

        # 给卡片装 eventFilter，捕获空白处点击（事件被 QFrame 吃掉，不会冒泡到对话框）
        self.card.installEventFilter(self)

        self._load_remind(remind_at)
        self._load_repeat(repeat)
        self._update_anchor_label()
        self._sync_calendar_header(self.cal.yearShown(), self.cal.monthShown())
        # 先强制布局一遍，再让 finalize 算高度
        self.card.layout().activate()
        self.finalize()
        self._sync_save_state()

    # ------------------------------------------------------------------ 构建
    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text, self.card)
        label.setObjectName("FieldLabel")
        return label

    def _build_calendar_header(self, parent_layout: QVBoxLayout):
        """自绘日历头部：上个月 / 月份 / 年份 / 下个月

        QCalendarWidget 自带的年份编辑在自定义 QSS 下会压住月份文字，
        所以干脆隐藏系统导航栏，改用同一套按钮和输入框。
        """
        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 2)
        row.setSpacing(4)

        self.cal_prev = IconButton(
            "chevron_left", color=C.INK_2, hover=C.INK,
            size=26, icon_size=14, tooltip="上个月", parent=self.remind_box,
        )
        self.cal_prev.clicked.connect(self.cal.showPreviousMonth)
        row.addWidget(self.cal_prev)

        # 「今天」：一键把日期选回今天（连同日历翻到本月）
        self.btn_today = QPushButton("今天", self.remind_box)
        self.btn_today.setObjectName("TodayPill")
        self.btn_today.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_today.setFixedHeight(26)
        self.btn_today.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_today.setToolTip("把提醒日期选回今天")
        self.btn_today.clicked.connect(self._go_today)
        row.addWidget(self.btn_today)

        row.addStretch(1)

        self.cal_month = QPushButton("11月", self.remind_box)
        self.cal_month.setObjectName("CalendarMonth")
        self.cal_month.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cal_month.setFixedHeight(32)
        self.cal_month.setMinimumWidth(80)
        self.cal_month.setIcon(icon("chevron_down", C.INK_3, 12))
        self.cal_month.setIconSize(QSize(12, 12))
        self.cal_month.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.cal_month.clicked.connect(self._show_month_menu)
        row.addWidget(self.cal_month)

        self.year_spin = QSpinBox(self.remind_box)
        self.year_spin.setObjectName("YearSpin")
        self.year_spin.setRange(1900, 2200)
        self.year_spin.setSuffix(" 年")
        self.year_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.year_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self.year_spin.setKeyboardTracking(False)
        self.year_spin.setFixedSize(116, 32)
        self.year_spin.setValue(self.cal.yearShown())
        self.year_spin.valueChanged.connect(self._on_year_changed)
        row.addWidget(self.year_spin)

        row.addStretch(1)
        self.cal_next = IconButton(
            "chevron_right", color=C.INK_2, hover=C.INK,
            size=26, icon_size=14, tooltip="下个月", parent=self.remind_box,
        )
        self.cal_next.clicked.connect(self.cal.showNextMonth)
        row.addWidget(self.cal_next)
        parent_layout.addLayout(row)

    def _sync_calendar_header(self, year: int, month: int):
        self.cal_month.setText(f"{month}月")
        self.year_spin.blockSignals(True)
        self.year_spin.setValue(year)
        self.year_spin.blockSignals(False)

    def _on_page_changed(self, year: int, month: int):
        # 换年 / 换月时把选中日期跟到当前页，避免“显示 2027、保存 2026”
        selected = self.cal.selectedDate()
        if selected.year() != year or selected.month() != month:
            days = QDate(year, month, 1).daysInMonth()
            self.cal.setSelectedDate(QDate(year, month, min(selected.day(), days)))
        self._sync_calendar_header(year, month)

    def _on_year_changed(self, year: int):
        if year != self.cal.yearShown():
            self.cal.setCurrentPage(year, self.cal.monthShown())

    def _set_month(self, month: int):
        self.cal.setCurrentPage(self.cal.yearShown(), month)

    def _go_today(self):
        """点「今天」：日历翻到本月、选中今天，时间不动"""
        today = QDate.currentDate()
        if (self.cal.yearShown(), self.cal.monthShown()) != (today.year(), today.month()):
            self.cal.setCurrentPage(today.year(), today.month())
        self.cal.setSelectedDate(today)
        self._sync_calendar_header(self.cal.yearShown(), self.cal.monthShown())

    def _show_month_menu(self):
        menu = QMenu(self)
        round_menu(menu)
        current = self.cal.monthShown()
        for month in range(1, 13):
            action = menu.addAction(f"{month}月")
            action.setCheckable(True)
            action.setChecked(month == current)
            action.triggered.connect(lambda checked=False, m=month: self._set_month(m))
        menu.exec(self.cal_month.mapToGlobal(QPoint(0, self.cal_month.height() + 2)))

    def _style_weekend(self):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C.INK_WEEKEND))
        self.cal.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, fmt)
        self.cal.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, fmt)

    def _install_day_delegate(self):
        view = self.cal.findChild(QTableView, "qt_calendar_calendarview")
        if view is None:
            view = self.cal.findChild(QTableView)
        if view is not None:
            self._day_delegate = _DayDelegate(self.cal, view)
            view.setItemDelegate(self._day_delegate)

    def showEvent(self, event):
        super().showEvent(event)
        self.title_edit.setFocus()
        # 确保无选中，光标在文字末尾
        cursor = self.title_edit.textCursor()
        cursor.clearSelection()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.title_edit.setTextCursor(cursor)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        # 只要不是点在标题框本身，就取消标题框的选中
        # （用户选中文字后，点任何其他地方都应该取消选中）
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            local = self.title_edit.mapFrom(self, pos)
            if not self.title_edit.geometry().contains(local):
                cursor = self.title_edit.textCursor()
                if cursor.hasSelection():
                    cursor.clearSelection()
                    self.title_edit.setTextCursor(cursor)

    def eventFilter(self, obj, event):
        if obj is self.time_combo.lineEdit():
            if event.type() == QEvent.Type.FocusIn:
                self.time_shell.setProperty("focused", True)
                repolish(self.time_shell)
            elif event.type() == QEvent.Type.FocusOut:
                self.time_shell.setProperty("focused", False)
                repolish(self.time_shell)
        # 卡片空白处点击：事件被 QFrame 吃掉不冒泡，在这里捕获
        if obj is self.card and event.type() == QEvent.Type.MouseButtonPress:
            pos = event.position().toPoint()
            # 把卡片坐标换算成对话框坐标
            dlg_pos = self.card.mapTo(self, pos)
            local = self.title_edit.mapFrom(self, dlg_pos)
            if not self.title_edit.geometry().contains(local):
                cursor = self.title_edit.textCursor()
                if cursor.hasSelection():
                    cursor.clearSelection()
                    self.title_edit.setTextCursor(cursor)
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ 数据
    def _default_remind(self) -> tuple[QDate, str]:
        """默认给 30 分钟后的整刻钟，避免一打开就是过去时间"""
        now = datetime.now()
        total = now.hour * 60 + now.minute + 30
        total = ((total + 14) // 15) * 15
        day_offset, total = divmod(total, 24 * 60)
        return QDate.currentDate().addDays(day_offset), f"{total // 60:02d}:{total % 60:02d}"

    def _load_remind(self, remind_at: str | None):
        dt = None
        if remind_at:
            try:
                dt = datetime.strptime(remind_at, "%Y-%m-%d %H:%M")
            except ValueError:
                dt = None
        if dt is None:
            date, time_text = self._default_remind()
            self.cal.setSelectedDate(date)
            idx = self.time_combo.findText(time_text)
            self.time_combo.setCurrentIndex(idx if idx >= 0 else 0)
            return
        self.cal.setSelectedDate(QDate(dt.year, dt.month, dt.day))
        time_text = dt.strftime("%H:%M")
        idx = self.time_combo.findText(time_text)
        if idx >= 0:
            self.time_combo.setCurrentIndex(idx)
        else:
            # 自定义分钟（如 07:33）不在 15 分钟列表里，直接写进输入框
            self.time_combo.setCurrentText(time_text)

    def _on_remind_toggled(self, enabled: bool):
        self.remind_box.setVisible(enabled)
        self.finalize()
    def _sync_save_state(self):
        self.btn_ok.setEnabled(bool(self.title_edit.toPlainText().strip()))

    def _on_ok(self):
        if not self.title_edit.toPlainText().strip():
            return
        self.year_spin.interpretText()
        self.time_combo.commit_time()
        self.accept()

    def _load_repeat(self, repeat: str | None):
        """把存储值（daily / weekday / …）显示成下拉里的那一项"""
        idx = self.repeat_combo.findData(repeat or "none")
        self.repeat_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._update_anchor_label()

    def _update_anchor_label(self):
        """更新重复锚点时间说明（跟随日历和时间选择器实时更新）"""
        rule = self.repeat_combo.currentData() if hasattr(self, "repeat_combo") else "none"
        if not rule or rule == "none" or not self.remind_switch.isChecked():
            self.anchor_label.setText("")
            return
        try:
            d = self.cal.selectedDate()
            t = self.time_combo.currentText()
            dt = datetime(d.year(), d.month(), d.day(), int(t[:2]), int(t[3:5]))
            time_str = dt.strftime("%H:%M")
            if rule == "daily":
                self.anchor_label.setText(f"每天 {time_str} 提醒")
            elif rule == "weekday":
                self.anchor_label.setText(f"工作日 {time_str} 提醒")
            elif rule == "weekly":
                weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
                wd = weekday_names[dt.weekday()]
                self.anchor_label.setText(f"每个{wd} {time_str} 提醒")
            elif rule == "monthly":
                self.anchor_label.setText(f"每月 {dt.day} 号 {time_str} 提醒")
            elif rule == "yearly":
                self.anchor_label.setText(f"每年 {dt.month}月{dt.day}日 {time_str} 提醒")
            else:
                self.anchor_label.setText("")
        except Exception:
            self.anchor_label.setText("")

    def result(self):
        self.year_spin.interpretText()
        self.time_combo.commit_time()
        title = self.title_edit.toPlainText().strip()
        if not self.remind_switch.isChecked():
            return title, None, "none"
        d = self.cal.selectedDate()
        t = self.time_combo.currentText()
        remind = f"{d.year():04d}-{d.month():02d}-{d.day():02d} {t}"
        repeat = self.repeat_combo.currentData() or "none"
        return title, remind, repeat


# --------------------------------------------------------------------------- #
#  设置
# --------------------------------------------------------------------------- #
class SettingsDialog(BaseDialog):
    """设置：开机自启 + 字体大小 + 待办排序"""

    def __init__(self, store, parent=None, on_font_preview=None, on_sort_preview=None):
        super().__init__("设置", parent, width=380)
        self.store = store
        self.on_font_preview = on_font_preview
        self.on_sort_preview = on_sort_preview
        self.body.setSpacing(18)

        # ---- 启动 ----
        startup = QFrame(self.card)
        startup.setObjectName("SectionCard")
        startup_lay = QHBoxLayout(startup)
        startup_lay.setContentsMargins(16, 12, 16, 12)
        startup_lay.setSpacing(12)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(3)
        title = QLabel("开机自启动", startup)
        title.setObjectName("SectionTitle")
        hint = QLabel("登录系统后在托盘后台静默运行", startup)
        hint.setObjectName("SectionHint")
        text_box.addWidget(title)
        text_box.addWidget(hint)
        startup_lay.addLayout(text_box, 1)
        startup_lay.addStretch(1)
        self.chk_autostart = Switch(startup)
        self.chk_autostart.setChecked(bool(self.store.get_setting("autostart", False)))
        startup_lay.addWidget(self.chk_autostart, 0, Qt.AlignmentFlag.AlignVCenter)
        self.body.addWidget(startup)

        # ---- 显示 ----
        display = QFrame(self.card)
        display.setObjectName("SectionCard")
        display_lay = QHBoxLayout(display)
        display_lay.setContentsMargins(16, 12, 16, 12)
        display_lay.setSpacing(12)

        text_box2 = QVBoxLayout()
        text_box2.setContentsMargins(0, 0, 0, 0)
        text_box2.setSpacing(3)
        title2 = QLabel("字体大小", display)
        title2.setObjectName("SectionTitle")
        hint2 = QLabel("界面与弹窗同步", display)
        hint2.setObjectName("SectionHint")
        text_box2.addWidget(title2)
        text_box2.addWidget(hint2)
        display_lay.addLayout(text_box2, 1)

        current = self.store.get_setting("font_scale", "中")
        self.font_control = SegmentedControl(["微", "小", "中", "大"], current, display)
        # 每个按钮用对应大小的字体显示，方便预览（单独设样式表，优先级最高）
        font_sizes = {"微": 10, "小": 11, "中": 12, "大": 14}
        for name, btn in self.font_control._buttons.items():
            size = font_sizes.get(name, 12)
            btn.setStyleSheet(f"font-size: {size}pt;")
        self.font_control.changed.connect(self._on_font_changed)
        display_lay.addWidget(self.font_control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.body.addWidget(display)

        # ---- 窗口 ----
        edge_card = QFrame(self.card)
        edge_card.setObjectName("SectionCard")
        edge_lay = QHBoxLayout(edge_card)
        edge_lay.setContentsMargins(16, 12, 16, 12)
        edge_lay.setSpacing(12)

        text_box3 = QVBoxLayout()
        text_box3.setContentsMargins(0, 0, 0, 0)
        text_box3.setSpacing(3)
        title3 = QLabel("贴边自动缩小", edge_card)
        title3.setObjectName("SectionTitle")
        hint3 = QLabel("贴边后鼠标移开自动收成桌宠", edge_card)
        hint3.setObjectName("SectionHint")
        hint3.setWordWrap(False)
        text_box3.addWidget(title3)
        text_box3.addWidget(hint3)
        edge_lay.addLayout(text_box3, 1)
        edge_lay.addStretch(1)

        self.chk_edge = Switch(edge_card)
        self.chk_edge.setChecked(bool(self.store.get_setting("edge_shrink", False)))
        edge_lay.addWidget(self.chk_edge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.body.addWidget(edge_card)

        # ---- 排序 ----
        sort_card = QFrame(self.card)
        sort_card.setObjectName("SectionCard")
        sort_lay = QVBoxLayout(sort_card)
        sort_lay.setContentsMargins(16, 12, 16, 14)
        sort_lay.setSpacing(6)

        sort_title = QLabel("待办排序", sort_card)
        sort_title.setObjectName("SectionTitle")
        self.sort_hint = QLabel("", sort_card)
        self.sort_hint.setObjectName("SectionHint")
        self.sort_hint.setWordWrap(True)
        sort_lay.addWidget(sort_title)
        sort_lay.addWidget(self.sort_hint)

        current_sort = self.store.get_setting("sort_mode", "created")
        sort_labels = {
            "remind": "按提醒时间",
            "manual": "自定义顺序",
        }
        sort_label = sort_labels.get(current_sort, "按创建时间")
        self.sort_control = SegmentedControl(
            ["按创建时间", "按提醒时间", "自定义顺序"], sort_label, sort_card
        )
        # 排序选项字体固定大小，不随全局变化
        for btn in self.sort_control._buttons.values():
            btn.setStyleSheet("font-size: 11pt;")
        self.sort_control.changed.connect(self._on_sort_changed)
        sort_lay.addWidget(self.sort_control)
        self.body.addWidget(sort_card)

        # 完成按钮去掉，点右上角叉号就保存关闭
        self.btn_close.clicked.disconnect()
        self.btn_close.clicked.connect(self.accept)

        self._update_sort_hint(current_sort)
        self.finalize()

    def _sort_mode(self) -> str:
        label = self.sort_control.value()
        return {"按提醒时间": "remind", "自定义顺序": "manual"}.get(label, "created")

    def _update_sort_hint(self, mode: str):
        if mode == "remind":
            self.sort_hint.setText("有提醒的排在前面；置顶的不参与排序，一直压在最上面")
        elif mode == "manual":
            self.sort_hint.setText("长按待办上下拖动来排；置顶的不参与排序，一直在最上面")
        else:
            self.sort_hint.setText("新创建的排在前面；置顶的不参与排序，一直在最上面")

    def _on_sort_changed(self, label: str):
        if self.sort_control.value() != label:
            self.sort_control.set_value(label)
        mode = {"按提醒时间": "remind", "自定义顺序": "manual"}.get(label, "created")
        self.store.set_setting("sort_mode", mode)
        self._update_sort_hint(mode)
        if self.on_sort_preview:
            self.on_sort_preview(mode)
        # 排序说明文字变了，高度会变，延迟一下重新算
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, self._relayout_after_font_change)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text, self.card)
        label.setObjectName("FieldLabel")
        return label

    def _on_font_changed(self, name: str):
        self.store.set_setting("font_scale", name)
        if self.on_font_preview:
            self.on_font_preview(name)
        # 字号变化后，QSS 会重新应用，需要重新设置字体大小选择器的按钮字号
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QTimer
        QApplication.processEvents()
        QTimer.singleShot(50, self._reset_font_preview_sizes)

    def _reset_font_preview_sizes(self):
        """重新设置字体大小选择器的按钮字号（固定，不随全局变化）"""
        font_sizes = {"微": 10, "小": 11, "中": 12, "大": 14}
        for name, btn in self.font_control._buttons.items():
            size = font_sizes.get(name, 12)
            btn.setStyleSheet(f"font-size: {size}pt;")
        self._relayout_after_font_change()

    def _relayout_after_font_change(self):
        self.card.setMinimumHeight(0)
        self.card.setMaximumHeight(16_777_215)
        self.body.activate()
        self.card.adjustSize()
        self.finalize()

    def values(self):
        return {
            "autostart": self.chk_autostart.isChecked(),
            "edge_shrink": self.chk_edge.isChecked(),
            "font_scale": self.font_control.value(),
            "sort_mode": self._sort_mode(),
        }


# --------------------------------------------------------------------------- #
#  通用提示框（替代系统 QMessageBox，保持圆角 / 投影 / 按钮一致）
# --------------------------------------------------------------------------- #
class InfoDialog(BaseDialog):
    def __init__(
        self,
        title: str,
        message: str,
        parent=None,
        icon_name: str = "info",
        tint: str | None = None,
    ):
        super().__init__(title, parent, width=320)
        if tint is None:
            tint = C.WARN if icon_name == "alert" else C.PRIMARY

        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 6)
        row.setSpacing(12)
        row.addWidget(icon_label(icon_name, tint, 26), 0, Qt.AlignmentFlag.AlignTop)

        label = QLabel(message, self.card)
        label.setObjectName("DialogMessage")
        label.setWordWrap(True)
        label.setMinimumWidth(230)
        row.addWidget(label, 1)
        self.body.addLayout(row)

        self.add_footer(primary_text="知道了", ghost_text=None)
        self.finalize()


class FindDialog(BaseDialog):
    """Ctrl+F 查找弹窗：非模态，搜索时主窗口仍可看；只负责交互，定位逻辑在主窗口"""

    queryChanged = pyqtSignal(str)
    nextRequested = pyqtSignal()
    prevRequested = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("查找", parent, width=360)
        self.setModal(False)
        self.body.setSpacing(12)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.input = QLineEdit(self.card)
        self.input.setObjectName("FindField")
        self.input.setPlaceholderText("查找待办 / 便签…")
        self.input.setFixedHeight(36)
        self.input.textChanged.connect(lambda: self.queryChanged.emit(self.input.text()))
        self.input.returnPressed.connect(self.nextRequested.emit)
        row.addWidget(self.input, 1)

        self.count = QLabel("", self.card)
        self.count.setObjectName("FindCount")
        self.count.setFixedWidth(46)
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.count, 0)
        self.body.addLayout(row)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)
        btn_row.addStretch(1)

        self.btn_prev = QPushButton("上一个", self.card)
        self.btn_prev.setObjectName("BtnGhost")
        self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_prev.clicked.connect(self.prevRequested.emit)
        btn_row.addWidget(self.btn_prev)

        self.btn_next = QPushButton("下一个", self.card)
        self.btn_next.setObjectName("BtnPrimary")
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next.clicked.connect(self.nextRequested.emit)
        btn_row.addWidget(self.btn_next)
        self.body.addLayout(btn_row)

        self.finalize()

    def set_count(self, text: str):
        self.count.setText(text)

    def query(self) -> str:
        return self.input.text()

    def focus_input(self):
        self.input.setFocus()
        self.input.selectAll()

    def reject(self):
        self.closed.emit()
        super().reject()
