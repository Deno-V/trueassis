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
                        include_undated=True, overdue_days=365)
        defaults.update(values)
        return argparse.Namespace(**defaults)

    def update_args(self, record_id, action, **values):
        defaults = dict(id=record_id, action=action, occurrence=None, to=None, reason=None,
                        note=None, title=None, category=None, tags=None, effective_from=None,
                        repeat=None, interval=1, on=None, month_days=None, until=None,
                        on_date=None, add_tags=None, replace_note=None)
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

    def test_bare_query_defaults_to_today_and_reports_range(self):
        self.service.create_task(self.ns(title="欠着的报告", due="2026-08-01"))
        self.service.create_task(self.ns(title="无期限体检", category="health"))
        result = self.service.query(self.query_args(from_=None, to=None))
        self.assertEqual("range", result["mode"])
        self.assertEqual("2026-08-04", result["from"])
        self.assertEqual("2026-08-04", result["to"])
        self.assertEqual(["欠着的报告"], [row["title"] for row in result["data"]["overdue"]])
        self.assertEqual(["无期限体检"], [row["title"] for row in result["data"]["undated"]])

    def test_include_flags_can_be_turned_off(self):
        self.service.create_task(self.ns(title="欠着的报告", due="2026-08-01"))
        self.service.create_task(self.ns(title="无期限体检", category="health"))
        result = self.service.query(self.query_args(include_overdue=False, include_undated=False))
        # 关掉开关等于没查这两个分区，因此字段必须缺席而不是给出空数组
        self.assertNotIn("overdue", result["data"])
        self.assertNotIn("undated", result["data"])
        self.assertNotIn("overdue", result["queried"])
        self.assertNotIn("undated", result["queried"])

    def test_historical_range_keeps_plan_in_scheduled(self):
        self.service.create_task(self.ns(title="上周的报告", due="2026-08-02"))
        result = self.service.query(self.query_args(from_="2026-08-01", to="2026-08-03"))
        rows = result["data"]["scheduled"]
        self.assertEqual(["上周的报告"], [row["title"] for row in rows])
        self.assertTrue(rows[0]["is_overdue"])
        self.assertEqual([], result["data"]["overdue"])

    def test_missed_skip_is_visible_in_default_pending_query(self):
        self.service.create_task(self.ns(title="跑步", category="health", repeat="daily",
                                         start="2026-08-01", overdue_policy="skip"))
        result = self.service.query(self.query_args(from_="2026-08-01", to="2026-08-03"))
        self.assertEqual(3, len(result["data"]["missed"]))
        self.assertEqual([], result["data"]["scheduled"])
        self.assertEqual([], result["data"]["overdue"])

    def test_future_range_does_not_mislabel_unreached_tasks(self):
        self.service.create_task(self.ns(title="真逾期", due="2026-08-01"))
        self.service.create_task(self.ns(title="还没到期", due="2026-08-06"))
        result = self.service.query(self.query_args(from_="2026-08-10", to="2026-08-12"))
        self.assertEqual(["真逾期"], [row["title"] for row in result["data"]["overdue"]])
        self.assertEqual([], result["data"]["scheduled"])

    def test_idea_lookup_without_range_is_not_limited_to_today(self):
        idea = self.service.create_idea(self.ns(title="旧想法", category="entertainment"))
        path, data, body = self.storage.find_record(idea["id"])
        data["created_at"] = "2026-05-01T09:00:00+08:00"
        self.storage.save_record(path, data, body)
        result = self.service.query(self.query_args(from_=None, to=None, kind="idea", status="open"))
        self.assertEqual([idea["id"]], [row["id"] for row in result["data"]["ideas"]])

    def test_report_separates_overdue_missed_and_plan(self):
        self.service.create_task(self.ns(title="跑步", category="health", repeat="daily",
                                         start="2026-08-01", overdue_policy="skip"))
        self.service.create_task(self.ns(title="欠着的报告", due="2026-08-01"))
        result = self.report.generate_report(argparse.Namespace(
            period="daily", date="2026-08-03", summary=None, reflection=None, extra=None))
        text = Path(result["path"]).read_text(encoding="utf-8")
        self.assertIn("## 错过未补", text)
        self.assertIn("## 逾期未完成", text)
        self.assertIn("## 无日期待办", text)
        missed_block = text.split("## 错过未补")[1].split("##")[0]
        self.assertIn("跑步", missed_block)
        overdue_block = text.split("## 逾期未完成")[1].split("##")[0]
        self.assertIn("欠着的报告", overdue_block)

    def test_overdue_days_limits_carry_lookback(self):
        self.service.create_task(self.ns(title="长期欠账", repeat="daily", start="2026-01-01",
                                         overdue_policy="carry"))
        wide = self.service.query(self.query_args(overdue_days=365))
        narrow = self.service.query(self.query_args(overdue_days=3))
        self.assertGreater(len(wide["data"]["overdue"]), len(narrow["data"]["overdue"]))
        self.assertEqual(3, len(narrow["data"]["overdue"]))

    def test_backfilled_occurrence_lands_on_its_planned_day(self):
        task = self.service.create_task(self.ns(title="跑步", category="health", repeat="daily",
                                                start="2026-08-01", overdue_policy="skip"))
        # 8月4日才补记“我1号跑了”，这件事应该算在 1号，而不是操作当天。
        self.service.update(self.update_args(task["id"], "complete", occurrence="2026-08-01", note="5公里"))
        first = self.service.query(self.query_args(from_="2026-08-01", to="2026-08-01", status="all"))
        self.assertEqual(["跑步"], [row["title"] for row in first["data"]["done"]])
        self.assertEqual("2026-08-01", first["data"]["done"][0]["completed_on"])
        self.assertEqual([], first["data"]["missed"])
        today_view = self.service.query(self.query_args(status="done"))
        self.assertEqual([], today_view["data"]["done"])

    def test_once_task_completion_defaults_to_today(self):
        task = self.service.create_task(self.ns(title="交周报", due="2026-08-01"))
        self.service.update(self.update_args(task["id"], "complete"))
        _, data, _ = self.storage.find_record(task["id"])
        self.assertEqual("2026-08-04", data["completed_on"])
        late = self.service.query(self.query_args(status="done"))
        self.assertEqual(["交周报"], [row["title"] for row in late["data"]["done"]])

    def test_on_date_backfills_once_task(self):
        task = self.service.create_task(self.ns(title="交周报", due="2026-08-01"))
        self.service.update(self.update_args(task["id"], "complete", on_date="2026-08-01"))
        result = self.service.query(self.query_args(from_="2026-08-01", to="2026-08-01", status="done"))
        self.assertEqual(["交周报"], [row["title"] for row in result["data"]["done"]])

    def test_legacy_record_without_on_field_still_groups(self):
        task = self.service.create_task(self.ns(title="老记录", due="2026-08-01"))
        self.service.update(self.update_args(task["id"], "complete"))
        path, data, body = self.storage.find_record(task["id"])
        data.pop("completed_on")
        data["completed_at"] = "2026-08-02T10:00:00+08:00"
        self.storage.save_record(path, data, body)
        result = self.service.query(self.query_args(from_="2026-08-02", to="2026-08-02", status="done"))
        self.assertEqual(["老记录"], [row["title"] for row in result["data"]["done"]])

    def test_edit_appends_supplement_without_losing_description(self):
        task = self.service.create_task(self.ns(title="任务", due="2026-08-04", note="最初的说明"))
        self.service.update(self.update_args(task["id"], "edit", note="客户改了验收标准"))
        self.service.update(self.update_args(task["id"], "edit", note="需要法务复核"))
        path, _, _ = self.storage.find_record(task["id"])
        text = path.read_text(encoding="utf-8")
        self.assertIn("最初的说明", text)
        self.assertIn("- 2026-08-04：客户改了验收标准", text)
        self.assertIn("- 2026-08-04：需要法务复核", text)

    def test_edit_add_tags_keeps_existing_and_records_change(self):
        task = self.service.create_task(self.ns(title="任务", due="2026-08-04", tags="a,b"))
        self.service.update(self.update_args(task["id"], "edit", add_tags="urgent"))
        _, data, _ = self.storage.find_record(task["id"])
        self.assertEqual(["a", "b", "urgent"], data["tags"])
        change = data["history"][-1]["changes"]["tags"]
        self.assertEqual(["a", "b"], change["from"])
        self.assertEqual(["a", "b", "urgent"], change["to"])

    def test_edit_title_syncs_body_heading(self):
        task = self.service.create_task(self.ns(title="原始标题", due="2026-08-04"))
        self.service.update(self.update_args(task["id"], "edit", title="改后的标题"))
        path, _, _ = self.storage.find_record(task["id"])
        text = path.read_text(encoding="utf-8")
        self.assertIn("# 改后的标题", text)
        self.assertNotIn("# 原始标题", text)

    def test_edit_without_any_change_fails_loudly(self):
        task = self.service.create_task(self.ns(title="任务", due="2026-08-04"))
        with self.assertRaisesRegex(ValueError, "至少一项修改"):
            self.service.update(self.update_args(task["id"], "edit"))

    def test_reschedule_records_original_date(self):
        task = self.service.create_task(self.ns(title="任务", due="2026-08-01"))
        self.service.update(self.update_args(task["id"], "reschedule", to="2026-08-20"))
        _, data, _ = self.storage.find_record(task["id"])
        entry = data["history"][-1]
        self.assertEqual("2026-08-01", entry["from"])
        self.assertEqual("2026-08-20", entry["to"])

    def test_report_rewrite_keeps_handwritten_content(self):
        self.service.create_task(self.ns(title="交周报", due="2026-08-01"))
        first = argparse.Namespace(period="daily", date="2026-08-01", summary="那天在赶周报",
                                   reflection="节奏太紧", extra=["和同事吃了饭"])
        result = self.report.generate_report(first)
        self.assertFalse(result["rewritten"])
        again = self.report.generate_report(argparse.Namespace(
            period="daily", date="2026-08-01", summary=None, reflection=None, extra=None))
        self.assertTrue(again["rewritten"])
        text = Path(again["path"]).read_text(encoding="utf-8")
        self.assertIn("那天在赶周报", text)
        self.assertIn("节奏太紧", text)
        self.assertIn("和同事吃了饭", text)

    def test_report_appends_new_notes_and_stays_idempotent(self):
        path_holder = self.report.generate_report(argparse.Namespace(
            period="daily", date="2026-08-01", summary="第一句", reflection=None, extra=None))
        for _ in range(2):
            self.report.generate_report(argparse.Namespace(
                period="daily", date="2026-08-01", summary="第二句", reflection=None, extra=None))
        text = Path(path_holder["path"]).read_text(encoding="utf-8")
        self.assertIn("第一句", text)
        self.assertEqual(1, text.count("第二句"))


    def test_day_start_defaults_to_natural_day(self):
        self.assertEqual("00:00", self.storage.day_start_label())

    def test_day_start_shifts_logical_date_for_night_owls(self):
        import datetime
        from trueassis import dayclock
        self.storage.set_day_start("04:00")
        boundary = self.storage.day_start()
        self.assertEqual((4, 0), boundary)
        before = datetime.datetime(2026, 8, 5, 2, 30)
        after = datetime.datetime(2026, 8, 5, 4, 0)
        self.assertEqual(datetime.date(2026, 8, 4), dayclock.logical_date(before, boundary))
        self.assertEqual(datetime.date(2026, 8, 5), dayclock.logical_date(after, boundary))

    def test_day_start_rejects_invalid_values(self):
        from trueassis import dayclock
        for bad in ("25:00", "4", "abc", "04:70", "-1:00"):
            with self.assertRaises(ValueError):
                dayclock.parse_clock(bad)

    def test_corrupt_config_falls_back_to_default(self):
        from trueassis import dayclock
        self.storage.set_day_start("05:00")
        self.storage.config_path().write_text("{ not json", encoding="utf-8")
        dayclock.reset_cache()
        self.assertEqual("00:00", self.storage.day_start_label())

    def test_config_roundtrip_persists_and_reports(self):
        import argparse as ap
        result = self.service.configure(ap.Namespace(day_start="03:30"))
        self.assertEqual("03:30", result["day_start"])
        again = self.service.configure(ap.Namespace(day_start=None))
        self.assertEqual("03:30", again["day_start"])
        self.assertIn("03:30", again["explain"])

    def test_query_reports_day_start(self):
        self.storage.set_day_start("04:00")
        result = self.service.query(self.query_args())
        self.assertEqual("04:00", result["day_start"])


    def _mixed_fixture(self):
        """造出覆盖各状态的数据，用于验证 --status 的默认与各取值语义。"""
        done = self.service.create_task(self.ns(title="已完成", due="2026-08-04"))["id"]
        self.service.update(self.update_args(done, "complete"))
        cancelled = self.service.create_task(self.ns(title="已取消", due="2026-08-04"))["id"]
        self.service.update(self.update_args(cancelled, "cancel", reason="不做了"))
        self.service.create_task(self.ns(title="今天计划", due="2026-08-04"))
        self.service.create_task(self.ns(title="carry欠账", due="2026-08-01"))
        self.service.create_task(self.ns(title="无日期"))
        idea = self.service.create_idea(self.ns(title="想法A"))["id"]
        archived = self.service.create_idea(self.ns(title="想法B"))["id"]
        self.service.update(self.update_args(archived, "archive"))
        return idea, archived

    def test_default_status_hides_done_cancelled_and_ideas(self):
        self._mixed_fixture()
        data = self.service.query(self.query_args())["data"]
        self.assertEqual(["今天计划"], [row["title"] for row in data["scheduled"]])
        self.assertEqual(["carry欠账"], [row["title"] for row in data["overdue"]])
        self.assertEqual(["无日期"], [row["title"] for row in data["undated"]])
        # 默认 pending 只回答「还欠着什么」：这些分区没有被查询，必须整个缺席，
        # 否则空数组会被误读成「今天什么都没完成」
        self.assertNotIn("done", data)
        self.assertNotIn("cancelled", data)
        self.assertNotIn("ideas", data)

    def test_status_all_includes_done_cancelled_and_ideas(self):
        self._mixed_fixture()
        data = self.service.query(self.query_args(status="all"))["data"]
        self.assertEqual(["已完成"], [row["title"] for row in data["done"]])
        self.assertEqual(["已取消"], [row["title"] for row in data["cancelled"]])
        self.assertEqual(["想法A", "想法B"], sorted(row["title"] for row in data["ideas"]))

    def test_idea_status_open_and_archived_are_separable(self):
        self._mixed_fixture()
        opened = self.service.query(self.query_args(kind="idea", status="open"))["data"]["ideas"]
        archived = self.service.query(self.query_args(kind="idea", status="archived"))["data"]["ideas"]
        self.assertEqual(["想法A"], [row["title"] for row in opened])
        self.assertEqual(["想法B"], [row["title"] for row in archived])

    def test_status_missed_covers_once_tasks_too(self):
        """skip 的一次性任务过期后也必须能被 --status missed 查到。"""
        self.service.create_task(self.ns(title="一次性错过", due="2026-08-02", overdue_policy="skip"))
        self.service.create_task(self.ns(title="循环错过", category="health", repeat="daily",
            start="2026-08-02", until="2026-08-02", overdue_policy="skip"))
        pending = self.service.query(self.query_args(from_="2026-08-02", to="2026-08-02"))["data"]["missed"]
        only = self.service.query(self.query_args(from_="2026-08-02", to="2026-08-02", status="missed"))["data"]
        self.assertEqual(["一次性错过", "循环错过"], sorted(row["title"] for row in pending))
        # --status missed 必须与默认查询里的 missed 分区一致，不能漏掉一次性任务
        self.assertEqual(sorted(row["title"] for row in pending), sorted(row["title"] for row in only["missed"]))
        self.assertNotIn("scheduled", only)

    def test_idea_belongs_to_logical_day(self):
        """想法的归属日走逻辑日，而不是墙钟日期，否则深夜记的想法会落错一天。"""
        idea = self.service.create_idea(self.ns(title="深夜灵感"))["id"]
        _, data, _ = self.storage.find_record(idea)
        self.assertEqual("2026-08-04", data["created_on"])
        rows = self.service.query(self.query_args(status="all", kind="idea"))["data"]["ideas"]
        self.assertEqual(["2026-08-04"], [row["created_on"] for row in rows])

    def test_legacy_idea_without_created_on_still_queryable(self):
        """旧记录没有 created_on，应回退到 created_at 的日期部分。"""
        idea = self.service.create_idea(self.ns(title="旧想法"))["id"]
        path, data, body = self.storage.find_record(idea)
        data.pop("created_on")
        data["created_at"] = "2026-08-04T23:30:00+08:00"
        self.storage.save_record(path, data, body)
        rows = self.service.query(self.query_args(status="all", kind="idea"))["data"]["ideas"]
        self.assertEqual(["旧想法"], [row["title"] for row in rows])


    def test_partitions_absent_unless_queried(self):
        """字段存在即已查询；空数组才代表确实没有。这条契约不能被破坏。"""
        cases = {
            "pending": {"scheduled", "overdue", "undated", "missed"},
            "done": {"done"},
            "cancelled": {"cancelled"},
            "missed": {"missed"},
            "archived": {"ideas"},
        }
        for status, expected in cases.items():
            result = self.service.query(self.query_args(status=status))
            self.assertEqual(expected, set(result["data"]), f"status={status}")
            self.assertEqual(sorted(expected), result["queried"], f"status={status}")

    def test_status_all_exposes_every_partition(self):
        result = self.service.query(self.query_args(status="all"))
        expected = {"scheduled", "overdue", "undated", "missed", "done", "cancelled", "ideas"}
        self.assertEqual(expected, set(result["data"]))

    def test_kind_filter_drops_irrelevant_partitions(self):
        tasks_only = self.service.query(self.query_args(status="all", kind="task"))["data"]
        ideas_only = self.service.query(self.query_args(status="all", kind="idea"))["data"]
        self.assertNotIn("ideas", tasks_only)
        self.assertEqual({"ideas"}, set(ideas_only))

    def test_lookup_mode_returns_only_records(self):
        self.service.create_task(self.ns(title="金融报告", due="2026-08-04"))
        result = self.service.query(self.query_args(from_=None, to=None, text="金融报告"))
        self.assertEqual("lookup", result["mode"])
        # 定位模式下其他分区并未参与计算，必须缺席
        self.assertEqual({"records"}, set(result["data"]))
        self.assertEqual(["records"], result["queried"])


    def test_filter_values_are_never_partition_names(self):
        """pending / open / all 只存在于过滤轴，绝不能变成 data 的键。"""
        partitions = {"records", "scheduled", "overdue", "undated", "done", "cancelled", "missed", "ideas"}
        for status in ("pending", "open", "all", "done", "cancelled", "missed", "archived"):
            result = self.service.query(self.query_args(status=status))
            self.assertNotIn("pending", result["data"], f"status={status}")
            self.assertNotIn("open", result["data"], f"status={status}")
            self.assertNotIn("all", result["data"], f"status={status}")
            self.assertTrue(set(result["data"]) <= partitions, f"status={status}")
            self.assertTrue(set(result["queried"]) <= partitions, f"status={status}")


if __name__ == "__main__":
    unittest.main()
