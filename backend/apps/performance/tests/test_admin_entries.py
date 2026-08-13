from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from apps.dairymetrics.models import DepartmentDailyMetricSummary, MemberDailyMetricEntry, MemberMetricTransaction
from apps.mail.models import MailSendHistory
from apps.targets.models import Period
from .base import PerformanceTestBase


class AdminEntriesTests(PerformanceTestBase):
    def test_closeout_notes_uses_shared_app_shell_and_current_navigation(self):
        response = self.client.get(reverse("performance_closeout_notes"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<div class="app-shell">', html=False)
        self.assertContains(
            response,
            '<main class="container app-shell-content closeout-notebook">',
            html=False,
        )
        self.assertContains(response, 'class="app-side-nav dashboard-drawer-nav"', html=False)
        self.assertContains(
            response,
            'class="ui-icon-button dashboard-drawer-toggle"',
            html=False,
        )
        self.assertNotContains(
            response,
            'class="btn-inline dashboard-drawer-toggle"',
            html=False,
        )
        self.assertContains(
            response,
            f'href="{reverse("performance_closeout_notes")}" class="is-current" aria-current="page"',
            html=False,
        )

    def test_performance_admin_crud_pages_use_shared_app_shell(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 6, 3),
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
        )
        page_urls = (
            (reverse("performance_admin_entries"), reverse("performance_admin_entries")),
            (reverse("performance_past_entry_create"), reverse("performance_past_entry_create")),
            (reverse("performance_adjustments"), reverse("performance_adjustments")),
            (reverse("performance_entry_edit", args=[entry.id]), reverse("performance_admin_entries")),
            (reverse("performance_transaction_edit", args=[transaction.id]), reverse("performance_admin_entries")),
        )

        for page_url, current_url in page_urls:
            with self.subTest(page_url=page_url):
                response = self.client.get(page_url)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '<div class="app-shell">', html=False)
                self.assertContains(response, '<main class="container app-shell-content">', html=False)
                self.assertContains(response, 'class="app-side-nav dashboard-drawer-nav"', html=False)
                self.assertContains(response, "管理・設定")
                self.assertContains(
                    response,
                    f'href="{current_url}" class="is-current" aria-current="page"',
                    html=False,
                )

    def test_performance_admin_entries_page_shows_summary_and_entry_actions(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 6, 3),
            approach_count=7,
            communication_count=4,
            result_count=2,
            support_amount=3500,
            location_name="渋谷駅前",
        )
        DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=entry.entry_date,
            approach_count=7,
            communication_count=4,
            result_count=2,
            support_amount=3500,
            created_by=self.member,
            updated_by=self.member,
        )

        response = self.client.get(reverse("performance_admin_entries"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "全体エントリー管理")
        self.assertContains(response, "UN / 2026/06/03")
        self.assertContains(response, self.member.name)
        self.assertContains(response, "渋谷駅前")
        self.assertContains(response, reverse("performance_entry_edit", args=[entry.id]))
        self.assertContains(response, reverse("performance_entry_delete", args=[entry.id]))


    def test_performance_closeout_notes_lists_and_filters_member_memos(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            location_name="新宿駅前",
            memo="話は進んだが予算の確認が必要だった。次は比較資料を準備する。",
            activity_closed=True,
        )
        other_member = self.create_member(name="Bob", department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=other_member,
            department=self.department,
            entry_date=today,
            memo="別のケース",
            activity_closed=True,
        )

        response = self.client.get(
            reverse("performance_closeout_notes"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "q": "比較資料",
                "date_from": today.strftime("%Y-%m-%d"),
                "date_to": today.strftime("%Y-%m-%d"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "あと一歩ケース")
        self.assertContains(response, self.member.name)
        self.assertContains(response, "新宿駅前")
        self.assertContains(response, "次は比較資料を準備する。")
        self.assertNotContains(response, "別のケース")
        self.assertContains(response, 'data-closeout-filter-open', html=False)
        self.assertContains(response, 'id="closeout-filter-panel"', html=False)
        self.assertContains(response, "詳細検索")


    def test_member_can_open_closeout_notes_from_performance_navigation(self):
        member_user, member_profile = self.create_member_user(
            username="notes-member",
            name="Notes Member",
            department=self.department,
        )
        MemberDailyMetricEntry.objects.create(
            member=member_profile,
            department=self.department,
            entry_date=timezone.localdate(),
            memo="次は質問の順番を変えて試す。",
            activity_closed=True,
        )
        self.client.force_login(member_user)

        dashboard_response = self.client.get(reverse("performance_index"))
        notes_response = self.client.get(reverse("performance_closeout_notes"))

        self.assertContains(dashboard_response, reverse("performance_closeout_notes"))
        self.assertContains(dashboard_response, "今日のあと一歩ノート")
        self.assertEqual(notes_response.status_code, 200)
        self.assertContains(notes_response, "次は質問の順番を変えて試す。")


    def test_closeout_notes_defaults_today_and_supports_scope_and_period_search(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        previous_month_day = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        current_period = Period.objects.create(
            month=today.replace(day=1),
            name="現在路程",
            status="active",
            start_date=yesterday,
            end_date=today + timedelta(days=2),
        )
        previous_period = Period.objects.create(
            month=previous_month_day.replace(day=1),
            name="前月路程",
            status="finished",
            start_date=previous_month_day - timedelta(days=2),
            end_date=previous_month_day,
        )
        for entry_date, memo in (
            (today, "今日のケース"),
            (yesterday, "昨日のケース"),
            (previous_month_day, "前月のケース"),
        ):
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=entry_date,
                memo=memo,
                activity_closed=True,
            )

        today_response = self.client.get(reverse("performance_closeout_notes"))
        yesterday_response = self.client.get(reverse("performance_closeout_notes"), {"scope": "yesterday"})
        current_period_response = self.client.get(reverse("performance_closeout_notes"), {"scope": "period"})
        month_response = self.client.get(
            reverse("performance_closeout_notes"),
            {"month": previous_month_day.strftime("%Y-%m")},
        )
        period_response = self.client.get(
            reverse("performance_closeout_notes"),
            {"period_id": previous_period.id},
        )

        self.assertContains(today_response, "今日のケース")
        self.assertNotContains(today_response, "昨日のケース")
        self.assertContains(yesterday_response, "昨日のケース")
        self.assertNotContains(yesterday_response, "今日のケース")
        self.assertContains(current_period_response, current_period.name)
        self.assertContains(current_period_response, "今日のケース")
        self.assertContains(current_period_response, "昨日のケース")
        self.assertContains(month_response, "前月のケース")
        self.assertContains(period_response, previous_period.name)
        self.assertContains(period_response, "前月のケース")


    def test_closeout_notes_ajax_returns_only_updated_results(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            memo="AJAXで見つかるケース",
            activity_closed=True,
        )

        response = self.client.get(
            reverse("performance_closeout_notes"),
            {"scope": "today", "q": "AJAX"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["scope_key"], "today")
        self.assertIn("AJAXで見つかるケース", payload["results_html"])
        self.assertNotIn("closeout-filter-panel", payload["results_html"])


    def test_performance_admin_entries_includes_inactive_member_filter_option(self):
        inactive_member = self.create_member(name="Inactive Entry", department=self.department)
        inactive_member.is_active = False
        inactive_member.save(update_fields=["is_active"])

        response = self.client.get(reverse("performance_admin_entries"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'<option value="{inactive_member.id}">{inactive_member.name}</option>', html=True)


    def test_performance_admin_entries_can_delete_orphan_summary(self):
        summary = DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=date(2026, 6, 4),
            approach_count=0,
            communication_count=0,
            result_count=0,
            support_amount=0,
            created_by=self.member,
            updated_by=self.member,
        )

        response = self.client.post(
            reverse("performance_summary_delete", args=[summary.id]),
            {"next": reverse("performance_admin_entries")},
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_admin_entries')}?deleted=summary",
            fetch_redirect_response=False,
        )
        self.assertFalse(DepartmentDailyMetricSummary.objects.filter(pk=summary.id).exists())


    def test_performance_admin_entries_does_not_delete_summary_with_entries(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 6, 5),
            result_count=1,
            support_amount=1000,
        )
        summary = DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=entry.entry_date,
            approach_count=0,
            communication_count=0,
            result_count=1,
            support_amount=1000,
            created_by=self.member,
            updated_by=self.member,
        )

        response = self.client.post(
            reverse("performance_summary_delete", args=[summary.id]),
            {"next": reverse("performance_admin_entries")},
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_admin_entries')}?status=summary_not_empty",
            fetch_redirect_response=False,
        )
        self.assertTrue(DepartmentDailyMetricSummary.objects.filter(pk=summary.id).exists())


    def test_performance_today_transaction_detail_shows_admin_cancel_action(self):
        today = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("performance_transaction_edit", args=[transaction.id]))
        self.assertContains(response, reverse("performance_transaction_delete", args=[transaction.id]))
        self.assertContains(response, "決済を取り消す")


    def test_admin_can_cancel_transaction_and_revert_totals(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 6, 20),
            result_count=0,
            support_amount=0,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
        )
        mail_history = MailSendHistory.objects.create(
            department=self.department,
            activity_date=entry.entry_date,
            sender_member=self.member,
            transaction=transaction,
            subject_snapshot="送信済み",
            body_snapshot="本文",
            status=MailSendHistory.STATUS_SENT,
            is_test=False,
            sent_at=timezone.now(),
        )

        response = self.client.post(
            reverse("performance_transaction_delete", args=[transaction.id]),
            {"next": reverse("performance_index")},
        )

        self.assertRedirects(response, f"{reverse('performance_index')}?deleted=transaction")
        self.assertFalse(MemberMetricTransaction.objects.filter(pk=transaction.pk).exists())
        entry.refresh_from_db()
        self.assertEqual(entry.result_count, 0)
        self.assertEqual(entry.support_amount, 0)
        mail_history.refresh_from_db()
        self.assertIsNone(mail_history.transaction_id)


    def test_performance_entry_edit_updates_daily_entry_and_department_summary(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 5, 15),
            result_count=1,
            support_amount=2000,
            approach_count=5,
            communication_count=2,
        )
        DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=entry.entry_date,
            approach_count=5,
            communication_count=2,
            result_count=1,
            support_amount=2000,
            created_by=self.member,
            updated_by=self.member,
        )

        response = self.client.post(
            reverse("performance_entry_edit", args=[entry.id]),
            {
                "department": self.department.id,
                "entry_date": "2026-05-15",
                "approach_count": 9,
                "communication_count": 6,
                "result_count": 3,
                "support_amount": 4500,
                "daily_target_count": 0,
                "daily_target_amount": 0,
                "location_name": "",
                "memo": "",
            },
        )

        self.assertRedirects(response, reverse("performance_index") + "?updated=entry")
        entry.refresh_from_db()
        summary = DepartmentDailyMetricSummary.objects.get(department=self.department, entry_date=entry.entry_date)
        self.assertEqual(entry.approach_count, 9)
        self.assertEqual(entry.communication_count, 6)
        self.assertEqual(entry.result_count, 3)
        self.assertEqual(entry.support_amount, 4500)
        self.assertEqual(summary.approach_count, 9)
        self.assertEqual(summary.communication_count, 6)
        self.assertEqual(summary.result_count, 3)
        self.assertEqual(summary.support_amount, 4500)


    def test_performance_entry_edit_locks_amount_when_transactions_exist(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 5, 15),
        )
        MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
        )

        response = self.client.get(reverse("performance_entry_edit", args=[entry.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "自動計算されます。")
        self.assertContains(response, "disabled")
