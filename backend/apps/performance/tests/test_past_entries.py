import json
from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from apps.dairymetrics.models import DepartmentDailyMetricSummary, MemberDailyMetricEntry, MemberMetricTransaction
from .base import PerformanceTestBase

User = get_user_model()


class PastEntriesTests(PerformanceTestBase):
    def test_performance_past_entry_create_renders_department_specific_transaction_inputs(self):
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV Member", department=wv_department)

        un_response = self.client.get(
            reverse("performance_past_entry_create"),
            {"department": self.department.id, "member": self.member.id, "entry_date": "2026-06-01"},
        )
        self.assertEqual(un_response.status_code, 200)
        self.assertContains(un_response, "決済金額")
        self.assertNotContains(un_response, "CS口数")

        wv_response = self.client.get(
            reverse("performance_past_entry_create"),
            {"department": wv_department.id, "member": wv_member.id, "entry_date": "2026-06-01"},
        )
        self.assertEqual(wv_response.status_code, 200)
        self.assertContains(wv_response, "CS口数")
        self.assertContains(wv_response, "難民支援金額")


    def test_performance_past_entry_create_saves_un_entry_and_transactions(self):
        response = self.client.post(
            reverse("performance_past_entry_create"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "entry_date": "2026-06-01",
                "location_name": "渋谷駅前",
                "approach_count": "8",
                "communication_count": "3",
                "transactions_payload": json.dumps(
                    [
                        {
                            "support_amount": 3000,
                            "wv_result_type": "",
                            "wv_cs_count": 0,
                            "wv_refugee_amount": 0,
                            "age_band": MemberMetricTransaction.AGE_BAND_TWENTIES,
                            "is_student": False,
                            "gender": MemberMetricTransaction.GENDER_FEMALE,
                            "nationality_type": MemberMetricTransaction.NATIONALITY_DOMESTIC,
                            "comment": "過去UN",
                        }
                    ]
                ),
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_past_entry_create')}?department={self.department.id}&member={self.member.id}&saved=1",
        )
        entry = MemberDailyMetricEntry.objects.get(member=self.member, department=self.department, entry_date=date(2026, 6, 1))
        self.assertTrue(entry.activity_closed)
        self.assertEqual(entry.location_name, "渋谷駅前")
        self.assertEqual(entry.approach_count, 8)
        self.assertEqual(entry.communication_count, 3)
        self.assertEqual(entry.result_count, 1)
        self.assertEqual(entry.support_amount, 3000)
        self.assertEqual(entry.transactions.count(), 1)
        summary = DepartmentDailyMetricSummary.objects.get(department=self.department, entry_date=date(2026, 6, 1))
        self.assertEqual(summary.approach_count, 8)
        self.assertEqual(summary.communication_count, 3)
        self.assertEqual(summary.result_count, 1)
        self.assertEqual(summary.support_amount, 3000)


    def test_performance_past_entry_create_saves_wv_entry_and_transactions(self):
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV Member", department=wv_department)

        response = self.client.post(
            reverse("performance_past_entry_create"),
            {
                "department": wv_department.id,
                "member": wv_member.id,
                "entry_date": "2026-06-01",
                "location_name": "新宿駅前",
                "approach_count": "10",
                "communication_count": "4",
                "transactions_payload": json.dumps(
                    [
                        {
                            "support_amount": 6500,
                            "wv_result_type": MemberMetricTransaction.WV_RESULT_BOTH,
                            "wv_cs_count": 1,
                            "wv_refugee_amount": 2000,
                            "age_band": MemberMetricTransaction.AGE_BAND_THIRTIES,
                            "is_student": False,
                            "gender": MemberMetricTransaction.GENDER_MALE,
                            "nationality_type": MemberMetricTransaction.NATIONALITY_DOMESTIC,
                            "comment": "過去WV",
                        }
                    ]
                ),
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_past_entry_create')}?department={wv_department.id}&member={wv_member.id}&saved=1",
        )
        entry = MemberDailyMetricEntry.objects.get(member=wv_member, department=wv_department, entry_date=date(2026, 6, 1))
        self.assertEqual(entry.result_count, 2)
        self.assertEqual(entry.cs_count, 1)
        self.assertEqual(entry.refugee_count, 1)
        self.assertEqual(entry.support_amount, 6500)


    def test_performance_past_entry_create_blocks_duplicate_entry_dates(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 6, 1),
            result_count=1,
            support_amount=1000,
        )

        response = self.client.post(
            reverse("performance_past_entry_create"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "entry_date": "2026-06-01",
                "location_name": "渋谷駅前",
                "approach_count": "8",
                "communication_count": "3",
                "transactions_payload": "[]",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "その日の実績はすでに登録されています。")


    def test_performance_past_entry_create_shows_edit_and_delete_for_existing_future_entry(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 6, 15),
            result_count=1,
            support_amount=1000,
        )

        response = self.client.get(
            reverse("performance_past_entry_create"),
            {"department": self.department.id, "member": self.member.id, "entry_date": "2026-06-15"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("performance_entry_edit", args=[entry.id]))
        self.assertContains(response, reverse("performance_entry_delete", args=[entry.id]))


    def test_performance_past_entry_create_get_with_department_shows_member_options(self):
        response = self.client.get(
            reverse("performance_past_entry_create"),
            {"department": self.department.id, "entry_date": "2026-06-01"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'<option value="{self.member.id}">{self.member.name}</option>', html=True)
        self.assertContains(response, "dashboard/mobile_drawer.js")


    def test_performance_past_entry_member_options_returns_department_members(self):
        self.member.un_activity_code = "12345"
        self.member.save(update_fields=["un_activity_code"])
        other_department = self.create_department("WV")
        other_member = self.create_member(name="Other Member", department=other_department)
        un_matched_member = self.create_member(name="UN Other", department=self.department)
        un_matched_member.un_activity_code = "98765"
        un_matched_member.save(update_fields=["un_activity_code"])

        response = self.client.get(
            reverse("performance_past_entry_member_options"),
            {"department": self.department.id, "un_code": "123"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["options"],
            [{"id": self.member.id, "name": self.member.name, "un_activity_code": "12345"}],
        )
        self.assertNotIn(
            {"id": other_member.id, "name": other_member.name, "un_activity_code": other_member.un_activity_code},
            payload["options"],
        )
        self.assertNotIn(
            {"id": un_matched_member.id, "name": un_matched_member.name, "un_activity_code": "98765"},
            payload["options"],
        )


    def test_performance_member_can_edit_own_past_entry_from_history_flow(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-edit", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate(),
            result_count=0,
            support_amount=0,
            approach_count=0,
            communication_count=0,
        )
        self.client.force_login(report_user)

        history_response = self.client.get(reverse("performance_member_history"))
        self.assertContains(history_response, reverse("performance_entry_edit", args=[entry.id]))

        response = self.client.post(
            f"{reverse('performance_entry_edit', args=[entry.id])}?next={reverse('performance_member_history')}",
            {
                "member": self.member.id,
                "department": self.department.id,
                "entry_date": entry.entry_date.strftime("%Y-%m-%d"),
                "approach_count": 12,
                "communication_count": 4,
                "result_count": 0,
                "support_amount": 0,
                "daily_target_count": 1,
                "daily_target_amount": 3000,
                "activity_closed": "on",
                "location_name": "",
                "memo": "",
                "next": reverse("performance_member_history"),
            },
        )

        self.assertRedirects(response, f"{reverse('performance_member_history')}?updated=entry")
        entry.refresh_from_db()
        self.assertEqual(entry.approach_count, 12)
        self.assertEqual(entry.communication_count, 4)


    def test_performance_member_can_delete_own_past_entry_from_history_flow(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-delete", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate() - timedelta(days=1),
            result_count=1,
            support_amount=3000,
            approach_count=5,
            communication_count=2,
        )
        DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=entry.entry_date,
            approach_count=5,
            communication_count=2,
            result_count=1,
            support_amount=3000,
            created_by=self.member,
            updated_by=self.member,
        )
        self.client.force_login(report_user)

        response = self.client.post(
            f"{reverse('performance_entry_delete', args=[entry.id])}?next={reverse('performance_member_history')}",
            {
                "next": reverse("performance_member_history"),
            },
        )

        self.assertRedirects(response, f"{reverse('performance_member_history')}?deleted=entry")
        self.assertFalse(MemberDailyMetricEntry.objects.filter(pk=entry.id).exists())
        summary = DepartmentDailyMetricSummary.objects.get(department=self.department, entry_date=entry.entry_date)
        self.assertEqual(summary.result_count, 0)
        self.assertEqual(summary.support_amount, 0)
