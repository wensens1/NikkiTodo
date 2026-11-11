"""
widgets/dialog_base.py —— 所有弹出窗口的统一外壳

统一的部分：
  · 无边框 + 半透明窗口 + 20px 圆角卡片 + 柔和投影
  · 相同的内边距（22 / 18）与标题栏（标题 + 右上角关闭）
  · 相同的底部按钮区（左文字按钮 / 右 灰色 + 主色按钮）
  · 按住卡片空白处可拖动；打开时相对父窗口居中
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from theme import C
from ui_icons import IconButton
from ui_utils import add_shadow

SHADOW_MARGIN = 22


class BaseDialog(QDialog):
    """统一弹窗外壳；子类往 self.body 里加内容即可"""

    def __init__(self, title: str, parent=None, width: int = 380):
        super().__init__(parent)
        self._body_width = width
        self._drag_offset = None

        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN)
        outer.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("DialogCard")
        add_shadow(self.card, blur=44, dy=0, alpha=50)
        outer.addWidget(self.card)

        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(22, 18, 22, 20)
        self.body.setSpacing(14)

        # ---- 标题栏 ----
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.title_label = QLabel(title, self.card)
        self.title_label.setObjectName("DialogTitle")
        header.addWidget(self.title_label, 1)

        self.btn_close = IconButton(
            "close", color=C.INK_3, hover=C.INK,
            size=26, icon_size=14, tooltip="关闭", parent=self.card,
        )
        self.btn_close.clicked.connect(self.reject)
        header.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(header)

    # ------------------------------------------------------------------ 底部
    def add_footer(
        self,
        *,
        primary_text: str = "确定",
        ghost_text: str | None = "取消",
        leading_text: str | None = None,
    ) -> tuple[QPushButton, QPushButton | None, QPushButton | None]:
        """添加统一的底部按钮区，返回 (主按钮, 次按钮, 左侧文字按钮)"""
        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        row.setSpacing(8)

        btn_leading = None
        if leading_text:
            btn_leading = QPushButton(leading_text, self.card)
            btn_leading.setObjectName("BtnText")
            btn_leading.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(btn_leading)

        row.addStretch(1)

        btn_ghost = None
        if ghost_text:
            btn_ghost = QPushButton(ghost_text, self.card)
            btn_ghost.setObjectName("BtnGhost")
            btn_ghost.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_ghost.clicked.connect(self.reject)
            row.addWidget(btn_ghost)

        btn_primary = QPushButton(primary_text, self.card)
        btn_primary.setObjectName("BtnPrimary")
        btn_primary.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_primary.setDefault(True)
        btn_primary.clicked.connect(self.accept)
        row.addWidget(btn_primary)

        self.body.addLayout(row)
        return btn_primary, btn_ghost, btn_leading

    # ------------------------------------------------------------------ 尺寸
    def finalize(self):
        """按内容收紧窗口尺寸（含四周投影留白），可在显示后重复调用"""
        self.card.setMinimumHeight(0)
        self.card.setMaximumHeight(16_777_215)
        self.card.setFixedWidth(self._body_width)
        self.card.adjustSize()
        height = self.card.height()
        self.card.setFixedHeight(height)
        self.setFixedSize(
            self._body_width + SHADOW_MARGIN * 2,
            height + SHADOW_MARGIN * 2,
        )

    # ------------------------------------------------------------------ 位置
    def showEvent(self, event):
        super().showEvent(event)
        self._center_on_parent()

    def _center_on_parent(self):
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            geo = parent.frameGeometry()
            x = geo.center().x() - self.width() // 2
            y = geo.center().y() - self.height() // 2
        else:
            screen = self.screen() or QGuiApplication.primaryScreen()
            avail = screen.availableGeometry()
            x = avail.center().x() - self.width() // 2
            y = avail.center().y() - self.height() // 2
        screen = self.screen() or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        x = max(avail.left(), min(x, avail.right() - self.width() + 1))
        y = max(avail.top(), min(y, avail.bottom() - self.height() + 1))
        self.move(x, y)

    # ------------------------------------------------------------------ 拖动
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            # 只在卡片空白处开始拖动（按钮 / 输入框会自己吃掉事件）
            if self.card.geometry().contains(pos):
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)
