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
                     include_overdue=True, include_undated=True, overdue_days=3660)
    return query(args)["data"]


def _section(title: str, rows: list, empty: str = "（无）") -> list[str]:
    lines = [f"## {title}", ""]
    if not rows:
        return lines + [f"- {empty}", ""]
    for row in rows:
        suffix = ""
        if row.get("scheduled_date"):
            suffix = f"（{row['scheduled_date']}）"
        if row.get("cancel_reason") or row.get("reason"):
            suffix += f"：{row.get('cancel_reason') or row.get('reason')}"
        lines.append(f"- {row['title']} {suffix}".rstrip())
    lines.append("")
    return lines


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
    lines = [heading, ""]
    lines += _section("完成", data["done"])
    lines += _section("取消", data["cancelled"])
    lines += _section("计划内未完成", data["scheduled"])
    lines += _section("逾期未完成", data["overdue"])
    lines += _section("新增想法", data["ideas"])
    lines += ["## 总结", "", (args.summary or "").strip(), "", "## 复盘", "", (args.reflection or "").strip(), ""]
    extras = getattr(args, "extra", None) or []
    if extras:
        lines += ["## 自由补充", ""]
        for text in extras:
            lines += [text.strip(), ""]
    atomic_write(path, "\n".join(lines))
    return {"ok": True, "period": args.period, "from": start.isoformat(), "to": end.isoformat(), "path": str(path)}
