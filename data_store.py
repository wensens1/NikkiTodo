"""
data_store.py —— 本地 JSON 持久化

要求：数据**必须**和代码放在同一目录（禁止写入 AppData）。
数据文件位置：<本文件所在目录>/data.json

结构：
{
  "version": 1,
  "todos": [
    {"id": "…", "title": "…", "content": "…", "done": false, "pinned": false,
     "created_at": "2026-11-07 21:53", "remind_at": "2026-11-08 08:45" | null,
     "repeat": "none" | "daily" | "weekly" | "monthly" | "yearly" | "weekday",
     "notified": false, "done_at": null}
  ],
  "notes": [{"id": "…", "title": "…", "content": "…", "updated_at": "…"}],
  "settings": {"autostart": false, "font_scale": "中", "pet_pos": [x, y],
               "win_pos": [x, y], "active_tab": "todo", "pet_visible": true},
  "meta": {"first_run": true}
}
"""

import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timedelta

if getattr(sys, "frozen", False):
    # 打包成 exe 后，数据必须放在 exe 旁边，而不是 PyInstaller 的临时解包目录
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data.json")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def default_data() -> dict:
    return {
        "version": 1,
        "todos": [],
        "notes": [],
        "settings": {
            "autostart": True,        # 默认开机自启
            "font_scale": "中",       # 微 / 小 / 中 / 大
            "sort_mode": "created",   # created（创建时间）/ remind（提醒时间）
            "pet_pos": None,
            "win_pos": None,
            "active_tab": "todo",
            "pet_visible": True,      # 下次启动以桌宠形态出现
            "snooze_minutes": 10,
        },
        "meta": {"first_run": True},
    }


class DataStore:
    """所有待办 / 便签 / 设置的唯一读写入口（原子写，防损坏）"""

    def __init__(self, path: str | None = None):
        self.path = path or DATA_PATH
        self.data = default_data()
        self.load()

    # ---------------- 读写 ----------------
    def load(self):
        if not os.path.exists(self.path):
            self.data = default_data()
            self.save()
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("data.json 顶层不是对象")
            # 与默认结构合并，避免旧版本文件缺字段
            merged = default_data()
            merged.update(loaded)
            merged["settings"] = {**default_data()["settings"], **(loaded.get("settings") or {})}
            for key in ("todos", "notes"):
                merged[key] = loaded.get(key) or []
            merged["meta"] = {**default_data()["meta"], **(loaded.get("meta") or {})}
            self.data = merged
        except Exception:
            # 文件损坏：备份后重建，绝不让程序因为读不到数据而打不开
            try:
                shutil.copy2(self.path, self.path + ".bak")
            except Exception:
                pass
            self.data = default_data()
            self.save()

    def save(self):
        """原子写：先写 .tmp 再 os.replace，避免写一半断电导致数据丢失"""
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except Exception as e:
            print(f"[DataStore] 保存失败：{e}")

    # ---------------- 待办 ----------------
    def todos(self, include_done: bool = False, sort_mode: str | None = None) -> list[dict]:
        items = [t for t in self.data["todos"] if include_done or not t.get("done")]
        mode = sort_mode or self.get_setting("sort_mode", "created")

        def created_desc(rows: list[dict]) -> list[dict]:
            return sorted(rows, key=lambda t: t.get("created_at") or "", reverse=True)

        pending = [t for t in items if not t.get("done")]
        done = [t for t in items if t.get("done")]
        done.sort(key=lambda t: t.get("done_at") or "", reverse=True)  # 最新完成的在前

        # 置顶项不参与排序：固定压在顶部，只按它们自己的先后（先钉的在上面之后钉的在上面）
        index = {t["id"]: i for i, t in enumerate(self.data["todos"])}
        pinned = sorted([t for t in pending if t.get("pinned")],
                        key=lambda t: index.get(t["id"], 1 << 30))
        normal = [t for t in pending if not t.get("pinned")]

        if mode == "manual":
            # 自定义顺序：非置顶的照 todos 数组的先后（拖动排序写回的）
            normal = sorted(normal, key=lambda t: index.get(t["id"], 1 << 30))
        elif mode == "remind":
            # 有提醒的排在无提醒的前面；组内按提醒时间 / 创建时间（只管非置顶的）
            with_remind = [t for t in normal if t.get("remind_at")]
            without_remind = [t for t in normal if not t.get("remind_at")]
            with_remind.sort(key=lambda t: t.get("remind_at") or "")
            normal = with_remind + created_desc(without_remind)
        else:
            # 默认：按创建时间倒序（新创建的在上）
            normal = created_desc(normal)
        return pinned + normal + done
        return pending + done

    def add_todo(self, title: str, content: str = "", remind_at: str | None = None,
                 repeat: str = "none") -> dict:
        todo = {
            "id": new_id(),
            "title": title.strip(),
            "content": content.strip(),
            "done": False,
            "pinned": False,
            "created_at": now_str(),
            "remind_at": remind_at,
            "base_remind_at": remind_at,  # 原始周期锚点，永不修改，用来算下一次
            "repeat": repeat or "none",
            "notified": False,
            "done_at": None,
        }
        self.data["todos"].insert(0, todo)     # 新加的排最前面，不用手动往上拖
        self.save()
        return todo

    def set_todo_order(self, ids: list[str]):
        """按给定顺序重写待办排列（拖动排序后调用）；不在列表里的保持原相对顺序排在后面"""
        by_id = {t["id"]: t for t in self.data["todos"]}
        ordered = [by_id[i] for i in ids if i in by_id]
        rest = [t for t in self.data["todos"] if t["id"] not in ids]
        self.data["todos"] = ordered + rest
        self.save()

    def get_todo(self, tid: str) -> dict | None:
        for t in self.data["todos"]:
            if t["id"] == tid:
                return t
        return None

    def update_todo(self, tid: str, **fields):
        todo = self.get_todo(tid)
        if not todo:
            return
        todo.update(fields)
        # 改了提醒时间就要允许再次提醒
        if "remind_at" in fields:
            todo["notified"] = False
        self.save()

    def delete_todo(self, tid: str):
        self.data["todos"] = [t for t in self.data["todos"] if t["id"] != tid]
        self.save()

    def toggle_done(self, tid: str):
        todo = self.get_todo(tid)
        if not todo:
            return
        rule = todo.get("repeat") or "none"
        if todo.get("done"):
            # 已经完成了，点一下取消完成
            todo["done"] = False
            todo["done_at"] = None
        else:
            todo["done"] = True
            todo["done_at"] = now_str()
            # 重复任务点完成后，自动滚到下一次
            if rule != "none":
                from repeat import advance
                base_str = todo.get("base_remind_at") or todo.get("remind_at")
                if base_str:
                    try:
                        base_dt = datetime.strptime(base_str, "%Y-%m-%d %H:%M")
                        nxt = advance(base_dt, rule, datetime.now())
                        if nxt:
                            todo["remind_at"] = nxt.strftime("%Y-%m-%d %H:%M")
                            # base_remind_at 保持原始锚点不变，不破坏循环规则
                            todo["notified"] = False
                            todo["done"] = False  # 回到待办列表，等待下一次
                            todo["done_at"] = None
                    except ValueError:
                        pass
        self.save()

    def toggle_pin(self, tid: str):
        todo = self.get_todo(tid)
        if not todo:
            return
        todo["pinned"] = not todo.get("pinned", False)
        # 置顶时把该任务挪到列表最前面，成为第一
        if todo["pinned"]:
            self.data["todos"].remove(todo)
            self.data["todos"].insert(0, todo)
        self.save()

    def snooze(self, tid: str, minutes: int = 10):
        todo = self.get_todo(tid)
        if not todo:
            return
        base = datetime.now()
        todo["remind_at"] = (base + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
        # base_remind_at 不动，不破坏循环规则
        todo["notified"] = False
        self.save()

    # ---------------- 便签 ----------------
    def notes(self) -> list[dict]:
        return self.data["notes"]

    def get_note(self, nid: str) -> dict | None:
        for n in self.data["notes"]:
            if n["id"] == nid:
                return n
        return None

    def add_note(self, title: str = "新便签", content: str = "") -> dict:
        note = {"id": new_id(), "title": title, "content": content, "updated_at": now_str()}
        self.data["notes"].append(note)
        self.save()
        return note

    def update_note(self, nid: str, **fields):
        note = self.get_note(nid)
        if not note:
            return
        note.update(fields)
        note["updated_at"] = now_str()
        self.save()

    def set_note_order(self, ids: list[str]):
        """按给定顺序重写便签排列（侧栏长按拖动后调用）"""
        by_id = {n["id"]: n for n in self.data["notes"]}
        ordered = [by_id[i] for i in ids if i in by_id]
        rest = [n for n in self.data["notes"] if n["id"] not in ids]
        self.data["notes"] = ordered + rest
        self.save()

    def delete_note(self, nid: str):
        self.data["notes"] = [n for n in self.data["notes"] if n["id"] != nid]
        self.save()

    # ---------------- 设置 ----------------
    def get_setting(self, key: str, default=None):
        return self.data["settings"].get(key, default)

    def set_setting(self, key: str, value):
        self.data["settings"][key] = value
        self.save()
