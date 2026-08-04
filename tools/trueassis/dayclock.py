from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# 日界时间：一天从几点开始算。对夜猫子来说凌晨 2 点仍属于「昨天」。
# 默认 00:00 等于自然日，保证既有数据与既有行为完全不变。
DEFAULT_DAY_START = "00:00"

_cache: Optional[Dict[str, Any]] = None


def reset_cache() -> None:
    global _cache
    _cache = None


def parse_clock(value: Any) -> Tuple[int, int]:
    """解析 HH:MM，只接受 00:00-23:59，避免非法值静默影响归属判断。"""
    parts = str(value).strip().split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError(f"日界时间必须形如 04:00，收到：{value}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"日界时间超出范围：{value}")
    return hour, minute


def _read_raw(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _sanitize(loaded: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in ("created_at", "updated_at"):
        if key in loaded:
            out[key] = loaded[key]
    candidate = str(loaded.get("day_start", DEFAULT_DAY_START)).strip()
    try:
        parse_clock(candidate)
    except ValueError:
        return out
    out["day_start"] = candidate
    return out


def load_config(path: Path) -> Dict[str, Any]:
    """读取配置；缺失或损坏时回退默认值，不让读配置成为命令失败的理由。"""
    global _cache
    if _cache is not None:
        return _cache
    config: Dict[str, Any] = {"schema": 1, "day_start": DEFAULT_DAY_START}
    loaded = _read_raw(path) if path.exists() else None
    if isinstance(loaded, dict):
        config.update(_sanitize(loaded))
    _cache = config
    return config


def day_start(path: Path, override: Optional[str] = None) -> Tuple[int, int]:
    try:
        return parse_clock(override or load_config(path).get("day_start", DEFAULT_DAY_START))
    except ValueError:
        return parse_clock(DEFAULT_DAY_START)


def logical_date(now: datetime, boundary: Tuple[int, int]) -> date:
    """日界之前的时刻归属前一天。"""
    if (now.hour, now.minute) < boundary:
        return now.date() - timedelta(days=1)
    return now.date()
