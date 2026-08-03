# -*- coding: utf-8 -*-
"""对话闭环补强：capture（批量收集）、search（全局检索）、wrap（一键收尾）。

这三个命令的存在理由：用户只通过自然语言对话，Agent 必须能
  1. 一次记下"我想到的五件事"          → capture
  2. 回答"我上次骑行是什么时候"        → search（跨任务/日志/日报/归档）
  3. 一句"今天结束了"完成所有收尾动作  → wrap
缺了它们，Agent 就得多轮试错，或者退化成让用户自己看文件。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .const import (DOMAIN_CN, DOMAINS, PRIORITIES, PRIV, ROOT, color, die,
                    require_init)
from .store import Item, all_items
from .yamlite import ds, parse_date, slugify, today

# ═══════════════════════════ capture ═══════════════════════════
# 行内标记语法（让 Agent 一次传多条，不必逐条拼 flag）：
#   @domain   领域        @work
#   !P1       优先级      !P0
#   ~日期     ddl         ~+3d  ~fri  ~2026-08-09
#   *估时     estimate    *2h   *30m
#   #标签     tag         #repo
#   ^场景     context     ^computer
#   ?         标记为想法（进 someday）

TOKEN_RE = re.compile(r"(?:^|\s)([@!~*#^?])([^\s]*)")


def parse_line(line: str, default_domain: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line or line.startswith("#") and " " not in line[:3]:
        return None
    spec: Dict[str, Any] = {
        "domain": default_domain, "priority": "P2", "due": "", "estimate": "",
        "tags": [], "context": [], "idea": False,
    }
    for m in TOKEN_RE.finditer(line):
        sym, val = m.group(1), m.group(2)
        if sym == "@" and val in DOMAINS:
            spec["domain"] = val
        elif sym == "!" and val.upper() in PRIORITIES:
            spec["priority"] = val.upper()
        elif sym == "~" and val:
            d = parse_date(val)
            spec["due"] = ds(d) if d else ""
        elif sym == "*" and val:
            spec["estimate"] = val
        elif sym == "#" and val:
            spec["tags"].append(val)
        elif sym == "^" and val:
            spec["context"].append(val)
        elif sym == "?":
            spec["idea"] = True
    title = TOKEN_RE.sub("", line).strip()
    if not title:
        return None
    spec["title"] = title
    return spec


def cmd_capture(args):
    require_init()
    raw: List[str] = []
    if args.stdin or not args.lines:
        if not sys.stdin.isatty():
            raw = sys.stdin.read().splitlines()
    raw += list(args.lines or [])
    # 支持单参数里塞多行
    lines: List[str] = []
    for r in raw:
        lines += [x for x in re.split(r"[\n;；]", r) if x.strip()]

    specs = [s for s in (parse_line(l, args.domain) for l in lines) if s]
    if not specs:
        die("没有解析到任何条目。示例：\n"
            '  assis capture "处理报销 @life !P2 ~+3d" "读完《XX》 @learning ?"')

    created: List[Item] = []
    for spec in specs:
        is_idea = spec["idea"] or args.someday
        target = PRIV / ("tasks/someday" if is_idea else "tasks/active")
        base = f"{today().strftime('%Y%m%d')}-{slugify(spec['title'])}"
        path = target / f"{base}.md"
        n = 2
        while path.exists():
            path = target / f"{base}-{n}.md"
            n += 1
        meta = {
            "id": path.stem, "title": spec["title"],
            "kind": "idea" if is_idea else "task",
            "status": "inbox",
            "domain": spec["domain"], "priority": spec["priority"],
            "due": spec["due"], "defer": "", "estimate": spec["estimate"],
            "energy": "mid", "context": spec["context"], "tags": spec["tags"],
            "project": "", "remind_before": [],
            "created": ds(today()), "updated": ds(today()),
        }
        it = Item(path, meta, "## 目标\n\n## 下一步动作\n- [ ] \n\n## 记录\n")
        it.log("批量收集")
        it.save()
        created.append(it)

    if args.json:
        print(json.dumps([i.to_dict() for i in created], ensure_ascii=False, indent=2))
        return 0

    print(color(f"✓ 收集 {len(created)} 条（状态均为 inbox，待澄清）", "green"))
    for it in created:
        flag = "🌱" if it.kind == "idea" else "  "
        print(f" {flag} {it.line()}")
    missing = [i for i in created if not i.due and i.kind != "idea"]
    if missing:
        print(color(f"\n  {len(missing)} 条缺 ddl —— 需要定日期的请告诉我，"
                    f"纯想法可以留空或降级 someday", "grey"))
    return 0


# ═══════════════════════════ search ═══════════════════════════

def _grep_file(p: Path, q: str) -> List[Tuple[int, str]]:
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    ql = q.lower()
    return [(i + 1, l.strip()) for i, l in enumerate(lines) if ql in l.lower()]


def cmd_search(args):
    """跨任务/日志/日报/归档的全局检索——回答"我上次 X 是什么时候"。"""
    require_init()
    q = args.query
    res: Dict[str, List[Dict[str, Any]]] = {"items": [], "logs": [], "journal": []}

    for it in all_items(include_archive=True):
        if q.lower() in (it.title + " " + it.body + " " + " ".join(it.tags)).lower():
            res["items"].append({
                "id": it.id, "title": it.title, "status": it.status,
                "domain": it.domain, "due": ds(it.due),
                "updated": ds(it.updated), "path": str(it.path.relative_to(ROOT)),
            })

    for scope, key in ((PRIV / "logs", "logs"), (PRIV / "journal", "journal")):
        if not scope.exists():
            continue
        for p in sorted(scope.rglob("*.md")):
            rel = p.relative_to(scope)          # 相对 scope，第一段才是领域名
            for ln, text in _grep_file(p, q):
                res[key].append({"file": str(p.relative_to(PRIV)),
                                 "scope_rel": str(rel),
                                 "line": ln, "text": text})

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    total = sum(len(v) for v in res.values())
    if not total:
        print(color(f"没有找到与「{q}」相关的记录", "grey"))
        return 0

    print(color(f"「{q}」的检索结果（{total} 条）", "bold"))
    if res["items"]:
        print("\n" + color("📌 事务条目", "cyan"))
        for r in res["items"][: args.limit]:
            mark = "✓" if r["status"] == "done" else ("✗" if r["status"] == "cancelled" else "·")
            print(f"  {mark} {r['title']}  "
                  + color(f"[{r['status']} · {r['domain']} · 更新于 {r['updated']}]", "grey"))
            print(color(f"    {r['id']}", "grey"))
    if res["logs"]:
        print("\n" + color("📖 领域日志", "cyan"))
        for r in res["logs"][: args.limit]:
            dom = str(r.get("scope_rel", "")).replace("\\", "/").split("/")[0]
            print(f"  [{DOMAIN_CN.get(dom, dom)}] {r['text'][:76]}")
            print(color(f"    {r['file']}:{r['line']}", "grey"))
    if res["journal"]:
        print("\n" + color("📓 日报/周报", "cyan"))
        for r in res["journal"][: args.limit]:
            print(f"  {r['text'][:76]}")
            print(color(f"    {r['file']}:{r['line']}", "grey"))
    print()
    return 0


# ═══════════════════════════ wrap ═══════════════════════════

def cmd_wrap(args):
    """一键收尾。用户只需说"今天结束了" / "做周复盘"。"""
    require_init()
    from . import cmd_ops
    from .store import all_items

    class NS:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    if args.period == "daily":
        print(color("── 日终收尾 ──", "bold"))
        print(color("\n[1/4] 生成到期的重复任务", "cyan"))
        cmd_ops.cmd_recur_run(NS(date=None, dry_run=False, json=False))
        print(color("\n[2/4] 生成/刷新日报", "cyan"))
        cmd_ops.cmd_journal(NS(period="daily", date=None, force=False))
        print(color("\n[3/4] 归档已完成/已取消", "cyan"))
        cmd_ops.cmd_archive(NS(dry_run=False, json=False))
        print(color("\n[4/4] 数据体检", "cyan"))
        rc = cmd_ops.cmd_doctor(NS(json=False))

        d = today()
        jp = PRIV / "journal" / "daily" / f"{d.isoformat()}.md"
        print(color("\n── 还需要你回答三个问题（我会写进日报） ──", "yellow"))
        print("  1. 今天最有价值的一件事是什么？")
        print("  2. 什么卡住了你？")
        print("  3. 明天第一件事做什么？")
        print(color(f"\n  日报位置: {jp.relative_to(ROOT)}", "grey"))
        return rc

    print(color("── 周复盘 ──", "bold"))
    print(color("\n[1/3] 生成/刷新周报", "cyan"))
    cmd_ops.cmd_journal(NS(period="weekly", date=None, force=False))
    print(color("\n[2/3] 数据体检", "cyan"))
    cmd_ops.cmd_doctor(NS(json=False))

    print(color("\n[3/3] 待决策清单 —— 每条四选一，不允许「先放着」", "cyan"))
    open_items = [i for i in all_items() if i.is_open() and i.kind != "recurring"]
    stale = [i for i in open_items if i.stale_days() >= 14]
    no_ddl = [i for i in open_items if i.due is None and i.kind == "task"]

    if stale:
        print("\n  " + color(f"停滞项（{len(stale)}）—— 推进 / 降级 / 取消", "yellow"))
        for i in stale[:10]:
            print(f"    · {i.title}  " + color(f"(停滞 {i.stale_days()} 天 · {i.id})", "grey"))
    if no_ddl:
        print("\n  " + color(f"无 ddl 任务（{len(no_ddl)}）—— 定日期 / 降级 someday", "yellow"))
        for i in no_ddl[:10]:
            print(f"    · {i.title}  " + color(f"({i.domain} · {i.id})", "grey"))

    print(color("\n  逐条告诉我怎么处理，我来执行。", "grey"))
    print(color("  另外：这周有什么值得写进画像的观察吗？（节律/偏好/雷区）", "grey"))
    return 0
