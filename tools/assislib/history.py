# -*- coding: utf-8 -*-
"""操作历史与撤销（undo）。

设计目标：用户永不碰代码，因此 Agent 的任何误操作都必须能**用一句话撤销**。

实现：每个写操作前对 private/ 做一次全量快照（数据体积极小，几十 KB），
存入 private/.undo/<seq>/。undo 时整体回滚到该快照。

为什么用全量快照而不是增量 diff：
  - 简单到不可能出错。文件移动（归档）、多文件联动（recur run）都天然覆盖。
  - private/ 是纯文本小数据，全量快照的成本可以忽略。
  - Agent 不需要理解任何事务语义就能安全回滚。
"""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .const import PRIV, ROOT, color

UNDO = PRIV / ".undo"
OPLOG = PRIV / "oplog.jsonl"
KEEP = 30                      # 保留最近 N 个快照
SKIP = {".undo"}               # 快照时跳过自身


def _snapshot_files() -> List[Path]:
    if not PRIV.exists():
        return []
    out = []
    for p in PRIV.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(PRIV)
        if rel.parts and rel.parts[0] in SKIP:
            continue
        out.append(p)
    return out


def _next_seq() -> int:
    UNDO.mkdir(parents=True, exist_ok=True)
    seqs = [int(d.name.split("-")[0]) for d in UNDO.iterdir()
            if d.is_dir() and d.name.split("-")[0].isdigit()]
    return (max(seqs) + 1) if seqs else 1


def _prune():
    if not UNDO.exists():
        return
    dirs = sorted([d for d in UNDO.iterdir() if d.is_dir()],
                  key=lambda d: d.name)
    for d in dirs[:-KEEP]:
        shutil.rmtree(d, ignore_errors=True)


def snapshot(op: str, argv: Optional[List[str]] = None) -> Optional[Path]:
    """写操作前调用。返回快照目录；private/ 不存在时返回 None。"""
    if not PRIV.exists():
        return None
    seq = _next_seq()
    dest = UNDO / f"{seq:05d}-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    (dest / "data").mkdir(parents=True, exist_ok=True)
    for p in _snapshot_files():
        rel = p.relative_to(PRIV)
        tgt = dest / "data" / rel
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, tgt)
    meta = {
        "seq": seq,
        "op": op,
        "argv": argv or [],
        "at": datetime.now().isoformat(timespec="seconds"),
        "files": len(_snapshot_files()),
    }
    (dest / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _prune()
    return dest


def append_oplog(op: str, argv: List[str], result: str = "ok"):
    PRIV.mkdir(parents=True, exist_ok=True)
    rec = {"at": datetime.now().isoformat(timespec="seconds"),
           "op": op, "argv": argv, "result": result}
    with OPLOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _snapshots() -> List[Path]:
    if not UNDO.exists():
        return []
    return sorted([d for d in UNDO.iterdir() if d.is_dir() and (d / "meta.json").exists()],
                  key=lambda d: d.name)


def _read_meta(d: Path) -> Dict[str, Any]:
    try:
        return json.loads((d / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cmd_undo(args):
    """回滚到上一个写操作之前的状态。"""
    snaps = _snapshots()
    if not snaps:
        print(color("没有可撤销的操作", "grey"))
        return 0

    target = snaps[-1]
    if args.to:
        match = [s for s in snaps if s.name.startswith(f"{int(args.to):05d}-")]
        if not match:
            print(color(f"找不到快照 #{args.to}，用 assis history 查看", "red"))
            return 1
        target = match[0]

    meta = _read_meta(target)
    data = target / "data"

    if args.dry_run:
        print(color(f"将回滚到 #{meta.get('seq')} 之前的状态", "yellow"))
        print(f"  该操作: {meta.get('op')} {' '.join(meta.get('argv', []))}")
        print(f"  时间:   {meta.get('at')}")
        return 0

    # 回滚本身也要可撤销（防止误撤销）
    snapshot("undo", [f"#{meta.get('seq')}"])

    for p in _snapshot_files():
        rel = p.relative_to(PRIV)
        if not (data / rel).exists():
            p.unlink()                      # 快照后新建的文件 → 删除
    for src in data.rglob("*"):
        if src.is_file():
            tgt = PRIV / src.relative_to(data)
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tgt)

    shutil.rmtree(target, ignore_errors=True)
    append_oplog("undo", [f"#{meta.get('seq')}"])
    print(color(f"✓ 已撤销：{meta.get('op')} {' '.join(meta.get('argv', []))}", "green"))
    print(color(f"  （数据已回到 {meta.get('at')} 该操作执行前的状态）", "grey"))
    return 0


def cmd_history(args):
    snaps = _snapshots()
    if args.json:
        print(json.dumps([_read_meta(s) for s in reversed(snaps)],
                         ensure_ascii=False, indent=2))
        return 0
    if not snaps:
        print(color("（还没有操作记录）", "grey"))
        return 0
    print(color("最近的写操作（可撤销的检查点）", "bold"))
    for s in reversed(snaps[-args.limit:]):
        m = _read_meta(s)
        argv = " ".join(m.get("argv", []))
        print(f"  #{m.get('seq'):<4} {m.get('at', ''):<20} "
              f"{color(str(m.get('op')), 'cyan')} {argv[:60]}")
    print(color("\n  撤销上一步: assis undo", "grey"))
    print(color("  撤销到某步: assis undo --to <序号>", "grey"))
    return 0
