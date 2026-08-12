from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Member
from apps.dairymetrics.models import DepartmentDailyMetricSummary, MemberDailyMetricEntry, MemberMetricTransaction, MemberMonthMetricTarget, MemberPeriodMetricTarget, MetricAdjustment, WVMetricCancellation
from apps.dairymetrics.services.final_actuals import collect_department_final_actual_totals, collect_member_final_actual_totals
from apps.performance.forms import PerformanceMetricAdjustmentForm
from apps.targets.models import MonthTargetMetricValue, Period, PeriodTargetMetricValue, TargetMetric
from .base import PerformanceTestBase


class AdjustmentsTests(PerformanceTestBase):
    def test_performance_adjustments_uses_shared_button_hierarchy(self):
        response = self.client.get(reverse("performance_adjustments"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ui-button--primary")

    def test_performance_index_renders_final_actual_rows_with_adjustment_totals(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 5, 15),
            result_count=2,
            support_amount=3000,
            approach_count=8,
            communication_count=4,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=entry.entry_date,
            result_count=1,
            support_amount=700,
            return_postal_count=1,
            return_postal_amount=600,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "実績管理")
        self.assertContains(response, "4件")
        self.assertContains(response, "4,300円")
        self.assertContains(response, "有効メンバー一覧")
        self.assertContains(response, "直近稼働の全体実績推移")
        self.assertContains(response, "performance-activity-trend-chart")
        self.assertContains(response, "日目達成率")
        self.assertContains(response, entry.entry_date.strftime("%m/%d"))
        self.assertContains(response, "戻り・増額登録")
        self.assertContains(response, reverse("performance_adjustments"))
        self.assertContains(response, reverse("dairymetrics_entry_v2_transaction_demo"))
        self.assertContains(response, reverse("dairymetrics_metrics_v2_demo"))
        self.assertContains(response, reverse("dashboard_index"))
        self.assertContains(response, "振り返りレポート")
        self.assertContains(response, reverse("dairymetrics_metrics_report"))


    def test_wv_cancellation_subtracts_from_final_actuals_without_changing_field_entry(self):
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV Cancel Member", department=wv_department)
        entry = MemberDailyMetricEntry.objects.create(
            member=wv_member,
            department=wv_department,
            entry_date=date(2026, 6, 7),
            result_count=2,
            support_amount=6500,
            cs_count=1,
            refugee_count=1,
        )
        WVMetricCancellation.objects.create(
            member=wv_member,
            department=wv_department,
            target_date=entry.entry_date,
            wv_result_type=MemberMetricTransaction.WV_RESULT_CS,
            wv_cs_count=1,
            location_name="横浜駅前",
        )

        entry.refresh_from_db()
        totals = collect_member_final_actual_totals(
            wv_member,
            wv_department,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(entry.result_count, 2)
        self.assertEqual(entry.support_amount, 6500)
        self.assertEqual(totals["result_count"], 1)
        self.assertEqual(totals["support_amount"], 2000)
        self.assertEqual(totals["cs_count"], 0)
        self.assertEqual(totals["refugee_count"], 1)


    def test_wv_refugee_cancellation_subtracts_only_refugee_side(self):
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV Refugee Cancel", department=wv_department)
        MemberDailyMetricEntry.objects.create(
            member=wv_member,
            department=wv_department,
            entry_date=date(2026, 6, 8),
            result_count=2,
            support_amount=7500,
            cs_count=1,
            refugee_count=1,
        )
        WVMetricCancellation.objects.create(
            member=wv_member,
            department=wv_department,
            target_date=date(2026, 6, 8),
            wv_result_type=MemberMetricTransaction.WV_RESULT_REFUGEE,
            wv_refugee_amount=3000,
        )

        totals = collect_department_final_actual_totals(
            wv_department,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(totals["result_count"], 1)
        self.assertEqual(totals["support_amount"], MemberMetricTransaction.WV_CS_UNIT_AMOUNT)
        self.assertEqual(totals["cs_count"], 1)
        self.assertEqual(totals["refugee_count"], 0)


    def test_performance_adjustment_create_sets_creator(self):
        response = self.client.post(
            reverse("performance_adjustments"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "target_date": "2026-05-14",
                "source_type": MetricAdjustment.SOURCE_QR,
                "location_name": "渋谷駅前",
                "amount_choice": "1500",
                "amount": "",
            },
        )

        self.assertRedirects(response, reverse("performance_adjustments") + "?saved=1")
        adjustment = MetricAdjustment.objects.get(member=self.member, department=self.department, target_date=date(2026, 5, 14))
        self.assertEqual(adjustment.created_by, self.user)
        self.assertEqual(adjustment.source_type, MetricAdjustment.SOURCE_QR)
        self.assertEqual(adjustment.return_qr_count, 1)
        self.assertEqual(adjustment.return_qr_amount, 1500)
        self.assertEqual(adjustment.location_name, "渋谷駅前")
        self.assertEqual(adjustment.support_amount, 0)


    def test_performance_adjustment_create_increase_counts_as_one(self):
        response = self.client.post(
            reverse("performance_adjustments"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "target_date": "2026-05-15",
                "source_type": MetricAdjustment.SOURCE_INCREASE,
                "location_name": "池袋駅前",
                "amount_choice": "direct",
                "amount": "6200",
            },
        )

        self.assertRedirects(response, reverse("performance_adjustments") + "?saved=1")
        adjustment = MetricAdjustment.objects.get(member=self.member, department=self.department, target_date=date(2026, 5, 15))
        self.assertEqual(adjustment.source_type, MetricAdjustment.SOURCE_INCREASE)
        self.assertEqual(adjustment.result_count, 1)
        self.assertEqual(adjustment.support_amount, 6200)
        self.assertEqual(adjustment.location_name, "池袋駅前")


    def test_performance_adjustment_member_options_include_un_activity_code(self):
        self.member.un_activity_code = "12345"
        self.member.save(update_fields=["un_activity_code"])
        adjustment = MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 13),
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=500,
        )

        response = self.client.get(reverse("performance_adjustments"), {"edit": adjustment.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UNコード")
        self.assertContains(response, "performance-selected-member-preview")
        options = response.context["member_options"][str(self.department.id)]
        self.assertEqual(options[0]["id"], self.member.id)
        self.assertEqual(options[0]["name"], self.member.name)
        self.assertEqual(options[0]["un_activity_code"], "12345")


    def test_performance_adjustment_member_options_only_load_selected_department(self):
        other_department = self.create_department("WV")
        other_member = self.create_member(name="Other Member", department=other_department)
        adjustment = MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 13),
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=500,
        )

        response = self.client.get(reverse("performance_adjustments"), {"edit": adjustment.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context["member_options"]), {str(self.department.id)})
        self.assertEqual(
            [option["id"] for option in response.context["member_options"][str(self.department.id)]],
            [self.member.id],
        )
        self.assertNotContains(response, f'"id": {other_member.id}')


    def test_performance_adjustment_create_page_does_not_preload_member_options(self):
        response = self.client.get(reverse("performance_adjustments"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["member_options"], {})


    def test_performance_adjustment_member_options_api_excludes_inactive_members(self):
        inactive_member = self.create_member(name="Inactive Member", department=self.department)
        inactive_member.is_active = False
        inactive_member.save(update_fields=["is_active"])

        response = self.client.get(
            reverse("performance_past_entry_member_options"),
            {"department": self.department.id, "active_only": "1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([option["id"] for option in response.json()["options"]], [self.member.id])


    def test_performance_adjustment_create_wv_cs_sets_fixed_amount_and_count(self):
        self.department.code = "WV"
        self.department.name = "WV"
        self.department.save(update_fields=["code", "name"])

        response = self.client.post(
            reverse("performance_adjustments"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "target_date": "2026-05-16",
                "source_type": MetricAdjustment.SOURCE_CS,
                "location_name": "横浜駅前",
                "amount_choice": "500",
                "amount": "",
            },
        )

        self.assertRedirects(response, reverse("performance_adjustments") + "?saved=1")
        adjustment = MetricAdjustment.objects.get(member=self.member, department=self.department, target_date=date(2026, 5, 16))
        self.assertEqual(adjustment.source_type, MetricAdjustment.SOURCE_CS)
        self.assertEqual(adjustment.result_count, 1)
        self.assertEqual(adjustment.cs_count, 1)
        self.assertEqual(adjustment.refugee_count, 0)
        self.assertEqual(adjustment.support_amount, MemberMetricTransaction.WV_CS_UNIT_AMOUNT)
        self.assertEqual(adjustment.location_name, "横浜駅前")


    def test_performance_adjustment_create_wv_cs_plus_refugee_sets_split_counts(self):
        self.department.code = "WV"
        self.department.name = "WV"
        self.department.save(update_fields=["code", "name"])

        response = self.client.post(
            reverse("performance_adjustments"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "target_date": "2026-05-17",
                "source_type": MetricAdjustment.SOURCE_CS_PLUS_REFUGEE,
                "location_name": "川崎駅前",
                "amount_choice": "1500",
                "amount": "",
            },
        )

        self.assertRedirects(response, reverse("performance_adjustments") + "?saved=1")
        adjustment = MetricAdjustment.objects.get(member=self.member, department=self.department, target_date=date(2026, 5, 17))
        self.assertEqual(adjustment.source_type, MetricAdjustment.SOURCE_CS_PLUS_REFUGEE)
        self.assertEqual(adjustment.result_count, 2)
        self.assertEqual(adjustment.cs_count, 1)
        self.assertEqual(adjustment.refugee_count, 1)
        self.assertEqual(adjustment.support_amount, MemberMetricTransaction.WV_CS_UNIT_AMOUNT + 1500)
        self.assertEqual(adjustment.location_name, "川崎駅前")


    def test_performance_adjustment_create_wv_cancel_saves_cancellation_record(self):
        self.department.code = "WV"
        self.department.name = "WV"
        self.department.save(update_fields=["code", "name"])

        response = self.client.post(
            reverse("performance_adjustments"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "target_date": "2026-05-18",
                "source_type": PerformanceMetricAdjustmentForm.SOURCE_CANCEL,
                "cancel_result_type": MemberMetricTransaction.WV_RESULT_BOTH,
                "cancel_cs_count": "1",
                "location_name": "横浜駅前",
                "amount_choice": "2000",
                "amount": "",
            },
        )

        self.assertRedirects(response, reverse("performance_adjustments") + "?saved=1")
        self.assertFalse(MetricAdjustment.objects.filter(member=self.member, target_date=date(2026, 5, 18)).exists())
        cancellation = WVMetricCancellation.objects.get(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 18),
        )
        self.assertEqual(cancellation.created_by, self.user)
        self.assertEqual(cancellation.wv_result_type, MemberMetricTransaction.WV_RESULT_BOTH)
        self.assertEqual(cancellation.cs_count, 1)
        self.assertEqual(cancellation.refugee_count, 1)
        self.assertEqual(cancellation.support_amount, MemberMetricTransaction.WV_CS_UNIT_AMOUNT + 2000)
        self.assertEqual(cancellation.location_name, "横浜駅前")


    def test_performance_adjustments_list_shows_wv_cancellation_and_can_delete(self):
        self.department.code = "WV"
        self.department.name = "WV"
        self.department.save(update_fields=["code", "name"])
        cancellation = WVMetricCancellation.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 19),
            wv_result_type=MemberMetricTransaction.WV_RESULT_CS,
            wv_cs_count=1,
            location_name="川崎駅前",
            created_by=self.user,
        )

        response = self.client.get(reverse("performance_adjustments"), {"department": self.department.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "キャンセル")
        self.assertContains(response, "川崎駅前")
        self.assertContains(response, "CS 1 / 難民 0")

        delete_response = self.client.post(reverse("performance_cancellation_delete", args=[cancellation.id]))

        self.assertRedirects(delete_response, reverse("performance_adjustments"))
        self.assertFalse(WVMetricCancellation.objects.filter(pk=cancellation.pk).exists())


    def test_performance_adjustments_ajax_filters_by_department(self):
        other_department = self.create_department("WV")
        other_member = self.create_member(name="Bob", department=other_department)
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 10),
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1500,
            location_name="渋谷駅前",
        )
        MetricAdjustment.objects.create(
            member=other_member,
            department=other_department,
            target_date=date(2026, 5, 11),
            source_type=MetricAdjustment.SOURCE_CS,
            support_amount=MemberMetricTransaction.WV_CS_UNIT_AMOUNT,
            result_count=1,
            cs_count=1,
            location_name="横浜駅前",
        )

        response = self.client.get(
            reverse("performance_adjustments"),
            {"department": other_department.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("list_html", payload)
        self.assertIn("Bob", payload["list_html"])
        self.assertIn("WV", payload["list_html"])
        self.assertNotIn("Alice", payload["list_html"])
        self.assertNotIn("UN", payload["list_html"])


    def test_performance_adjustments_ajax_searches_source_type_display_label(self):
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 10),
            source_type=MetricAdjustment.SOURCE_INCREASE,
            result_count=1,
            support_amount=3000,
            location_name="東京A現場",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 11),
            source_type=MetricAdjustment.SOURCE_POSTAL,
            return_postal_count=1,
            return_postal_amount=1500,
            location_name="東京B現場",
        )

        response = self.client.get(
            reverse("performance_adjustments"),
            {"q": "増額"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        list_html = response.json()["list_html"]
        self.assertIn("東京A現場", list_html)
        self.assertIn("増額", list_html)
        self.assertNotIn("東京B現場", list_html)


    def test_performance_adjustments_ajax_returns_load_more_button(self):
        for index in range(21):
            MetricAdjustment.objects.create(
                member=self.member,
                department=self.department,
                target_date=date(2026, 5, 1) + timedelta(days=index),
                source_type=MetricAdjustment.SOURCE_INCREASE,
                result_count=1,
                support_amount=1000 + index,
                location_name=f"現場{index:02d}",
            )

        response = self.client.get(
            reverse("performance_adjustments"),
            {"page": 2},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("list_html", payload)
        self.assertIn("現場00", payload["list_html"] or "")
        self.assertNotIn("performance-adjustments-load-more-btn", payload["list_html"])


    def test_performance_adjustments_default_list_shows_all_departments(self):
        other_department = self.create_department("WV")
        other_member = self.create_member(name="Bob", department=other_department)
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 10),
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1500,
            location_name="渋谷駅前",
        )
        MetricAdjustment.objects.create(
            member=other_member,
            department=other_department,
            target_date=date(2026, 5, 11),
            source_type=MetricAdjustment.SOURCE_CS,
            support_amount=MemberMetricTransaction.WV_CS_UNIT_AMOUNT,
            result_count=1,
            cs_count=1,
            location_name="横浜駅前",
        )

        response = self.client.get(reverse("performance_adjustments"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice")
        self.assertContains(response, "Bob")
        self.assertContains(response, "UN")
        self.assertContains(response, "WV")


    def test_performance_index_shows_activity_lists_and_progress_with_adjustments(self):
        today = timezone.localdate()
        other_member = Member.objects.create(name="Bob", default_department=self.department)
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="5月第2次路程",
            status="active",
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=5),
        )
        amount_metric = TargetMetric.objects.create(
            department=self.department,
            code="amount",
            label="金額",
            unit="円",
            display_order=1,
            is_active=True,
        )
        MonthTargetMetricValue.objects.create(
            department=self.department,
            target_month=today.replace(day=1),
            metric=amount_metric,
            value=10000,
        )
        PeriodTargetMetricValue.objects.create(
            period=active_period,
            department=self.department,
            metric=amount_metric,
            value=30000,
        )
        active_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
            daily_target_amount=8000,
            location_name="渋谷駅前",
            activity_closed=False,
        )
        finished_entry = MemberDailyMetricEntry.objects.create(
            member=other_member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=2000,
            daily_target_amount=8000,
            location_name="新宿駅前",
            activity_closed=True,
        )
        DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=today,
            daily_target_count=3,
            daily_target_amount=8000,
            created_by=self.member,
            updated_by=self.member,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today,
            support_amount=500,
        )
        MetricAdjustment.objects.create(
            member=other_member,
            department=self.department,
            target_date=today - timedelta(days=1),
            support_amount=1500,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "現在活動中メンバー")
        self.assertContains(response, "活動終了メンバー")
        self.assertContains(response, "今日の合計件数")
        self.assertContains(response, "2件")
        self.assertContains(response, "今日の合計金額")
        self.assertContains(response, "5,000円")
        self.assertContains(response, "8,000円")
        self.assertContains(response, "62.5%")
        self.assertContains(response, active_entry.member.name)
        self.assertContains(response, finished_entry.member.name)
        self.assertContains(response, "3,000円 / 8,000円")
        self.assertContains(response, "2,000円 / 8,000円")
        self.assertContains(response, "目標達成率")
        self.assertContains(response, "70.0%")
        self.assertContains(response, "7,000円")
        self.assertContains(response, "現場: 渋谷駅前")
        self.assertContains(response, "現場: 新宿駅前")
        self.assertContains(response, "補正 2,000円")
        self.assertContains(response, "通常実績")
        self.assertContains(response, "補正実績")
        self.assertContains(response, "残り")
        self.assertContains(response, 'data-chart-values="5000,2000,3000"', html=False)
        self.assertContains(response, "5月第2次路程")
        self.assertContains(response, f"{active_period.start_date:%Y/%m/%d} - {active_period.end_date:%Y/%m/%d}")


    def test_performance_index_streak_uses_adjustment_counts(self):
        today = timezone.localdate()
        for offset in range(3):
            entry = MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=today - timedelta(days=offset),
                result_count=0,
                support_amount=0,
                activity_closed=True,
            )
            if offset == 0:
                MetricAdjustment.objects.create(
                    member=self.member,
                    department=self.department,
                    target_date=entry.entry_date,
                    source_type=MetricAdjustment.SOURCE_INCREASE,
                    result_count=1,
                    support_amount=500,
                )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "3稼働連続0件")


    def test_performance_member_history_shows_scoped_entries_and_adjustments(self):
        today = timezone.localdate()
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="5月第2次路程",
            status="active",
            start_date=today - timedelta(days=3),
            end_date=today + timedelta(days=3),
        )
        entry_today = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
            approach_count=8,
            communication_count=4,
            location_name="渋谷駅前",
        )
        MemberMetricTransaction.objects.create(
            entry=entry_today,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="初回決済",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today,
            source_type=MetricAdjustment.SOURCE_POSTAL,
            return_postal_count=1,
            return_postal_amount=900,
        )
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=today.replace(day=1),
            target_amount=10000,
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=active_period,
            target_amount=20000,
        )

        response = self.client.get(
            reverse("performance_member_history_detail", args=[self.member.id, self.department.id]),
            {"dashboard_scope": "month", "dashboard_month": today.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.member.name} の過去の実績")
        self.assertContains(response, "集計条件")
        self.assertContains(response, "全体の月目標")
        self.assertContains(response, "個人の月目標")
        self.assertContains(response, "日次実績")
        self.assertContains(response, "補正実績")
        self.assertContains(response, entry_today.entry_date.strftime("%Y/%m/%d"))
        self.assertContains(response, "渋谷駅前")
        self.assertContains(response, "郵送")
        self.assertContains(response, ">2件<", html=False)
        self.assertContains(response, "<th>現場</th>", html=False)
        self.assertContains(response, ">-<", html=False)
        self.assertContains(response, "900円")
        self.assertContains(response, "初回決済")
        self.assertContains(response, "<th>操作</th>", html=False)
        self.assertContains(response, 'aria-label="過去の実績を修正"', html=False)
        self.assertContains(response, 'aria-label="日次実績を削除"', html=False)
        self.assertNotContains(response, "<th>状態</th>", html=False)
        self.assertNotContains(response, "<th>メモ</th>", html=False)


    def test_performance_member_history_shows_qr_adjustment_amount_and_count(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today,
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1500,
            location_name="現場A",
        )

        response = self.client.get(
            reverse("performance_member_history_detail", args=[self.member.id, self.department.id]),
            {"dashboard_scope": "month", "dashboard_month": today.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "QR")
        self.assertContains(response, "1件")
        self.assertContains(response, "1500円")
        self.assertContains(response, "補正実績")
        self.assertContains(response, "現場A")


    def test_performance_member_dashboard_trend_includes_adjustment_only_dates(self):
        today = timezone.localdate()
        entry_day = today - timedelta(days=1)
        adjustment_only_day = today - timedelta(days=3)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_day,
            result_count=1,
            support_amount=3000,
            approach_count=4,
            communication_count=2,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=adjustment_only_day,
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1500,
        )

        response = self.client.get(reverse("performance_member_detail", args=[self.member.id, self.department.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["activity_trend"]["labels"],
            [adjustment_only_day.strftime("%m/%d"), entry_day.strftime("%m/%d")],
        )
        self.assertEqual(
            response.context["activity_trend"]["dates"],
            [adjustment_only_day.isoformat(), entry_day.isoformat()],
        )
        self.assertEqual(response.context["activity_trend"]["amounts"], [1500, 3000])
        self.assertEqual(response.context["activity_trend"]["counts"], [1, 1])
