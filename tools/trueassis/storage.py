from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

ROOT = Path(os.environ.get("TRUEASSIS_ROOT", Path(__file__).resolve().parents[2])).resolve()
PRIVATE = ROOT / "private"
TASKS = PRIVATE / "tasks"
IDEAS = PRIVATE / "ideas"
REPORTS = PRIVATE / "reports"

CATEGORIES = {
    "work": "工作",
    "life": "生活",
    "health": "健康",
    "learning": "学习",
    "entertainment": "娱乐",
    "finance": "财务",
    "relationship": "关系",
    "household": "家庭",
    "other": "其他",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> date:
    override = os.environ.get("TRUEASSIS_TODAY")
    return date.fromisoformat(override) if override else date.today()


def parse_date(value: Optional[str], *, required: bool = False) -> Optional[date]:
    if value is None or not str(value).strip():
        if required:
            raise ValueError("缺少日期")
        return None
    raw = str(value).strip().lower()
    base = today()
    if raw in {"today", "今天"}:
        return base
    if raw in {"tomorrow", "明天"}:
        return base + timedelta(days=1)
    if raw in {"yesterday", "昨天"}:
        return base - timedelta(days=1)
    if len(raw) > 2 and raw[0] in "+-" and raw[-1] in "dw" and raw[1:-1].isdigit():
        amount = int(raw[1:-1]) * (1 if raw[0] == "+" else -1)
        return base + timedelta(days=amount * (7 if raw[-1] == "w" else 1))
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"无法解析日期：{value}，请使用 YYYY-MM-DD / today / +3d") from exc


def parse_tags(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    values = [part.strip() for part in str(raw).split(",") if part.strip()]
    return list(dict.fromkeys(values))


def ensure_private() -> None:
    for path in (TASKS, IDEAS, REPORTS / "daily", REPORTS / "weekly"):
        path.mkdir(parents=True, exist_ok=True)


def new_id(kind: str) -> str:
    return f"{kind}-{today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


def record_path(kind: str, record_id: str, created_at: Optional[str] = None) -> Path:
    stamp = (created_at or today().isoformat())[:10]
    year, month = stamp[:4], stamp[5:7]
    root = TASKS if kind == "task" else IDEAS
    return root / year / month / f"{record_id}.md"


def render_record(data: Dict[str, Any], body: str = "") -> str:
    header = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)
    title = data.get("title", data.get("id", ""))
    clean_body = body.strip()
    if not clean_body:
        clean_body = f"# {title}\n\n## 说明\n"
    return f"---\n{header}\n---\n\n{clean_body}\n"


def parse_record(text: str) -> Tuple[Dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ValueError("文件缺少 JSON front matter")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise ValueError("文件 front matter 未闭合")
    data = json.loads(text[4:marker])
    if not isinstance(data, dict):
        raise ValueError("front matter 必须是对象")
    return data, text[marker + 5 :].lstrip("\n")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save_record(path: Path, data: Dict[str, Any], body: str = "") -> None:
    validate_record(data)
    atomic_write(path, render_record(data, body))


def load_record(path: Path) -> Tuple[Dict[str, Any], str]:
    return parse_record(path.read_text(encoding="utf-8"))


def iter_records(kind: str = "all") -> Iterable[Tuple[Path, Dict[str, Any], str]]:
    ensure_private()
    roots = []
    if kind in {"all", "task"}:
        roots.append(TASKS)
    if kind in {"all", "idea"}:
        roots.append(IDEAS)
    for root in roots:
        for path in sorted(root.rglob("*.md")):
            try:
                data, body = load_record(path)
                validate_record(data)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"无法读取记录 {path.relative_to(PRIVATE)}：{exc}") from exc
            yield path, data, body


def find_record(record_id: str) -> Tuple[Path, Dict[str, Any], str]:
    if not record_id or "/" in record_id or "\\" in record_id:
        raise ValueError("必须提供完整、合法的任务 ID")
    matches = [(p, d, b) for p, d, b in iter_records("all") if d.get("id") == record_id]
    if not matches:
        raise ValueError(f"找不到记录：{record_id}。请先用 query 定位完整 ID")
    if len(matches) > 1:
        raise ValueError(f"ID 重复：{record_id}")
    return matches[0]


def validate_record(data: Dict[str, Any]) -> None:
    required = {"schema", "id", "kind", "title", "category", "tags", "status", "created_at", "updated_at", "history"}
    missing = sorted(required - set(data))
    if missing:
        raise ValueError("缺少字段：" + ", ".join(missing))
    if data["kind"] not in {"task", "idea"}:
        raise ValueError("kind 只能是 task 或 idea")
    if not isinstance(data["title"], str) or not data["title"].strip():
        raise ValueError("title 不能为空")
    if not isinstance(data["history"], list):
        raise ValueError("history 必须是列表")
    if data["category"] not in CATEGORIES:
        raise ValueError("未知分类：" + str(data["category"]))
    if not isinstance(data["tags"], list) or not all(isinstance(tag, str) for tag in data["tags"]):
        raise ValueError("tags 必须是字符串列表")
    if data["kind"] == "idea":
        if data["status"] not in {"open", "archived"}:
            raise ValueError("idea 状态只能是 open 或 archived")
        return
    if data["status"] not in {"open", "done", "cancelled"}:
        raise ValueError("任务状态只能是 open、done 或 cancelled")
    schedule = data.get("schedule")
    if not isinstance(schedule, dict) or schedule.get("type") not in {"once", "recurring"}:
        raise ValueError("任务必须包含 once 或 recurring 计划")
    if schedule.get("overdue_policy") not in {"carry", "skip"}:
        raise ValueError("overdue_policy 只能是 carry 或 skip")
    if schedule["type"] == "recurring" and not schedule.get("versions"):
        raise ValueError("循环任务至少需要一个计划版本")
    if not isinstance(data.get("occurrences"), list):
        raise ValueError("occurrences 必须是列表")
