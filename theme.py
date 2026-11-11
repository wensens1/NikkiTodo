"""
theme.py —— 全局视觉规范（配色 / 字体 / 圆角 / QSS）

这是整个程序唯一的视觉来源：
  · 颜色、圆角、字号都从这里取，窗口代码里不再写任何内联颜色；
  · 所有控件通过 objectName（#Card / #BtnPrimary …）或动态属性
    （[pinned="true"] / [overdue="true"] …）套用样式；
  · 改字号时调用 set_font_scale() 后重新 setStyleSheet(app_qss())，
    所有界面一起缩放，不会出现某个窗口字体不跟手的情况。

设计语言：
  浅冷灰画布（BG） + 纯白浮层（SURFACE） + 蓝色主操作（PRIMARY）
  + 深蓝灰选中态（NAVY） + 20px 大圆角卡片 / 12~14px 控件圆角。
"""

from __future__ import annotations

import os
import sys

BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.path.join(BASE_DIR, "assets")
# QSS 里的 url() 必须用正斜杠
ASSET_QSS = ASSET_DIR.replace("\\", "/")

FONT_FAMILY = "Microsoft YaHei UI"
FONT_FAMILY_FALLBACK = (
    "'Microsoft YaHei UI', 'Microsoft YaHei', 'PingFang SC', 'Segoe UI', sans-serif"
)

# 字体档位：以 1.0 为基准，避免旧版 1.5/2.0 那种过大的跳变
# 「微」= 设计值 ×1（FONT_ZOOM 1.25 之下的 0.8），给小屏 / 密排场景用
FONT_SCALES = {"微": 0.8, "小": 0.92, "中": 1.0, "大": 1.12}

# 全局字号倍率：所有界面文字统一再放大
FONT_ZOOM = 1.25

_current_scale = "中"


def font_ratio(scale: str | None = None) -> float:
    return FONT_SCALES.get(scale or _current_scale, 1.0) * FONT_ZOOM


def set_font_scale(scale: str) -> None:
    """记录当前字号档位（下次 app_qss() 生效）"""
    global _current_scale
    if scale in FONT_SCALES:
        _current_scale = scale


def font_px(px: int, scale: str | None = None) -> int:
    """把设计稿像素换算成当前字号档位下的像素"""
    return max(9, round(px * font_ratio(scale)))


class C:
    """配色常量"""

    # 画布 / 浮层（取自角色立绘：粉发 + 深灰紫斗篷 + 白衣）
    BG = "#FDF6F9"            # 卡片底（极浅粉调白）
    BG_SOFT = "#F7EDF2"       # 次级面板 / 悬浮态
    SURFACE = "#FFFFFF"       # 浮起的白卡片、输入框、胶囊
    SURFACE_HOVER = "#FFFCFD"
    FIELD = "#FFFFFF"
    FIELD_HOVER = "#FBF2F6"

    # 描边（粉灰）
    LINE = "#F0E2E9"
    LINE_STRONG = "#E3D0DA"

    # 文字（深灰紫）
    INK = "#3F3540"           # 主文字
    INK_2 = "#7B6A75"         # 次要文字
    INK_3 = "#A68F9B"         # 提示 / 占位符
    INK_WEEKEND = "#C4B2BC"   # 日历周末（更淡）

    # 主色（立绘里那抹玫瑰粉，压深到能白字可用）
    PRIMARY = "#B96B8C"
    PRIMARY_HOVER = "#A85B7C"
    PRIMARY_SOFT = "#FAE7EF"
    PRIMARY_BORDER = "#EFC6D7"

    # 深灰紫（选中胶囊，取自斗篷）
    NAVY = "#544651"
    NAVY_HOVER = "#453841"

    # 语义色
    DANGER = "#D4515E"
    DANGER_SOFT = "#FCE9EC"
    WARN = "#C9843F"
    WARN_SOFT = "#FDF0E2"
    WARN_HOVER = "#F8E2CB"
    OK = "#4E9A83"

    # 文字编辑右键菜单（圆角浅粉）
    MENU_BG = "#FDF1F6"       # 菜单底：比卡片底再粉一点，浮在白色便签上也分得清
    MENU_HOVER = "#FAE7EF"    # 悬停行
    MENU_BORDER = "#EFC6D7"   # 菜单描边
    MENU_SEP = "#F3DFE9"      # 分组细线
    INK_DISABLE = "#BAA1AD"   # 不可用项的文字 / 图标

    # 兼容旧命名（其它模块还在引用）
    WHITE = SURFACE
    REMIND = "#F8EAF1"
    REMIND_HOVER = "#F2DCE7"
    REMIND_INK = "#8E6C7E"
    DARK = NAVY
    DARK_HOVER = NAVY_HOVER
    HOT = DANGER
    HOT_SOFT = DANGER_SOFT

    SHADOW = "#3B2A33"


# 圆角规范
R_CARD = 20
R_DIALOG = 20
R_ITEM = 14
R_FIELD = 12
R_PILL = 14
R_TAG = 8
R_BUTTON = 10

# 动效时长（毫秒）
ANIM_FAST = 140


def app_qss(scale: str | None = None) -> str:
    """返回全局 QSS（在 QApplication 上一次性设置）

    scale 传 None 时使用 set_font_scale() 记录的当前档位。
    """
    r = font_ratio(scale)
    f = lambda px: max(9, round(px * r))  # noqa: E731

    return f"""
/* ============================ 基础 ============================ */
QWidget {{
    font-family: {FONT_FAMILY_FALLBACK};
    font-size: {f(14)}px;
    color: {C.INK};
}}
QMainWindow, QDialog {{ background: transparent; }}
QLabel {{ background: transparent; }}
QPushButton:focus, QTextEdit:focus, QLineEdit:focus, QComboBox:focus {{
    outline: none;
}}

/* ============================ 卡片 ============================ */
QFrame#Card {{
    background: {C.BG};
    border: 1px solid {C.LINE};
    border-left: 0px;
    border-radius: {R_CARD}px;
}}
/* 胶囊列翻到卡片右侧时，接缝那条空白边跟着换到右边 */
QFrame#Card[side="right"] {{
    border-left: 1px solid {C.LINE};
    border-right: 0px;
}}
QFrame#CardSoft,
QFrame#SectionCard,
QFrame#CalendarCard {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    border-radius: {R_ITEM}px;
}}
QFrame#DialogCard,
QFrame#Bubble {{
    background: {C.BG};
    border: 1px solid {C.LINE};
    border-radius: {R_DIALOG}px;
}}

/* ============================ 图标按钮 ============================ */
QPushButton#BtnTopBar,
QPushButton#BtnIcon {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 0;
}}
QPushButton#BtnTopBar:hover,
QPushButton#BtnIcon:hover {{
    background: {C.BG_SOFT};
}}
QPushButton#BtnTopBar:pressed,
QPushButton#BtnIcon:pressed {{
    background: {C.LINE};
}}
QPushButton#BtnTopBar[kind="danger"]:hover,
QPushButton#BtnIcon[kind="danger"]:hover {{
    background: {C.DANGER_SOFT};
}}

/* ============================ 侧栏胶囊 ============================ */
QPushButton#SidePill {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    border-right: 0px;
    border-top-left-radius: {R_PILL}px;
    border-bottom-left-radius: {R_PILL}px;
    border-top-right-radius: 0px;
    border-bottom-right-radius: 0px;
    color: {C.INK_2};
    font-size: {f(13)}px;
    padding: 0 6px;
    text-align: center;
}}
QPushButton#SidePill:hover {{
    background: {C.SURFACE_HOVER};
    border-color: {C.LINE_STRONG};
    color: {C.INK};
}}
QPushButton#SidePill:pressed {{
    background: {C.BG_SOFT};
}}
QPushButton#SidePill:checked,
QPushButton#SidePill:checked:hover {{
    background: {C.NAVY};
    border-color: {C.NAVY};
    color: #FFFFFF;
    font-weight: 600;
}}
QLineEdit#SidePillEdit {{
    background: {C.SURFACE};
    border: 1.5px solid {C.PRIMARY};
    border-right: 0px;
    border-top-left-radius: {R_PILL}px;
    border-bottom-left-radius: {R_PILL}px;
    border-top-right-radius: 0px;
    border-bottom-right-radius: 0px;
    padding: 0 6px;
    font-size: {f(13)}px;
    color: {C.INK};
    /* 选中态用主色实底：一进改名就整段选中，和电脑里改文件名的观感一致 */
    selection-background-color: {C.PRIMARY};
    selection-color: #FFFFFF;
}}

/* ---------- 胶囊列翻到卡片右边（贴左屏边时用）：圆角与接缝一起对调 ---------- */
QPushButton#SidePill[side="right"] {{
    border: 1px solid {C.LINE};
    border-left: 0px;
    border-top-left-radius: 0px;
    border-bottom-left-radius: 0px;
    border-top-right-radius: {R_PILL}px;
    border-bottom-right-radius: {R_PILL}px;
}}
QPushButton#SidePill[side="right"]:hover {{
    background: {C.SURFACE_HOVER};
    border: 1px solid {C.LINE_STRONG};
    border-left: 0px;
    color: {C.INK};
}}
QPushButton#SidePill[side="right"]:pressed {{
    background: {C.BG_SOFT};
    border: 1px solid {C.LINE};
    border-left: 0px;
}}
QPushButton#SidePill[side="right"]:checked,
QPushButton#SidePill[side="right"]:checked:hover {{
    background: {C.NAVY};
    border: 1px solid {C.NAVY};
    border-left: 0px;
    color: #FFFFFF;
    font-weight: 600;
}}
/* 键盘焦点进侧栏时抽屉拉开，这一圈描边就是「焦点现在在哪一颗」的唯一提示：
   全局 QPushButton:focus 把 outline 关了，这里用 border 补回来（接缝那侧仍然留空） */
QPushButton#SidePill:focus {{
    border: 2px solid {C.PRIMARY};
    border-right: 0px;
}}
QPushButton#SidePill:checked:focus {{
    border: 2px solid {C.PRIMARY};
    border-right: 0px;
}}
QPushButton#SidePill[side="right"]:focus {{
    border: 2px solid {C.PRIMARY};
    border-left: 0px;
}}
QPushButton#SidePill[side="right"]:checked:focus {{
    border: 2px solid {C.PRIMARY};
    border-left: 0px;
}}
QLineEdit#SidePillEdit[side="right"] {{
    border: 1.5px solid {C.PRIMARY};
    border-left: 0px;
    border-top-left-radius: 0px;
    border-bottom-left-radius: 0px;
    border-top-right-radius: {R_PILL}px;
    border-bottom-right-radius: {R_PILL}px;
}}

/* ============================ 输入区 ============================ */
QFrame#InputShell {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    border-radius: {R_FIELD}px;
}}
QFrame#InputShell[focused="true"] {{
    border: 1.5px solid {C.PRIMARY};
}}
QTextEdit#TodoInput {{
    background: transparent;
    border: none;
    padding: 12px 0px 0px 0px;
    font-size: {f(13)}px;
    color: {C.INK};
    placeholder-text-color: {C.INK_3};
    selection-background-color: {C.PRIMARY_SOFT};
    selection-color: {C.INK};
}}
QTextEdit#TodoInput, QTextEdit#TodoInput:focus {{
    border: none;
}}
QPushButton#BellBtn {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 0;
}}
QPushButton#BellBtn:hover {{
    background: {C.PRIMARY_SOFT};
}}

/* ---------- 编辑待办里的时间选择外壳 ---------- */
QFrame#TimeShell {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    border-radius: 11px;
}}
QFrame#TimeShell:hover {{
    background: {C.SURFACE};
    border-color: {C.LINE_STRONG};
}}
QFrame#TimeShell[focused="true"] {{
    border: 1.5px solid {C.PRIMARY};
}}
QComboBox#TimeComboFlat {{
    background: transparent;
    border: none;
    padding: 0px;
    color: {C.INK};
    font-size: {f(14)}px;
    font-weight: 600;
}}
QComboBox#TimeComboFlat::drop-down {{
    width: 0px;
    border: none;
}}
QComboBox#TimeComboFlat::down-arrow {{
    width: 0px;
    height: 0px;
    image: none;
}}
QComboBox#TimeComboFlat QLineEdit {{
    background: transparent;
    border: none;
    padding: 0px;
    color: {C.INK};
    font-size: {f(14)}px;
    font-weight: 600;
    selection-background-color: {C.PRIMARY_SOFT};
    selection-color: {C.INK};
}}

/* ---------- 输入框悬浮提示（自绘圆角） ---------- */
QFrame#InputHint {{
    background: {C.NAVY};
    border-radius: 10px;
}}
QLabel#HintKey {{
    background: rgba(255, 255, 255, 0.14);
    color: #FFFFFF;
    border-radius: 5px;
    padding: 2px 7px;
    font-size: {f(11)}px;
    font-weight: 600;
}}
QLabel#HintText {{
    color: #EBD9E2;
    font-size: {f(11)}px;
    background: transparent;
}}
QLabel#HintDot {{
    color: #A08A95;
    font-size: {f(11)}px;
    background: transparent;
}}

/* ============================ 顶栏文字 ============================ */
QLabel#TimeLabel {{
    color: {C.INK};
    font-size: {f(36)}px;
    font-weight: 600;
}}
QLabel#DateLabel {{
    color: {C.INK_3};
    font-size: {f(13)}px;
}}
QLabel#NoteTitle {{
    color: {C.INK};
    font-size: {f(16)}px;
    font-weight: 600;
}}

/* ============================ 待办项 ============================ */
QFrame#TodoItem {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    border-radius: {R_ITEM}px;
}}
QFrame#TodoItem:hover {{
    border-color: {C.LINE_STRONG};
}}
QFrame#TodoItem[pinned="true"] {{
    background: #FEF5FA;
    border: 1px solid {C.PRIMARY_BORDER};
}}
QFrame#TodoItem[done="true"] {{
    background: {C.BG_SOFT};
    border-color: transparent;
}}
QFrame#TodoItem[dragging="true"] {{
    background: {C.SURFACE_HOVER};
    border: 1px solid {C.PRIMARY_BORDER};
}}
QLabel#TodoText {{
    color: {C.INK};
}}
QLabel#TodoText[done="true"] {{
    color: {C.INK_3};
}}

/* ============================ 提醒标签 ============================ */
QWidget#RemindChip {{
    background: {C.REMIND};
    border-radius: {R_TAG}px;
}}
QWidget#RemindChip:hover {{
    background: {C.REMIND_HOVER};
}}
QWidget#RemindChip[overdue="true"] {{
    background: {C.WARN_SOFT};
}}
QWidget#RemindChip[overdue="true"]:hover {{
    background: {C.WARN_HOVER};
}}
QLabel#RemindChipText {{
    color: {C.REMIND_INK};
    font-size: {f(12)}px;
    background: transparent;
}}
QWidget#RemindChip[overdue="true"] QLabel#RemindChipText {{
    color: {C.WARN};
}}

/* ============================ 折叠 / 文字按钮 ============================ */
QPushButton#BtnFold {{
    background: transparent;
    border: none;
    border-radius: 8px;
    color: {C.INK_3};
    font-size: {f(12)}px;
    padding: 6px 12px;
}}
QPushButton#BtnFold:hover {{
    background: {C.BG_SOFT};
    color: {C.INK_2};
}}
QPushButton#BtnText {{
    background: transparent;
    border: none;
    border-radius: 8px;
    color: {C.INK_3};
    font-size: {f(12)}px;
    padding: 6px 10px;
}}
QPushButton#BtnText:hover {{
    background: {C.BG_SOFT};
    color: {C.INK};
}}

/* ============================ 普通按钮 ============================ */
QPushButton#BtnPrimary {{
    background: {C.PRIMARY};
    color: #FFFFFF;
    border: none;
    border-radius: {R_BUTTON}px;
    padding: 0 20px;
    font-size: {f(13)}px;
    font-weight: 600;
    min-height: 36px;
}}
QPushButton#BtnPrimary:hover {{
    background: {C.PRIMARY_HOVER};
}}
QPushButton#BtnPrimary:pressed {{
    background: #8E4966;
}}
QPushButton#BtnPrimary:disabled {{
    background: #E6CBD6;
    color: #FCF5F8;
}}
QPushButton#BtnGhost {{
    background: {C.SURFACE};
    color: {C.INK_2};
    border: 1px solid {C.LINE};
    border-radius: {R_BUTTON}px;
    padding: 0 18px;
    font-size: {f(13)}px;
    min-height: 36px;
}}
QPushButton#BtnGhost:hover {{
    background: {C.SURFACE_HOVER};
    border-color: {C.LINE_STRONG};
    color: {C.INK};
}}
QPushButton#BtnGhost:pressed {{
    background: {C.BG_SOFT};
}}
QPushButton#BtnGhostSmall,
QPushButton#BtnPrimarySmall {{
    border: none;
    border-radius: {R_BUTTON}px;
    padding: 0 12px;
    font-size: {f(12)}px;
    min-height: 30px;
}}
QPushButton#BtnGhostSmall {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    color: {C.INK_2};
}}
QPushButton#BtnGhostSmall:hover {{
    background: {C.SURFACE_HOVER};
    color: {C.INK};
}}
QPushButton#BtnPrimarySmall {{
    background: {C.PRIMARY};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton#BtnPrimarySmall:hover {{
    background: {C.PRIMARY_HOVER};
}}

/* ============================ 对话框内容 ============================ */
QLabel#DialogTitle {{
    color: {C.INK};
    font-size: {f(15)}px;
    font-weight: 600;
}}
QLabel#DialogMessage {{
    color: {C.INK_2};
    font-size: {f(13)}px;
}}
/* ---------------- 帮助文档 ---------------- */
QLabel#DialogHint {{
    color: {C.INK_3};
    font-size: {f(12)}px;
}}
QFrame#HelpSection {{
    background: {C.BG_SOFT};
    border: 1px solid {C.LINE};
    border-radius: {R_ITEM}px;
}}
QFrame#HelpSection QLabel {{
    border: none;
    background: transparent;
}}
QLabel#HelpSectionTitle {{
    color: {C.PRIMARY};
    font-size: {f(13)}px;
    font-weight: 600;
}}
QLabel#HelpItemTitle {{
    color: {C.INK};
    font-size: {f(12)}px;
    font-weight: 600;
}}
QLabel#HelpText {{
    color: {C.INK_2};
    font-size: {f(12)}px;
}}
QScrollArea#HelpScroll {{
    background: transparent;
    border: none;
}}
QLabel#FieldLabel {{
    color: {C.INK_2};
    font-size: {f(12)}px;
    font-weight: 600;
}}
QLabel#Hint {{
    color: {C.INK_3};
    font-size: {f(11)}px;
}}
QLabel#SectionTitle {{
    color: {C.INK};
    font-size: {f(13)}px;
    font-weight: 600;
}}
QLabel#SectionHint {{
    color: {C.INK_3};
    font-size: {f(11)}px;
}}
QLabel#FindCount {{
    color: {C.INK_3};
    font-size: {f(12)}px;
}}
QTextEdit#Field,
QLineEdit#Field,
QLineEdit#FindField {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    border-radius: {R_FIELD}px;
    padding: 10px 12px;
    font-size: {f(14)}px;
    color: {C.INK};
    placeholder-text-color: {C.INK_3};
    selection-background-color: {C.PRIMARY_SOFT};
    selection-color: {C.INK};
}}
QLineEdit#FindField {{
    font-size: {f(13)}px;
    padding: 6px 12px;
}}
QTextEdit#Field:focus,
QLineEdit#Field:focus,
QLineEdit#FindField:focus {{
    border: 1.5px solid {C.PRIMARY};
}}
QTextEdit#NoteEdit {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    border-radius: {R_ITEM}px;
    padding: 14px 16px;
    font-size: {f(14)}px;
    color: {C.INK};
    placeholder-text-color: {C.INK_3};
    selection-background-color: {C.PRIMARY_SOFT};
    selection-color: {C.INK};
}}
QTextEdit#NoteEdit:focus {{
    border: 1px solid {C.PRIMARY_BORDER};
}}

/* ============================ 下拉框 ============================ */
QComboBox#Field {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    border-radius: {R_FIELD}px;
    padding: 0 12px;
    font-size: {f(13)}px;
    color: {C.INK};
    min-height: 38px;
}}
QComboBox#Field:hover {{
    border-color: {C.LINE_STRONG};
}}
QComboBox#Field:focus {{
    border: 1.5px solid {C.PRIMARY};
}}
QComboBox#Field::drop-down {{
    border: none;
    width: 30px;
}}
QComboBox#Field::down-arrow {{
    image: url("{ASSET_QSS}/chevron_down.svg");
    width: 12px;
    height: 12px;
}}
QComboBox#Field QLineEdit {{
    background: transparent;
    border: none;
    padding: 0px;
    color: {C.INK};
    font-size: {f(13)}px;
    selection-background-color: {C.PRIMARY_SOFT};
    selection-color: {C.INK};
}}
QComboBox QAbstractItemView {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    border-radius: {R_FIELD}px;
    padding: 4px;
    outline: none;
    font-size: {f(13)}px;
    selection-background-color: {C.PRIMARY_SOFT};
    selection-color: {C.INK};
}}
QComboBox QAbstractItemView::item {{
    min-height: 32px;
    padding-left: 10px;
    border-radius: 7px;
    color: {C.INK};
}}
QComboBox QAbstractItemView::item:hover {{
    background: {C.BG_SOFT};
}}
QComboBox QAbstractItemView::item:selected {{
    background: {C.PRIMARY_SOFT};
    color: {C.INK};
}}
/* 时间下拉弹层 */
QFrame#PopupCard {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    border-radius: {R_FIELD}px;
}}
QListWidget#TimeList {{
    background: transparent;
    border: none;
    border-radius: {R_FIELD}px;
    padding: 6px;
    outline: none;
    font-size: {f(13)}px;
    color: {C.INK};
}}
QListWidget#TimeList::item {{
    height: 30px;
    border-radius: 7px;
    padding-left: 10px;
}}
QListWidget#TimeList::item:hover {{
    background: {C.BG_SOFT};
}}
QListWidget#TimeList::item:selected {{
    background: {C.PRIMARY_SOFT};
    color: {C.INK};
}}

/* ============================ 分段选择 ============================ */
QFrame#Segmented {{
    background: {C.BG_SOFT};
    border: 1px solid {C.LINE};
    border-radius: 10px;
}}
QPushButton#SegBtn {{
    background: transparent;
    border: none;
    border-radius: 6px;
    color: {C.INK_2};
    min-height: {f(26)}px;
    padding: 2px 6px;
}}
QPushButton#SegBtn:hover {{
    background: {C.SURFACE};
    color: {C.INK};
}}
QPushButton#SegBtn:checked,
QPushButton#SegBtn:checked:hover {{
    background: {C.NAVY};
    color: #FFFFFF;
    font-weight: 600;
}}

/* ============================ 空状态 ============================ */
QLabel#EmptyTitle {{
    color: {C.INK_2};
    font-size: {f(13)}px;
    font-weight: 600;
}}
QLabel#EmptyHint {{
    color: {C.INK_3};
    font-size: {f(11)}px;
}}

/* ============================ 气泡 ============================ */
QLabel#BubbleKicker {{
    color: {C.INK_3};
    font-size: {f(11)}px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#BubbleTitle {{
    color: {C.INK};
    font-size: {f(14)}px;
    font-weight: 600;
}}
QLabel#BubbleTime {{
    color: {C.INK_3};
    font-size: {f(11)}px;
}}

/* ============================ 滚动条 ============================ */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px 1px 2px 1px;
}}
QScrollBar::handle:vertical {{
    background: {C.LINE_STRONG};
    /* 圆角值必须小于把手宽度的一半（8px 宽取 3px）；7px 宽 + 3px 会退化成直角，实测只有 8px 才出圆角 */
    border-radius: 3px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: #D3BFC9;
}}
QScrollBar::handle:vertical:pressed {{
    background: {C.PRIMARY};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    height: 0px;
}}

/* ============================ 菜单 ============================ */
QMenu {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    border-radius: 12px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 12px;
    border-radius: 8px;
    font-size: {f(13)}px;
    color: {C.INK};
}}
QMenu::item:selected {{
    background: {C.BG_SOFT};
}}
QMenu::separator {{
    height: 1px;
    background: {C.LINE};
    margin: 6px 8px;
}}

/* 便签右键菜单 */
QMenu#NoteMenu {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    border-radius: 12px;
    padding: 6px;
}}
QMenu#NoteMenu::item {{
    padding: 7px 26px 7px 10px;
    border-radius: 8px;
    font-size: {f(13)}px;
    color: {C.INK};
}}
QMenu#NoteMenu::item:selected {{
    background: {C.PRIMARY_SOFT};
    color: {C.INK};
}}
QMenu#NoteMenu::separator {{
    height: 1px;
    background: {C.LINE};
    margin: 5px 8px;
}}
QLabel#MenuKicker {{
    color: {C.INK_3};
    font-size: {f(10)}px;
    background: transparent;
}}
QLabel#MenuTitle {{
    color: {C.INK};
    font-size: {f(13)}px;
    font-weight: 600;
    background: transparent;
}}

/* ---------- 便签页右键菜单（便签正文的撤销 / 复制 / 粘贴…）---------- */
QFrame#TextMenu {{
    background: {C.MENU_BG};
    border: 1px solid {C.MENU_BORDER};
    border-radius: {R_ITEM}px;
}}
QWidget#MenuRow {{
    background: transparent;
    border: none;
    border-radius: 9px;
}}
QWidget#MenuRow[hover="true"] {{
    background: {C.MENU_HOVER};
}}
QLabel#MenuLabel {{
    color: {C.INK};
    font-size: {f(13)}px;
    background: transparent;
}}
QLabel#MenuLabel[disabled="true"] {{
    color: {C.INK_DISABLE};
}}
QLabel#MenuHint {{
    color: {C.INK_3};
    font-size: {f(12)}px;
    background: transparent;
}}
QLabel#MenuHint[disabled="true"] {{
    color: {C.INK_DISABLE};
}}
QFrame#MenuSep {{
    background: {C.MENU_SEP};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

/* ============================ 日历头部 ============================ */
QPushButton#CalendarMonth {{
    background: transparent;
    border: none;
    border-radius: 8px;
    color: {C.INK};
    font-size: {f(13)}px;
    font-weight: 600;
    padding: 0 4px;
}}
QPushButton#CalendarMonth:hover {{
    background: {C.BG_SOFT};
}}
QPushButton#TodayPill {{
    background: {C.PRIMARY_SOFT};
    border: 1px solid {C.LINE};
    border-radius: 8px;
    color: {C.PRIMARY};
    font-size: {f(12)}px;
    font-weight: 600;
    padding: 0 9px;
}}
QPushButton#TodayPill:hover {{
    background: {C.SURFACE};
    border-color: {C.PRIMARY};
}}
QPushButton#TodayPill:pressed {{
    background: {C.PRIMARY};
    border-color: {C.PRIMARY};
    color: #FFFFFF;
}}
QSpinBox#YearSpin {{
    background: {C.SURFACE};
    border: 1px solid {C.LINE};
    border-radius: 8px;
    padding: 0 2px 0 8px;
    color: {C.INK};
    font-size: {f(13)}px;
}}
QSpinBox#YearSpin:hover {{
    border-color: {C.LINE_STRONG};
}}
QSpinBox#YearSpin:focus {{
    border: 1.5px solid {C.PRIMARY};
}}
QSpinBox#YearSpin::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid {C.LINE};
    background: transparent;
}}
QSpinBox#YearSpin::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 20px;
    border-left: 1px solid {C.LINE};
    background: transparent;
}}
QSpinBox#YearSpin::up-button:hover,
QSpinBox#YearSpin::down-button:hover {{
    background: {C.BG_SOFT};
}}
QSpinBox#YearSpin::up-arrow {{
    image: url("{ASSET_QSS}/chevron_up_dark.svg");
    width: 11px;
    height: 11px;
}}
QSpinBox#YearSpin::down-arrow {{
    image: url("{ASSET_QSS}/chevron_down_dark.svg");
    width: 11px;
    height: 11px;
}}

/* ============================ 日历 ============================ */
QCalendarWidget {{
    background: transparent;
    border: none;
}}
QCalendarWidget QAbstractItemView {{
    background: {C.SURFACE};
    alternate-background-color: {C.SURFACE};
    border: none;
    outline: none;
    selection-background-color: transparent;
    selection-color: #FFFFFF;
    font-size: {f(13)}px;
}}
QCalendarWidget QAbstractItemView:enabled {{
    color: {C.INK};
    background: {C.SURFACE};
}}
QCalendarWidget QHeaderView {{
    background: {C.SURFACE};
}}
QCalendarWidget QHeaderView::section {{
    background-color: {C.SURFACE};
    color: {C.INK_3};
    border: none;
    font-size: {f(11)}px;
    padding: 4px 0;
}}
"""
