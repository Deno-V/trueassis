# -*- coding: utf-8 -*-
"""context —— 把仓库现状摊开给 Agent，供它自己做意图理解。

═══ 设计铁律（改动前必读）═══

    工具不理解语义。工具只回答"现在有什么、在哪个文件里"。

用户说的话是无穷的：
    "我提交了 eval 分支" / "今天称了 77.2" / "读到第 120 页" /
    "喝了 8 杯水" / "背了 50 个单词" / "浇了花" / "妈生日礼物买好了"

任何试图在工具里枚举这些的做法（关键词词典、数值正则、领域规则表）
都必然失败——领域是列举不完的。这类代码只会得到一个又脆弱又永远不全的假智能。

正确的分工：
    工具（本模块）    → 列出结构：有哪些领域、哪些未完成项、规则是什么、文件在哪
    Agent（Codex 等）→ 读这些结构 + 必要时读文件原文 → 理解意图 → 调用写原语

所以本模块：
    ✅ 列条目、列规则、列文件路径、给出原始文本行
    ❌ 不做分词、不做关键词匹配、不做数值提取、不做任何"这句话是什么意思"的判断

Agent 需要更多信息时，`paths` 字段告诉它该读哪个文件——它有读文件的能力，
让它自己读，比在这里预解析成结构化字段更灵活，也永远不会过时。
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .const import DOMAIN_CN, DOMAINS, PRIV, ROOT, color, require_init
from .store import Item, all_items
from .yamlite import to_date, today


def _item_view(it: Item) -> Dict[str, Any]:
    """条目的结构化视图。不解释内容，只给字段 + 文件路径。"""
    v: Dict[str, Any] = {
        "id": it.id,
        "title": it.title,
        "kind": it.kind,
        "status": it.status,
        "domain": it.domain,
        "priority": it.priority,
        "due": it.due.isoformat() if it.due else None,
        "days_left": it.days_left(),
        "estimate": str(it.meta.get("estimate") or ""),
        "energy": it.energy,
        "context": it.contexts,
        "tags": it.tags,
        "project": it.project,
        "updated": it.updated.isoformat() if it.updated else None,
        "stale_days": it.stale_days(),
        "path": str(it.path.relative_to(ROOT)),
    }
    if it.kind == "recurring":
        v["rule"] = str(it.meta.get("rule") or "")
        v["last_run"] = str(it.meta.get("last_run") or "")
    if it.meta.get("source"):
        v["from_recurring"] = str(it.meta["source"])
    if it.meta.get("blocked_by"):
        v["blocked_by"] = str(it.meta["blocked_by"])
    # 未勾选的 checkbox：这是条目自己声明的"下一步"，原文照给
    v["unchecked"] = [
        re.sub(r"^\s*-\s*\[ \]\s*", "", l).strip()
        for l in it.body.splitlines()
        if re.match(r"^\s*-\s*\[ \]", l)
        and re.sub(r"^\s*-\s*\[ \]\s*", "", l).strip()
    ]
    return v


def _log_lines(domain: Optional[str], days: int) -> List[Dict[str, Any]]:
    """近期日志原始行。原文照给，不做任何解析。"""
    cutoff = today() - timedelta(days=days)
    out: List[Dict[str, Any]] = []
    root = PRIV / "logs"
    if not root.exists():
        return out
    scopes = [root / domain] if domain else [root]
    for scope in scopes:
        if not scope.exists():
            continue
        for f in sorted(scope.rglob("*.md")):
            dom = f.parent.name
            cur: Optional[date] = None
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                m = re.match(r"^##\s+(\d{4}-\d{2}-\d{2})", line)
                if m:
                    cur = to_date(m.group(1))
                    continue
                if not line.strip().startswith("- ") or not cur or cur < cutoff:
                    continue
                out.append({
                    "date": cur.isoformat(), "domain": dom,
                    "text": line.strip()[2:],
                    "path": str(f.relative_to(ROOT)), "line": n,
                })
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def _log_index() -> Dict[str, List[str]]:
    """各领域已有哪些日志文件——Agent 决定往哪写、从哪读的依据。"""
    idx: Dict[str, List[str]] = {}
    root = PRIV / "logs"
    if not root.exists():
        return idx
    for dom_dir in sorted(root.iterdir()):
        if not dom_dir.is_dir():
            continue
        files = sorted(str(f.relative_to(ROOT)) for f in dom_dir.glob("*.md"))
        if files:
            idx[dom_dir.name] = files
    return idx


def cmd_context(args):
    """摊开现状。Agent 拿到后自己判断意图，再调用写原语。

    典型流程（Agent 内部，与领域无关）：
        用户: "我提交了 eval 分支"
          1. assis context --query eval --json
          2. 在 open_items 里看到 "测试仓库推 eval 分支" (id: ...-push-eval-branch)
          3. 自行判断这是完成事件 → assis done <id> --note "已提交"

        用户: "今天称了 77.2"
          1. assis context --domain health --json     （或不带 domain 先看全局）
          2. 看到 recurring 定义"称重并记录"、今天到期的实例、项目"减重到 72kg"
          3. 自行判断 → assis log health "77.2" + assis done <称重实例 id>

        用户: "读到第 120 页了"
          1. assis context --query 读 --json
          2. 看到 learning 领域有任务"读完 DDIP"，其 path 指向具体文件
          3. 需要细节就直接读那个文件 → 更新进度 → assis edit / log

    工具在这三个例子里做的事完全相同：列出现状。差异全在 Agent 的判断里。
    """
    require_init()
    dom = args.domain
    items = all_items(include_archive=False)
    if dom:
        items = [i for i in items if i.domain == dom]
    open_items = [i for i in items if i.is_open()]

    payload: Dict[str, Any] = {
        "today": today().isoformat(),
        "weekday": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][today().weekday()],
        "domain_filter": dom or "all",
        "domains": {d: DOMAIN_CN[d] for d in DOMAINS},
        "tasks": [_item_view(i) for i in open_items
                  if i.kind in ("task", "event")],
        "projects": [_item_view(i) for i in open_items if i.kind == "project"],
        "recurring": [_item_view(i) for i in items if i.kind == "recurring"],
        "someday": [_item_view(i) for i in open_items if i.kind == "idea"],
        "recent_logs": _log_lines(dom, args.log_days),
        "log_files": _log_index(),
        "paths": {
            "profile": "private/profile/profile.md",
            "tasks_active": "private/tasks/active/",
            "tasks_someday": "private/tasks/someday/",
            "projects": "private/projects/",
            "recurring": "private/recurring/",
            "logs": "private/logs/<domain>/YYYY-MM.md",
            "journal_daily": "private/journal/daily/YYYY-MM-DD.md",
            "journal_weekly": "private/journal/weekly/YYYY-Www.md",
            "archive": "private/archive/{done,cancelled}/YYYY/MM/",
            "config": "config/config.yml",
        },
        "hint": ("这是结构与路径，不含语义判断。意图理解由你完成："
                 "先在 tasks/projects/recurring 里找用户提到的事；找不到就考虑新建；"
                 "需要细节时直接读 path 指向的文件。"),
    }

    if args.query:
        q = args.query.lower()
        payload["query"] = args.query
        payload["query_hits"] = {
            "note": "纯字面包含匹配，仅用于快速定位；判断是否真的相关由你决定",
            "items": [_item_view(i) for i in items
                      if q in (i.title + " " + i.body).lower()],
            "logs": [r for r in _log_lines(dom, max(args.log_days, 90))
                     if q in r["text"].lower()],
        }

    if args.json or not args.human:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    scope = DOMAIN_CN.get(dom, dom) if dom else "全部领域"
    print(color(f"── {scope} 现状（{payload['today']}）──", "bold"))
    for key, label in (("tasks", "未完成"), ("projects", "项目"),
                       ("recurring", "重复定义"), ("someday", "愿望池")):
        rows = payload[key]
        if not rows:
            continue
        print("\n" + color(label, "cyan") + color(f"  ({len(rows)})", "grey"))
        for r in rows:
            extra = f"  rule={r['rule']}" if r.get("rule") else (
                f"  {r['days_left']}天后" if r.get("days_left") is not None else "")
            print(f"  {r['id'][:32]:<32} {r['priority']}{extra}  {r['title']}")
            print(color(f"    {r['path']}", "grey"))
    if payload["recent_logs"]:
        print("\n" + color(f"最近 {args.log_days} 天日志", "cyan"))
        for r in payload["recent_logs"][:20]:
            print(f"  {r['date']} [{DOMAIN_CN.get(r['domain'], r['domain'])}] {r['text'][:56]}")
    print(color(f"\n  完整结构与文件路径请用 --json 获取", "grey"))
    return 0
