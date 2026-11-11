"""
widgets/help_dialog.py —— 帮助文档

托盘右键「帮助文档」打开。按功能模块分节（待办 / 提醒 / 便签 / 窗口 / 桌宠 / 设置），
每个模块里写的都是「想做什么 → 怎么做」，不写实现细节。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from theme import C
from widgets.controls import repolish
from widgets.dialog_base import BaseDialog

# (模块名, [(想做这件事, 怎么做), ...])
SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "待办列表",
        [
            ("新建待办",
             "顶部输入框打字，按回车即可。"),
            ("加提醒",
             "新建时点输入框右侧的铃铛，或点已有待办下方的时间胶囊修改。"),
            ("双击编辑",
             "双击某条待办，可修改标题和提醒时间。"),
            ("打勾完成",
             "点标题左侧的圆圈，任务会移入底部的「已完成」折叠栏。"),
            ("置顶",
             "点行尾的图钉，置顶任务固定在顶部，不参与排序。"),
            ("删除",
             "点行尾的垃圾桶图标。提醒气泡上的 × 是关闭此次提醒，不是删除待办。"),
            ("自定义排序",
             "设置中选「自定义顺序」，长按待办上下拖动即可换位。"),
            ("查找待办 / 便签",
             "按 Ctrl+F 调出查找弹窗，全局同时搜索待办和便签（标题、正文）；回车跳下一个，Esc 关闭。"),
        ],
    ),
    (
        "提醒机制",
        [
            ("弹窗位置",
             "到点后暖暖身边会自动弹出气泡。"),
            ("重复提醒",
             "支持每日、每周、每月、每年及工作日（自动跳过周末）。到点后按设定周期自动滚动。"),
            ("稍后提醒",
             "点击「稍后 N 分钟」，可自定义推迟 10 分钟 / 30 分钟 / 1 小时。该操作只影响本次，不影响下次正常提醒。"),
            ("防堆积",
             "若昨天没点完成，今天不会补弹昨天的提醒，而是直接按今天的周期重新开始。"),
            ("收成星星",
             "点气泡右上角的 −，可将提醒缩小成星星挂在桌宠旁。点击星星可还原为气泡。"),
            ("右键菜单",
             "在气泡或星星上右键，可一键展开所有星星、缩小所有气泡、或关闭特定提醒。"),
        ],
    ),
    (
        "便签功能",
        [
            ("侧边栏",
             "鼠标悬停时滑出，移开自动收起。"),
            ("新建与切换",
             "点左侧栏 + 新建，点击胶囊切换。"),
            ("重命名",
             "双击胶囊，或右键重命名；回车确认。"),
            ("管理",
             "右键胶囊可删除；长按上下拖动可调整顺序。"),
            ("数量",
             "支持无限添加，内容超出有滚动条。"),
        ],
    ),
    (
        "窗口与桌宠",
        [
            ("形态切换",
             "点右上角 − 收回成桌宠；点桌宠或托盘图标切换回窗口。"),
            ("桌宠缩放",
             "鼠标放在桌宠上，滚轮可放大缩小。"),
            ("边缘吸附",
             "在设置里开启「贴边自动缩小」后，窗口贴边后鼠标移开自动收成桌宠；当窗口在屏幕左边缘时，侧边栏会自动翻到右侧防止被挡。"),
            ("自由拖拽",
             "按住窗口空白处或桌宠可自由拖动。拉右下角斜纹可调整窗口大小。"),
            ("隐藏后台",
             "点右上角 × 关闭窗口后，程序继续在托盘运行，到点依然会准时提醒。"),
        ],
    ),
    (
        "设置与托盘",
        [
            ("字体大小",
             "设置里可将全局字体（微/小/中/大）同步调大调小。"),
            ("开机自启",
             "设置里开启后，登录系统自动在托盘静默运行。"),
            ("托盘操作",
             "右键托盘图标可显示窗口、切换桌宠形态、开启自启或退出程序。"),
        ],
    ),
]


class _Section(QFrame):
    """一个功能模块：模块名 + 若干条「想做什么 / 怎么做」"""

    def __init__(self, title: str, rows: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("HelpSection")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        head = QLabel(title, self)
        head.setObjectName("HelpSectionTitle")
        lay.addWidget(head)

        for want, how in rows:
            row = QWidget(self)
            hl = QVBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(3)

            q = QLabel("· " + want, row)
            q.setObjectName("HelpItemTitle")
            q.setWordWrap(True)
            hl.addWidget(q)

            a = QLabel(how, row)
            a.setObjectName("HelpText")
            a.setWordWrap(True)
            hl.addWidget(a)
            lay.addWidget(row)


class HelpDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__("帮助文档", parent, width=430)

        tip = QLabel("按功能分好了，想知道哪件事怎么做，直接找对应的那一条。", self.card)
        tip.setObjectName("DialogHint")
        tip.setWordWrap(True)
        self.body.addWidget(tip)

        scroll = QScrollArea(self.card)
        scroll.setObjectName("HelpScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        holder = QWidget(scroll)
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 2, 6, 2)
        hl.setSpacing(10)
        for title, rows in SECTIONS:
            hl.addWidget(_Section(title, rows, holder))
        hl.addStretch(1)
        scroll.setWidget(holder)
        scroll.setFixedHeight(430)
        self.body.addWidget(scroll)

        self.add_footer(primary_text="知道了", ghost_text=None)
        self.finalize()
        repolish(self)
