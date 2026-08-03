# -*- coding: utf-8 -*-
"""常量、词表与路径。所有取值必须与 config/config.yml 保持一致。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PRIV = ROOT / "private"
TPL = ROOT / "templates"

DIRS = [
    "profile",
    "tasks/active",
    "tasks/someday",
    "projects",
    "recurring",
    "journal/daily",
    "journal/weekly",
    "journal/monthly",
    "logs",
    "archive/done",
    "archive/cancelled",
]

DOMAINS = ["work", "life", "health", "learning", "hobby", "fun", "finance", "relation"]
DOMAIN_CN = {
    "work": "工作", "life": "生活", "health": "健康", "learning": "学习",
    "hobby": "爱好", "fun": "娱乐", "finance": "财务", "relation": "关系",
}
KINDS = ["task", "project", "recurring", "event", "idea"]
STATUSES = ["inbox", "next", "active", "blocked", "done", "cancelled"]
PRIORITIES = ["P0", "P1", "P2", "P3"]
ENERGIES = ["low", "mid", "high"]
ENERGY_RANK = {"low": 0, "mid": 1, "high": 2}
CONTEXTS = ["computer", "phone", "outdoor", "errand", "home", "office", "anywhere"]

OPEN_STATUSES = {"inbox", "next", "active", "blocked"}
CLOSED_STATUSES = {"done", "cancelled"}

SOON_DAYS = 3
STALE_DAYS = 14
SOMEDAY_REVIEW_DAYS = 30
MAX_SUGGEST = 3

WEEKDAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

_C = {
    "red": "\033[31m", "yellow": "\033[33m", "green": "\033[32m",
    "cyan": "\033[36m", "blue": "\033[34m", "grey": "\033[90m",
    "bold": "\033[1m", "off": "\033[0m",
}


def color(s: str, name: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return s
    return f"{_C.get(name, '')}{s}{_C['off']}"


def die(msg: str, code: int = 1):
    print(color(f"错误: {msg}", "red"), file=sys.stderr)
    sys.exit(code)


def require_init():
    if not PRIV.exists():
        die("private/ 未初始化，请先运行: ./tools/assis init")
