from __future__ import annotations

import argparse
import importlib
import os
import tempfile
import unittest
from pathlib import Path


class TrueAssisTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TRUEASSIS_ROOT"] = self.tmp.name
        os.environ["TRUEASSIS_TODAY"] = "2026-08-04"
        import trueassis.storage as storage
        import trueassis.service as service
        import trueassis.report as report
        import trueassis.reminder as reminder
        importlib.reload(storage)
        import trueassis.recurrence as recurrence
        importlib.reload(recurrence)
        importlib.reload(service)
        importlib.reload(report)
        importlib.reload(reminder)
        self.storage, self.service, self.report, self.reminder = storage, service, report, reminder

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TRUEASSIS_ROOT", None)
        os.environ.pop("TRUEASSIS_TODAY", None)

    def ns(self, **values):
        defaults = dict(category="work", tags=None, note=None, due=None, repeat=None,
                        interval=1, on=None, month_days=None, start=None, until=None,
                        overdue_policy=None, title="任务")
        defaults.update(values)
        return argparse.Namespace(**defaults)

    def query_args(self, **values):
        defaults = dict(from_="2026-08-04", to="2026-08-04", kind="all", status="pending",
                        category=None, tag=None, text=None, id=None, include_overdue=True,
                        include_undated=True, overdue_days=3660)
        defaults.update(values)
        return argparse.Namespace(**defaults)

    def update_args(self, record_id, action, **values):
        defaults = dict(id=record_id, action=action, occurrence=None, to=None, reason=None,
                        note=None, title=None, category=None, tags=None, effective_from=None,
                        repeat=None, interval=1, on=None, month_days=None, until=None)
        defaults.update(values)
        return argparse.Namespace(**defaults)

    def test_once_task_query_and_complete(self):
        task = self.service.create_task(self.ns(title="今天交报告", due="2026-08-04"))
        result = self.service.query(self.query_args())
        self.assertEqual([task["id"]], [row["id"] for row in result["data"]["scheduled"]])
        self.service.update(self.update_args(task["id"], "complete"))
        done = self.service.query(self.query_args(status="done"))
        self.assertEqual([task["id"]], [row["id"] for row in done["data"]["done"]])

    def test_overdue_and_future_are_separated(self):
        old = self.service.create_task(self.ns(title="旧任务", due="2026-08-01"))
        self.service.create_task(self.ns(title="未来任务", due="2026-08-10"))
        result = self.service.query(self.query_args())
        self.assertEqual([old["id"]], [row["id"] for row in result["data"]["overdue"]])
        self.assertEqual([], result["data"]["scheduled"])

    def test_recurring_skip_does_not_accumulate(self):
        task = self.service.create_task(self.ns(title="跑步", category="health", repeat="daily",
                                                   start="2026-08-01", overdue_policy="skip"))
        result = self.service.query(self.query_args())
        self.assertEqual([task["id"]], [row["id"] for row in result["data"]["scheduled"]])
        self.assertEqual([], result["data"]["overdue"])
        missed = self.service.query(self.query_args(from_="2026-08-01", to="2026-08-03", status="missed"))
        self.assertEqual(3, len(missed["data"]["missed"]))

    def test_recurring_carry_accumulates(self):
        self.service.create_task(self.ns(title="每日必交", repeat="daily", start="2026-08-01",
                                         overdue_policy="carry"))
        result = self.service.query(self.query_args())
        self.assertEqual(3, len(result["data"]["overdue"]))
        self.assertEqual(1, len(result["data"]["scheduled"]))

    def test_recurring_occurrence_reschedule_and_complete(self):
        task = self.service.create_task(self.ns(title="跑步", category="health", repeat="weekly",
                                                   start="2026-08-03", on="mon,wed,fri"))
        self.service.update(self.update_args(task["id"], "reschedule", occurrence="2026-08-05", to="2026-08-04"))
        today_result = self.service.query(self.query_args())
        matches = [row for row in today_result["data"]["scheduled"] if row["id"] == task["id"]]
        self.assertEqual("2026-08-05", matches[0]["original_date"])
        self.service.update(self.update_args(task["id"], "complete", occurrence="2026-08-05", note="5km"))
        done = self.service.query(self.query_args(status="done"))
        self.assertEqual("done", done["data"]["done"][0]["status"])

    def test_edit_schedule_keeps_old_version(self):
        task = self.service.create_task(self.ns(title="学习", repeat="weekly", start="2026-08-03", on="mon"))
        self.service.update(self.update_args(task["id"], "edit-schedule", effective_from="2026-09-01",
                                             repeat="weekly", on="tue,thu", until="2026-12-31"))
        _, data, _ = self.storage.find_record(task["id"])
        self.assertEqual(2, len(data["schedule"]["versions"]))
        self.assertEqual("2026-08-31", data["schedule"]["versions"][0]["effective_until"])

    def test_cancel_is_retained(self):
        task = self.service.create_task(self.ns(title="取消我", due="2026-08-04"))
        self.service.update(self.update_args(task["id"], "cancel", reason="不再需要"))
        _, data, _ = self.storage.find_record(task["id"])
        self.assertEqual("cancelled", data["status"])
        self.assertEqual("不再需要", data["cancel_reason"])

    def test_idea_and_reports(self):
        idea = self.service.create_idea(self.ns(title="小游戏想法", category="entertainment"))
        result = self.service.query(self.query_args(kind="idea", status="open", include_overdue=False))
        self.assertEqual(idea["id"], result["data"]["ideas"][0]["id"])
        report = self.report.generate_report(argparse.Namespace(period="daily", date="2026-08-04", summary="总结", reflection="复盘", extra=["今天还见了老朋友。", "灵感：改进训练方法。"]))
        text = Path(report["path"]).read_text(encoding="utf-8")
        self.assertIn("小游戏想法", text)
        self.assertIn("总结", text)
        self.assertIn("今天还见了老朋友。", text)
        self.assertIn("灵感：改进训练方法。", text)

    def test_daily_reminder_message_uses_query_buckets(self):
        data = {
            "overdue": [{"title": "逾期报告"}],
            "scheduled": [{"title": "准备材料", "scheduled_date": "2026-08-06"}],
            "undated": [{"title": "预约复查"}],
        }
        title, body, total = self.reminder.build_message(data)
        self.assertEqual(3, total)
        self.assertIn("未来 3 天有 3 项待办", title)
        self.assertIn("[逾期] 逾期报告", body)
        self.assertIn("[2026-08-06] 准备材料", body)
        self.assertIn("[无日期] 预约复查", body)

    def test_text_lookup_without_date_returns_full_id(self):
        task = self.service.create_task(self.ns(title="定位金融报告", due="2026-12-01"))
        result = self.service.query(self.query_args(from_=None, to=None, text="金融", include_overdue=False))
        self.assertEqual(task["id"], result["data"]["records"][0]["id"])

    def test_write_requires_exact_id(self):
        task = self.service.create_task(self.ns(title="精确任务", due="2026-08-04"))
        with self.assertRaises(ValueError):
            self.service.update(self.update_args(task["id"][:12], "complete"))

    def test_cancel_single_occurrence_is_reported(self):
        task = self.service.create_task(self.ns(title="跑步", repeat="daily", start="2026-08-04"))
        self.service.update(self.update_args(task["id"], "cancel", occurrence="2026-08-04", reason="下雨"))
        result = self.service.query(self.query_args(status="cancelled"))
        self.assertEqual("下雨", result["data"]["cancelled"][0]["reason"])

    def test_cancel_future_series_keeps_task_file(self):
        task = self.service.create_task(self.ns(title="晨读", repeat="daily", start="2026-08-01"))
        self.service.update(self.update_args(task["id"], "cancel-series", effective_from="2026-08-06", reason="计划结束"))
        _, data, _ = self.storage.find_record(task["id"])
        self.assertEqual("2026-08-06", data["schedule"]["cancelled_from"])
        future = self.service.query(self.query_args(from_="2026-08-06", to="2026-08-07"))
        self.assertEqual([], future["data"]["scheduled"])

    def test_monthly_schedule(self):
        self.service.create_task(self.ns(title="月度结算", repeat="monthly", start="2026-08-01", month_days="1,15"))
        result = self.service.query(self.query_args(from_="2026-08-01", to="2026-08-31", status="all"))
        dates = sorted(row["original_date"] for row in result["data"]["scheduled"] + result["data"]["missed"])
        self.assertEqual(["2026-08-01", "2026-08-15"], dates)

    def test_malformed_record_fails_loudly(self):
        path = self.storage.TASKS / "2026" / "08" / "broken.md"
        path.parent.mkdir(parents=True)
        path.write_text("not a record", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "无法读取记录"):
            self.service.query(self.query_args())

    def test_record_is_readable_markdown(self):
        task = self.service.create_task(self.ns(title="人类可读", due="2026-08-04", note="详细说明"))
        path, _, _ = self.storage.find_record(task["id"])
        text = path.read_text(encoding="utf-8")
        self.assertIn('"title": "人类可读"', text)
        self.assertIn("# 人类可读", text)
        self.assertIn("详细说明", text)


if __name__ == "__main__":
    unittest.main()
