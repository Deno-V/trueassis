# -*- coding: utf-8 -*-
"""assis CLI 参数解析与分发。"""
from __future__ import annotations

import argparse
import sys

from .const import CONTEXTS, DOMAINS, ENERGIES, KINDS, PRIORITIES, STATUSES
from . import cmd_brief, cmd_capture, cmd_context, cmd_items, cmd_ops, history

EPILOG = """\
常用流程:
  ./tools/assis brief                      # 早上第一件事：看简报
  ./tools/assis next --energy low --time 30 # 只有 30 分钟且没精神时
  ./tools/assis add "标题" --domain work --due +3d --p P1
  ./tools/assis done <id> --note "产出"
  ./tools/assis journal daily              # 晚上：生成日报
  ./tools/assis doctor                     # 提交前：数据体检

日期支持: 2026-08-07 | today | tomorrow | +3d | +2w | fri
完整协议见仓库 AGENTS.md
"""


def _add_item_flags(p, with_status=True):
    p.add_argument("--domain", default="life", choices=DOMAINS, help="所属领域")
    p.add_argument("--priority", "--p", dest="priority", default="P2",
                   choices=PRIORITIES, help="优先级（默认 P2）")
    p.add_argument("--due", help="截止日期，如 2026-08-07 / +3d / fri")
    p.add_argument("--defer", help="在此日期前不出现在建议中")
    p.add_argument("--estimate", help="预计耗时，如 2h / 45m")
    p.add_argument("--energy", choices=ENERGIES, help="精力需求")
    p.add_argument("--context", help="执行场景，逗号分隔: " + ",".join(CONTEXTS))
    p.add_argument("--tags", help="标签，逗号分隔")
    p.add_argument("--project", help="归属项目 id")
    p.add_argument("--remind", help="提前提醒，如 1d,3d")
    p.add_argument("--note", help="创建时附加一条记录")
    p.add_argument("--slug", help="自定义 id 后缀（默认由标题生成）")
    if with_status:
        p.add_argument("--status", choices=STATUSES, help="初始状态")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="assis", description="trueassis 私人秘书 —— 管理长期/短期/重复事务，主动给建议",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", metavar="<命令>")

    # init
    p = sub.add_parser("init", help="初始化 private/ 个人数据骨架（幂等）")
    p.set_defaults(func=cmd_items.cmd_init)

    # brief
    p = sub.add_parser("brief", help="秘书简报：逾期/今日/临近/停滞 + 行动建议")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_brief.cmd_brief)

    # next
    p = sub.add_parser("next", help="我现在能做什么（按精力/可用时间/场景筛选）")
    p.add_argument("--energy", choices=ENERGIES, help="当前可投入精力上限")
    p.add_argument("--time", type=int, help="可用分钟数")
    p.add_argument("--context", choices=CONTEXTS, help="当前场景")
    p.add_argument("--domain", choices=DOMAINS)
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_brief.cmd_next)

    # add
    p = sub.add_parser("add", help="新增任务/项目/想法")
    p.add_argument("title")
    p.add_argument("--kind", default="task", choices=KINDS)
    p.add_argument("--someday", action="store_true", help="放入愿望池而非 active")
    p.add_argument("--rule", help="仅 kind=recurring：daily|weekday|weekly:mon,fri|monthly:1|every:3d")
    _add_item_flags(p)
    p.set_defaults(func=cmd_items.cmd_add)

    # list
    p = sub.add_parser("list", aliases=["ls"], help="列出条目")
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--domain", choices=DOMAINS)
    p.add_argument("--kind", choices=KINDS)
    p.add_argument("--priority", "--p", dest="priority", choices=PRIORITIES)
    p.add_argument("--project")
    p.add_argument("--tag")
    p.add_argument("--due-in", type=int, dest="due_in", help="N 天内到期")
    p.add_argument("--grep", help="标题/正文关键词")
    p.add_argument("--all", action="store_true", help="含已完成/已取消")
    p.add_argument("--archive", action="store_true", help="含归档目录")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_items.cmd_list)

    # show
    p = sub.add_parser("show", help="查看条目全文（支持 id 前缀）")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_items.cmd_show)

    # edit
    p = sub.add_parser("edit", help="修改字段：--set due=+3d --set priority=P0")
    p.add_argument("id")
    p.add_argument("--set", action="append", metavar="k=v")
    p.add_argument("--kind", choices=KINDS)
    p.add_argument("--note")
    p.set_defaults(func=cmd_items.cmd_edit)

    # 状态流转
    p = sub.add_parser("start", help="标记为进行中")
    p.add_argument("id"); p.add_argument("--note")
    p.set_defaults(func=cmd_items.cmd_start)

    p = sub.add_parser("done", help="完成")
    p.add_argument("id"); p.add_argument("--note", help="产出/结果")
    p.set_defaults(func=cmd_items.cmd_done)

    p = sub.add_parser("cancel", help="取消（必须给理由）")
    p.add_argument("id"); p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_items.cmd_cancel)

    p = sub.add_parser("defer", help="推迟")
    p.add_argument("id")
    p.add_argument("--to", required=True, help="推迟到，如 +3d / 2026-08-10")
    p.add_argument("--due", help="同时改 ddl")
    p.add_argument("--note")
    p.set_defaults(func=cmd_items.cmd_defer)

    p = sub.add_parser("block", help="标记阻塞")
    p.add_argument("id"); p.add_argument("--by", required=True, help="被什么阻塞")
    p.set_defaults(func=cmd_items.cmd_block)

    p = sub.add_parser("someday", help="降级到愿望池")
    p.add_argument("id"); p.add_argument("--note")
    p.set_defaults(func=cmd_items.cmd_someday)

    # recur
    p = sub.add_parser("recur", help="重复任务：add / list / run / pause")
    rsub = p.add_subparsers(dest="sub", metavar="<子命令>")

    q = rsub.add_parser("add", help="新增重复任务定义")
    q.add_argument("title")
    q.add_argument("--rule", required=True,
                   help="daily | weekday | weekly:mon,fri | monthly:1,15 | every:3d")
    _add_item_flags(q)
    q.set_defaults(func=cmd_ops.cmd_recur_add)

    q = rsub.add_parser("list", help="列出重复任务定义")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_ops.cmd_recur_list)

    q = rsub.add_parser("run", help="生成今天到期的重复实例（幂等，可每日跑）")
    q.add_argument("--date", help="模拟某天")
    q.add_argument("--dry-run", action="store_true")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_ops.cmd_recur_run)

    q = rsub.add_parser("pause", help="暂停/恢复某个重复任务")
    q.add_argument("id")
    q.add_argument("--off", action="store_true", default=True, help="暂停（默认）")
    q.add_argument("--on", dest="off", action="store_false", help="恢复")
    q.add_argument("--reason")
    q.set_defaults(func=cmd_ops.cmd_recur_pause)

    # log
    p = sub.add_parser("log", help="记一条领域流水日志")
    p.add_argument("domain", choices=DOMAINS)
    p.add_argument("text")
    p.add_argument("--date")
    p.set_defaults(func=cmd_ops.cmd_log)

    # context —— 摊开现状，供 Agent 自己做意图理解（不含任何语义判断）
    p = sub.add_parser("context",
                       help="摊开现状：未完成项/项目/重复规则/近期日志/文件路径")
    p.add_argument("--domain", choices=DOMAINS, help="只看某个领域")
    p.add_argument("--query", help="字面定位（仅辅助，相关性由你判断）")
    p.add_argument("--log-days", dest="log_days", type=int, default=30,
                   help="附带最近 N 天日志原文（默认 30）")
    p.add_argument("--human", action="store_true", help="人类可读格式（默认 JSON）")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_context.cmd_context)

    # journal
    p = sub.add_parser("journal", help="生成日报/周报/月报（自动汇总完成项与日志）")
    p.add_argument("period", choices=["daily", "weekly", "monthly"])
    p.add_argument("--date", help="默认今天")
    p.add_argument("--force", action="store_true", help="覆盖重建")
    p.set_defaults(func=cmd_ops.cmd_journal)

    # archive
    p = sub.add_parser("archive", help="把 done/cancelled 移入 archive/YYYY/MM")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ops.cmd_archive)

    # doctor
    p = sub.add_parser("doctor", help="数据一致性 + 隐私红线体检（提交前必跑）")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ops.cmd_doctor)

    # profile
    p = sub.add_parser("profile", help="查看/追加用户画像")
    p.add_argument("--append", help="向「近期观察」追加一条带日期的观察")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ops.cmd_profile)

    # ── 安全网：撤销与历史 ──
    p = sub.add_parser("undo", help="撤销上一次写操作（误操作救命命令）")
    p.add_argument("--to", help="撤销到指定检查点序号（见 assis history）")
    p.add_argument("--dry-run", action="store_true", help="只看会回滚什么")
    p.set_defaults(func=history.cmd_undo)

    p = sub.add_parser("history", help="查看最近的写操作与可撤销检查点")
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=history.cmd_history)

    # ── 批量收集：一句话记多件事 ──
    p = sub.add_parser("capture", help="批量收集多条待办（每行一条，原子写入）")
    p.add_argument("lines", nargs="*",
                   help='每条形如 "标题 @work !P1 ~+3d"，或用 --stdin 从管道读')
    p.add_argument("--stdin", action="store_true", help="从标准输入逐行读取")
    p.add_argument("--domain", default="life", choices=DOMAINS, help="默认领域")
    p.add_argument("--someday", action="store_true", help="全部进愿望池")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capture.cmd_capture)

    # ── 全局检索：任务 + 日志 + 日报 一起搜 ──
    p = sub.add_parser("search", help="全局检索：条目 + 日志 + 日报/周报 + 归档")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capture.cmd_search)

    # ── 一键日终 / 周终 ──
    p = sub.add_parser("wrap", help="一键收尾：daily=recur+日报+归档+体检；weekly=周报+复盘清单")
    p.add_argument("period", nargs="?", default="daily", choices=["daily", "weekly"])
    p.set_defaults(func=cmd_capture.cmd_wrap)

    return ap


# 只读命令不做快照；其余写操作在执行前自动建立可撤销检查点
READONLY = {"brief", "next", "list", "ls", "show", "doctor", "history", "search",
            "init", "context"}


def main(argv=None) -> int:
    ap = build_parser()
    argv_list = list(argv if argv is not None else sys.argv[1:])
    args = ap.parse_args(argv_list)
    if not getattr(args, "func", None):
        ap.print_help()
        return 0

    cmd = getattr(args, "cmd", "") or ""
    sub_ = getattr(args, "sub", None)
    op = f"{cmd} {sub_}".strip() if sub_ else cmd

    # profile 不带 --append 时是只读的
    readonly = cmd in READONLY or (cmd == "profile" and not getattr(args, "append", None))
    # undo 自身管理快照；wrap 内部逐步操作各自快照
    if not readonly and cmd not in ("undo",):
        history.snapshot(op, argv_list)

    rc = args.func(args)
    if not readonly:
        history.append_oplog(op, argv_list, "ok" if not rc else f"rc={rc}")
    return int(rc) if isinstance(rc, int) else 0
