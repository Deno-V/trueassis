from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .report import generate_report
from .service import create_idea, create_task, query, update
from .storage import CATEGORIES, ensure_private


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--category", required=True, choices=CATEGORIES)
    parser.add_argument("--tags", help="逗号分隔的自由标签")
    parser.add_argument("--note", help="说明")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="assis", description="人类可读的私人任务秘书")
    sub = parser.add_subparsers(dest="command", required=True)

    task = sub.add_parser("task", help="创建一次性或循环任务")
    task.add_argument("title")
    add_common(task)
    task.add_argument("--due", help="一次性任务日期；循环任务未给 start 时也可作开始日期")
    task.add_argument("--repeat", choices=["daily", "weekly", "monthly"])
    task.add_argument("--interval", type=int, default=1)
    task.add_argument("--on", help="weekly 的星期，如 mon,wed,fri")
    task.add_argument("--month-days", help="monthly 的日期，如 1,15")
    task.add_argument("--start")
    task.add_argument("--until")
    task.add_argument("--overdue-policy", choices=["carry", "skip"])
    task.set_defaults(handler=create_task)

    idea = sub.add_parser("idea", help="记录一个不承诺执行的想法")
    idea.add_argument("title")
    add_common(idea)
    idea.set_defaults(handler=create_idea)

    find = sub.add_parser("query", help="唯一查询入口")
    find.add_argument("--from", dest="from_", help="计划或活动起始日期")
    find.add_argument("--to", help="计划或活动结束日期")
    find.add_argument("--kind", choices=["all", "task", "idea"], default="all")
    find.add_argument("--status", choices=["all", "pending", "open", "done", "cancelled", "missed", "archived"], default="pending")
    find.add_argument("--category", choices=CATEGORIES)
    find.add_argument("--tag")
    find.add_argument("--text")
    find.add_argument("--id")
    find.add_argument("--include-overdue", action=argparse.BooleanOptionalAction, default=True,
                      help="是否带出区间之前仍欠着的逾期任务，默认带出")
    find.add_argument("--include-undated", action=argparse.BooleanOptionalAction, default=True,
                      help="是否带出没有日期的开放任务，默认带出")
    find.add_argument("--overdue-days", type=int, default=365, help="循环 carry 最多向前追溯天数，默认一年")
    find.set_defaults(handler=query)

    change = sub.add_parser("update", help="修改任务、想法或某次循环")
    change.add_argument("id", help="完整 ID；写操作不接受模糊匹配")
    change.add_argument("--action", required=True,
                        choices=["complete", "cancel", "reopen", "reschedule", "edit", "edit-schedule", "cancel-series", "archive", "restore"])
    change.add_argument("--occurrence", help="循环任务的原始发生日期")
    change.add_argument("--to", help="改期后的日期")
    change.add_argument("--on-date", help="这件事实际发生的那一天，用于事后补记")
    change.add_argument("--reason")
    change.add_argument("--note", help="补充说明；对任务是追加一条带日期的补充")
    change.add_argument("--replace-note", help="改写说明正文，而不是追加")
    change.add_argument("--title")
    change.add_argument("--category", choices=CATEGORIES)
    change.add_argument("--tags", help="整组替换标签")
    change.add_argument("--add-tags", help="追加标签，保留已有标签")
    change.add_argument("--effective-from")
    change.add_argument("--repeat", choices=["daily", "weekly", "monthly"])
    change.add_argument("--interval", type=int, default=1)
    change.add_argument("--on")
    change.add_argument("--month-days")
    change.add_argument("--until")
    change.set_defaults(handler=update)

    report = sub.add_parser("report", help="生成日报或周报")
    report.add_argument("period", choices=["daily", "weekly"])
    report.add_argument("--date")
    report.add_argument("--summary")
    report.add_argument("--reflection")
    report.add_argument("--extra", action="append", help="自由补充内容，可重复提供")
    report.set_defaults(handler=generate_report)
    return parser


def main(argv: Any = None) -> int:
    ensure_private()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        emit(args.handler(args))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        emit({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
