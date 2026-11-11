"""
widgets/text_menu.py —— 便签正文的右键菜单

系统自带的右键菜单是白底直角的系统菜单，和整体的浅粉风格不搭。
这里用「自绘圆角卡片 + 行控件」重做：左侧线性图标、右侧快捷键提示、
不可用项自动置灰；分组细线、悬停浅粉高亮，全部取自 theme.py。

用法：
    menu = TextContextMenu(parent)
    menu.popup_at(global_pos, note_edit)
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from theme import C
from ui_icons import icon_pixmap
from ui_utils import add_shadow
from widgets.controls import repolish


class _MenuRow(QWidget):
    """一行菜单项：图标 + 名称 + 右侧快捷键提示

    悬停高亮用动态属性交给 QSS 画（圆角才有），不可用时整行置灰、不响应点击。
    """

    ROW_H = 34
    ICON = 16

    picked = pyqtSignal(str)

    def __init__(self, key: str, icon_name: str, label: str, hint: str, parent=None):
        super().__init__(parent)
        self.key = key
        self._icon_name = icon_name
        self._enabled = True
        self.setObjectName("MenuRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(self.ROW_H)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(self.ICON, self.ICON)
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.text_label = QLabel(label, self)
        self.text_label.setObjectName("MenuLabel")
        self.text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.text_label)

        lay.addStretch(1)

        self.hint_label = QLabel(hint, self)
        self.hint_label.setObjectName("MenuHint")
        self.hint_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.hint_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.hint_label)

        self.set_enabled(True)

    # ------------------------------------------------------------------ 状态
    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.icon_label.setPixmap(
            icon_pixmap(self._icon_name, C.INK_2 if enabled else C.INK_DISABLE, self.ICON)
        )
        for label in (self.text_label, self.hint_label):
            label.setProperty("disabled", not enabled)
            repolish(label)
        self.setProperty("hover", False)
        repolish(self)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )

    # ------------------------------------------------------------------ 交互
    def enterEvent(self, event):
        if self._enabled:
            self.setProperty("hover", True)
            repolish(self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("hover", False)
        repolish(self)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            self._enabled
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.picked.emit(self.key)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class TextContextMenu(QWidget):
    """便签正文右键菜单：圆角浅粉卡片 + 若干行 + 分组细线"""

    PAD = 6                  # 卡片内边距
    SHADOW = 14              # 留给投影的透明边
    SEP_GAP = 4              # 分组细线上下的留白
    MIN_W = 196

    # (key, 图标, 名称, 快捷键)；key 为 None 表示一条分组细线
    SPEC = (
        ("undo", "undo", "撤销", "Ctrl+Z"),
        ("redo", "redo", "重做", "Ctrl+Y"),
        (None, None, None, None),
        ("cut", "cut", "剪切", "Ctrl+X"),
        ("copy", "copy", "复制", "Ctrl+C"),
        ("paste", "paste", "粘贴", "Ctrl+V"),
        ("delete", "trash", "删除", "Delete"),
        (None, None, None, None),
        ("select_all", "select_all", "全选", "Ctrl+A"),
    )

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._editor: QTextEdit | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.SHADOW, self.SHADOW, self.SHADOW, self.SHADOW)
        outer.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("TextMenu")
        add_shadow(self.card, blur=26, dy=0, alpha=45)
        outer.addWidget(self.card)

        self._lay = QVBoxLayout(self.card)
        self._lay.setContentsMargins(self.PAD, self.PAD, self.PAD, self.PAD)
        self._lay.setSpacing(2)

        self.rows: dict[str, _MenuRow] = {}
        self._sep_h = 1 + self.SEP_GAP * 2
        for key, icon_name, label, hint in self.SPEC:
            if key is None:
                self._lay.addWidget(self._make_separator())
                continue
            row = _MenuRow(key, icon_name, label, hint, self.card)
            row.picked.connect(self._fire)
            self._lay.addWidget(row)
            self.rows[key] = row

    # ------------------------------------------------------------------ 组装
    def _make_separator(self) -> QWidget:
        holder = QWidget(self.card)
        holder.setFixedHeight(self._sep_h)      # 定高：不参与拉伸，菜单高度才好算准
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(10, self.SEP_GAP, 10, self.SEP_GAP)
        lay.setSpacing(0)
        line = QFrame(holder)
        line.setObjectName("MenuSep")
        line.setFixedHeight(1)
        lay.addWidget(line)
        return holder

    def _card_w(self) -> int:
        for row in self.rows.values():
            row.text_label.ensurePolished()
            row.hint_label.ensurePolished()
        hint = self.card.layout().sizeHint().width()
        return max(self.MIN_W, hint)

    def _card_h(self) -> int:
        items = self._lay.count()
        seps = items - len(self.rows)
        return (
            self.PAD * 2
            + len(self.rows) * _MenuRow.ROW_H
            + seps * self._sep_h
            + self._lay.spacing() * max(0, items - 1)
        )

    # ------------------------------------------------------------------ 弹出
    def popup_at(self, global_pos: QPoint, editor: QTextEdit):
        """在鼠标位置弹出；按此刻的选区 / 剪贴板 / 撤销栈决定哪几项可用"""
        self._editor = editor
        doc = editor.document()
        cursor = editor.textCursor()
        has_sel = cursor.hasSelection()
        mime = QGuiApplication.clipboard().mimeData()
        can_paste = bool(mime is not None and (mime.hasText() or mime.hasHtml()))

        self.rows["undo"].set_enabled(doc.isUndoAvailable())
        self.rows["redo"].set_enabled(doc.isRedoAvailable())
        for key in ("cut", "copy", "delete"):
            self.rows[key].set_enabled(has_sel)
        self.rows["paste"].set_enabled(can_paste)
        self.rows["select_all"].set_enabled(not doc.isEmpty())

        card_w = self._card_w()
        card_h = self._card_h()
        self.card.setFixedSize(card_w, card_h)
        self.setFixedSize(card_w + self.SHADOW * 2, card_h + self.SHADOW * 2)

        avail = (editor.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        x = global_pos.x() + 2
        y = global_pos.y() + 2
        if x + card_w > avail.right() + 1:
            x = avail.right() + 1 - card_w
        if y + card_h > avail.bottom() + 1:
            y = avail.bottom() + 1 - card_h
        x = max(avail.left(), x)
        y = max(avail.top(), y)

        self.move(x - self.SHADOW, y - self.SHADOW)
        self.show()
        self.raise_()
        self.setFocus()

    # ------------------------------------------------------------------ 动作
    def _fire(self, key: str):
        ed = self._editor
        self.hide()
        if ed is None:
            return
        ed.setFocus()
        if key == "undo":
            ed.undo()
        elif key == "redo":
            ed.redo()
        elif key == "cut":
            ed.cut()
        elif key == "copy":
            ed.copy()
        elif key == "paste":
            ed.paste()
        elif key == "delete":
            cursor = ed.textCursor()
            if cursor.hasSelection():
                cursor.removeSelectedText()
                ed.setTextCursor(cursor)
        elif key == "select_all":
            ed.selectAll()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        # 兜底：切到别的程序（标题栏、任务栏）时也给收起来
        self.hide()
        super().focusOutEvent(event)
