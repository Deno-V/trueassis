from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Iterable, Optional

from .recurrence import (is_scheduled, make_version, normalize_month_days,
                         normalize_weekdays, occurrence_dates, occurrence_override)
from .storage import (CATEGORIES, find_record, iter_records, new_id, now_iso,
                      parse_date, parse_tags, record_path, save_record, today)


def _history(action: str, **details: Any) -> Dict[str, Any]:
    value = {"at": now_iso(), "action": action}
    value.update({key: item for key, item in details.items() if item is not None})
    return value


def create_task(args: Any) -> Dict[str, Any]:
    stamp = now_iso()
    record_id = new_id("task")
    if args.category not in CATEGORIES:
        raise ValueError(f"未知分类：{args.category}")
    if args.repeat:
        start = parse_date(args.start or args.due or "today", required=True)
        until = parse_date(args.until)
        version = make_version(
            effective_from=start,
            effective_until=until,
            frequency=args.repeat,
            interval=args.interval,
            weekdays=normalize_weekdays(args.on),
            month_days=normalize_month_days(args.month_days),
            created_at=stamp,
        )
        schedule = {
            "type": "recurring",
            "overdue_policy": args.overdue_policy or "skip",
            "versions": [version],
            "cancelled_from": None,
        }
    else:
        schedule = {
            "type": "once",
            "due": parse_date(args.due).isoformat() if parse_date(args.due) else None,
            "overdue_policy": args.overdue_policy or "carry",
        }
    data = {
        "schema": 1,
        "id": record_id,
        "kind": "task",
        "title": args.title.strip(),
        "category": args.category,
        "tags": parse_tags(args.tags),
        "status": "open",
        "schedule": schedule,
        "occurrences": [],
        "created_at": stamp,
        "updated_at": stamp,
        "completed_at": None,
        "cancelled_at": None,
        "cancel_reason": None,
        "history": [_history("created")],
    }
    path = record_path("task", record_id, stamp)
    body = f"# {data['title']}\n\n## 说明\n\n{(args.note or '').strip()}\n"
    save_record(path, data, body)
    return {"id": record_id, "path": str(path.relative_to(path.parents[3])), "record": data}


def create_idea(args: Any) -> Dict[str, Any]:
    stamp = now_iso()
    if args.category not in CATEGORIES:
        raise ValueError(f"未知分类：{args.category}")
    record_id = new_id("idea")
    data = {
        "schema": 1,
        "id": record_id,
        "kind": "idea",
        "title": args.title.strip(),
        "category": args.category,
        "tags": parse_tags(args.tags),
        "status": "open",
        "created_at": stamp,
        "updated_at": stamp,
        "history": [_history("created")],
    }
    path = record_path("idea", record_id, stamp)
    body = f"# {data['title']}\n\n## 想法\n\n{(args.note or '').strip()}\n"
    save_record(path, data, body)
    return {"id": record_id, "record": data}


def _in_range(value: Optional[str], start: Optional[date], end: Optional[date]) -> bool:
    if not value:
        return False
    day = date.fromisoformat(value[:10])
    return (start is None or day >= start) and (end is None or day <= end)


def _occurrence_view(task: Dict[str, Any], original: date, override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    scheduled = original
    state = "pending"
    result: Dict[str, Any] = {}
    if override:
        scheduled = date.fromisoformat(override.get("scheduled_date") or original.isoformat())
        state = override.get("status", "pending")
        result.update({key: override.get(key) for key in
                       ("completed_at", "cancelled_at", "reason", "note") if override.get(key) is not None})
    result.update({
        "id": task["id"], "title": task["title"], "kind": "occurrence",
        "category": task["category"], "tags": task.get("tags", []),
        "original_date": original.isoformat(), "scheduled_date": scheduled.isoformat(),
        "status": state,
    })
    return result


def _matching(data: Dict[str, Any], body: str, args: Any) -> bool:
    if args.category and data.get("category") != args.category:
        return False
    if args.tag and args.tag not in data.get("tags", []):
        return False
    if args.text and args.text.lower() not in (data.get("title", "") + " " + body).lower():
        return False
    if args.id and data.get("id") != args.id:
        return False
    return True


def query(args: Any) -> Dict[str, Any]:
    start = parse_date(args.from_) if args.from_ else None
    end = parse_date(args.to) if args.to else None
    if start and not end:
        end = start
    if end and not start:
        start = end
    if start and end and start > end:
        raise ValueError("from 不能晚于 to")
    status = args.status
    direct_lookup = bool(args.text or args.id) and start is None and end is None
    out: Dict[str, list] = {"records": [], "scheduled": [], "overdue": [], "undated": [], "done": [], "cancelled": [], "missed": [], "ideas": []}
    scan_start = start or today()
    scan_end = end or scan_start

    for _, data, body in iter_records(args.kind):
        if not _matching(data, body, args):
            continue
        if direct_lookup:
            out["records"].append({
                "id": data["id"], "title": data["title"], "kind": data["kind"],
                "category": data["category"], "tags": data.get("tags", []),
                "status": data["status"], "schedule": data.get("schedule"),
                "created_at": data["created_at"], "updated_at": data["updated_at"],
            })
            continue
        if data["kind"] == "idea":
            if status == "all" or status == data["status"]:
                if start is None or _in_range(data["created_at"], start, end):
                    out["ideas"].append({key: data.get(key) for key in ("id", "title", "category", "tags", "status", "created_at")})
            continue

        if data["schedule"]["type"] == "once":
            due_raw = data["schedule"].get("due")
            due = date.fromisoformat(due_raw) if due_raw else None
            view = {"id": data["id"], "title": data["title"], "kind": "task", "category": data["category"],
                    "tags": data.get("tags", []), "status": data["status"], "scheduled_date": due_raw,
                    "completed_at": data.get("completed_at"), "cancelled_at": data.get("cancelled_at"),
                    "cancel_reason": data.get("cancel_reason")}
            if data["status"] == "done" and status in {"all", "done"} and _in_range(data.get("completed_at"), start, end):
                out["done"].append(view)
            elif data["status"] == "cancelled" and status in {"all", "cancelled"} and _in_range(data.get("cancelled_at"), start, end):
                out["cancelled"].append(view)
            elif data["status"] == "open" and status in {"all", "pending", "open"}:
                if due is None and args.include_undated:
                    out["undated"].append(view)
                elif due and due < today() and data["schedule"]["overdue_policy"] == "carry":
                    if (start and end and start <= due <= end) or (args.include_overdue and start and due < start):
                        out["overdue"].append(view)
                elif due and start and end and start <= due <= end:
                    out["scheduled"].append(view)
            continue

        if data["status"] in {"done", "cancelled"}:
            closed_at = data.get("completed_at") if data["status"] == "done" else data.get("cancelled_at")
            if status in {"all", data["status"]} and _in_range(closed_at, start, end):
                out[data["status"]].append({"id": data["id"], "title": data["title"], "kind": "task-series",
                                             "category": data["category"], "status": data["status"], "at": closed_at})
            continue

        generated: Dict[str, Dict[str, Any]] = {}
        for original in occurrence_dates(data, scan_start, scan_end):
            view = _occurrence_view(data, original, occurrence_override(data, original))
            generated[original.isoformat()] = view

        for occurrence in data.get("occurrences", []):
            original = date.fromisoformat(occurrence["original_date"])
            scheduled = date.fromisoformat(occurrence.get("scheduled_date") or occurrence["original_date"])
            state = occurrence.get("status", "pending")
            if state == "done" and status in {"all", "done"} and _in_range(occurrence.get("completed_at"), start, end):
                out["done"].append(_occurrence_view(data, original, occurrence))
            elif state == "cancelled" and status in {"all", "cancelled"} and _in_range(occurrence.get("cancelled_at"), start, end):
                out["cancelled"].append(_occurrence_view(data, original, occurrence))
            elif state == "pending" and status in {"all", "pending", "open"} and start and end and start <= scheduled <= end:
                generated[original.isoformat()] = _occurrence_view(data, original, occurrence)

        if status in {"all", "pending", "open", "missed"}:
            for view in generated.values():
                scheduled = date.fromisoformat(view["scheduled_date"])
                if view["status"] != "pending":
                    continue
                policy = data["schedule"]["overdue_policy"]
                if scheduled < today():
                    if policy == "carry" and status in {"all", "pending", "open"}:
                        out["overdue"].append(view)
                    elif policy == "skip" and status in {"all", "missed"}:
                        out["missed"].append(view)
                elif start and end and start <= scheduled <= end and status in {"all", "pending", "open"}:
                    out["scheduled"].append(view)

        if args.include_overdue and status in {"all", "pending", "open"} and start:
            carry_start = max(_first_schedule_date(data), start - timedelta(days=args.overdue_days))
            for original in occurrence_dates(data, carry_start, start - timedelta(days=1)):
                override = occurrence_override(data, original)
                view = _occurrence_view(data, original, override)
                if view["status"] == "pending" and date.fromisoformat(view["scheduled_date"]) < start:
                    if data["schedule"]["overdue_policy"] == "carry":
                        out["overdue"].append(view)

    for values in out.values():
        values.sort(key=lambda item: (item.get("scheduled_date") or item.get("created_at") or "", item.get("title", "")))
    return {"ok": True, "from": start.isoformat() if start else None, "to": end.isoformat() if end else None,
            "filters": {"kind": args.kind, "status": status, "category": args.category, "tag": args.tag}, "data": out}


def _first_schedule_date(task: Dict[str, Any]) -> date:
    schedule = task["schedule"]
    if schedule["type"] == "once":
        return date.fromisoformat(schedule["due"]) if schedule.get("due") else today()
    return min(date.fromisoformat(version["effective_from"]) for version in schedule["versions"])


def update(args: Any) -> Dict[str, Any]:
    path, data, body = find_record(args.id)
    stamp = now_iso()
    action = args.action
    if data["kind"] == "idea":
        if action not in {"archive", "restore", "edit"}:
            raise ValueError("idea 仅支持 archive、restore、edit")
        if action == "archive":
            data["status"] = "archived"
        elif action == "restore":
            data["status"] = "open"
        else:
            _edit_common(data, args)
        data["history"].append(_history(action))
        data["updated_at"] = stamp
        save_record(path, data, body)
        return {"ok": True, "id": data["id"], "action": action}

    occurrence_date = parse_date(args.occurrence) if args.occurrence else None
    if occurrence_date:
        if data["schedule"]["type"] != "recurring":
            raise ValueError("--occurrence 仅适用于循环任务")
        if not is_scheduled(data, occurrence_date):
            raise ValueError(f"{occurrence_date} 不是该循环任务的原始发生日期")
        _update_occurrence(data, occurrence_date, action, args, stamp)
    elif action == "complete":
        data.update({"status": "done", "completed_at": stamp})
    elif action == "cancel":
        if not args.reason:
            raise ValueError("取消任务必须提供 --reason")
        data.update({"status": "cancelled", "cancelled_at": stamp, "cancel_reason": args.reason})
    elif action == "reopen":
        data.update({"status": "open", "completed_at": None, "cancelled_at": None, "cancel_reason": None})
    elif action == "reschedule":
        if data["schedule"]["type"] != "once":
            raise ValueError("修改某次循环请同时提供 --occurrence")
        data["schedule"]["due"] = parse_date(args.to, required=True).isoformat()
    elif action == "edit":
        _edit_common(data, args)
    elif action == "edit-schedule":
        _edit_schedule(data, args, stamp)
    elif action == "cancel-series":
        if data["schedule"]["type"] != "recurring":
            raise ValueError("cancel-series 仅适用于循环任务")
        if not args.reason:
            raise ValueError("取消后续循环必须提供 --reason")
        data["schedule"]["cancelled_from"] = parse_date(args.effective_from or "today", required=True).isoformat()
    else:
        raise ValueError(f"不支持的 action：{action}")
    data["updated_at"] = stamp
    data["history"].append(_history(action, occurrence=args.occurrence, reason=args.reason, to=args.to))
    save_record(path, data, body)
    return {"ok": True, "id": data["id"], "action": action}


def _edit_common(data: Dict[str, Any], args: Any) -> None:
    if args.title:
        data["title"] = args.title.strip()
    if args.category:
        if args.category not in CATEGORIES:
            raise ValueError(f"未知分类：{args.category}")
        data["category"] = args.category
    if args.tags is not None:
        data["tags"] = parse_tags(args.tags)


def _update_occurrence(data: Dict[str, Any], original: date, action: str, args: Any, stamp: str) -> None:
    current = occurrence_override(data, original)
    value = dict(current) if current else {"original_date": original.isoformat(), "scheduled_date": original.isoformat(), "status": "pending"}
    if action == "complete":
        value.update({"status": "done", "completed_at": stamp, "cancelled_at": None, "reason": None})
    elif action == "cancel":
        if not args.reason:
            raise ValueError("取消某次循环必须提供 --reason")
        value.update({"status": "cancelled", "cancelled_at": stamp, "reason": args.reason})
    elif action == "reopen":
        value.update({"status": "pending", "completed_at": None, "cancelled_at": None, "reason": None})
    elif action == "reschedule":
        value.update({"status": "pending", "scheduled_date": parse_date(args.to, required=True).isoformat()})
    else:
        raise ValueError("带 --occurrence 时仅支持 complete、cancel、reopen、reschedule")
    if args.note:
        value["note"] = args.note
    value["updated_at"] = stamp
    data["occurrences"] = [item for item in data["occurrences"] if item.get("original_date") != original.isoformat()]
    data["occurrences"].append(value)


def _edit_schedule(data: Dict[str, Any], args: Any, stamp: str) -> None:
    if data["schedule"]["type"] != "recurring":
        raise ValueError("edit-schedule 仅适用于循环任务")
    effective = parse_date(args.effective_from, required=True)
    for version in data["schedule"]["versions"]:
        start = date.fromisoformat(version["effective_from"])
        end = date.fromisoformat(version["effective_until"]) if version.get("effective_until") else None
        if start < effective and (end is None or end >= effective):
            version["effective_until"] = (effective - timedelta(days=1)).isoformat()
        elif start >= effective:
            version["state"] = "superseded"
    data["schedule"]["versions"].append(make_version(
        effective_from=effective,
        effective_until=parse_date(args.until),
        frequency=args.repeat,
        interval=args.interval,
        weekdays=normalize_weekdays(args.on),
        month_days=normalize_month_days(args.month_days),
        created_at=stamp,
    ))
