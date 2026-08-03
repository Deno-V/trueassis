#!/usr/bin/env bash
# 主动提醒安装脚本（可选）
#
# 用途：把每日简报 / 重复任务生成 / 日报提醒挂到系统 cron。
# 若你的 AI 工具支持定时任务（如 CodeBuddy automation），优先用它 —— 
# 因为 Agent 能读懂 brief 并给出带理由的建议，而 cron 只能跑命令。
#
#   查看将要写入的内容:  bash tools/install-reminders.sh --dry-run
#   安装:                bash tools/install-reminders.sh
#   卸载:                bash tools/install-reminders.sh --uninstall

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$(command -v python3)"
TAG="# trueassis-reminders"
LOG="${TMPDIR:-/tmp}/trueassis.log"

read -r -d '' BLOCK <<EOF || true
$TAG start
# 09:00 生成今天到期的重复任务
0 9 * * * cd "$REPO" && "$PY" tools/assis recur run >> "$LOG" 2>&1
# 09:05 若有逾期/今日到期，弹一条桌面通知（macOS）
5 9 * * * cd "$REPO" && n=\$("$PY" tools/assis brief --json | "$PY" -c 'import json,sys;d=json.load(sys.stdin);print(len(d["overdue"])+len(d["today"]))') && [ "\$n" -gt 0 ] && osascript -e "display notification \"今天有 \$n 项到期待办，去问问秘书\" with title \"trueassis\"" >> "$LOG" 2>&1
# 21:30 生成日报骨架并提醒补写复盘
30 21 * * * cd "$REPO" && "$PY" tools/assis journal daily >> "$LOG" 2>&1 && osascript -e 'display notification "日报已生成，补写三行复盘" with title "trueassis"' >> "$LOG" 2>&1
# 周日 20:00 生成周报，提醒做周复盘
0 20 * * 0 cd "$REPO" && "$PY" tools/assis journal weekly >> "$LOG" 2>&1 && osascript -e 'display notification "周报已生成，该做周复盘了" with title "trueassis"' >> "$LOG" 2>&1
$TAG end
EOF

strip_existing() {
  crontab -l 2>/dev/null | sed "/$TAG start/,/$TAG end/d" || true
}

case "${1:-install}" in
  --dry-run)
    echo "将写入以下 cron 条目："; echo; echo "$BLOCK"
    ;;
  --uninstall)
    strip_existing | crontab -
    echo "✓ 已移除 trueassis 提醒"
    ;;
  install|"")
    { strip_existing; echo "$BLOCK"; } | crontab -
    echo "✓ 已安装 trueassis 提醒（日志: $LOG）"
    echo "  查看: crontab -l | sed -n '/trueassis/,/trueassis-reminders end/p'"
    echo "  卸载: bash tools/install-reminders.sh --uninstall"
    echo
    echo "注意: macOS 需要在「系统设置 → 隐私与安全性 → 完全磁盘访问权限」"
    echo "      中授权 cron，否则可能无法读写仓库文件。"
    ;;
  *)
    echo "用法: $0 [install|--dry-run|--uninstall]" >&2; exit 1
    ;;
esac
