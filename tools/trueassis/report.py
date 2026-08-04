from __future__ import annotations

from argparse import Namespace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict

from .service import query
from .storage import REPORTS, atomic_write, parse_date, today


def _query(start: date, end: date) -> Dict[str, Any]:
    args = Namespace(from_=start.isoformat(), to=end.isoformat(), kind="all", status="all",
                     category=None, tag=None, text=None, id=None,
                     include_overdue=True, include_undated=True, overdue_days=365)
    return query(args)["data"]


def _section(title: str, rows: list, empty: str = "（无）") -> list[str]:
    lines = [f"## {title}", ""]
    if not rows:
        return lines + [f"- {empty}", ""]
    for row in rows:
        suffix = ""
        if row.get("scheduled_date"):
            suffix = f"（{row['scheduled_date']}）"
        elif row.get("on"):
            suffix = f"（{row['on']}）"
        if row.get("cancel_reason") or row.get("reason"):
            suffix += f"：{row.get('cancel_reason') or row.get('reason')}"
        lines.append(f"- {row['title']} {suffix}".rstrip())
    lines.append("")
    return lines


# 自动汇总每次重算，用户亲手写下的内容只增不减：报告可以反复补写。
MANUAL_SECTIONS = ("总结", "复盘", "自由补充")


def _parse_sections(text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    current = None
    buffer: list = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            current = line[3:].strip()
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    return sections


def _merge_manual(previous: str, incoming: str) -> str:
    previous, incoming = (previous or "").strip(), (incoming or "").strip()
    if not incoming:
        return previous
    if not previous or incoming == previous:
        return incoming if not previous else previous
    if incoming in previous:
        return previous
    return f"{previous}\n\n{incoming}"


def generate_report(args: Any) -> Dict[str, Any]:
    base = parse_date(args.date) if args.date else today()
    if args.period == "daily":
        start = end = base
        path = REPORTS / "daily" / f"{base.year}" / f"{base.month:02d}" / f"{base.isoformat()}.md"
        heading = f"# {base.isoformat()} 日报"
    else:
        start = base - timedelta(days=base.weekday())
        end = start + timedelta(days=6)
        iso_year, week, _ = base.isocalendar()
        path = REPORTS / "weekly" / f"{iso_year}" / f"{iso_year}-W{week:02d}.md"
        heading = f"# {iso_year}-W{week:02d} 周报（{start.isoformat()} 至 {end.isoformat()}）"
    data = _query(start, end)
    existing = _parse_sections(path.read_text(encoding="utf-8")) if path.exists() else {}
    summary = _merge_manual(existing.get("总结", ""), args.summary)
    reflection = _merge_manual(existing.get("复盘", ""), args.reflection)
    extras = _merge_manual(existing.get("自由补充", ""),
                           "\n\n".join(text.strip() for text in (getattr(args, "extra", None) or []) if text.strip()))
    # 区间内未完成的项按是否已过期拆开：前者是当期计划，后者是仍然欠着的债。
    in_range_pending = [row for row in data["scheduled"] if not row.get("is_overdue")]
    in_range_overdue = [row for row in data["scheduled"] if row.get("is_overdue")]
    lines = [heading, ""]
    lines += _section("完成", data["done"])
    lines += _section("取消", data["cancelled"])
    lines += _section("计划内未完成", in_range_pending)
    lines += _section("逾期未完成", in_range_overdue + data["overdue"])
    lines += _section("错过未补", data["missed"], empty="（无）")
    lines += _section("无日期待办", data["undated"])
    lines += _section("新增想法", data["ideas"])
    lines += ["## 总结", "", summary, "", "## 复盘", "", reflection, ""]
    if extras:
        lines += ["## 自由补充", "", extras, ""]
    atomic_write(path, "\n".join(lines))
    return {"ok": True, "period": args.period, "from": start.isoformat(), "to": end.isoformat(),
            "path": str(path), "rewritten": bool(existing)}
