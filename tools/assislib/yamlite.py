# -*- coding: utf-8 -*-
"""极简 YAML front-matter 解析/序列化 + 日期与字符串工具。

刻意不依赖 PyYAML：保证任何机器上的任何 AI 工具都能零安装直接运行。
只支持本项目 schema 用到的子集：标量、[a, b] 内联列表、- 短横线列表。
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from .const import WEEKDAY_MAP, die

# ────────────────────────── front-matter ──────────────────────────

FM_ORDER = [
    "id", "title", "kind", "status", "domain", "priority", "due", "defer",
    "estimate", "energy", "context", "tags", "project", "rule", "remind_before",
    "reason", "blocked_by", "last_run", "source", "created", "updated",
]


def _parse_scalar(raw: str) -> Any:
    v = raw.strip()
    if v == "" or v in ("~", "null"):
        return ""
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(x) for x in inner.split(",") if x.strip() != ""]
    if v in ("true", "True", "yes"):
        return True
    if v in ("false", "False", "no"):
        return False
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def _dump_scalar(v: Any) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    s = str(v)
    if s == "":
        return ""
    if re.search(r"^[\s>|*&!%@`{\[]|:\s|#", s) or s.strip() != s:
        return json.dumps(s, ensure_ascii=False)
    return s


def parse_front_matter(text: str) -> Tuple[Dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return {}, text
    meta: Dict[str, Any] = {}
    key: Optional[str] = None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if re.match(r"^\s*-\s+", raw) and key:
            item = _parse_scalar(re.sub(r"^\s*-\s+", "", raw))
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(item)
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", raw)
        if m:
            key = m.group(1)
            rest = m.group(2)
            meta[key] = [] if rest.strip() == "" else _parse_scalar(rest)
    return meta, "\n".join(lines[end + 1:]).lstrip("\n")


def dump_front_matter(meta: Dict[str, Any], body: str) -> str:
    keys = [k for k in FM_ORDER if k in meta] + [k for k in meta if k not in FM_ORDER]
    out = ["---"]
    for k in keys:
        out.append(f"{k}: {_dump_scalar(meta[k])}".rstrip())
    out.append("---")
    return "\n".join(out) + "\n\n" + body.strip() + "\n"


# ────────────────────────── 日期 ──────────────────────────

def today() -> date:
    return date.today()


def parse_date(s: Optional[str], base: Optional[date] = None) -> Optional[date]:
    """YYYY-MM-DD / today / tomorrow / +3d / +2w / +1m / mon..sun(下一个)。"""
    if s is None:
        return None
    raw = str(s).strip().lower()
    if not raw:
        return None
    base = base or today()
    if raw in ("today", "今天"):
        return base
    if raw in ("tomorrow", "明天"):
        return base + timedelta(days=1)
    if raw in ("yesterday", "昨天"):
        return base - timedelta(days=1)
    m = re.fullmatch(r"([+-])(\d+)([dwmy])", raw)
    if m:
        n = int(m.group(2)) * (1 if m.group(1) == "+" else -1)
        unit = m.group(3)
        if unit == "d":
            return base + timedelta(days=n)
        if unit == "w":
            return base + timedelta(weeks=n)
        if unit == "m":
            return base + timedelta(days=30 * n)
        return base + timedelta(days=365 * n)
    if raw in WEEKDAY_MAP:
        delta = (WEEKDAY_MAP[raw] - base.weekday()) % 7 or 7
        return base + timedelta(days=delta)
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        die(f"无法解析日期: {s}（用 YYYY-MM-DD / today / +3d / fri）")
        return None


def to_date(v: Any) -> Optional[date]:
    if not v:
        return None
    try:
        return datetime.strptime(str(v).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def ds(d: Optional[date]) -> str:
    return d.isoformat() if d else ""


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_range(d: date) -> tuple:
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


# ────────────────────────── 字符串 ──────────────────────────

def slugify(title: str) -> str:
    t = unicodedata.normalize("NFKD", title)
    ascii_part = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
    if len(ascii_part) >= 3:
        return ascii_part[:48]
    cn = re.sub(r"[\\/:*?\"<>|\s]+", "-", title.strip())
    return (cn[:24] or "item").strip("-")


def parse_estimate(s: Any) -> Optional[int]:
    """'2h' / '90m' / '1.5h' → 分钟。"""
    if not s:
        return None
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([hm])\s*", str(s).lower())
    if not m:
        return None
    v = float(m.group(1))
    return int(v * 60) if m.group(2) == "h" else int(v)


def fmt_minutes(n: Optional[int]) -> str:
    if not n:
        return "—"
    if n < 60:
        return f"{n}m"
    h = n / 60
    return f"{h:.0f}h" if abs(h - round(h)) < 0.05 else f"{h:.1f}h"
