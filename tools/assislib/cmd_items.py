# -*- coding: utf-8 -*-
"""条目类命令：init / add / list / show / edit / done / cancel / defer / start / block。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .const import (CONTEXTS, DIRS, DOMAINS, ENERGIES, KINDS, PRIORITIES, PRIV,
                    ROOT, STATUSES, TPL, color, die, require_init)
from .store import (Item, all_items, find_one, read_state, sort_key,
                    validate_choice, validate_contexts, write_state)
from .yamlite import (ds, dump_front_matter, parse_date, parse_front_matter,
                      slugify, today)

# ────────────────────────────── init ──────────────────────────────

PRIVATE_README = """# private —— 个人数据区（不进公共远端）

本目录已被根 `.gitignore` 忽略。这里是你真实的任务、日志、画像与归档。

- 备份方案见 `docs/sync.md`（推荐：给 private/ 挂一个独立的私有 git 仓库）。
- 不要手动删除任何文件；完成/取消请用 `assis done` / `assis cancel`，会自动归档。
"""


def cmd_init(args):
    for d in DIRS:
        (PRIV / d).mkdir(parents=True, exist_ok=True)
    for dom in DOMAINS:
        (PRIV / "logs" / dom).mkdir(parents=True, exist_ok=True)

    prof = PRIV / "profile" / "profile.md"
    if not prof.exists():
        src = TPL / "profile.md"
        prof.write_text(src.read_text(encoding="utf-8") if src.exists() else "# 用户画像\n",
                        encoding="utf-8")
    readme = PRIV / "README.md"
    if not readme.exists():
        readme.write_text(PRIVATE_README, encoding="utf-8")
    st = read_state()
    st.setdefault("version", 1)
    st.setdefault("recur_last_run", "")
    write_state(st)

    print(color("✓ private/ 已就绪", "green"))
    print(f"  画像: {prof.relative_to(ROOT)}")
    print("  下一步: ./tools/assis add \"我的第一件事\" --domain work --due +3d")


# ────────────────────────────── add ──────────────────────────────

def _template_body(kind: str, title: str) -> str:
    for name in (kind, "task"):
        p = TPL / f"{name}.md"
        if p.exists():
            _, body = parse_front_matter(p.read_text(encoding="utf-8"))
            if body.strip():
                return body.replace("{{title}}", title)
    return "## 目标\n\n## 下一步动作\n- [ ] \n\n## 记录\n"


def _split(csv: str) -> List[str]:
    return [x.strip() for x in (csv or "").split(",") if x.strip()]


def cmd_add(args):
    require_init()
    validate_choice(args.kind, KINDS, "kind")
    validate_choice(args.domain, DOMAINS, "domain")
    validate_choice(args.priority, PRIORITIES, "priority")
    if args.energy:
        validate_choice(args.energy, ENERGIES, "energy")
    ctxs = _split(args.context)
    validate_contexts(ctxs)

    kind = args.kind
    if kind == "project":
        target = PRIV / "projects"
    elif kind == "recurring":
        target = PRIV / "recurring"
    elif kind == "idea" or args.someday:
        target = PRIV / "tasks" / "someday"
    else:
        target = PRIV / "tasks" / "active"

    base = f"{today().strftime('%Y%m%d')}-{args.slug or slugify(args.title)}"
    path = target / f"{base}.md"
    n = 2
    while path.exists():
        path = target / f"{base}-{n}.md"
        n += 1

    status = args.status or ("inbox" if kind == "idea" else "next")
    validate_choice(status, STATUSES, "status")

    meta: Dict[str, Any] = {
        "id": path.stem,
        "title": args.title,
        "kind": kind,
        "status": status,
        "domain": args.domain,
        "priority": args.priority,
        "due": ds(parse_date(args.due)),
        "defer": ds(parse_date(args.defer)),
        "estimate": args.estimate or "",
        "energy": args.energy or "mid",
        "context": ctxs,
        "tags": _split(args.tags),
        "project": args.project or "",
        "remind_before": _split(args.remind),
        "created": ds(today()),
        "updated": ds(today()),
    }
    if kind == "recurring":
        meta["rule"] = args.rule or "weekly:mon"
        meta["last_run"] = ""

    it = Item(path, meta, _template_body(kind, args.title))
    it.log(args.note or "创建")
    it.save()

    print(color(f"✓ 已创建 {it.id}", "green") + f"  → {path.relative_to(ROOT)}")
    if kind == "task" and not meta["due"] and not args.someday:
        print(color("  提示: 无 ddl。若只是想法，建议 --someday 放入愿望池，避免 active 噪音", "grey"))


# ────────────────────────────── list / show ──────────────────────────────

def filter_items(args) -> List[Item]:
    g = lambda k, d=None: getattr(args, k, d)
    items = all_items(include_archive=bool(g("archive")))
    out = []
    for it in items:
        if g("status") and it.status != args.status:
            continue
        if not g("status") and not g("all") and not g("archive") and not it.is_open():
            continue
        if g("domain") and it.domain != args.domain:
            continue
        if g("kind") and it.kind != args.kind:
            continue
        if g("priority") and it.priority != args.priority:
            continue
        if g("project") and it.project != args.project:
            continue
        if g("tag") and args.tag not in it.tags:
            continue
        if g("due_in") is not None:
            dl = it.days_left()
            if dl is None or dl > args.due_in:
                continue
        if g("grep") and args.grep.lower() not in (it.title + it.body).lower():
            continue
        out.append(it)
    return sorted(out, key=sort_key)


def cmd_list(args):
    require_init()
    items = filter_items(args)
    if args.json:
        print(json.dumps([i.to_dict() for i in items], ensure_ascii=False, indent=2))
        return
    if not items:
        print(color("（无匹配条目）", "grey"))
        return
    for it in items:
        print(f"{it.status:<9} {it.line()}")
    print(color(f"\n共 {len(items)} 条", "grey"))


def cmd_show(args):
    require_init()
    it = find_one(args.id)
    if args.json:
        print(json.dumps(it.to_dict(with_body=True), ensure_ascii=False, indent=2))
        return
    print(color(f"── {it.path.relative_to(ROOT)} ──", "cyan"))
    print(dump_front_matter(it.meta, it.body))


# ────────────────────────────── edit ──────────────────────────────

SETTABLE = {
    "title", "status", "domain", "priority", "due", "defer", "estimate",
    "energy", "context", "tags", "project", "rule", "remind_before",
    "reason", "blocked_by",
}
DATE_FIELDS = {"due", "defer"}
LIST_FIELDS = {"context", "tags", "remind_before"}
ENUM_FIELDS = {
    "status": STATUSES, "domain": DOMAINS, "priority": PRIORITIES,
    "energy": ENERGIES, "kind": KINDS,
}


def apply_sets(it: Item, pairs: List[str]):
    for pair in pairs:
        if "=" not in pair:
            die(f"--set 需要 key=value 形式: {pair}")
        k, v = pair.split("=", 1)
        k, v = k.strip(), v.strip()
        if k == "id":
            die("id 不可修改（它是文件名与全局引用）")
        if k not in SETTABLE:
            die(f"字段 {k} 不可通过 --set 修改（可改: {', '.join(sorted(SETTABLE))}）")
        if k in ENUM_FIELDS:
            validate_choice(v, ENUM_FIELDS[k], k)
        if k in DATE_FIELDS:
            it.meta[k] = ds(parse_date(v)) if v else ""
        elif k in LIST_FIELDS:
            vals = _split(v)
            if k == "context":
                validate_contexts(vals)
            it.meta[k] = vals
        else:
            it.meta[k] = v


def _relocate(it: Item) -> Item:
    """按 status/kind 把文件挪到正确目录（someday 降级、恢复等）。"""
    if it.kind == "recurring":
        want = PRIV / "recurring"
    elif it.kind == "project":
        want = PRIV / "projects"
    elif it.kind == "idea":
        want = PRIV / "tasks" / "someday"
    else:
        want = PRIV / "tasks" / "active"
    if it.path.parent.resolve() == want.resolve() or "archive" in str(it.path):
        return it
    want.mkdir(parents=True, exist_ok=True)
    new = want / it.path.name
    old = it.path
    it.path = new
    it.save()
    try:
        old.unlink()
    except OSError:
        pass
    print(color(f"  ↪ 已移动到 {new.parent.relative_to(ROOT)}/", "grey"))
    return it


def cmd_edit(args):
    require_init()
    it = find_one(args.id, include_archive=False)
    before = {k: it.meta.get(k) for k in SETTABLE if k in it.meta}
    apply_sets(it, args.set or [])
    if args.kind:
        validate_choice(args.kind, KINDS, "kind")
        it.meta["kind"] = args.kind
    changed = [k for k in set(list(before) + list(it.meta))
               if k in SETTABLE and before.get(k) != it.meta.get(k)]
    if not changed and not args.note:
        print(color("（无变更）", "grey"))
        return
    it.touch()
    if changed:
        it.log("更新 " + "；".join(f"{k}→{it.meta.get(k)}" for k in sorted(changed)))
    if args.note:
        it.log(args.note)
    it.save()
    _relocate(it)
    print(color(f"✓ {it.id} 已更新", "green") + (f"  ({', '.join(sorted(changed))})" if changed else ""))


# ────────────────────────────── 状态流转 ──────────────────────────────

def cmd_start(args):
    require_init()
    it = find_one(args.id, include_archive=False)
    it.meta["status"] = "active"
    it.touch()
    it.log("开始处理" + (f"：{args.note}" if args.note else ""))
    it.save()
    print(color(f"▶ {it.id} → active", "green") + f"  {it.title}")


def cmd_done(args):
    require_init()
    it = find_one(args.id, include_archive=False)
    if it.status == "done":
        print(color("已经是 done 状态", "grey"))
        return
    it.meta["status"] = "done"
    it.touch()
    it.log("完成" + (f"：{args.note}" if args.note else ""))
    it.save()
    print(color(f"✓ 完成 {it.id}", "green") + f"  {it.title}")
    if it.project:
        print(color(f"  所属项目 {it.project} —— 记得检查是否还有下一步", "grey"))
    print(color("  运行 ./tools/assis archive 可归档已完成项", "grey"))


def cmd_cancel(args):
    require_init()
    it = find_one(args.id, include_archive=False)
    it.meta["status"] = "cancelled"
    it.meta["reason"] = args.reason
    it.touch()
    it.log(f"取消：{args.reason}")
    it.save()
    print(color(f"✗ 已取消 {it.id}", "yellow") + f"  {it.title}")
    print(color("  取消是健康的：理由已记录，可用于画像学习", "grey"))


def cmd_defer(args):
    require_init()
    it = find_one(args.id, include_archive=False)
    d = parse_date(args.to)
    if args.due:
        it.meta["due"] = ds(parse_date(args.due))
    it.meta["defer"] = ds(d)
    it.touch()
    it.log(f"推迟到 {ds(d)}" + (f"：{args.note}" if args.note else ""))
    it.save()
    print(color(f"⏳ {it.id} 推迟至 {ds(d)}", "cyan"))


def cmd_block(args):
    require_init()
    it = find_one(args.id, include_archive=False)
    it.meta["status"] = "blocked"
    it.meta["blocked_by"] = args.by
    it.touch()
    it.log(f"阻塞于：{args.by}")
    it.save()
    print(color(f"⛔ {it.id} → blocked ({args.by})", "yellow"))


def cmd_someday(args):
    """把条目降级到愿望池。"""
    require_init()
    it = find_one(args.id, include_archive=False)
    it.meta["kind"] = "idea"
    it.meta["status"] = "inbox"
    it.meta["due"] = ""
    it.touch()
    it.log("降级到 someday 愿望池" + (f"：{args.note}" if args.note else ""))
    it.save()
    _relocate(it)
    print(color(f"🌱 {it.id} 已移入 someday", "cyan"))
