"""
main.py —— 程序入口（NikkiTodo：暖暖桌宠待办）

职责：
  1. QApplication 初始化：Fusion 风格 + 全局 QSS + 图标
  2. 单实例守护（QLockFile，防止双开导致 data.json 互相覆盖）
  3. 装配 主窗口 / 桌宠窗口，并处理两者互切
  4. 系统托盘（显示 / 切换形态 / 开机自启 / 退出）
  5. 开机自启（winreg 写 HKCU\\...\\Run）
  6. 提醒调度（后台 QTimer 扫描待办，到点交给桌宠弹气泡）

运行：
    python main.py            # 按上次保存的形态启动
    python main.py --window   # 强制以主窗口启动
    python main.py --pet      # 强制以桌宠启动
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

from PyQt6.QtCore import QEvent, QLockFile, QObject, QTimer
from PyQt6.QtGui import QAction, QFont, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from data_store import BASE_DIR, DataStore
from repeat import advance, roll_repeats, should_pop
from theme import ASSET_DIR, C, FONT_FAMILY, app_qss, set_font_scale
from ui_icons import icon
from ui_utils import app_icon, round_menu

try:
    import winreg  # 仅 Windows 可用
except ImportError:  # 非 Windows 环境下降级（程序仍可运行，只是没有自启）
    winreg = None

APP_NAME = "NikkiTodo"
APP_KEY_NAME = "NikkiTodo"
LEGACY_KEYS = ("VertinTodo",)      # 旧名字的注册表项，首次启动时清掉，免得两个自启项并存
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LOCK_PATH = os.path.join(BASE_DIR, "app.lock")


def _kill_pid(pid: int) -> bool:
    """关掉占着锁的旧实例（只针对本程序的 pid，不动别的进程）"""
    if sys.platform != "win32":
        return False
    try:
        p = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=5,
        )
        return p.returncode == 0
    except Exception:
        return False


# --------------------------------------------------------------------------- #
#  开机自启
# --------------------------------------------------------------------------- #
class AutoStart:
    """通过 HKCU 注册表 Run 项实现开机自启（不需要管理员权限）"""

    @staticmethod
    def _command() -> str:
        if getattr(sys, "frozen", False):
            # 优先用隐藏启动器，开机自启时不弹控制台
            launcher = os.path.join(
                os.path.dirname(sys.executable), "启动NikkiTodo.vbs"
            )
            if os.path.exists(launcher):
                wscript = os.path.join(
                    os.environ.get("SystemRoot", r"C:\Windows"),
                    "System32",
                    "wscript.exe",
                )
                return f'"{wscript}" "{launcher}"'
            return f'"{sys.executable}"'
        exe = sys.executable
        # 优先用 pythonw.exe：开机启动时不弹黑框
        if exe.lower().endswith("python.exe"):
            cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(cand):
                exe = cand
        script = os.path.join(BASE_DIR, "main.py")
        return f'"{exe}" "{script}"'

    @classmethod
    def is_enabled(cls) -> bool:
        if winreg is None:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, APP_KEY_NAME)
            # 注册表里存的是旧的解释器路径时也算"已开启"，但下次 enable 会刷新
            return bool(value)
        except FileNotFoundError:
            return False
        except OSError:
            return False

    @classmethod
    def command_matches(cls) -> bool:
        """注册表里的启动命令是否仍指向当前程序（exe 被挪位置后需要刷新）"""
        if winreg is None:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, APP_KEY_NAME)
        except OSError:
            return False
        return str(value).strip().lower() == cls._command().strip().lower()

    @classmethod
    def set_enabled(cls, enabled: bool) -> bool:
        if winreg is None:
            return False
        try:
            if enabled:
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                        winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, APP_KEY_NAME, 0, winreg.REG_SZ, cls._command())
            else:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                        winreg.KEY_SET_VALUE) as key:
                        winreg.DeleteValue(key, APP_KEY_NAME)
                except FileNotFoundError:
                    pass
            return True
        except OSError as e:
            print(f"[AutoStart] 操作注册表失败：{e}")
            return False

    @classmethod
    def drop_legacy(cls) -> None:
        """把旧名字（VertinTodo）留下的自启项删掉，避免注册表里两条并存"""
        if winreg is None:
            return
        for name in LEGACY_KEYS:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, name)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
#  应用装配
# --------------------------------------------------------------------------- #
class _TooltipBlocker(QObject):
    """拦截所有 QToolTip，界面不再出现悬停提示条"""

    def eventFilter(self, obj, event):
        return event.type() == QEvent.Type.ToolTip


class VertinApp:
    def __init__(
        self,
        app: QApplication,
        store: DataStore | None = None,
        start_mode: str | None = None,
    ):
        self.app = app
        self.store = store or DataStore()
        self.tray: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._act_autostart: QAction | None = None
        self._tooltip_blocker = _TooltipBlocker(app)
        app.installEventFilter(self._tooltip_blocker)

        # 两个窗口由 widgets 提供；main.py 只负责装配与事件路由
        from widgets.main_window import CARD_X, CARD_Y, MainWindow
        from widgets.pet_window import PET_W, PetWindow

        self._pet_w = PET_W
        self.main_win = MainWindow(self.store)
        self.pet_win = PetWindow(self.store)
        self._pet_minimized = False          # 右键最小化：桌宠收进任务栏
        self._last_tray_act = 0.0            # 上一次托盘点击时间（拦单击+双击连发）

        self.main_win.enterPetMode.connect(lambda: self.show_pet("keep"))
        self.main_win.hideToTray.connect(self.on_window_to_tray)
        self.main_win.todoDoneChanged.connect(lambda tid: self.pet_win.hide_reminder(tid))
        self.main_win.todoDeleted.connect(lambda tid: self.pet_win.hide_reminder(tid))
        self.pet_win.enterWindowMode.connect(self.show_main)
        self.pet_win.snoozeRequested.connect(self.on_snooze)
        self.pet_win.doneRequested.connect(self.on_done)
        self.pet_win.minimizeToTray.connect(self.minimize_pet)
        self.pet_win.quitRequested.connect(self.quit)

        self._build_tray()
        # 兼容旧数据：没有 base_remind_at 的待办自动补上
        for todo in self.store.data.get("todos", []):
            if not todo.get("base_remind_at") and todo.get("remind_at"):
                todo["base_remind_at"] = todo["remind_at"]
        self.store.save()
        # 上次可能关了机、错过了零点：启动时先把重复待办往前滚一次，再画界面
        roll_repeats(self.store)
        self._init_reminder_timer()
        self._sync_autostart_setting()

        # 首次启动按设置决定先显示哪个形态；命令行可强制指定（方便测试）
        if start_mode == "pet":
            self.show_pet()
        elif start_mode == "window":
            self.show_main()
        elif self.store.get_setting("pet_visible", True):
            self.show_pet()
        else:
            self.show_main()

    # ---------------- 开机自启 ----------------
    def _sync_autostart_setting(self):
        """默认开机自启：注册表被清掉 / 换了安装位置时自动补登记，用户关掉后不再强开

        源码运行（「测试启动.bat」跑 main.py）时一律不碰注册表：否则测一次就把用户
        原来指向 exe 的自启项改写成 pythonw + main.py，下次开机跑的是源码目录。
        自启项只由打包后的 exe 维护；托盘开关的状态仍然照实读注册表。
        """
        if not getattr(sys, "frozen", False):
            return
        want = bool(self.store.get_setting("autostart", True))
        if not want:
            return
        if AutoStart.is_enabled():
            # 已有登记，但 exe 可能被挪了位置：路径不一致就刷新
            if AutoStart.command_matches():
                return
        if AutoStart.set_enabled(True):
            self.store.set_setting("autostart", True)
        if self._act_autostart is not None:
            self._act_autostart.setChecked(AutoStart.is_enabled())

    # ---------------- 形态切换 ----------------
    def show_help(self):
        """托盘「帮助文档」：讲鼠标操作与功能，用统一弹窗外壳"""
        from widgets.help_dialog import HelpDialog

        dlg = HelpDialog(self.main_win if self.main_win.isVisible() else None)
        dlg.exec()

    def show_main(self):
        # 常量放在方法内导入：从桌宠展开时要用它换算窗口位置
        from widgets.main_window import window_pos_for_pet

        if self.main_win.isVisible():
            self.main_win.raise_()
            self.main_win.activateWindow()
            return
        if self.pet_win.isVisible():
            # 角色中心对齐：主窗口里那张立绘正好落在桌宠立绘原来的位置上
            pet_x, pet_y = self.pet_win.x(), self.pet_win.y()
            scale = self.pet_win.pet_scale
            pet_w, pet_h = self.pet_win.width(), self.pet_win.height()
            self.pet_win.hide()
            # 根据桌宠当前位置判断贴在哪个角，卡片边也贴在对应角
            from PyQt6.QtGui import QGuiApplication
            from widgets.main_window import CARD_X, CARD_Y, CARD_BOTTOM_GAP
            screen = QGuiApplication.primaryScreen()
            avail = screen.availableGeometry()
            EDGE_PX = 2
            win_w = self.main_win.width()
            win_h = self.main_win.height()
            touch_l = pet_x <= avail.left() + EDGE_PX
            touch_r = pet_x + pet_w >= avail.right() - EDGE_PX
            touch_t = pet_y <= avail.top() + EDGE_PX
            touch_b = pet_y + pet_h >= avail.bottom() - EDGE_PX

            if touch_t and touch_l:                       # 左上
                win_x = avail.left() - CARD_X
                win_y = avail.top() - CARD_Y
            elif touch_b and touch_l:                     # 左下
                win_x = avail.left() - CARD_X
                win_y = avail.bottom() - win_h + CARD_BOTTOM_GAP
            elif touch_t and touch_r:                     # 右上
                win_x = avail.right() - win_w + CARD_X + self.main_win.card.width()
                win_y = avail.top() - CARD_Y
            elif touch_b and touch_r:                     # 右下
                win_x = avail.right() - win_w + CARD_X + self.main_win.card.width()
                win_y = avail.bottom() - win_h + CARD_BOTTOM_GAP
            else:
                # 没贴角，按角色中心对齐
                win_x, win_y = window_pos_for_pet(pet_x, pet_y, scale)
            wx, wy = self.main_win._fit_on_screen(int(win_x), int(win_y))
            self.main_win.move(wx, wy)
        self._pet_minimized = False
        self.store.set_setting("pet_visible", False)
        self.pet_win.set_reminder_mode("window")   # 提醒只贴桌宠：窗口形态先收起来
        self.main_win.refresh()
        self.main_win.show()
        self.main_win.raise_()
        self.main_win.activateWindow()

    def show_pet(self, source: str = "anchor"):
        """source='anchor'：按主窗口角色中心原地换成桌宠（提醒弹窗、托盘切换）
           source='keep'：位置已由主窗口算好并写入 pet_pos，直接用（最小化 / 贴边）"""
        from widgets.main_window import pet_pos_for_window

        if source == "anchor" and self.main_win.isVisible():
            pet_pos = pet_pos_for_window(
                self.main_win.x(), self.main_win.y(), self.pet_win.pet_scale
            )
            self.store.set_setting("pet_pos", [int(pet_pos[0]), int(pet_pos[1])])
        self.main_win.hide()
        self._pet_minimized = False
        self.store.set_setting("pet_visible", True)
        self.pet_win.set_reminder_mode("pet")      # 回到桌宠形态：提醒重新贴回暖暖
        # 桌宠位置由 pet_pos 决定（贴边触发 / 锚点换算时已写入）
        pet_pos = self.store.get_setting("pet_pos")
        if pet_pos:
            x, y = self.pet_win._clamp(int(pet_pos[0]), int(pet_pos[1]))
            self.pet_win.move(x, y)
        self.pet_win.show()
        self.pet_win.raise_()

    def minimize_pet(self):
        """右键「最小化到任务栏」：桌宠消失，之后的提醒改在桌面右下角往上排"""
        self.store.set_setting("pet_pos", [self.pet_win.x(), self.pet_win.y()])
        self._pet_minimized = True
        self.pet_win.set_reminder_mode("tray")     # 窗口和桌宠都没了：提醒落到右下角
        self.pet_win.hide()

    def on_window_to_tray(self):
        """窗口点 × 收进托盘：窗口和桌宠都不在，提醒（含已经在等的星星）挪到右下角"""
        self.store.set_setting("pet_visible", False)
        if not self.pet_win.isVisible():
            self.pet_win.set_reminder_mode("tray")

    # ---------------- 托盘 ----------------
    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self.app)

        menu = QMenu()
        act_show = QAction(icon("inbox", C.INK_2, 16), "显示待办窗口", menu)
        act_show.triggered.connect(self.show_main)
        act_pet = QAction(icon("smile", C.INK_2, 16), "桌宠形态", menu)
        act_pet.triggered.connect(lambda: self.show_pet("anchor"))

        self._checkbox_off = QIcon(os.path.join(ASSET_DIR, "checkbox_off.svg"))
        self._checkbox_on = QIcon(os.path.join(ASSET_DIR, "checkbox_on.svg"))
        autostart_on = AutoStart.is_enabled()
        self._act_autostart = QAction(
            self._checkbox_on if autostart_on else self._checkbox_off,
            "开机自启",
            menu,
        )
        self._act_autostart.setCheckable(True)
        self._act_autostart.setChecked(autostart_on)
        self._act_autostart.toggled.connect(self._sync_autostart_icon)
        self._act_autostart.triggered.connect(self._toggle_autostart)

        act_quit = QAction(icon("close", C.INK_2, 16), "退出", menu)
        act_quit.triggered.connect(self.quit)

        act_help = QAction(icon("info", C.INK_2, 16), "帮助文档", menu)
        act_help.triggered.connect(self.show_help)

        menu.addAction(act_show)
        menu.addAction(act_pet)
        menu.addSeparator()
        menu.addAction(self._act_autostart)
        menu.addSeparator()
        menu.addAction(act_help)
        menu.addAction(act_quit)
        round_menu(menu)
        self._tray_menu = menu

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason not in (QSystemTrayIcon.ActivationReason.Trigger,
                          QSystemTrayIcon.ActivationReason.DoubleClick):
            return
        # Windows 上双击会先来一个 Trigger 再来 DoubleClick：合并成一次处理，
        # 否则第一次把桌宠叫回来、第二次又把它换成主窗口
        now = time.monotonic()
        if now - self._last_tray_act < 0.6:
            return
        self._last_tray_act = now
        # 桌宠在（含刚从任务栏叫回来的）就保持桌宠形态，只有当前是窗口形态才开窗口
        if self._pet_minimized or self.pet_win.isVisible():
            self.show_pet("anchor")
            return
        self.show_main()

    def _toggle_autostart(self, checked: bool):
        ok = AutoStart.set_enabled(checked)
        if ok:
            self.store.set_setting("autostart", checked)
        else:
            self._act_autostart.setChecked(not checked)
            from widgets.dialogs import InfoDialog

            InfoDialog(
                APP_NAME,
                "写入开机启动项失败，请检查系统权限。",
                parent=self.main_win,
                icon_name="alert",
            ).exec()

    def _sync_autostart_icon(self, checked: bool):
        self._act_autostart.setIcon(
            self._checkbox_on if checked else self._checkbox_off
        )

    # ---------------- 提醒调度 ----------------
    def _init_reminder_timer(self):
        self._reminder_timer = QTimer(self.app)
        self._reminder_timer.setInterval(15000)   # 15 秒扫一次，够准且几乎不耗电
        self._reminder_timer.timeout.connect(self.tick_reminders)
        self._reminder_timer.start()

    def tick_reminders(self):
        from datetime import datetime
        now = datetime.now()
        # 先判断有没有到点该提醒的（必须在 roll_repeats 之前，
        # 否则刚到点的重复待办会被直接跳到下一次，提醒永远触发不了）
        popped_ids = []
        for todo in self.store.data["todos"]:
            should, _due = should_pop(todo, now)
            if not should:
                continue
            todo["notified"] = True
            self.store.save()
            popped_ids.append(todo["id"])
            # 提醒要贴着暖暖出现：
            # 窗口模式 → 立刻切回桌宠；桌宠在场 → 直接用；
            # 窗口和桌宠都不显示（窗口 × / 桌宠右键最小化）→ 落到右下角往上排
            if self.main_win.isVisible():
                self.main_win.flush_pending()      # 先落盘便签，免得切换丢字
                self.show_pet("anchor")
            elif not self.pet_win.isVisible():
                if not self._pet_minimized and self.store.get_setting("pet_visible", True):
                    self.show_pet()                # 上次就是桌宠形态：把它叫回来
                else:
                    self.pet_win.set_reminder_mode("tray")
            self.pet_win.show_reminder(todo)
            # 重复任务本轮已弹：推进到下一个未来轮次，避免 15 秒后同一轮重复弹
            rule = todo.get("repeat") or "none"
            if rule != "none":
                base_str = todo.get("base_remind_at") or todo.get("remind_at")
                if base_str:
                    try:
                        base_dt = datetime.strptime(base_str, "%Y-%m-%d %H:%M")
                        nxt = advance(base_dt, rule, now)
                        if nxt:
                            todo["remind_at"] = nxt.strftime("%Y-%m-%d %H:%M")
                            todo["notified"] = False
                    except ValueError:
                        pass
                self.store.save()
        # 再处理跨天：重复待办过了零点要顺到下一次
        if roll_repeats(self.store, now):
            for todo in self.store.data["todos"]:
                if ((todo.get("repeat") or "none") != "none"
                        and todo["id"] not in popped_ids):
                    self.pet_win.hide_reminder(todo["id"])   # 旧时间的气泡不该留着；本轮刚弹的保留
            if self.main_win.isVisible():
                self.main_win.refresh()

    def on_snooze(self, tid: str, minutes: int | None = None):
        if minutes is None:
            minutes = int(self.store.get_setting("snooze_minutes", 10) or 10)
        minutes = max(1, int(minutes))
        # 记住这次选的时长，下次点「稍后」沿用
        self.store.set_setting("snooze_minutes", minutes)
        self.store.snooze(tid, minutes)

    def on_done(self, tid: str):
        todo = self.store.get_todo(tid)
        if not todo:
            return
        if not todo.get("done"):
            self.store.toggle_done(tid)
        if self.main_win.isVisible():
            self.main_win.refresh()

    # ---------------- 退出 ----------------
    def quit(self):
        self.main_win.flush_pending()
        self.main_win.save_position()
        self.pet_win.hide_reminder()        # 先关掉所有提醒小窗，免得退出时留残影
        self.store.save()
        if self.tray:
            self.tray.hide()
        self.app.quit()


START_FLAGS = ("--window", "--pet")


def start_mode_from_args(argv: list[str]) -> str | None:
    """解析启动形态参数（测试启动器会用到）"""
    if "--window" in argv:
        return "window"
    if "--pet" in argv:
        return "pet"
    return None


def main() -> int:
    start_mode = start_mode_from_args(sys.argv)
    # 双击 exe 时默认直接打开待办窗口（桌宠仍可从托盘切换）
    if getattr(sys, "frozen", False) and start_mode is None:
        start_mode = "window"
    # 去掉自定义参数，避免 Qt 把 --window / --pet 当未知选项
    argv = [arg for arg in sys.argv if arg not in START_FLAGS]
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")                 # 统一各平台控件基线，QSS 才稳定
    app.setFont(QFont(FONT_FAMILY, 10))
    app.setWindowIcon(app_icon())

    store = DataStore()
    scale = store.get_setting("font_scale", "中")
    set_font_scale(scale)
    app.setStyleSheet(app_qss(scale))
    # 改名后第一次启动：把旧名字的自启项清掉，保持注册表干净
    AutoStart.drop_legacy()

    # 单实例：拿不到锁说明已经有一个在跑
    # 注意：staleLockTime 不要设 0（永不判定为陈旧），否则异常退出后会永久锁死
    lock = QLockFile(LOCK_PATH)
    lock.setStaleLockTime(30000)
    got = lock.tryLock(100)
    if not got and lock.removeStaleLockFile() and lock.tryLock(100):
        got = True
    if not got:
        # 旧实例还开着：平时只允许一个，但改完代码重新启动时留着旧进程会让人
        # 以为改动没生效，于是直接关掉旧实例再接管
        # PyQt6 的 getLockInfo 返回 (是否持有, pid, 主机名, 应用名)
        info = lock.getLockInfo()
        pid = info[1] if info and len(info) > 1 else 0
        if pid > 0 and _kill_pid(pid):
            for _ in range(30):
                time.sleep(0.1)
                lock.removeStaleLockFile()
                if lock.tryLock(100):
                    got = True
                    break
    if not got:
        from widgets.dialogs import InfoDialog

        InfoDialog(APP_NAME, "程序已经在运行了。").exec()
        return 0
    # lock 必须在整个生命周期内持有，挂到 app 上防止被回收
    app._lock = lock  # type: ignore[attr-defined]

    controller = VertinApp(app, store, start_mode=start_mode)
    code = app.exec()
    return code


if __name__ == "__main__":
    sys.exit(main())
