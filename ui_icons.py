"""
ui_icons.py —— 统一的线性图标库 + 图标按钮

所有图标都是内联 SVG，按需着色渲染，不依赖外部图片资源，
因此普通 / 悬停 / 选中状态可以用同一套颜色规范切换。
"""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QPushButton

from theme import C

# 24x24 画布，描边风格统一
_PATHS = {
    "more": (
        '<circle cx="5" cy="12" r="1.5" fill="{c}" stroke="none"/>'
        '<circle cx="12" cy="12" r="1.5" fill="{c}" stroke="none"/>'
        '<circle cx="19" cy="12" r="1.5" fill="{c}" stroke="none"/>'
    ),
    "settings": (
        '<path d="M4 7h11"/><path d="M19 7h1"/>'
        '<circle cx="17" cy="7" r="2.1"/>'
        '<path d="M4 17h1"/><path d="M9 17h11"/>'
        '<circle cx="7" cy="17" r="2.1"/>'
    ),
    "minus": '<path d="M5 12h14"/>',
    # 缩小到桌宠旁：长度与 close 的 ×（6..18）对齐，粗细同为 1.8
    "minimize": '<path d="M6 12h12"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "bell": (
        '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>'
        '<path d="M13.73 21a2 2 0 0 1-3.46 0"/>'
    ),
    "chevron_down": '<path d="M6 9.5l6 6 6-6"/>',
    "chevron_up": '<path d="M6 14.5l6-6 6 6"/>',
    "chevron_left": '<path d="M14.5 6l-6 6 6 6"/>',
    "chevron_right": '<path d="M9.5 6l6 6-6 6"/>',
    "pin": (
        '<path d="M12 20V8"/>'
        '<path d="M6.5 12.5L12 7l5.5 5.5"/>'
        '<path d="M5 4h14"/>'
    ),
    "trash": (
        '<path d="M3 6h18"/><path d="M8 6V4h8v2"/>'
        '<path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/>'
    ),
    "edit": (
        '<path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3z"/>'
        '<path d="M14.5 6.5l3 3"/>'
    ),
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7"/>',
    "check_circle": (
        '<circle cx="12" cy="12" r="8.5"/><path d="M8.2 12.4l2.6 2.6 5-5.4"/>'
    ),
    "alert": '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/>',
    "note": (
        '<path d="M6 3.5h8L19 8.5v12H6z"/>'
        '<path d="M14 3.5v5h5"/><path d="M9 13h6M9 16.5h4"/>'
    ),
    "calendar": (
        '<rect x="3.5" y="5" width="17" height="15.5" rx="3"/>'
        '<path d="M8 3v4M16 3v4M3.5 10h17"/>'
    ),
    "inbox": (
        '<path d="M4 13.5l2.2-7A2 2 0 0 1 8.1 5h7.8a2 2 0 0 1 1.9 1.5l2.2 7"/>'
        '<path d="M4 13.5H8l1.2 2.5h5.6L16 13.5h4v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/>'
    ),
    "info": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M12 11v5"/><path d="M12 8h.01"/>'
    ),
    "smile": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M9 10h.01M15 10h.01"/>'
        '<path d="M8.5 14a4.5 4.5 0 0 0 7 0"/>'
    ),
    # ---- 编辑菜单（撤销 / 重做 / 剪切 / 复制 / 粘贴 / 全选）----
    "undo": (
        '<path d="M10 7.5L5.5 12l4.5 4.5"/>'
        '<path d="M5.5 12h8.5a5 5 0 0 1 5 5"/>'
    ),
    "redo": (
        '<path d="M14 7.5L18.5 12l-4.5 4.5"/>'
        '<path d="M18.5 12H10a5 5 0 0 0-5 5"/>'
    ),
    "cut": (
        '<circle cx="6.8" cy="7.2" r="2.3"/>'
        '<circle cx="6.8" cy="16.8" r="2.3"/>'
        '<path d="M9 8.6L19 17"/><path d="M9 15.4L19 7"/>'
    ),
    "copy": (
        '<rect x="9" y="9" width="10.5" height="10.5" rx="2.5"/>'
        '<path d="M14.5 9V6.6A2.6 2.6 0 0 0 11.9 4H6.6A2.6 2.6 0 0 0 4 6.6'
        'v5.3A2.6 2.6 0 0 0 6.6 14.5H9"/>'
    ),
    "paste": (
        '<rect x="5.5" y="5" width="13" height="15.5" rx="2.8"/>'
        '<rect x="9" y="2.8" width="6" height="4" rx="1.5"/>'
    ),
    "select_all": (
        '<path d="M4.5 9V7a2.5 2.5 0 0 1 2.5-2.5h2"/>'
        '<path d="M15 4.5h2A2.5 2.5 0 0 1 19.5 7v2"/>'
        '<path d="M19.5 15v2A2.5 2.5 0 0 1 17 19.5h-2"/>'
        '<path d="M9 19.5H7A2.5 2.5 0 0 1 4.5 17v-2"/>'
    ),
}

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round">'
    "{body}</svg>"
)

# 横平竖直的线在同样 stroke-width 下看着比斜线（×）细，单独补一点粗细
_STROKE = {"minimize": 2.6}

_CACHE: dict[tuple[str, str, int, int], QPixmap] = {}


def icon_pixmap(name: str, color: str = C.INK_3, size: int = 16, dpr: int = 2) -> QPixmap:
    """渲染单色线性图标；按 (名称, 颜色, 尺寸, DPR) 缓存"""
    key = (name, color, size, dpr)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    body = _PATHS.get(name)
    if body is None:
        return QPixmap()
    svg = _SVG.format(c=color, w=_STROKE.get(name, 1.8), body=body).replace("{c}", color)
    pm = QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(dpr)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    _CACHE[key] = pm
    return pm


def icon(name: str, color: str = C.INK_2, size: int = 16) -> QIcon:
    """QIcon 版本（菜单、普通按钮用）"""
    return QIcon(icon_pixmap(name, color, size))


class IconButton(QPushButton):
    """只有图标、没有文字的按钮。

    普通 / 悬停 / 选中三种颜色由代码切换，背景和圆角交给全局 QSS，
    这样主窗口、对话框、桌宠气泡里的图标按钮表现完全一致。
    """

    def __init__(
        self,
        name: str,
        *,
        color: str = C.INK_3,
        hover: str = C.INK,
        checked_color: str | None = None,
        size: int | tuple[int, int] = 28,
        icon_size: int = 16,
        object_name: str = "BtnIcon",
        checkable: bool = False,
        tooltip: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._name = name
        self._color = color
        self._hover = hover
        self._checked_color = checked_color or color
        self._icon_size = icon_size
        w, h = (size, size) if isinstance(size, int) else size
        self.setObjectName(object_name)
        self.setCheckable(checkable)
        self.setFixedSize(w, h)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        if tooltip:
            self.setAccessibleName(tooltip)
        self._sync_icon()

    # ---------------- 状态 ----------------
    def set_colors(self, *, color=None, hover=None, checked_color=None, name=None):
        if name is not None:
            self._name = name
        if color is not None:
            self._color = color
        if hover is not None:
            self._hover = hover
        if checked_color is not None:
            self._checked_color = checked_color
        self._sync_icon()

    def _target_color(self) -> str:
        if self.isCheckable() and self.isChecked():
            return self._checked_color
        if self.underMouse() or self.isDown():
            return self._hover
        return self._color

    def _sync_icon(self):
        color = self._target_color()
        if getattr(self, "_last_color", None) == color:
            return
        self._last_color = color
        self.setIcon(QIcon(icon_pixmap(self._name, color, self._icon_size)))

    def setChecked(self, checked: bool):  # noqa: N802 (Qt 命名)
        super().setChecked(checked)
        self._sync_icon()

    def enterEvent(self, event):
        self._sync_icon()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._sync_icon()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._sync_icon()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._sync_icon()
