from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Member, MemberDepartment
from apps.dairymetrics.models import MemberDailyMetricEntry, MemberMetricTransaction, MemberMonthMetricTarget, MemberPeriodMetricTarget, MetricAdjustment
from apps.performance.services.member_ajax import build_member_dashboard_detail_context
from apps.performance.services.member_details import build_member_dashboard_entry_rows
from apps.performance.services.formatters import field_amount_text, field_count_text
from apps.targets.models import Period
from .base import PerformanceTestBase

User = get_user_model()


class MemberPagesTests(PerformanceTestBase):
    def test_member_dashboard_entry_rows_prefetch_transactions_in_fixed_query_count(self):
        entries = [
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=date(2026, 8, day),
            )
            for day in (8, 9, 10)
        ]
        expected_transaction_ids = {}
        for entry in entries:
            transactions = [
                MemberMetricTransaction.objects.create(
                    entry=entry,
                    support_amount=amount,
                    age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
                    gender=MemberMetricTransaction.GENDER_FEMALE,
                    nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
                )
                for amount in (1000, 2000)
            ]
            expected_transaction_ids[entry.id] = [transaction.id for transaction in transactions]

        with self.assertNumQueries(3):
            rows = build_member_dashboard_entry_rows(
                member=self.member,
                department=self.department,
                month_start=date(2026, 8, 1),
                month_end=date(2026, 8, 31),
                field_count_text=field_count_text,
                field_amount_text=field_amount_text,
            )

        self.assertEqual([row["entry"].id for row in rows], [entry.id for entry in reversed(entries)])
        self.assertEqual(
            [[transaction.id for transaction in row["transactions"]] for row in rows],
            [expected_transaction_ids[entry.id] for entry in reversed(entries)],
        )

    def test_member_dashboard_day_detail_context_uses_each_history_route(self):
        common = {
            "member": self.member,
            "department": self.department,
            "entry_rows": [],
            "adjustment_rows": [],
            "selected_date": date(2026, 8, 10),
        }

        admin_context = build_member_dashboard_detail_context(is_admin=True, **common)
        member_context = build_member_dashboard_detail_context(**common)
        readonly_context = build_member_dashboard_detail_context(readonly_member_view=True, **common)

        self.assertEqual(
            admin_context["detail_history_url"],
            reverse("performance_member_history_detail", args=[self.member.id, self.department.id]),
        )
        self.assertEqual(member_context["detail_history_url"], reverse("performance_member_history"))
        self.assertEqual(
            readonly_context["detail_history_url"],
            reverse("performance_member_history_insight", args=[self.member.id, self.department.id]),
        )

    def test_performance_member_detail_day_detail_returns_selected_day(self):
        selected_day = timezone.localdate() - timedelta(days=1)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_day,
            result_count=1,
            support_amount=3000,
            activity_closed=True,
            location_name="日別ドリルダウン現場",
        )

        response = self.client.get(
            reverse("performance_member_detail_day_detail", args=[self.member.id, self.department.id]),
            {"date": selected_day.isoformat()},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{selected_day:%Y/%m/%d} の実績")
        self.assertContains(response, "日別ドリルダウン現場")

    def test_performance_member_dashboard_nav_includes_report_app(self):
        self.client.logout()
        member_user = User.objects.create_user(username="perf-member-report-nav", password="pass1234", is_staff=False)
        self.member.user = member_user
        self.member.save(update_fields=["user"])
        self.client.force_login(member_user)

        response = self.client.get(reverse("performance_member_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("report_index"))
        self.assertContains(response, "振り返りレポート")
        self.assertContains(response, reverse("dairymetrics_metrics_report"))


    def test_performance_member_dashboard_shows_own_closeout_notes_collapsed(self):
        self.client.logout()
        member_user = User.objects.create_user(username="perf-member-closeout-notes", password="pass1234", is_staff=False)
        self.member.user = member_user
        self.member.save(update_fields=["user"])
        other_member = self.create_member(name="Bob", department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 6, 1),
            memo="次は質問の順番を変えて試す。",
        )
        MemberDailyMetricEntry.objects.create(
            member=other_member,
            department=self.department,
            entry_date=date(2026, 6, 1),
            memo="他メンバーのメモ",
        )
        self.client.force_login(member_user)

        response = self.client.get(reverse("performance_member_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<details>", html=False)
        self.assertContains(response, "自分のあと一歩ノート")
        self.assertContains(response, "次は質問の順番を変えて試す。")
        self.assertNotContains(response, "他メンバーのメモ")


    def test_performance_member_dashboard_redirects_to_performance_login(self):
        self.client.logout()

        response = self.client.get(reverse("performance_member_dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('performance_login')}?next={reverse('performance_member_dashboard')}",
        )


    def test_performance_history_defaults_dashboard_department_to_member_default_for_report_role(self):
        self.client.logout()
        member_user, member_profile = self.create_member_user(
            username="perf-history-member",
            name="History Member",
            department=self.department,
            default_department=self.department,
        )
        other_department = self.create_department("WV")
        MemberDepartment.objects.create(member=member_profile, department=other_department)
        self.client.force_login(member_user)

        response = self.client.get(reverse("performance_history"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_department"].id, self.department.id)


    def test_performance_login_redirects_member_to_member_dashboard(self):
        self.client.logout()
        member_user = User.objects.create_user(username="perf-member-login", password="pass1234", is_staff=False)
        self.member.user = member_user
        self.member.save(update_fields=["user"])

        response = self.client.post(
            reverse("performance_login"),
            {"login_id": "perf-member-login", "password": "pass1234"},
        )

        self.assertRedirects(response, reverse("performance_member_dashboard"))


    def test_performance_index_shows_active_member_cards_with_detail_link(self):
        today = timezone.localdate()
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="5月第2次路程",
            status="active",
            start_date=today - timedelta(days=3),
            end_date=today + timedelta(days=3),
        )
        active_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
            activity_closed=False,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today - timedelta(days=1),
            result_count=2,
            support_amount=2500,
            activity_closed=True,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today,
            support_amount=500,
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

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "有効メンバー一覧")
        self.assertContains(response, self.member.name)
        self.assertContains(response, "今月累計")
        self.assertContains(response, "路程累計")
        self.assertContains(response, "直近の実績")
        self.assertContains(response, reverse("performance_member_insight", args=[self.member.id, self.department.id]))


    def test_performance_member_dashboard_syncs_finished_period_when_dates_overlap_today(self):
        today = timezone.localdate()
        period = Period.objects.create(
            month=today.replace(day=1),
            name=f"{today.year}年度{today.month}月 第1次路程",
            status="finished",
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=period,
            target_amount=9999,
        )
        self.client.logout()
        member_user = User.objects.create_user(username="perf-member-finished-period", password="pass1234", is_staff=False)
        self.member.user = member_user
        self.member.save(update_fields=["user"])
        self.client.force_login(member_user)

        response = self.client.get(reverse("performance_member_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "9,999円")
        period.refresh_from_db()
        self.assertEqual(period.status, "active")


    def test_performance_member_detail_uses_active_period_even_if_finished_period_param_exists(self):
        today = timezone.localdate()
        finished_period = Period.objects.create(
            month=today.replace(day=1),
            name="終了済み個人路程",
            status="finished",
            start_date=today - timedelta(days=14),
            end_date=today - timedelta(days=7),
        )
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="現在Active個人路程",
            status="active",
            start_date=today,
            end_date=today + timedelta(days=6),
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=finished_period,
            target_amount=9999,
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=active_period,
            target_amount=20000,
        )

        response = self.client.get(
            reverse("performance_member_detail", args=[self.member.id, self.department.id]),
            {"dashboard_period": str(finished_period.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["period_label"], active_period.name)
        self.assertContains(response, "現在Active個人路程")
        self.assertNotContains(response, "終了済み個人路程進捗")


    def test_performance_member_detail_shows_realtime_dashboard(self):
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
        )
        entry_old = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today - timedelta(days=1),
            result_count=2,
            support_amount=2500,
            approach_count=6,
            communication_count=3,
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

        response = self.client.get(reverse("performance_member_detail", args=[self.member.id, self.department.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.member.name} の実績ダッシュボード")
        self.assertContains(response, "直近稼働の実績推移")
        self.assertContains(response, "performance-activity-trend-chart")
        self.assertContains(response, "-10")
        self.assertContains(response, "+10")
        self.assertContains(response, "日目達成率")
        self.assertContains(response, "AP/CM")
        self.assertContains(response, entry_today.entry_date.strftime("%m/%d"))
        self.assertContains(response, "全体の月目標")
        self.assertContains(response, "全体の路程目標")
        self.assertContains(response, "個人の月目標")
        self.assertContains(response, "個人の路程目標")
        self.assertContains(response, "Aliceさんの割合")
        self.assertContains(response, "9,400円 / 9,400円")
        self.assertContains(response, "月目標")
        self.assertContains(response, "修正")
        self.assertContains(response, "直近30日の実績")
        self.assertContains(response, "直近30日の補正実績")
        self.assertContains(response, f'{reverse("dairymetrics_metrics_v2_demo")}?department={self.department.code}')
        self.assertEqual(response.context["activity_trend"]["amounts"], [2500, 6900])
        self.assertEqual(response.context["activity_trend"]["counts"], [2, 3])
        self.assertContains(response, "補正実績件数")
        self.assertContains(response, "1件")
        self.assertContains(response, "補正実績金額")
        self.assertContains(response, "900円")


    def test_performance_member_detail_limits_recent_dashboard_rows_to_five(self):
        today = timezone.localdate()
        created_dates = []
        for offset in range(7):
            entry_date = today - timedelta(days=offset)
            created_dates.append(entry_date)
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=entry_date,
                result_count=offset + 1,
                support_amount=1000 * (offset + 1),
                activity_closed=True,
                location_name="渋谷駅前" if offset == 0 else "",
            )

        response = self.client.get(reverse("performance_member_detail", args=[self.member.id, self.department.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["recent_entry_rows"]), 5)
        self.assertContains(response, created_dates[0].strftime("%Y/%m/%d"))
        self.assertContains(response, created_dates[4].strftime("%Y/%m/%d"))
        self.assertContains(response, "渋谷駅前")
        self.assertNotContains(response, created_dates[5].strftime("%Y/%m/%d"))
        self.assertContains(response, "さらに5件表示")
        self.assertContains(response, 'data-performance-recent-date-search', html=False)


    def test_performance_member_detail_recent_detail_ajax_filters_by_date(self):
        today = timezone.localdate()
        selected_day = today - timedelta(days=1)
        other_day = today - timedelta(days=3)
        selected_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_day,
            result_count=1,
            support_amount=3000,
            activity_closed=True,
            location_name="現場A",
        )
        other_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=other_day,
            result_count=2,
            support_amount=4500,
            activity_closed=True,
            location_name="現場B",
        )
        MemberMetricTransaction.objects.create(
            entry=selected_entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="選択日決済",
        )
        MemberMetricTransaction.objects.create(
            entry=other_entry,
            support_amount=4500,
            age_band=MemberMetricTransaction.AGE_BAND_THIRTIES,
            gender=MemberMetricTransaction.GENDER_MALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="池袋",
            comment="別日決済",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=selected_day,
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1200,
            location_name="現場A",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=other_day,
            source_type=MetricAdjustment.SOURCE_POSTAL,
            return_postal_count=1,
            return_postal_amount=700,
            location_name="現場B",
        )

        response = self.client.get(
            reverse("performance_member_detail_recent_detail", args=[self.member.id, self.department.id]),
            {"date": selected_day.isoformat(), "limit": 5},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "選択日決済")
        self.assertContains(response, "現場A")
        self.assertContains(response, 'data-label="現場">現場A', html=False)
        self.assertNotContains(response, "別日決済")
        self.assertNotContains(response, "現場B")
        self.assertNotContains(response, "さらに5件表示")


    def test_performance_member_dashboard_recent_detail_uses_logged_in_member(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-recent", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        selected_day = timezone.localdate() - timedelta(days=2)
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_day,
            result_count=1,
            support_amount=2500,
            activity_closed=True,
        )
        MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=2500,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="新宿",
            comment="本人 recent detail",
        )
        self.client.force_login(report_user)

        response = self.client.get(
            reverse("performance_member_dashboard_recent_detail"),
            {"date": selected_day.isoformat()},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "本人 recent detail")
        self.assertContains(response, reverse("performance_member_dashboard"))


    def test_performance_member_history_limits_initial_rows_to_five(self):
        today = timezone.localdate()
        for offset in range(7):
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=today - timedelta(days=offset),
                result_count=1,
                support_amount=1000 * (offset + 1),
                activity_closed=True,
            )

        response = self.client.get(
            reverse("performance_member_history_detail", args=[self.member.id, self.department.id]),
            {"dashboard_scope": "month", "dashboard_month": today.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["entry_rows"]), 5)
        self.assertContains(response, "さらに5件表示")
        self.assertContains(response, 'data-performance-history-date-links', html=False)


    def test_performance_history_includes_inactive_member_with_scope_records(self):
        today = timezone.localdate()
        inactive_user, inactive_member = self.create_member_user(
            username="inactive_history_member",
            password="pass123",
            name="Inactive History",
            department=self.department,
        )
        inactive_member.is_active = False
        inactive_member.save(update_fields=["is_active"])
        MemberDailyMetricEntry.objects.create(
            member=inactive_member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=2000,
            activity_closed=True,
        )

        response = self.client.get(
            reverse("performance_history"),
            {"dashboard_scope": "month", "dashboard_month": today.strftime("%Y-%m"), "department": self.department.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inactive History")


    def test_performance_member_history_range_uses_date_input_filter(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today - timedelta(days=1),
            result_count=1,
            support_amount=1500,
            activity_closed=True,
        )

        response = self.client.get(
            reverse("performance_member_history_detail", args=[self.member.id, self.department.id]),
            {
                "dashboard_scope": "range",
                "dashboard_start": (today - timedelta(days=10)).isoformat(),
                "dashboard_end": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-performance-history-date-search', html=False)
        self.assertNotContains(response, 'data-performance-history-date-links', html=False)


    def test_performance_member_history_day_detail_returns_selected_day_rows(self):
        today = timezone.localdate()
        selected_day = today - timedelta(days=1)
        other_day = today - timedelta(days=2)
        selected_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_day,
            result_count=1,
            support_amount=3000,
            approach_count=5,
            communication_count=2,
            activity_closed=True,
        )
        other_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=other_day,
            result_count=2,
            support_amount=6000,
            approach_count=8,
            communication_count=4,
            activity_closed=True,
        )
        MemberMetricTransaction.objects.create(
            entry=selected_entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="選択日の決済",
        )
        MemberMetricTransaction.objects.create(
            entry=other_entry,
            support_amount=6000,
            age_band=MemberMetricTransaction.AGE_BAND_THIRTIES,
            gender=MemberMetricTransaction.GENDER_MALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="池袋",
            comment="別日の決済",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=selected_day,
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1200,
            location_name="現場A",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=other_day,
            source_type=MetricAdjustment.SOURCE_POSTAL,
            return_postal_count=1,
            return_postal_amount=700,
            location_name="現場B",
        )

        response = self.client.get(
            reverse("performance_member_history_detail_day_detail", args=[self.member.id, self.department.id]),
            {"date": selected_day.isoformat()},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{selected_day:%Y/%m/%d} の日次実績")
        self.assertContains(response, "選択日の決済")
        self.assertContains(response, "現場A")
        self.assertContains(response, "1200円")
        self.assertNotContains(response, "別日の決済")
        self.assertNotContains(response, "現場B")


    def test_performance_member_history_day_detail_uses_logged_in_member(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-day-detail", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        selected_day = timezone.localdate() - timedelta(days=1)
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_day,
            result_count=1,
            support_amount=2500,
            activity_closed=True,
        )
        MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=2500,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="新宿",
            comment="本人日次",
        )
        self.client.force_login(report_user)

        response = self.client.get(
            reverse("performance_member_history_day_detail"),
            {"date": selected_day.isoformat()},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "本人日次")
        self.assertContains(response, reverse("performance_member_history"))


    def test_performance_member_history_list_ajax_filters_by_date(self):
        today = timezone.localdate()
        selected_day = today - timedelta(days=1)
        other_day = today - timedelta(days=3)
        selected_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_day,
            result_count=1,
            support_amount=3000,
            activity_closed=True,
        )
        other_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=other_day,
            result_count=2,
            support_amount=4500,
            activity_closed=True,
        )
        MemberMetricTransaction.objects.create(
            entry=selected_entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="履歴選択日",
        )
        MemberMetricTransaction.objects.create(
            entry=other_entry,
            support_amount=4500,
            age_band=MemberMetricTransaction.AGE_BAND_THIRTIES,
            gender=MemberMetricTransaction.GENDER_MALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="池袋",
            comment="履歴別日",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=selected_day,
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1200,
            location_name="現場A",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=other_day,
            source_type=MetricAdjustment.SOURCE_POSTAL,
            return_postal_count=1,
            return_postal_amount=700,
            location_name="現場B",
        )

        response = self.client.get(
            reverse("performance_member_history_detail_list", args=[self.member.id, self.department.id]),
            {
                "dashboard_scope": "month",
                "dashboard_month": today.strftime("%Y-%m"),
                "date": selected_day.isoformat(),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "履歴選択日")
        self.assertContains(response, "現場A")
        self.assertNotContains(response, "履歴別日")
        self.assertNotContains(response, "現場B")


    def test_performance_member_detail_shows_target_forms_when_edit_requested(self):
        today = timezone.localdate()
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=today.replace(day=1),
            target_amount=10000,
        )

        response = self.client.get(
            reverse("performance_member_detail", args=[self.member.id, self.department.id]),
            {"month": today.strftime("%Y-%m"), "edit_month_target": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "月目標を保存")


    def test_performance_member_dashboard_uses_logged_in_member_profile(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=timezone.localdate().replace(day=1),
            target_amount=9000,
        )
        self.client.force_login(report_user)

        response = self.client.get(reverse("performance_member_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.member.name} の実績ダッシュボード")
        self.assertContains(response, "個人の月目標")
        self.assertContains(response, "直近30日の実績")
        self.assertContains(response, "直近30日の補正実績")
        self.assertContains(response, reverse("performance_member_history"))
        self.assertContains(response, "実績管理ダッシュボード")
        self.assertContains(response, "全体実績")
        self.assertContains(response, reverse("performance_index"))
        self.assertContains(response, "決済入力")
        self.assertContains(response, "過去の実績を見る")
        self.assertContains(response, "分析する")
        self.assertContains(response, "振り返りレポート")
        self.assertContains(response, reverse("dairymetrics_metrics_report"))
        self.assertContains(response, reverse("talks_index"))
        self.assertContains(response, reverse("performance_closeout_notes"))
        self.assertNotContains(response, "総合管理者ページ")


    def test_performance_member_can_open_overall_dashboard_and_history(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-overall", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        self.client.force_login(report_user)

        dashboard_response = self.client.get(reverse("performance_index"))
        history_response = self.client.get(reverse("performance_history"))

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertContains(dashboard_response, "本日の活動状況")
        self.assertContains(dashboard_response, "全体実績")
        self.assertEqual(history_response.status_code, 200)
        self.assertContains(history_response, "集計条件")
        self.assertContains(history_response, "全体実績")


    def test_performance_member_insight_is_readonly_for_member_viewer(self):
        self.client.logout()
        viewer_user = User.objects.create_user(username="perf-viewer", password="pass1234", is_staff=False)
        self.member.user = viewer_user
        self.member.save(update_fields=["user"])
        teammate = Member.objects.create(name="Teammate", default_department=self.department)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberMonthMetricTarget.objects.create(
            member=teammate,
            department=self.department,
            target_month=timezone.localdate().replace(day=1),
            target_amount=8000,
        )
        self.client.force_login(viewer_user)

        response = self.client.get(reverse("performance_member_insight", args=[teammate.id, self.department.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{teammate.name} の実績ダッシュボード")
        self.assertContains(
            response,
            f'{reverse("dairymetrics_metrics_v2_demo")}?department={self.department.code}&member={teammate.id}',
        )
        self.assertContains(response, reverse("performance_member_insight", args=[teammate.id, self.department.id]))
        self.assertContains(response, reverse("performance_member_history_insight", args=[teammate.id, self.department.id]))
        self.assertNotContains(response, "このメンバーの 分析する")
        self.assertNotContains(response, "月目標を保存")
        self.assertNotContains(response, "路程目標を保存")


    def test_admin_member_detail_menu_links_to_that_members_history(self):
        response = self.client.get(reverse("performance_member_detail", args=[self.member.id, self.department.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("performance_index"))
        self.assertContains(response, reverse("performance_member_detail", args=[self.member.id, self.department.id]))
        self.assertContains(response, reverse("performance_member_history_detail", args=[self.member.id, self.department.id]))


    def test_performance_member_history_uses_logged_in_member_profile(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-history", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate(),
            result_count=1,
            support_amount=3000,
        )
        self.client.force_login(report_user)

        response = self.client.get(reverse("performance_member_history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.member.name} の過去の実績")
        self.assertContains(response, "集計条件")
        self.assertContains(response, "実績管理ダッシュボード")
        self.assertContains(response, "決済入力")
        self.assertContains(response, "分析する")


    def test_performance_member_history_shows_transaction_edit_link(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-history-link", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate(),
            result_count=0,
            support_amount=0,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="初回決済",
        )
        self.client.force_login(report_user)

        response = self.client.get(reverse("performance_member_history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("performance_transaction_edit", args=[transaction.id]))


    def test_performance_member_can_edit_own_transaction_from_history_flow(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-tx-edit", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate() - timedelta(days=1),
            result_count=0,
            support_amount=0,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="初回決済",
        )
        self.client.force_login(report_user)

        response = self.client.post(
            f"{reverse('performance_transaction_edit', args=[transaction.id])}?next={reverse('performance_member_history')}",
            {
                "support_amount": 4200,
                "wv_result_type": "",
                "wv_cs_count": 0,
                "wv_refugee_amount": 0,
                "location": "渋谷",
                "age_band": MemberMetricTransaction.AGE_BAND_TWENTIES,
                "is_student": "",
                "gender": MemberMetricTransaction.GENDER_FEMALE,
                "nationality_type": MemberMetricTransaction.NATIONALITY_DOMESTIC,
                "comment": "金額修正",
                "next": reverse("performance_member_history"),
            },
        )

        self.assertRedirects(response, f"{reverse('performance_member_history')}?updated=transaction")
        transaction.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(transaction.support_amount, 4200)
        self.assertEqual(entry.support_amount, 4200)


    def test_admin_member_history_insight_shows_edit_and_delete_actions(self):
        teammate = Member.objects.create(name="Teammate", default_department=self.department)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        entry = MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=timezone.localdate(),
            result_count=1,
            support_amount=3000,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="管理者確認",
        )

        response = self.client.get(
            reverse("performance_member_history_insight", args=[teammate.id, self.department.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("performance_entry_edit", args=[entry.id]))
        self.assertContains(response, reverse("performance_entry_delete", args=[entry.id]))
        self.assertContains(response, reverse("performance_transaction_edit", args=[transaction.id]))


    def test_performance_member_detail_can_save_month_target(self):
        today = timezone.localdate()

        response = self.client.post(
            f"{reverse('performance_member_detail', args=[self.member.id, self.department.id])}?month={today:%Y-%m}",
            {
                "action": "save_month_target",
                "department": self.department.id,
                "target_count": 3,
                "target_amount": 12000,
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_member_detail', args=[self.member.id, self.department.id])}?month={today:%Y-%m}&saved=target",
        )
        target = MemberMonthMetricTarget.objects.get(
            member=self.member,
            department=self.department,
            target_month=today.replace(day=1),
        )
        self.assertEqual(target.target_count, 3)
        self.assertEqual(target.target_amount, 12000)


    def test_performance_member_detail_can_save_wv_month_target_with_split_counts(self):
        today = timezone.localdate()
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="Wv Member", department=wv_department)

        response = self.client.post(
            f"{reverse('performance_member_detail', args=[wv_member.id, wv_department.id])}?month={today:%Y-%m}",
            {
                "action": "save_month_target",
                "department": wv_department.id,
                "target_cs_count": 4,
                "target_refugee_count": 3,
                "target_amount": 28000,
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_member_detail', args=[wv_member.id, wv_department.id])}?month={today:%Y-%m}&saved=target",
        )
        target = MemberMonthMetricTarget.objects.get(
            member=wv_member,
            department=wv_department,
            target_month=today.replace(day=1),
        )
        self.assertEqual(target.target_cs_count, 4)
        self.assertEqual(target.target_refugee_count, 3)
        self.assertEqual(target.target_count, 7)
        self.assertEqual(target.target_amount, 28000)


    def test_performance_member_detail_can_save_wv_period_target_with_split_counts(self):
        today = timezone.localdate()
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="Wv Period Member", department=wv_department)
        current_period = Period.objects.create(
            name="2026年5月 第4次路程",
            month=today.replace(day=1),
            status="active",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=2),
        )

        response = self.client.post(
            f"{reverse('performance_member_detail', args=[wv_member.id, wv_department.id])}?month={today:%Y-%m}",
            {
                "action": "save_period_target",
                "department": wv_department.id,
                "target_cs_count": 5,
                "target_refugee_count": 2,
                "target_amount": 32000,
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_member_detail', args=[wv_member.id, wv_department.id])}?month={today:%Y-%m}&saved=target",
        )
        target = MemberPeriodMetricTarget.objects.get(
            member=wv_member,
            department=wv_department,
            period=current_period,
        )
        self.assertEqual(target.target_cs_count, 5)
        self.assertEqual(target.target_refugee_count, 2)
        self.assertEqual(target.target_count, 7)
        self.assertEqual(target.target_amount, 32000)
