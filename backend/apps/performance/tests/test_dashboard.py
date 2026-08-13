from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Department, Member, MemberDepartment
from apps.dairymetrics.models import MemberDailyMetricEntry, MemberMetricTransaction, MetricAdjustment
from apps.mail.models import MailSendHistory
from apps.targets.models import MonthTargetMetricValue, Period, PeriodTargetMetricValue, TargetMetric
from .base import PerformanceTestBase


class DashboardTests(PerformanceTestBase):
    def test_performance_index_does_not_show_manual_activity_reminder(self):
        active_member = self.create_member(name="活動中メンバー", department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=active_member,
            department=self.department,
            entry_date=timezone.localdate(),
            activity_closed=False,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "活動中メンバー")
        self.assertNotContains(response, "入力リマインド")
        self.assertNotContains(response, "/remind/")

    def test_performance_index_wv_overall_activity_trend_does_not_double_count_counts(self):
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV Member", department=wv_department)
        entry_date = date(2026, 6, 4)
        MemberDailyMetricEntry.objects.create(
            member=wv_member,
            department=wv_department,
            entry_date=entry_date,
            result_count=2,
            support_amount=6000,
            cs_count=1,
            refugee_count=1,
            approach_count=5,
            communication_count=2,
        )
        MetricAdjustment.objects.create(
            member=wv_member,
            department=wv_department,
            target_date=entry_date,
            support_amount=1500,
            result_count=1,
            cs_count=1,
            refugee_count=0,
        )

        response = self.client.get(reverse("performance_index"), {"dashboard_department": wv_department.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_snapshot"]["overall_activity_trend"]["counts"], [3])
        self.assertEqual(response.context["dashboard_snapshot"]["overall_activity_trend"]["cs_counts"], [2])
        self.assertEqual(response.context["dashboard_snapshot"]["overall_activity_trend"]["refugee_counts"], [1])


    def test_performance_index_defaults_dashboard_department_to_un(self):
        other_department = Department.objects.create(code="WV", name="WV", is_active=True)
        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_department"].code, "UN")
        self.assertContains(response, "月目標達成率")


    def test_performance_index_uses_active_period_even_if_finished_period_param_exists(self):
        today = timezone.localdate()
        finished_period = Period.objects.create(
            month=today.replace(day=1),
            name="終了済み路程",
            status="finished",
            start_date=today - timedelta(days=14),
            end_date=today - timedelta(days=7),
        )
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="現在Active路程",
            status="active",
            start_date=today,
            end_date=today + timedelta(days=6),
        )

        response = self.client.get(
            reverse("performance_index"),
            {"dashboard_period": str(finished_period.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_period"].id, active_period.id)
        self.assertContains(response, "現在Active路程")
        self.assertNotContains(response, "終了済み路程進捗")


    def test_performance_history_ignores_finished_period_param_unless_period_scope(self):
        today = timezone.localdate()
        finished_period = Period.objects.create(
            month=today.replace(day=1),
            name="終了済み路程",
            status="finished",
            start_date=today - timedelta(days=14),
            end_date=today - timedelta(days=7),
        )
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="現在Active路程",
            status="active",
            start_date=today,
            end_date=today + timedelta(days=6),
        )

        response = self.client.get(
            reverse("performance_history"),
            {
                "dashboard_scope": "month",
                "dashboard_department": str(self.department.id),
                "dashboard_period": str(finished_period.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_period"].id, active_period.id)


    def test_performance_index_can_switch_dashboard_department(self):
        other_department = Department.objects.create(code="WV", name="WV", is_active=True)

        response = self.client.get(reverse("performance_index"), {"dashboard_department": other_department.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_department"].id, other_department.id)
        self.assertContains(
            response,
            f'<option value="{other_department.id}" selected>WV</option>',
            html=True,
        )

    def test_performance_index_places_ajax_department_switch_in_header(self):
        other_department = Department.objects.create(code="WV", name="West View", is_active=True)

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-performance-department-switch-root", html=False)
        self.assertContains(response, "data-performance-department-switch", html=False)
        self.assertContains(response, 'data-switch-url="/performance/"', html=False)
        self.assertContains(response, 'data-performance-dashboard-content', html=False)
        self.assertContains(response, "performance/department_switch.js", html=False)
        self.assertNotContains(response, ">表示</button>", html=False)
        header_html = response.content.decode("utf-8").split("</header>", 1)[0]
        self.assertLess(header_html.index("実績管理"), header_html.index("performance-dashboard-department"))
        self.assertLess(header_html.index("performance-dashboard-department"), header_html.index("dashboard-drawer-toggle"))
        self.assertIn(f'<option value="{other_department.id}">WV (West View)</option>', header_html)


    def test_performance_index_auto_closes_stale_open_entries(self):
        stale_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate() - timedelta(days=1),
            result_count=1,
            support_amount=1000,
            activity_closed=False,
            activity_closed_at=None,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        stale_entry.refresh_from_db()
        self.assertTrue(stale_entry.activity_closed)
        self.assertIsNotNone(stale_entry.activity_closed_at)


    def test_performance_login_redirects_admin_to_admin_dashboard(self):
        self.client.logout()

        response = self.client.post(
            reverse("performance_login"),
            {"login_id": "perf-admin", "password": "pass1234"},
        )

        self.assertRedirects(response, reverse("performance_index"))


    def test_performance_logout_redirects_to_performance_login(self):
        response = self.client.get(reverse("performance_logout"))

        self.assertRedirects(response, reverse("performance_login"))


    def test_performance_history_uses_selected_month_and_period_for_progress_cards(self):
        today = timezone.localdate()
        selected_month = date(today.year, 4, 1)
        selected_period = Period.objects.create(
            month=selected_month,
            name="4月第2次路程",
            status="closed",
            start_date=selected_month,
            end_date=selected_month + timedelta(days=6),
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
            target_month=selected_month,
            metric=amount_metric,
            value=12000,
        )
        PeriodTargetMetricValue.objects.create(
            period=selected_period,
            department=self.department,
            metric=amount_metric,
            value=28000,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_month + timedelta(days=1),
            result_count=1,
            support_amount=4500,
        )

        response = self.client.get(
            reverse("performance_history"),
            {
                "dashboard_scope": "period",
                "dashboard_department": str(self.department.id),
                "dashboard_month": selected_month.strftime("%Y-%m"),
                "dashboard_period": str(selected_period.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "4月第2次路程")
        self.assertContains(response, f"{selected_period.start_date:%Y/%m/%d} - {selected_period.end_date:%Y/%m/%d}")
        self.assertContains(response, "4,500円")
        self.assertContains(response, "16.1%")
        self.assertContains(response, 'class="card performance-history-value-card"')
        self.assertContains(response, 'class="performance-history-track"')
        self.assertContains(response, "過去の実績を見る")


    def test_performance_index_and_history_show_today_transaction_and_mail_details(self):
        today = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
            approach_count=4,
            communication_count=2,
            location_name="渋谷駅前",
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="当日詳細",
        )
        MailSendHistory.objects.create(
            department=self.department,
            activity_date=today,
            sender_member=self.member,
            transaction=transaction,
            subject_snapshot="【UN】当日送信",
            body_snapshot="本文です",
            sent_to_snapshot="group@example.com",
            status=MailSendHistory.STATUS_SENT,
            is_test=False,
            sent_at=timezone.now(),
            last_attempt_at=timezone.now(),
        )

        index_response = self.client.get(reverse("performance_index"))
        history_response = self.client.get(reverse("performance_history"))

        self.assertEqual(index_response.status_code, 200)
        self.assertContains(index_response, "本日の決済詳細")
        self.assertContains(index_response, "本日の送信メール詳細")
        self.assertContains(index_response, "本日の記録")
        self.assertContains(index_response, '<span class="performance-record-tab-count">1件</span>', count=2)
        self.assertContains(index_response, 'role="tablist"')
        self.assertContains(index_response, 'data-performance-record-panel="transactions"')
        self.assertContains(index_response, 'data-performance-record-panel="mails"')
        self.assertContains(index_response, 'class="performance-record-card performance-transaction-record-card"')
        self.assertContains(index_response, 'class="performance-record-card performance-mail-record-card"')
        self.assertContains(index_response, 'class="performance-mail-status is-sent">送信済み</span>')
        self.assertContains(index_response, "詳細を見る")
        self.assertContains(index_response, "メール内容を見る")
        self.assertNotContains(index_response, 'class="mobile-card-table performance-recent-detail-table"')
        self.assertContains(index_response, 'class="card ui-section mt-16 performance-dashboard-section"')
        self.assertContains(index_response, 'class="ui-section-kicker performance-dashboard-section-kicker">TODAY</span>')
        self.assertContains(index_response, 'class="ui-section-kicker performance-dashboard-section-kicker">RECORDS</span>')
        self.assertContains(index_response, 'class="ui-section-kicker performance-dashboard-section-kicker">PROGRESS</span>')
        self.assertContains(index_response, 'class="ui-section-kicker performance-dashboard-section-kicker">TREND</span>')
        self.assertContains(index_response, 'class="ui-section-kicker performance-dashboard-section-kicker">MEMBERS</span>')
        self.assertContains(index_response, 'class="app-header-department-switch"')
        self.assertContains(index_response, 'data-performance-department-switch')
        self.assertContains(index_response, 'class="performance-member-status-filters ui-tabs mt-12"')
        self.assertContains(index_response, 'class="card performance-progress-card performance-dashboard-inner-card"')
        self.assertContains(index_response, 'class="performance-chart-card performance-dashboard-inner-card mt-12"')
        self.assertContains(index_response, 'class="performance-activity-grid mt-12"')
        self.assertContains(index_response, 'class="performance-activity-group performance-activity-group-active"')
        self.assertContains(index_response, 'class="performance-activity-group performance-activity-group-finished"')
        self.assertContains(index_response, 'class="performance-activity-member-result"')
        self.assertContains(index_response, "【UN】当日送信")
        self.assertContains(index_response, "本文です")
        index_content = index_response.content.decode()
        self.assertLess(index_content.index("本日の活動状況"), index_content.index("本日の決済詳細"))
        self.assertLess(index_content.index("本日の決済詳細"), index_content.index("本日の送信メール詳細"))
        self.assertLess(index_content.index("本日の送信メール詳細"), index_content.index("目標達成率"))
        self.assertEqual(history_response.status_code, 200)
        self.assertContains(history_response, "本日の決済詳細")
        self.assertContains(history_response, "本日の送信メール詳細")
        self.assertContains(history_response, "【UN】当日送信")


    def test_performance_index_shows_enabled_member_card_without_today_entry(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today - timedelta(days=2),
            result_count=2,
            support_amount=2800,
            activity_closed=True,
        )


    def test_performance_index_shows_wv_total_count_with_breakdown_subtext(self):
        today = timezone.localdate()
        self.department.code = "WV"
        self.department.name = "WV"
        self.department.save(update_fields=["code", "name"])
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            support_amount=6500,
            result_count=2,
            cs_count=1,
            refugee_count=1,
            activity_closed=True,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=entry.entry_date,
            source_type=MetricAdjustment.SOURCE_CS,
            support_amount=MemberMetricTransaction.WV_CS_UNIT_AMOUNT,
            result_count=1,
            cs_count=1,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3件")
        self.assertContains(response, "(CS 2件 / 難民 1件)")


    def test_performance_index_orders_enabled_member_cards_by_recent_entry_desc(self):
        today = timezone.localdate()
        newer_member = Member.objects.create(name="Newer", default_department=self.department)
        older_member = Member.objects.create(name="Older", default_department=self.department)
        MemberDepartment.objects.create(member=newer_member, department=self.department)
        MemberDepartment.objects.create(member=older_member, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=older_member,
            department=self.department,
            entry_date=today - timedelta(days=3),
            support_amount=1000,
        )
        MemberDailyMetricEntry.objects.create(
            member=newer_member,
            department=self.department,
            entry_date=today - timedelta(days=1),
            support_amount=2000,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertLess(content.index("Newer"), content.index("Older"))


    def test_performance_index_marks_member_when_last_three_entries_are_zero_count(self):
        today = timezone.localdate()
        for offset in range(3):
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=today - timedelta(days=offset),
                result_count=0,
                support_amount=0,
                activity_closed=True,
            )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3稼働連続0件")
        self.assertContains(response, 'data-member-status="warning"')
        for offset in (2, 1, 0):
            self.assertContains(response, (today - timedelta(days=offset)).strftime("%-m/%-d"))


    def test_performance_index_does_not_mark_zero_streak_until_third_entry_is_closed(self):
        today = timezone.localdate()
        for offset in (1, 2):
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=today - timedelta(days=offset),
                result_count=0,
                support_amount=0,
                activity_closed=True,
            )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=0,
            support_amount=0,
            activity_closed=False,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "3稼働連続0件")


    def test_performance_index_marks_member_when_last_three_entries_have_results(self):
        today = timezone.localdate()
        for offset, count in enumerate((2, 1, 3)):
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=today - timedelta(days=offset),
                result_count=count,
                support_amount=1000 * count,
                activity_closed=True,
            )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3稼働連続1件以上")
        self.assertContains(response, 'data-member-status="positive"')
        self.assertContains(response, "直近の実績（3稼働・古い順）")
