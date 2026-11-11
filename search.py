"""search.py —— 待办 / 便签的 Ctrl+F 查找匹配（纯逻辑，不依赖 Qt）。

匹配规则：
  · 大小写、首尾空格不敏感；
  · 待办匹配标题与备注；便签匹配标题与正文；
  · 空查询不命中；过滤后保留原有顺序。
"""

from __future__ import annotations


def _norm(text: str | None) -> str:
    return (text or "").strip().lower()


def match_todo(query: str, todo: dict) -> bool:
    q = _norm(query)
    if not q:
        return False
    return q in _norm(todo.get("title")) or q in _norm(todo.get("content"))


def match_note(query: str, note: dict) -> bool:
    q = _norm(query)
    if not q:
        return False
    return q in _norm(note.get("title")) or q in _norm(note.get("content"))


def filter_todos(query: str, todos: list[dict]) -> list[dict]:
    return [t for t in todos if match_todo(query, t)]


def filter_notes(query: str, notes: list[dict]) -> list[dict]:
    return [n for n in notes if match_note(query, n)]
