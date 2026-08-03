# -*- coding: utf-8 -*-
"""重复任务、日志、日报/周报、归档、体检、画像。"""
from __future__ import annotations

import json
import re
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .const import (CLOSED_STATUSES, DOMAIN_CN, DOMAINS, PRIORITIES, PRIV,
                    ROOT, STATUSES, TPL, WEEKDAY_CN, WEEKDAY_MAP, color, die,
                    require_init)
from .store import (Item, all_items, find_one, load_item, read_state,
                    validate_choice, write_state)
from .yamlite import (ds, dump_front_matter, iso_week, parse_date,
                      parse_front_matter, slugify, to_date, today, week_range)

# ═══════════════════════════ 重复任务 ═══════════════════════════
# rule 语法: daily | weekday | weekly:mon,fri | monthly:1,15 | every:3d


def rule_due_today(rule: str, d: date, last_run: Optional[date]) -> bool:
    r = (rule or "").strip().lower()
    if r == "daily":
        return True
    if r == "weekday":
        return d.weekday() < 5
    if r.startswith("weekly:"):
        days = [WEEKDAY_MAP[x.strip()] for x in r[7:].split(",")
                if x.strip() in WEEKDAY_MAP]
        return d.weekday() in days
    if r.startswith("monthly:"):
        nums = [int(x) for x in re.findall(r"\d+", r[8:])]
        return d.day in nums
    m = re.fullmatch(r"every:(\d+)d", r)
    if m:
        n = int(m.group(1))
        return last_run is None or (d - last_run).days >= n
    return False


def cmd_recur_add(args):
    require_init()
    from .cmd_items import cmd_add
    args.kind = "recurring"
    args.someday = False
    cmd_add(args)


def cmd_recur_list(args):
    require_init()
    defs = [i for i in all_items() if i.kind == "recurring"]
    if args.json:
        print(json.dumps([i.to_dict() for i in defs], ensure_ascii=False, indent=2))
        return
    if not defs:
        print(color("（还没有重复任务，用 assis recur add 创建）", "grey"))
        return
    for it in defs:
        st = "暂停" if it.status == "cancelled" else "启用"
        print(f"  {color(it.id[:30].ljust(30), 'grey')} {it.meta.get('rule', ''):<16} "
              f"{st}  上次生成 {it.meta.get('last_run') or '—'}  {it.title}")


def cmd_recur_run(args):
    """把今天到期的重复任务定义实例化成 active 任务。幂等：同一天不重复生成。"""
    require_init()
    d = parse_date(args.date) if args.date else today()
    created, skipped = [], []

    for defn in [i for i in all_items() if i.kind == "recurring"]:
        if defn.status == "cancelled":
            continue
        last = to_date(defn.meta.get("last_run"))
        if last and last >= d:
            skipped.append((defn, "本期已生成"))
            continue
        if not rule_due_today(str(defn.meta.get("rule", "")), d, last):
            continue

        # 实例 id 与定义 id 必须区分：定义是模具，实例是当期待办。
        base_slug = re.sub(r"^\d{8}-", "", defn.id)
        inst_id = "{}-{}".format(d.strftime("%Y%m%d"), base_slug)
        if inst_id == defn.id:
            inst_id = "{}-r-{}".format(d.strftime("%Y%m%d"), base_slug)
        path = PRIV / "tasks" / "active" / f"{inst_id}.md"
        if path.exists():
            skipped.append((defn, "实例已存在"))
            continue

        meta: Dict[str, Any] = {
            "id": inst_id,
            "title": defn.title,
            "kind": "task",
            "status": "next",
            "domain": defn.domain,
            "priority": defn.priority,
            "due": ds(d),
            "defer": "",
            "estimate": defn.meta.get("estimate") or "",
            "energy": defn.energy,
            "context": defn.contexts,
            "tags": sorted(set(defn.tags + ["recurring"])),
            "project": defn.project,
            "remind_before": defn.remind_before,
            "source": defn.id,
            "created": ds(d),
            "updated": ds(d),
        }
        _, body = parse_front_matter(dump_front_matter(defn.meta, defn.body))
        inst = Item(path, meta, body or "## 目标\n\n## 记录\n")
        inst.log(f"由重复任务 {defn.id} 生成")
        if not args.dry_run:
            inst.save()
            defn.meta["last_run"] = ds(d)
            defn.touch()
            defn.save()
        created.append(inst)

    if args.json:
        print(json.dumps({"created": [i.to_dict() for i in created],
                          "skipped": [{"id": s[0].id, "why": s[1]} for s in skipped]},
                         ensure_ascii=False, indent=2))
        return
    if created:
        print(color(f"✓ 生成 {len(created)} 个重复任务实例" +
                    ("（dry-run，未落盘）" if args.dry_run else ""), "green"))
        for i in created:
            print("  " + i.line())
    else:
        print(color("今天没有需要生成的重复任务", "grey"))
    if not args.dry_run:
        st = read_state()
        st["recur_last_run"] = ds(d)
        write_state(st)


def cmd_recur_pause(args):
    require_init()
    it = find_one(args.id)
    if it.kind != "recurring":
        die(f"{it.id} 不是重复任务定义")
    it.meta["status"] = "cancelled" if args.off else "active"
    it.meta["reason"] = args.reason or ("用户暂停" if args.off else "")
    it.touch()
    it.log("暂停重复生成" if args.off else "恢复重复生成")
    it.save()
    print(color(f"{'⏸ 已暂停' if args.off else '▶ 已恢复'} {it.id}", "yellow"))


# ═══════════════════════════ 日志 ═══════════════════════════

def cmd_log(args):
    require_init()
    validate_choice(args.domain, DOMAINS, "domain")
    d = parse_date(args.date) if args.date else today()
    p = PRIV / "logs" / args.domain / f"{d.strftime('%Y-%m')}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(f"# {DOMAIN_CN.get(args.domain, args.domain)}日志 "
                     f"{d.strftime('%Y-%m')}\n\n", encoding="utf-8")
    text = p.read_text(encoding="utf-8")
    head = f"## {d.isoformat()} {WEEKDAY_CN[d.weekday()]}"
    entry = f"- {args.text}\n"
    if head in text:
        text = text.replace(head + "\n", head + "\n" + entry, 1)
    else:
        text = text.rstrip() + f"\n\n{head}\n{entry}"
    p.write_text(text, encoding="utf-8")
    print(color(f"✓ 已记录到 {p.relative_to(ROOT)}", "green"))


def read_logs_between(start: date, end: date) -> Dict[str, List[str]]:
    """收集 [start, end] 区间内各领域日志条目。"""
    out: Dict[str, List[str]] = {}
    months = set()
    cur = start
    while cur <= end:
        months.add(cur.strftime("%Y-%m"))
        cur += timedelta(days=1)
    for dom in DOMAINS:
        lines: List[str] = []
        for mon in sorted(months):
            p = PRIV / "logs" / dom / f"{mon}.md"
            if not p.exists():
                continue
            cur_day: Optional[date] = None
            for raw in p.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^##\s+(\d{4}-\d{2}-\d{2})", raw)
                if m:
                    cur_day = to_date(m.group(1))
                    continue
                if raw.strip().startswith("- ") and cur_day and start <= cur_day <= end:
                    lines.append(f"{cur_day.isoformat()} {raw.strip()[2:]}")
        if lines:
            out[dom] = lines
    return out


# ═══════════════════════════ 日报 / 周报 ═══════════════════════════

def _closed_between(start: date, end: date) -> Tuple[List[Item], List[Item]]:
    done, cancelled = [], []
    for it in all_items(include_archive=True):
        if it.status not in CLOSED_STATUSES:
            continue
        u = it.updated
        if not u or not (start <= u <= end):
            continue
        (done if it.status == "done" else cancelled).append(it)
    return done, cancelled


def _tpl(name: str, fallback: str) -> str:
    p = TPL / f"{name}.md"
    return p.read_text(encoding="utf-8") if p.exists() else fallback


def cmd_journal(args):
    require_init()
    if args.period == "daily":
        _journal_daily(args)
    elif args.period == "weekly":
        _journal_weekly(args)
    else:
        _journal_monthly(args)


def _journal_daily(args):
    d = parse_date(args.date) if args.date else today()
    p = PRIV / "journal" / "daily" / f"{d.isoformat()}.md"
    done, cancelled = _closed_between(d, d)
    logs = read_logs_between(d, d)

    auto = ["## 今日完成"]
    auto += [f"- {i.title}  `{i.id}`" for i in done] or ["- （无）"]
    if cancelled:
        auto.append("\n## 今日取消")
        auto += [f"- {i.title} —— {i.meta.get('reason', '')}" for i in cancelled]
    if logs:
        auto.append("\n## 领域记录")
        for dom, lines in logs.items():
            auto.append(f"\n### {DOMAIN_CN.get(dom, dom)}")
            auto += [f"- {ln.split(' ', 1)[1]}" for ln in lines]

    block = "\n".join(auto)
    if p.exists() and not args.force:
        text = p.read_text(encoding="utf-8")
        text = re.sub(r"<!-- auto:start -->.*?<!-- auto:end -->",
                      f"<!-- auto:start -->\n{block}\n<!-- auto:end -->",
                      text, flags=re.S)
        p.write_text(text, encoding="utf-8")
        print(color(f"✓ 已刷新 {p.relative_to(ROOT)} 的自动汇总区", "green"))
    else:
        body = _tpl("daily", "# {{date}} 日报\n\n<!-- auto:start -->\n<!-- auto:end -->\n\n"
                             "## 复盘\n- 今天最有价值的一件事：\n- 卡住我的是：\n- 明天第一件事：\n")
        body = (body.replace("{{date}}", d.isoformat())
                    .replace("{{weekday}}", WEEKDAY_CN[d.weekday()])
                    .replace("{{week}}", iso_week(d)))
        body = re.sub(r"<!-- auto:start -->.*?<!-- auto:end -->",
                      f"<!-- auto:start -->\n{block}\n<!-- auto:end -->", body, flags=re.S)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        print(color(f"✓ 已生成 {p.relative_to(ROOT)}", "green"))
    print(color(f"  完成 {len(done)} · 取消 {len(cancelled)} · 日志领域 {len(logs)}", "grey"))
    print(color("  请补写「复盘」三行，这是画像更新的主要来源", "grey"))


def _journal_weekly(args):
    base = parse_date(args.date) if args.date else today()
    start, end = week_range(base)
    p = PRIV / "journal" / "weekly" / f"{iso_week(base)}.md"
    done, cancelled = _closed_between(start, end)
    logs = read_logs_between(start, end)
    open_items = [i for i in all_items() if i.actionable()]

    lines = [f"# {iso_week(base)} 周报（{start.isoformat()} ~ {end.isoformat()}）",
             "", "<!-- auto:start -->", "## 本周完成（按领域）"]
    if done:
        for dom in DOMAINS:
            grp = [i for i in done if i.domain == dom]
            if grp:
                lines.append(f"\n### {DOMAIN_CN.get(dom, dom)}（{len(grp)}）")
                lines += [f"- {i.title}  `{i.id}`" for i in grp]
    else:
        lines.append("- （无）")

    if cancelled:
        lines.append("\n## 本周取消（含理由，供画像学习）")
        lines += [f"- {i.title} —— {i.meta.get('reason', '')}" for i in cancelled]

    if logs:
        lines.append("\n## 领域记录汇总")
        for dom, ls in logs.items():
            lines.append(f"\n### {DOMAIN_CN.get(dom, dom)}（{len(ls)} 条）")
            lines += [f"- {x}" for x in ls]

    lines.append("\n## 下周待办快照")
    for pr in PRIORITIES:
        grp = [i for i in open_items if i.priority == pr]
        if grp:
            lines.append(f"\n### {pr}（{len(grp)}）")
            lines += [f"- {i.title} — {i.due_text()}  `{i.id}`" for i in grp[:10]]
    lines += ["<!-- auto:end -->", "",
              "## 复盘", "- 本周最大产出：", "- 本周最大浪费：",
              "- 有没有该放弃的事（去 assis cancel）：",
              "- 下周三件最重要的事：", "  1. ", "  2. ", "  3. ",
              "", "## 画像更新", "- 观察到的新偏好/节律（同步到 private/profile/profile.md）："]

    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and not args.force:
        text = p.read_text(encoding="utf-8")
        new_auto = "\n".join(lines[2:lines.index("<!-- auto:end -->") + 1])
        text = re.sub(r"<!-- auto:start -->.*?<!-- auto:end -->", new_auto, text, flags=re.S)
        p.write_text(text, encoding="utf-8")
        print(color(f"✓ 已刷新 {p.relative_to(ROOT)}", "green"))
    else:
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(color(f"✓ 已生成 {p.relative_to(ROOT)}", "green"))
    print(color(f"  完成 {len(done)} · 取消 {len(cancelled)} · 未完 {len(open_items)}", "grey"))


def _journal_monthly(args):
    base = parse_date(args.date) if args.date else today()
    start = base.replace(day=1)
    end = (start + timedelta(days=31)).replace(day=1) - timedelta(days=1)
    p = PRIV / "journal" / "monthly" / f"{base.strftime('%Y-%m')}.md"
    done, cancelled = _closed_between(start, end)
    logs = read_logs_between(start, end)

    lines = [f"# {base.strftime('%Y-%m')} 月报", "",
             f"完成 {len(done)} 项 · 取消 {len(cancelled)} 项", "", "## 按领域"]
    for dom in DOMAINS:
        grp = [i for i in done if i.domain == dom]
        if grp or dom in logs:
            lines.append(f"\n### {DOMAIN_CN.get(dom, dom)}")
            lines += [f"- ✓ {i.title}" for i in grp]
            lines += [f"- · {x}" for x in logs.get(dom, [])[:20]]
    lines += ["", "## 月度复盘", "- 目标达成情况：", "- 需要调整的方向：",
              "- 下月重心（≤3）：", "  1. ", "  2. ", "  3. "]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(color(f"✓ 已生成 {p.relative_to(ROOT)}", "green"))


# ═══════════════════════════ 归档 ═══════════════════════════

def cmd_archive(args):
    require_init()
    moved = []
    for it in all_items(include_archive=False):
        if it.status not in CLOSED_STATUSES:
            continue
        u = it.updated or today()
        sub = "done" if it.status == "done" else "cancelled"
        dest_dir = PRIV / "archive" / sub / f"{u.year}" / f"{u.month:02d}"
        dest = dest_dir / it.path.name
        if dest.exists():
            dest = dest_dir / f"{it.path.stem}-dup{it.path.suffix}"
        if args.dry_run:
            moved.append((it, dest))
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(it.path), str(dest))
        moved.append((it, dest))

    if args.json:
        print(json.dumps([{"id": i.id, "to": str(p.relative_to(ROOT))} for i, p in moved],
                         ensure_ascii=False, indent=2))
        return
    if not moved:
        print(color("没有需要归档的条目", "grey"))
        return
    print(color(f"✓ 归档 {len(moved)} 项" + ("（dry-run）" if args.dry_run else ""), "green"))
    for it, p in moved:
        print(f"  {it.status:<9} {it.title}  → {p.parent.relative_to(PRIV)}/")


# ═══════════════════════════ 体检 ═══════════════════════════

def cmd_doctor(args):
    require_init()
    errors: List[str] = []
    warns: List[str] = []

    ids: Dict[str, List[str]] = {}
    items = all_items(include_archive=True)
    project_ids = {i.id for i in items if i.kind == "project"}

    for it in items:
        rel = str(it.path.relative_to(ROOT))
        ids.setdefault(it.id, []).append(rel)
        if it.id != it.path.stem:
            errors.append(f"{rel}: id({it.id}) 与文件名({it.path.stem}) 不一致")
        if it.status not in STATUSES:
            errors.append(f"{rel}: status 非法 '{it.status}'")
        if it.domain not in DOMAINS:
            errors.append(f"{rel}: domain 非法 '{it.domain}'")
        if it.priority not in PRIORITIES:
            errors.append(f"{rel}: priority 非法 '{it.priority}'")
        for k in ("due", "defer", "created", "updated"):
            v = it.meta.get(k)
            if v and not to_date(v):
                errors.append(f"{rel}: {k} 日期格式非法 '{v}'")
        if it.status == "cancelled" and not str(it.meta.get("reason") or "").strip():
            warns.append(f"{rel}: cancelled 但缺 reason")
        if it.status == "blocked" and not str(it.meta.get("blocked_by") or "").strip():
            warns.append(f"{rel}: blocked 但缺 blocked_by")
        if it.kind == "recurring" and not str(it.meta.get("rule") or "").strip():
            errors.append(f"{rel}: recurring 缺 rule")
        if it.project and it.project not in project_ids:
            warns.append(f"{rel}: project '{it.project}' 不存在")
        if it.status in CLOSED_STATUSES and "archive" not in rel:
            warns.append(f"{rel}: 已关闭但未归档（跑 assis archive）")
        if it.kind == "recurring" and "recurring/" not in rel.replace("\\", "/"):
            warns.append(f"{rel}: recurring 定义应放在 private/recurring/")
        if not str(it.meta.get("title") or "").strip():
            errors.append(f"{rel}: 缺 title")

    for iid, paths in ids.items():
        if len(paths) > 1:
            errors.append(f"id 重复 '{iid}': " + " | ".join(paths))

    # 隐私红线：private/ 不得进入 git 索引
    try:
        import subprocess
        r = subprocess.run(["git", "ls-files", "private"], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=10)
        leaked = [x for x in r.stdout.splitlines() if x.strip()]
        if leaked:
            errors.append("🔒 隐私泄漏风险：private/ 下文件已被 git 跟踪：\n      "
                          + "\n      ".join(leaked[:10])
                          + "\n      修复：git rm -r --cached private")
    except Exception:
        pass

    if args.json:
        print(json.dumps({"errors": errors, "warnings": warns,
                          "checked": len(items)}, ensure_ascii=False, indent=2))
        return 1 if errors else 0

    print(color(f"体检 {len(items)} 个条目", "bold"))
    for e in errors:
        print(color("  ✗ " + e, "red"))
    for w in warns:
        print(color("  ! " + w, "yellow"))
    if not errors and not warns:
        print(color("  ✓ 全部通过", "green"))
    else:
        print(color(f"\n  错误 {len(errors)} · 警告 {len(warns)}", "grey"))
    return 1 if errors else 0


# ═══════════════════════════ 画像 ═══════════════════════════

def cmd_profile(args):
    require_init()
    p = PRIV / "profile" / "profile.md"
    if not p.exists():
        die("画像不存在，请先跑 assis init")
    text = p.read_text(encoding="utf-8")
    if args.append:
        stamp = today().isoformat()
        if "## 近期观察" in text:
            text = text.replace("## 近期观察\n", f"## 近期观察\n- {stamp} {args.append}\n", 1)
        else:
            text = text.rstrip() + f"\n\n## 近期观察\n- {stamp} {args.append}\n"
        p.write_text(text, encoding="utf-8")
        print(color("✓ 已追加到画像「近期观察」", "green"))
        return
    if args.json:
        print(json.dumps({"path": str(p.relative_to(ROOT)), "content": text},
                         ensure_ascii=False, indent=2))
        return
    print(text)
