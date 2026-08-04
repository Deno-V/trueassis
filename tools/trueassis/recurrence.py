from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Iterable, Optional

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def normalize_weekdays(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    values = [part.strip().lower() for part in raw.split(",") if part.strip()]
    unknown = [value for value in values if value not in WEEKDAYS]
    if unknown:
        raise ValueError("未知星期：" + ", ".join(unknown))
    return list(dict.fromkeys(values))


def normalize_month_days(raw: Optional[str]) -> list[int]:
    if not raw:
        return []
    values: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or not 1 <= int(part) <= 31:
            raise ValueError(f"每月日期必须在 1..31：{part}")
        values.append(int(part))
    return list(dict.fromkeys(values))


def make_version(*, effective_from: date, frequency: str, interval: int = 1,
                 effective_until: Optional[date] = None, weekdays: Optional[list[str]] = None,
                 month_days: Optional[list[int]] = None, created_at: str) -> Dict[str, Any]:
    if frequency not in {"daily", "weekly", "monthly"}:
        raise ValueError("repeat 只能是 daily、weekly 或 monthly")
    if interval < 1:
        raise ValueError("interval 必须大于等于 1")
    weekdays = weekdays or []
    month_days = month_days or []
    if frequency == "weekly" and not weekdays:
        weekdays = [list(WEEKDAYS)[effective_from.weekday()]]
    if frequency == "monthly" and not month_days:
        month_days = [effective_from.day]
    if effective_until and effective_until < effective_from:
        raise ValueError("循环结束日期不能早于开始日期")
    return {
        "effective_from": effective_from.isoformat(),
        "effective_until": effective_until.isoformat() if effective_until else None,
        "frequency": frequency,
        "interval": interval,
        "weekdays": weekdays,
        "month_days": month_days,
        "state": "active",
        "created_at": created_at,
    }


def _month_delta(start: date, current: date) -> int:
    return (current.year - start.year) * 12 + current.month - start.month


def version_matches(version: Dict[str, Any], current: date) -> bool:
    if version.get("state", "active") != "active":
        return False
    start = date.fromisoformat(version["effective_from"])
    end = date.fromisoformat(version["effective_until"]) if version.get("effective_until") else None
    if current < start or (end and current > end):
        return False
    interval = int(version.get("interval", 1))
    frequency = version["frequency"]
    if frequency == "daily":
        return (current - start).days % interval == 0
    if frequency == "weekly":
        weeks = ((current - timedelta(days=current.weekday())) -
                 (start - timedelta(days=start.weekday()))).days // 7
        return weeks >= 0 and weeks % interval == 0 and current.weekday() in {
            WEEKDAYS[value] for value in version.get("weekdays", [])
        }
    months = _month_delta(start, current)
    return months >= 0 and months % interval == 0 and current.day in set(version.get("month_days", []))


def occurrence_dates(task: Dict[str, Any], start: date, end: date) -> Iterable[date]:
    if start > end:
        return
    schedule = task["schedule"]
    if schedule["type"] == "once":
        due = schedule.get("due")
        if due:
            value = date.fromisoformat(due)
            if start <= value <= end:
                yield value
        return
    cancelled_from = date.fromisoformat(schedule["cancelled_from"]) if schedule.get("cancelled_from") else None
    versions = schedule.get("versions", [])
    current = start
    while current <= end:
        if cancelled_from and current >= cancelled_from:
            current += timedelta(days=1)
            continue
        if any(version_matches(version, current) for version in versions):
            yield current
        current += timedelta(days=1)


def occurrence_override(task: Dict[str, Any], original: date) -> Optional[Dict[str, Any]]:
    key = original.isoformat()
    for occurrence in reversed(task.get("occurrences", [])):
        if occurrence.get("original_date") == key:
            return occurrence
    return None


def is_scheduled(task: Dict[str, Any], original: date) -> bool:
    return any(True for _ in occurrence_dates(task, original, original))
