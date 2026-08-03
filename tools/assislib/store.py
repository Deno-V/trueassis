# -*- coding: utf-8 -*-
"""Item 模型与仓库访问层（加载 / 查找 / 排序 / 运行态）。"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .const import (CONTEXTS, OPEN_STATUSES, PRIORITIES, PRIV, ROOT, SOON_DAYS,
                    color, die)
from .yamlite import (ds, dump_front_matter, parse_estimate,
                      parse_front_matter, to_date, today)


class Item:
    """一个事务条目 = 一个 Markdown 文件。"""

    def __init__(self, path: Path, meta: Dict[str, Any], body: str):
        self.path = path
        self.meta = meta
        self.body = body

    # ── 字段访问 ────────────────────────────────────────────
    def _s(self, key: str, default: str = "") -> str:
        """取标量字段。空值（含被解析成空 list 的空字段）统一回落到 default。"""
        v = self.meta.get(key)
        if v is None or v == "" or v == []:
            return default
        return str(v)

    @property
    def id(self) -> str:
        return self._s("id", self.path.stem)

    @property
    def title(self) -> str:
        return self._s("title", self.id)

    @property
    def status(self) -> str:
        return self._s("status", "inbox")

    @property
    def kind(self) -> str:
        return self._s("kind", "task")

    @property
    def domain(self) -> str:
        return self._s("domain", "life")

    @property
    def priority(self) -> str:
        return self._s("priority", "P2")

    @property
    def energy(self) -> str:
        return self._s("energy", "mid")

    @property
    def project(self) -> str:
        return self._s("project")

    @property
    def due(self) -> Optional[date]:
        return to_date(self.meta.get("due"))

    @property
    def defer(self) -> Optional[date]:
        return to_date(self.meta.get("defer"))

    @property
    def updated(self) -> Optional[date]:
        return to_date(self.meta.get("updated")) or to_date(self.meta.get("created"))

    def _list(self, key: str) -> List[str]:
        v = self.meta.get(key) or []
        if isinstance(v, list):
            return [str(x) for x in v if str(x)]
        return [str(v)] if str(v) else []

    @property
    def contexts(self) -> List[str]:
        return self._list("context")

    @property
    def tags(self) -> List[str]:
        return self._list("tags")

    @property
    def remind_before(self) -> List[str]:
        return self._list("remind_before")

    @property
    def minutes(self) -> Optional[int]:
        return parse_estimate(self.meta.get("estimate"))

    # ── 派生判断 ────────────────────────────────────────────
    def days_left(self) -> Optional[int]:
        d = self.due
        return (d - today()).days if d else None

    def stale_days(self) -> int:
        u = self.updated
        return (today() - u).days if u else 9999

    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    def is_deferred(self) -> bool:
        d = self.defer
        return bool(d and d > today())

    def actionable(self) -> bool:
        """能否出现在"现在可以做什么"里。"""
        if not self.is_open() or self.status == "blocked":
            return False
        if self.kind in ("project", "recurring"):
            return False
        if "someday" in str(self.path):
            return False
        return not self.is_deferred()

    def remind_lead_days(self) -> int:
        """remind_before 中最大的提前天数。"""
        best = 0
        for r in self.remind_before:
            m = re.fullmatch(r"(\d+)([dw])", str(r).strip().lower())
            if m:
                n = int(m.group(1)) * (7 if m.group(2) == "w" else 1)
                best = max(best, n)
        return best

    def urgency(self) -> int:
        """0=逾期 1=今天 2=提醒窗口内/临近 3=其它。"""
        dl = self.days_left()
        if dl is None:
            return 3
        if dl < 0:
            return 0
        if dl == 0:
            return 1
        if dl <= max(SOON_DAYS, self.remind_lead_days()):
            return 2
        return 3

    # ── 写入 ────────────────────────────────────────────────
    def touch(self):
        self.meta["updated"] = ds(today())

    def log(self, line: str):
        stamp = ds(today())
        entry = f"- {stamp} {line}\n"
        if re.search(r"^##\s*记录\s*$", self.body, re.M):
            self.body = re.sub(r"(^##\s*记录\s*\n)", r"\1" + entry, self.body,
                               count=1, flags=re.M)
        else:
            self.body = self.body.rstrip() + f"\n\n## 记录\n{entry}"

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(dump_front_matter(self.meta, self.body), encoding="utf-8")

    # ── 输出 ────────────────────────────────────────────────
    def to_dict(self, with_body: bool = False) -> Dict[str, Any]:
        d = {k: v for k, v in self.meta.items()}
        d["_path"] = str(self.path.relative_to(ROOT))
        d["_days_left"] = self.days_left()
        d["_stale_days"] = self.stale_days()
        d["_actionable"] = self.actionable()
        if with_body:
            d["_body"] = self.body
        return d

    def due_text(self) -> str:
        dl = self.days_left()
        if dl is None:
            return "无 ddl"
        if dl < 0:
            return f"逾期 {-dl} 天"
        if dl == 0:
            return "今天到期"
        if dl == 1:
            return "明天到期"
        return f"{dl} 天后"

    def line(self) -> str:
        dl = self.days_left()
        due = self.due_text()
        if dl is not None and dl <= 0:
            due = color(due, "red")
        elif dl is not None and dl <= SOON_DAYS:
            due = color(due, "yellow")
        return "  ".join([
            color(self.id[:28].ljust(28), "grey"),
            self.priority,
            due.ljust(12),
            self.domain.ljust(8),
            self.title,
        ])


# ────────────────────────── 仓库访问 ──────────────────────────

def item_dirs(include_archive: bool = False) -> List[Path]:
    dirs = [PRIV / "tasks" / "active", PRIV / "tasks" / "someday",
            PRIV / "projects", PRIV / "recurring"]
    if include_archive:
        dirs.append(PRIV / "archive")
    return dirs


def load_item(path: Path) -> Optional[Item]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = parse_front_matter(text)
    if not meta:
        return None
    meta.setdefault("id", path.stem)
    return Item(path, meta, body)


def all_items(include_archive: bool = False) -> List[Item]:
    out: List[Item] = []
    for d in item_dirs(include_archive):
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.md")):
            if p.name.startswith("_") or p.name.upper() == "README.MD":
                continue
            it = load_item(p)
            if it:
                out.append(it)
    return out


def sort_key(it: Item):
    return (
        PRIORITIES.index(it.priority) if it.priority in PRIORITIES else 9,
        it.days_left() if it.days_left() is not None else 9999,
        it.title,
    )


def urgency_key(it: Item):
    return (it.urgency(), PRIORITIES.index(it.priority) if it.priority in PRIORITIES else 9,
            it.days_left() if it.days_left() is not None else 9999)


def find_one(ref: str, include_archive: bool = True) -> Item:
    items = all_items(include_archive=include_archive)
    for pool in (
        [i for i in items if i.id == ref],
        [i for i in items if i.id.startswith(ref)],
        [i for i in items if ref.lower() in i.id.lower() or ref in i.title],
    ):
        if len(pool) == 1:
            return pool[0]
        if len(pool) > 1:
            die("匹配到多个条目，请给更精确的 id：\n  " + "\n  ".join(i.id for i in pool[:10]))
    die(f"找不到条目: {ref}")
    raise SystemExit(1)


def validate_choice(value: str, allowed: List[str], field: str):
    if value and value not in allowed:
        die(f"{field} 取值非法: {value}（可选: {', '.join(allowed)}）")


def validate_contexts(vals: List[str]):
    for v in vals:
        validate_choice(v, CONTEXTS, "context")


# ────────────────────────── 运行态 ──────────────────────────

def read_state() -> Dict[str, Any]:
    p = PRIV / "state.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def write_state(st: Dict[str, Any]):
    PRIV.mkdir(parents=True, exist_ok=True)
    (PRIV / "state.json").write_text(
        json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
