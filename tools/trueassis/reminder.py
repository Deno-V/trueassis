from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .storage import PRIVATE

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def query_upcoming() -> Dict[str, Any]:
    command = [
        sys.executable, str(PROJECT_ROOT / "tools" / "assis"), "query",
        "--from", "today", "--to", "+3d", "--status", "pending",
    ]
    result = subprocess.run(command, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "query 执行失败")
    payload = json.loads(result.stdout)
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "query 返回失败")
    return payload["data"]


def build_message(data: Dict[str, Any]) -> Tuple[str, str, int]:
    overdue = data.get("overdue", [])
    scheduled = data.get("scheduled", [])
    undated = data.get("undated", [])
    missed = data.get("missed", [])
    total = len(overdue) + len(scheduled) + len(undated)
    title = f"trueassis：未来 3 天有 {total} 项待办"
    summary = f"逾期 {len(overdue)} · 未来三天 {len(scheduled)} · 无日期 {len(undated)}"
    lines: List[str] = [summary]
    rows = (
        [("逾期", row) for row in overdue]
        + [(row.get("scheduled_date") or "计划", row) for row in scheduled]
        + [("无日期", row) for row in undated]
    )
    for label, row in rows[:4]:
        lines.append(f"[{label}] {row.get('title', '未命名任务')}")
    if len(rows) > 4:
        lines.append(f"另有 {len(rows) - 4} 项，打开 trueassis 查看")
    if missed:
        lines.append(f"另有 {len(missed)} 次已错过，不用补做")
    return title, "\n".join(lines), total


def notify(title: str, body: str) -> None:
    if sys.platform == "darwin":
        script = [
            "on run argv",
            "display notification (item 2 of argv) with title (item 1 of argv)",
            "end run",
        ]
        command = ["osascript"]
        for line in script:
            command.extend(["-e", line])
        subprocess.run(command + [title, body], check=True, timeout=20)
        return
    if os.name == "nt":
        env = os.environ.copy()
        env["TRUEASSIS_NOTIFY_TITLE"] = title
        env["TRUEASSIS_NOTIFY_BODY"] = body
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$n=New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon=[System.Drawing.SystemIcons]::Information;"
            "$n.BalloonTipTitle=$env:TRUEASSIS_NOTIFY_TITLE;"
            "$n.BalloonTipText=$env:TRUEASSIS_NOTIFY_BODY;"
            "$n.Visible=$true;$n.ShowBalloonTip(10000);Start-Sleep -Seconds 11;$n.Dispose()"
        )
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                       check=True, timeout=30, env=env)
        return
    notifier = shutil.which("notify-send")
    if notifier:
        subprocess.run([notifier, title, body], check=True, timeout=20)
        return
    raise RuntimeError("当前系统没有可用的桌面通知工具（Linux 需要 notify-send）")


def append_error(message: str) -> None:
    PRIVATE.mkdir(parents=True, exist_ok=True)
    path = PRIVATE / "reminder-error.log"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {message}\n")


def main(argv: Any = None) -> int:
    parser = argparse.ArgumentParser(description="查询未来三天待办并发送系统通知")
    parser.add_argument("--dry-run", action="store_true", help="仅输出通知内容")
    parser.add_argument("--test", action="store_true", help="发送一条测试通知")
    args = parser.parse_args(argv)
    try:
        if args.test:
            title, body, total = "trueassis 提醒测试", "系统通知已安装成功。", 1
        else:
            title, body, total = build_message(query_upcoming())
            if total == 0:
                if args.dry_run:
                    print(json.dumps({"ok": True, "total": 0, "message": "未来三天没有待办"}, ensure_ascii=False))
                return 0
        if args.dry_run:
            print(json.dumps({"ok": True, "total": total, "title": title, "body": body}, ensure_ascii=False, indent=2))
        else:
            notify(title, body)
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        append_error(str(exc))
        print(f"trueassis reminder: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
