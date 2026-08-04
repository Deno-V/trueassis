from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Iterable, Optional

from .recurrence import (is_scheduled, make_version, normalize_month_days,
                         normalize_weekdays, occurrence_dates, occurrence_override)
from .storage import (CATEGORIES, day_start, day_start_label, find_record,
          iter_records, load_config, new_id, now_iso, parse_date,
          parse_tags, record_path, save_record, set_day_start, today)


def _history(action: str, **details: Any) -> Dict[str, Any]:
    value = {"at": now_iso(), "action": action}
    value.update({key: item for key, item in details.items() if item is not None})
    return value


# 全系统只有两种时间：
#   *_at 是系统记录这件事的时刻，只用于审计，永不参与归属判断；
#   *_on 是这件事真正发生的那一天，所有查询与报告都按它归档。
# 补记时两者必然分离，例如 8 月 4 日才说“我 1 号跑了”。
def _settle_on(args: Any, anchor: date) -> str:
    value = parse_date(getattr(args, "on_date", None))
    return (value or anchor).isoformat()


def _settled_on(value: Dict[str, Any], key: str) -> Optional[str]:
    direct = value.get(f"{key}_on")
    if direct:
        return direct
    stamp = value.get(f"{key}_at")
    return stamp[:10] if stamp else None


def configure(args: Any) -> Dict[str, Any]:
    """查看或设置日界时间。不传 --day-start 即只查看。"""
    if getattr(args, "day_start", None):
        config = set_day_start(args.day_start)
    else:
        config = load_config()
    hour, minute = day_start()
    return {
        "ok": True,
        "day_start": config.get("day_start"),
        "logical_today": today().isoformat(),
        "wall_clock": now_iso(),
        "explain": f"每天从 {hour:02d}:{minute:02d} 开始计算；此刻归属 {today().isoformat()}",
    }


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
        "created_on": today().isoformat(),
        "updated_at": stamp,
        "completed_at": None,
        "completed_on": None,
        "cancelled_at": None,
        "cancelled_on": None,
        "cancel_reason": None,
        "history": [_history("created")],
    }
    path = record_path("task", record_id, today().isoformat())
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
        "created_on": today().isoformat(),
        "updated_at": stamp,
        "history": [_history("created")],
    }
    path = record_path("idea", record_id, today().isoformat())
    body = f"# {data['title']}\n\n## 想法\n\n{(args.note or '').strip()}\n"
    save_record(path, data, body)
    return {"id": record_id, "record": data}


def _in_range(value: Optional[str], start: Optional[date], end: Optional[date]) -> bool:
    if not value:
        return False
    day = date.fromisoformat(value[:10])
    return (start is None or day >= start) and (end is None or day <= end)


def _occurrence_view(task: Dict[str, Any], original: date, override: Optional[Dict[str, Any]], body: str = "") -> Dict[str, Any]:
    scheduled = original
    state = "pending"
    result: Dict[str, Any] = {}
    if override:
        scheduled = date.fromisoformat(override.get("scheduled_date") or original.isoformat())
        state = override.get("status", "pending")
        result.update({key: override.get(key) for key in
                       ("completed_at", "completed_on", "cancelled_at", "cancelled_on", "reason", "note")
                       if override.get(key) is not None})
    result.update({
        "id": task["id"], "title": task["title"], "kind": "occurrence",
        "category": task["category"], "tags": task.get("tags", []),
        "original_date": original.isoformat(), "scheduled_date": scheduled.isoformat(),
        "status": state,
    })
    return _with_details(result, body)


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


# 分区可见性：只返回本次真正查询过的分区。
# 这样「字段存在且为空」才明确表示确实没有，而不是根本没查，避免语义歧义。
def _visible_partitions(kind: str, status: str, include_overdue: bool,
      include_undated: bool, direct_lookup: bool) -> set:
    if direct_lookup:
        return {"records"}
    visible = set()
    if kind in {"all", "task"}:
        if status in {"all", "pending", "open"}:
            visible.add("scheduled")
            if include_overdue:
                visible.add("overdue")
            if include_undated:
                visible.add("undated")
        if status in {"all", "pending", "open", "missed"}:
            visible.add("missed")
        if status in {"all", "done"}:
            visible.add("done")
        if status in {"all", "cancelled"}:
            visible.add("cancelled")
    if kind in {"all", "idea"} and status in {"all", "open", "archived"}:
        visible.add("ideas")
    return visible


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
    has_range = start is not None
    direct_lookup = bool(args.text or args.id) and not has_range
    if not has_range:
        start = end = today()
    now = today()
    # 债务边界：只有早于区间起点、同时确实已过今天的欠账才算逾期。
    # 查询未来区间时，今天到区间之间的任务尚未到期，不应被称为逾期。
    debt_before = min(start, now)
    out: Dict[str, list] = {"records": [], "scheduled": [], "overdue": [], "undated": [], "done": [], "cancelled": [], "missed": [], "ideas": []}
    scan_start = start
    scan_end = end

    for _, data, body in iter_records(args.kind):
        if not _matching(data, body, args):
            continue
        if direct_lookup:
            out["records"].append(_with_details({
                "id": data["id"], "title": data["title"], "kind": data["kind"],
                "category": data["category"], "tags": data.get("tags", []),
                "status": data["status"], "schedule": data.get("schedule"),
                "created_at": data["created_at"], "updated_at": data["updated_at"],
            }, body))
            continue
        if data["kind"] == "idea":
            if status == "all" or status == data["status"]:
                if not has_range or _in_range(_settled_on(data, "created"), start, end):
                    idea_view = {key: data.get(key) for key in ("id", "title", "category", "tags", "status", "created_at")}
                    idea_view["created_on"] = _settled_on(data, "created")
                    out["ideas"].append(_with_details(idea_view, body))
            continue

        if data["schedule"]["type"] == "once":
            due_raw = data["schedule"].get("due")
            due = date.fromisoformat(due_raw) if due_raw else None
            view = _with_details({"id": data["id"], "title": data["title"], "kind": "task", "category": data["category"],
                    "tags": data.get("tags", []), "status": data["status"], "scheduled_date": due_raw,
                    "completed_at": data.get("completed_at"), "completed_on": _settled_on(data, "completed"),
                    "cancelled_at": data.get("cancelled_at"), "cancelled_on": _settled_on(data, "cancelled"),
                    "cancel_reason": data.get("cancel_reason")}, body)
            if data["status"] == "done" and status in {"all", "done"} and _in_range(_settled_on(data, "completed"), start, end):
                out["done"].append(view)
            elif data["status"] == "cancelled" and status in {"all", "cancelled"} and _in_range(_settled_on(data, "cancelled"), start, end):
                out["cancelled"].append(view)
            elif data["status"] == "open" and status in {"all", "pending", "open", "missed"}:
                policy = data["schedule"]["overdue_policy"]
                if due is None:
                    if args.include_undated and status != "missed":
                        out["undated"].append(view)
                elif start <= due <= end:
                    view["is_overdue"] = due < now
                    if due < now and policy == "skip":
                        out["missed"].append(view)
                    elif status != "missed":
                        out["scheduled"].append(view)
                elif due < debt_before and policy == "carry" and args.include_overdue and status != "missed":
                    view["is_overdue"] = True
                    out["overdue"].append(view)
            continue

        if data["status"] in {"done", "cancelled"}:
            closed_on = _settled_on(data, "completed" if data["status"] == "done" else "cancelled")
            if status in {"all", data["status"]} and _in_range(closed_on, start, end):
                out[data["status"]].append(_with_details({"id": data["id"], "title": data["title"], "kind": "task-series",
                                             "category": data["category"], "status": data["status"], "on": closed_on}, body))
            continue

        generated: Dict[str, Dict[str, Any]] = {}
        for original in occurrence_dates(data, scan_start, scan_end):
            view = _occurrence_view(data, original, occurrence_override(data, original), body)
            generated[original.isoformat()] = view

        for occurrence in data.get("occurrences", []):
            original = date.fromisoformat(occurrence["original_date"])
            scheduled = date.fromisoformat(occurrence.get("scheduled_date") or occurrence["original_date"])
            state = occurrence.get("status", "pending")
            if state == "done" and status in {"all", "done"} and _in_range(_settled_on(occurrence, "completed"), start, end):
                out["done"].append(_occurrence_view(data, original, occurrence, body))
            elif state == "cancelled" and status in {"all", "cancelled"} and _in_range(_settled_on(occurrence, "cancelled"), start, end):
                out["cancelled"].append(_occurrence_view(data, original, occurrence, body))
            elif state == "pending" and status in {"all", "pending", "open"} and start <= scheduled <= end:
                generated[original.isoformat()] = _occurrence_view(data, original, occurrence, body)

        policy = data["schedule"]["overdue_policy"]
        if status in {"all", "pending", "open", "missed"}:
            for view in generated.values():
                if view["status"] != "pending":
                    continue
                scheduled = date.fromisoformat(view["scheduled_date"])
                if not start <= scheduled <= end:
                    continue
                view["is_overdue"] = scheduled < now
                if scheduled < now and policy == "skip":
                    out["missed"].append(view)
                elif status in {"all", "pending", "open"}:
                    out["scheduled"].append(view)

        if args.include_overdue and policy == "carry" and status in {"all", "pending", "open"}:
            horizon = start - timedelta(days=max(args.overdue_days, 0))
            carry_start = max(_first_schedule_date(data), horizon)
            for original in occurrence_dates(data, carry_start, debt_before - timedelta(days=1)):
                view = _occurrence_view(data, original, occurrence_override(data, original), body)
                scheduled = date.fromisoformat(view["scheduled_date"])
                if view["status"] != "pending" or start <= scheduled <= end:
                    continue
                if scheduled < debt_before:
                    view["is_overdue"] = True
                    out["overdue"].append(view)

    for values in out.values():
        values.sort(key=lambda item: (item.get("scheduled_date") or item.get("created_on") or item.get("created_at") or "", item.get("title", "")))
    visible = _visible_partitions(args.kind, status, bool(args.include_overdue),
             bool(args.include_undated), direct_lookup)
    data = {key: values for key, values in out.items() if key in visible}
    return {"ok": True,
        "mode": "lookup" if direct_lookup else "range",
        "from": None if direct_lookup else start.isoformat(),
        "to": None if direct_lookup else end.isoformat(),
        "filters": {"kind": args.kind, "status": status, "category": args.category, "tag": args.tag,
                 "include_overdue": bool(args.include_overdue),
                 "include_undated": bool(args.include_undated),
                 "overdue_days": args.overdue_days},
        "day_start": day_start_label(),
        # 本次查询覆盖的分区。未列出的分区本次没有查询，不能据此判断「没有」。
        "queried": sorted(visible),
        "data": data}


def _first_schedule_date(task: Dict[str, Any]) -> date:
    schedule = task["schedule"]
    if schedule["type"] == "once":
        return date.fromisoformat(schedule["due"]) if schedule.get("due") else today()
    return min(date.fromisoformat(version["effective_from"]) for version in schedule["versions"])


def update(args: Any) -> Dict[str, Any]:
    path, data, body = find_record(args.id)
    stamp = now_iso()
    action = args.action
    detail: Dict[str, Any] = {}
    if data["kind"] == "idea":
        if action not in {"archive", "restore", "edit"}:
            raise ValueError("idea 仅支持 archive、restore、edit")
        if action == "archive":
            data["status"] = "archived"
        elif action == "restore":
            data["status"] = "open"
        else:
            body, detail["changes"] = _edit_common(data, body, args)
        data["history"].append(_history(action, **detail))
        data["updated_at"] = stamp
        save_record(path, data, body)
        return {"ok": True, "id": data["id"], "action": action, **_echo(detail)}

    occurrence_date = parse_date(args.occurrence) if args.occurrence else None
    if occurrence_date:
        if data["schedule"]["type"] != "recurring":
            raise ValueError("--occurrence 仅适用于循环任务")
        if not is_scheduled(data, occurrence_date):
            raise ValueError(f"{occurrence_date} 不是该循环任务的原始发生日期")
        detail["occurrence"] = occurrence_date.isoformat()
        detail.update(_update_occurrence(data, occurrence_date, action, args, stamp))
    elif action == "complete":
        # 一次性任务默认记在今天：没有别的线索说明它在更早的哪天完成。
        settled = _settle_on(args, today())
        data.update({"status": "done", "completed_at": stamp, "completed_on": settled,
                     "cancelled_at": None, "cancelled_on": None, "cancel_reason": None})
        detail["on"] = settled
    elif action == "cancel":
        if not args.reason:
            raise ValueError("取消任务必须提供 --reason")
        settled = _settle_on(args, today())
        data.update({"status": "cancelled", "cancelled_at": stamp, "cancelled_on": settled,
                     "cancel_reason": args.reason})
        detail.update({"on": settled, "reason": args.reason})
    elif action == "reopen":
        data.update({"status": "open", "completed_at": None, "completed_on": None,
                     "cancelled_at": None, "cancelled_on": None, "cancel_reason": None})
    elif action == "reschedule":
        if data["schedule"]["type"] != "once":
            raise ValueError("修改某次循环请同时提供 --occurrence")
        moved_to = parse_date(args.to, required=True).isoformat()
        detail["from"] = data["schedule"].get("due")
        detail["to"] = moved_to
        data["schedule"]["due"] = moved_to
    elif action == "edit":
        body, detail["changes"] = _edit_common(data, body, args)
    elif action == "edit-schedule":
        _edit_schedule(data, args, stamp)
        detail.update({"effective_from": parse_date(args.effective_from, required=True).isoformat(),
                       "repeat": args.repeat, "interval": args.interval, "weekdays": args.on,
                       "month_days": args.month_days, "until": args.until})
    elif action == "cancel-series":
        if data["schedule"]["type"] != "recurring":
            raise ValueError("cancel-series 仅适用于循环任务")
        if not args.reason:
            raise ValueError("取消后续循环必须提供 --reason")
        effective = parse_date(args.effective_from or "today", required=True).isoformat()
        data["schedule"]["cancelled_from"] = effective
        detail.update({"effective_from": effective, "reason": args.reason})
    else:
        raise ValueError(f"不支持的 action：{action}")
    data["updated_at"] = stamp
    data["history"].append(_history(action, **detail))
    save_record(path, data, body)
    return {"ok": True, "id": data["id"], "action": action, **_echo(detail)}


def _echo(detail: Dict[str, Any]) -> Dict[str, Any]:
    return {key: detail[key] for key in ("on", "occurrence", "changes") if detail.get(key) is not None}


DESCRIPTION_HEADINGS = ("## 说明", "## 想法")
SUPPLEMENT_HEADING = "## 补充"


def _section_bounds(lines: list, heading: str) -> Optional[tuple]:
    for index, line in enumerate(lines):
        if line.strip() == heading:
            end = len(lines)
            for cursor in range(index + 1, len(lines)):
                if lines[cursor].startswith("## "):
                    end = cursor
                    break
            return index, end
    return None


def _body_details(body: str) -> Dict[str, str]:
    """从正文提取可供查询展示的细节：说明正文与补充内容。"""
    lines = body.splitlines()
    note = supplement = ""
    for heading in DESCRIPTION_HEADINGS:
        bounds = _section_bounds(lines, heading)
        if bounds:
            start, end = bounds
            note = "\n".join(lines[start + 1:end]).strip()
            break
    sup = _section_bounds(lines, SUPPLEMENT_HEADING)
    if sup:
        start, end = sup
        supplement = "\n".join(lines[start + 1:end]).strip()
    result: Dict[str, str] = {}
    if note:
        result["note"] = note
    if supplement:
        result["supplement"] = supplement
    return result


def _with_details(view: Dict[str, Any], body: str) -> Dict[str, Any]:
    details = _body_details(body)
    if details:
        view["details"] = details
    return view


def _retitle(body: str, title: str) -> str:
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            lines[index] = f"# {title}"
            return "\n".join(lines) + "\n"
    return f"# {title}\n\n{body.lstrip()}"


def _append_note(body: str, text: str, on: str) -> str:
    entry = f"- {on}：{text.strip()}"
    lines = body.rstrip().splitlines()
    bounds = _section_bounds(lines, SUPPLEMENT_HEADING)
    if bounds is None:
        return "\n".join(lines) + f"\n\n{SUPPLEMENT_HEADING}\n\n{entry}\n"
    start, end = bounds
    block = lines[start:end]
    while block and not block[-1].strip():
        block.pop()
    return "\n".join(lines[:start] + block + [entry] + lines[end:]) + "\n"


def _replace_description(body: str, text: str) -> str:
    lines = body.rstrip().splitlines()
    for heading in DESCRIPTION_HEADINGS:
        bounds = _section_bounds(lines, heading)
        if bounds is None:
            continue
        start, end = bounds
        rebuilt = lines[:start] + [heading, "", text.strip(), ""] + lines[end:]
        return "\n".join(rebuilt).rstrip() + "\n"
    return "\n".join(lines) + f"\n\n{DESCRIPTION_HEADINGS[0]}\n\n{text.strip()}\n"


def _edit_common(args_data: Dict[str, Any], body: str, args: Any) -> tuple:
    data, changes = args_data, {}
    if args.title:
        value = args.title.strip()
        if value != data["title"]:
            changes["title"] = {"from": data["title"], "to": value}
            body = _retitle(body, value)
            data["title"] = value
    if args.category:
        if args.category not in CATEGORIES:
            raise ValueError(f"未知分类：{args.category}")
        if args.category != data["category"]:
            changes["category"] = {"from": data["category"], "to": args.category}
            data["category"] = args.category
    if args.tags is not None:
        value = parse_tags(args.tags)
        if value != data["tags"]:
            changes["tags"] = {"from": list(data["tags"]), "to": value}
            data["tags"] = value
    if getattr(args, "add_tags", None):
        merged = list(dict.fromkeys(list(data["tags"]) + parse_tags(args.add_tags)))
        if merged != data["tags"]:
            changes["tags"] = {"from": list(data["tags"]), "to": merged}
            data["tags"] = merged
    if getattr(args, "replace_note", None):
        body = _replace_description(body, args.replace_note)
        changes["description"] = "replaced"
    if args.note:
        settled = _settle_on(args, today())
        body = _append_note(body, args.note, settled)
        changes["supplement"] = settled
    if not changes:
        raise ValueError("edit 需要至少一项修改：--title / --category / --tags / --add-tags / --note / --replace-note")
    return body, changes


def _update_occurrence(data: Dict[str, Any], original: date, action: str, args: Any, stamp: str) -> Dict[str, Any]:
    current = occurrence_override(data, original)
    value = dict(current) if current else {"original_date": original.isoformat(), "scheduled_date": original.isoformat(), "status": "pending"}
    detail: Dict[str, Any] = {}
    # 这一次原本安排在哪天，就是它默认归属的那天；用户已经用 --occurrence 指明了。
    anchor = date.fromisoformat(value.get("scheduled_date") or original.isoformat())
    if action == "complete":
        settled = _settle_on(args, anchor)
        value.update({"status": "done", "completed_at": stamp, "completed_on": settled,
                      "cancelled_at": None, "cancelled_on": None, "reason": None})
        detail["on"] = settled
    elif action == "cancel":
        if not args.reason:
            raise ValueError("取消某次循环必须提供 --reason")
        settled = _settle_on(args, anchor)
        value.update({"status": "cancelled", "cancelled_at": stamp, "cancelled_on": settled,
                      "reason": args.reason})
        detail.update({"on": settled, "reason": args.reason})
    elif action == "reopen":
        value.update({"status": "pending", "completed_at": None, "completed_on": None,
                      "cancelled_at": None, "cancelled_on": None, "reason": None})
    elif action == "reschedule":
        moved_to = parse_date(args.to, required=True).isoformat()
        detail.update({"from": value.get("scheduled_date"), "to": moved_to})
        value.update({"status": "pending", "scheduled_date": moved_to})
    else:
        raise ValueError("带 --occurrence 时仅支持 complete、cancel、reopen、reschedule")
    if args.note:
        value["note"] = args.note
    value["updated_at"] = stamp
    data["occurrences"] = [item for item in data["occurrences"] if item.get("original_date") != original.isoformat()]
    data["occurrences"].append(value)
    return detail


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
