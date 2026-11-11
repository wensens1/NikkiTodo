"""repeat.py —— 重复提醒

两件事：
  1. `next_occurrence` / `advance`：按「每日 / 每周 / 每月 / 每年 / 工作日」算下一次触发时间；
  2. `roll_repeats`：跨天（或程序启动）时把已经过点的重复待办往前滚。

跨天规则（用户定义）：
  · 没完成的：提醒时间直接重置为「今天这个点」（工作日则顺到下一个工作日），不新建；
  · 已完成的：同一套处理，但把 done 复位、清掉完成时间 ——
    在他眼里等于「第二天又给了一条新的喝水待办」；
  · 两者都只在这条待办已经过点时才动，没到点的不碰。
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta

# 存储值 → 界面文字
REPEAT_LABELS = {
    "none": "不重复",
    "daily": "每日",
    "weekly": "每周",
    "monthly": "每月",
    "yearly": "每年",
    "weekday": "工作日",
}


def _add_months(dt: datetime, months: int) -> datetime:
    """加月份，落到小月时截断到月末（10 月 31 日 → 11 月 30 日）"""
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _add_years(dt: datetime, years: int) -> datetime:
    """加年份，2 月 29 日落平年截断到 28 日"""
    year = dt.year + years
    day = min(dt.day, calendar.monthrange(year, dt.month)[1])
    return dt.replace(year=year, day=day)


def next_occurrence(dt: datetime, rule: str):
    """紧挨着的下一个周期（不判断是否已经过了现在）；不重复返回 None"""
    if rule == "daily":
        return dt + timedelta(days=1)
    if rule == "weekly":
        return dt + timedelta(days=7)
    if rule == "monthly":
        return _add_months(dt, 1)
    if rule == "yearly":
        return _add_years(dt, 1)
    if rule == "weekday":
        nxt = dt + timedelta(days=1)
        while nxt.weekday() >= 5:          # 5 = 周六，6 = 周日
            nxt += timedelta(days=1)
        return nxt
    return None


def advance(dt: datetime, rule: str, after: datetime):
    """从 dt 往后一步步推，直到第一次晚于 after（错过多天也能一次追平）"""
    if rule not in REPEAT_LABELS or rule == "none":
        return None
    if rule in ("monthly", "yearly"):
        # 以原始日期为锚点，避免 31 号 → 28 号之后一路漂成 28 号
        for k in range(1, 5000):
            cand = _add_months(dt, k) if rule == "monthly" else _add_years(dt, k)
            if cand > after:
                return cand
        return None
    nxt = next_occurrence(dt, rule)
    for _ in range(10000):
        if nxt is None:
            return None
        if nxt > after:
            return nxt
        nxt = next_occurrence(nxt, rule)
    return None


def _parse_dt(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def should_pop(todo: dict, now: datetime) -> tuple[bool, datetime | None]:
    """判断这条待办本轮是否该弹提醒。

    返回 (是否弹, 到点时间)：
      · 已完成 / 无提醒时间 / 未到点 → 不弹；
      · 单次任务：过期且已弹过 → 不补历史；未弹过且已到点 → 弹一次；
      · 重复任务：跨天（或跨周期）遗留的，上一轮 notified 不挡本轮补弹；
        同一天内已弹过的不重复弹。
    """
    if todo.get("done"):
        return False, None
    due = _parse_dt(todo.get("remind_at"))
    if due is None or due > now:
        return False, None
    rule = todo.get("repeat") or "none"
    notified = bool(todo.get("notified"))
    if rule == "none":
        return (not notified), due
    same_day = due.date() == now.date()
    if notified and same_day:
        return False, None
    return True, due


def roll_repeats(store, now: datetime | None = None) -> int:
    """把已经过了下一个周期的重复待办切到最新的周期锚点，返回改动的条数"""
    now = now or datetime.now()
    changed = 0
    for todo in store.data.get("todos", []):
        rule = todo.get("repeat") or "none"
        if rule == "none" or rule not in REPEAT_LABELS:
            continue
        # 已是未来时间的任务不回拉：弹过后已推进到下一轮，别拉回今天
        remind_dt = _parse_dt(todo.get("remind_at"))
        if remind_dt is not None and remind_dt > now:
            continue
        base_str = todo.get("base_remind_at") or todo.get("remind_at")
        if not base_str:
            continue
        try:
            base_dt = datetime.strptime(base_str, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        # 找到最大的 <= now 的锚点时间
        current = base_dt
        while True:
            nxt = next_occurrence(current, rule)
            if nxt is None:
                break
            if nxt > now:
                break
            current = nxt
        # 如果 current > base_dt，说明已经过了至少一个周期，应该切天
        if current > base_dt:
            todo["remind_at"] = current.strftime("%Y-%m-%d %H:%M")
            # base_remind_at 保持原始锚点不变，不破坏循环规则
            todo["notified"] = False          # 新的一轮重新允许弹提醒
            if todo.get("done"):
                todo["done"] = False          # 完成的这条复位，等于第二天又来一条
                todo["done_at"] = None
            changed += 1
    if changed:
        store.save()
    return changed
