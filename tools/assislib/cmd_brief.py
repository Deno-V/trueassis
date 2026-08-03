# -*- coding: utf-8 -*-
"""秘书大脑：brief（简报）与 next（现在能做什么）。"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .const import (DOMAIN_CN, ENERGY_RANK, MAX_SUGGEST, PRIORITIES, PRIV,
                    SOMEDAY_REVIEW_DAYS, SOON_DAYS, STALE_DAYS, color,
                    require_init)
from .const import WEEKDAY_CN
from .store import Item, all_items, sort_key, urgency_key
from .yamlite import fmt_minutes, iso_week, today


def _buckets() -> Dict[str, List[Item]]:
    items = all_items()
    open_items = [i for i in items if i.is_open()]
    actionable = [i for i in open_items if i.actionable()]

    overdue, due_today, soon = [], [], []
    for it in actionable:
        u = it.urgency()
        if u == 0:
            overdue.append(it)
        elif u == 1:
            due_today.append(it)
        elif u == 2:
            soon.append(it)

    stale = [i for i in actionable
             if i.urgency() == 3 and i.stale_days() >= STALE_DAYS]
    blocked = [i for i in open_items if i.status == "blocked"]
    deferred = [i for i in open_items if i.is_deferred()]
    inbox = [i for i in actionable if i.status == "inbox"]
    projects = [i for i in open_items if i.kind == "project"]
    someday = [i for i in items if "someday" in str(i.path) and i.is_open()]
    no_ddl = [i for i in actionable if i.due is None]

    for lst in (overdue, due_today, soon, stale, blocked, deferred, inbox, projects, someday, no_ddl):
        lst.sort(key=sort_key)
    return {
        "overdue": overdue, "today": due_today, "soon": soon, "stale": stale,
        "blocked": blocked, "deferred": deferred, "inbox": inbox,
        "projects": projects, "someday": someday, "no_ddl": no_ddl,
        "actionable": sorted(actionable, key=urgency_key),
        "open": open_items,
    }


def score(it: Item) -> float:
    """建议排序分：越大越该现在做。"""
    s = 0.0
    s += {0: 100, 1: 80, 2: 45, 3: 10}[it.urgency()]
    s += {"P0": 40, "P1": 25, "P2": 10, "P3": 0}.get(it.priority, 5)
    if it.status == "active":
        s += 12          # 已经在做的，优先收尾
    if it.project:
        s += 5           # 推进项目比孤立杂事有杠杆
    if it.stale_days() >= STALE_DAYS:
        s += 8           # 快腐烂了，扶一把
    m = it.minutes
    if m and m <= 30:
        s += 6           # 短任务容易起步
    return s


def _reason(it: Item) -> str:
    bits = []
    dl = it.days_left()
    if dl is not None:
        bits.append("已逾期 %d 天" % -dl if dl < 0 else
                    "今天到期" if dl == 0 else f"还剩 {dl} 天")
    bits.append(f"{it.priority}")
    if it.minutes:
        bits.append(f"约 {fmt_minutes(it.minutes)}")
    if it.status == "active":
        bits.append("已在进行，宜收尾")
    elif it.stale_days() >= STALE_DAYS:
        bits.append(f"已停滞 {it.stale_days()} 天")
    if it.project:
        bits.append(f"推进项目 {it.project}")
    return "，".join(bits)


def cmd_brief(args):
    require_init()
    b = _buckets()

    if args.json:
        out = {k: [i.to_dict() for i in v] for k, v in b.items()
               if k not in ("actionable", "open")}
        out["suggestions"] = [i.to_dict() for i in
                              sorted(b["actionable"], key=score, reverse=True)[:MAX_SUGGEST]]
        out["stats"] = {"open": len(b["open"]), "actionable": len(b["actionable"]),
                        "overdue": len(b["overdue"]), "today": len(b["today"])}
        out["date"] = today().isoformat()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    d = today()
    print(color(f"╭─ 秘书简报  {d.isoformat()}  {iso_week(d)}  {WEEKDAY_CN[d.weekday()]}", "bold"))
    print(color(f"│  进行中 {len(b['open'])} 项 · 可执行 {len(b['actionable'])} 项", "grey"))
    print(color("╰" + "─" * 58, "grey"))

    def section(title: str, items: List[Item], col: str, limit: int = 8, hint: str = ""):
        if not items:
            return
        print("\n" + color(title, col) + color(f"  ({len(items)})", "grey"))
        for it in items[:limit]:
            print("  " + it.line())
        if len(items) > limit:
            print(color(f"  … 另有 {len(items) - limit} 项，用 assis list 查看", "grey"))
        if hint:
            print(color(f"  ▸ {hint}", "grey"))

    section("⚠️  逾期", b["overdue"], "red", hint="要么今天做掉，要么 assis defer 改期，要么 assis cancel --reason")
    section("📅 今天到期", b["today"], "red")
    section(f"⏰ {SOON_DAYS} 天内 / 提醒窗口", b["soon"], "yellow")
    section("⛔ 阻塞中", b["blocked"], "yellow", hint="检查依赖是否已解除")
    section("📥 待澄清 inbox", b["inbox"], "cyan", hint="补 due / priority 后进入队列")
    section("🌾 停滞（超 %d 天未动）" % STALE_DAYS, b["stale"], "grey",
            limit=5, hint="推进一步 / 降级 someday / 直接取消")

    sug = sorted(b["actionable"], key=score, reverse=True)[:MAX_SUGGEST]
    if sug:
        print("\n" + color("▶️  建议现在做", "green"))
        for i, it in enumerate(sug, 1):
            print(f"  {i}. {color(it.title, 'bold')}")
            print(color(f"     {_reason(it)}  · {it.id}", "grey"))

    grow = [i for i in b["stale"] if i not in sug] or b["someday"][:1]
    if grow:
        it = grow[0]
        print("\n" + color("🌱 顺手推进", "cyan"))
        print(f"  {it.title}  " + color(f"({it.domain} · {it.due_text()} · {it.id})", "grey"))

    tips = []
    if b["projects"]:
        empty = [p for p in b["projects"]
                 if not any(x.project == p.id for x in b["actionable"])]
        if empty:
            tips.append(f"{len(empty)} 个项目没有可执行的下一步：" +
                        "、".join(p.title for p in empty[:3]))
    if len(b["no_ddl"]) >= 5:
        tips.append(f"{len(b['no_ddl'])} 项没有 ddl，建议给关键项定日期或降级 someday")
    old_someday = [i for i in b["someday"] if i.stale_days() >= SOMEDAY_REVIEW_DAYS]
    if old_someday:
        tips.append(f"愿望池有 {len(old_someday)} 项超 {SOMEDAY_REVIEW_DAYS} 天未复盘")
    if not (PRIV / "journal" / "daily" / f"{d.isoformat()}.md").exists():
        tips.append("今天还没写日报：assis journal daily")
    if d.weekday() == 6:
        tips.append("今天周日 —— 建议做周复盘：assis journal weekly")
    if tips:
        print("\n" + color("💡 提醒", "blue"))
        for t in tips[:4]:
            print(f"  · {t}")

    if not b["overdue"] and not b["today"] and not sug:
        print("\n" + color("🎉 没有紧急事项。可以看看 someday 里想做的事，或者休息。", "green"))
    print()


def cmd_next(args):
    """在给定能量/时间/场景约束下，现在能做什么。"""
    require_init()
    pool = [i for i in all_items() if i.actionable()]

    if args.energy:
        cap = ENERGY_RANK[args.energy]
        pool = [i for i in pool if ENERGY_RANK.get(i.energy, 1) <= cap]
    if args.time:
        pool = [i for i in pool if (i.minutes or 30) <= args.time]
    if args.context:
        pool = [i for i in pool
                if not i.contexts or args.context in i.contexts or "anywhere" in i.contexts]
    if args.domain:
        pool = [i for i in pool if i.domain == args.domain]

    pool = sorted(pool, key=score, reverse=True)[: args.limit]

    if args.json:
        print(json.dumps([i.to_dict() for i in pool], ensure_ascii=False, indent=2))
        return
    if not pool:
        print(color("在这些约束下没有合适的任务。放宽条件，或去 someday 里挑一件想做的事。", "grey"))
        return

    cond = []
    if args.energy:
        cond.append(f"精力 ≤ {args.energy}")
    if args.time:
        cond.append(f"≤ {args.time} 分钟")
    if args.context:
        cond.append(f"@{args.context}")
    print(color("现在可以做（" + ("；".join(cond) or "无约束") + "）", "bold"))
    for i, it in enumerate(pool, 1):
        print(f"\n  {i}. {color(it.title, 'green')}   "
              + color(f"[{DOMAIN_CN.get(it.domain, it.domain)}]", "grey"))
        print(color(f"     {_reason(it)}", "grey"))
        print(color(f"     开始：./tools/assis start {it.id}", "grey"))
    print()
