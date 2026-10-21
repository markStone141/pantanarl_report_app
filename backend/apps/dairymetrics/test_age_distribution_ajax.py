from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.common.test_helpers import AppTestMixin
from .models import MemberDailyMetricEntry, MemberMetricTransaction


class AgeDistributionAjaxTests(AppTestMixin, TestCase):
    def setUp(self):
        self.department = self.create_department("UNW", name="UN関西")
        self.user, self.member = self.create_member_user(username="age-member", name="関西メンバー", department=self.department)
        self.other_member = self.create_member(name="関西メンバー2", department=self.department)
        self.admin = self.create_user("age-admin", is_staff=True)
        self.other_department = self.create_department("UN")
        self.today = timezone.localdate()
        for nationality, age in [("domestic", "twenties"), ("overseas", "thirties"), ("overseas", "thirties")]:
            self.add_transaction(self.member, self.department, self.today, nationality, age)
        self.add_transaction(self.other_member, self.department, self.today, "overseas", "twenties")
        self.add_transaction(self.member, self.other_department, self.today, "overseas", "twenties")
        self.add_transaction(self.member, self.department, self.today - timedelta(days=5), "overseas", "twenties")
        self.login(self.user)
        self.query = {"department": "UNW", "scope": "custom", "start_date": self.today.isoformat(), "end_date": self.today.isoformat()}

    def add_transaction(self, member, department, day, nationality, age):
        entry, _ = MemberDailyMetricEntry.objects.get_or_create(member=member, department=department, entry_date=day)
        MemberMetricTransaction.objects.create(entry=entry, support_amount=1000, nationality_type=nationality, age_band=age)

    def get_card(self, page, nationality, **extra):
        response = self.client.get(reverse(page), {**self.query, "age_nationality": nationality, **extra}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        card = response.json()["card"]
        self.assertEqual(sum(card["counts"]), sum(int(row["count_text"].removesuffix("件")) for row in card["rows"]))
        return card

    def test_analysis_personal_filters_keep_member_department_and_dates(self):
        page = "dairymetrics_metrics_v2_demo"
        self.assertEqual(self.get_card(page, "all")["total_text"], "3件")
        self.assertEqual(self.get_card(page, "overseas")["total_text"], "2件")
        self.assertEqual(self.get_card(page, "domestic")["total_text"], "1件")
        self.assertEqual(self.get_card(page, "overseas")["labels"], ["30代"])
        self.assertEqual(self.get_card(page, "domestic")["labels"], ["20代"])
        # A member cannot switch to another member's distribution via a query parameter.
        self.assertEqual(self.get_card(page, "overseas", member=self.other_member.pk)["total_text"], "2件")

    def test_admin_overall_and_selected_member_are_kept(self):
        self.login(self.admin)
        page = "dairymetrics_metrics_v2_demo"
        self.assertEqual(self.get_card(page, "overseas")["total_text"], "3件")
        self.assertEqual(self.get_card(page, "all", member=self.member.pk)["total_text"], "3件")

    def test_reflection_filters_match_department_wide_report_scope(self):
        page = "dairymetrics_metrics_report"
        self.assertEqual(self.get_card(page, "all")["total_text"], "4件")
        self.assertEqual(self.get_card(page, "overseas")["total_text"], "3件")
        self.assertEqual(self.get_card(page, "domestic")["total_text"], "1件")

    def test_empty_filter_and_invalid_filter(self):
        self.login(self.admin)
        page = "dairymetrics_metrics_v2_demo"
        card = self.get_card(page, "domestic", member=self.other_member.pk)
        self.assertFalse(card["has_data"])
        self.assertEqual(card["total_text"], "0件")
        for page in [page, "dairymetrics_metrics_report"]:
            response = self.client.get(reverse(page), {**self.query, "age_nationality": "invalid"})
            self.assertEqual(response.status_code, 400)

    def test_both_pages_render_three_buttons_only_on_main_age_card(self):
        for page in ["dairymetrics_metrics_v2_demo", "dairymetrics_metrics_report"]:
            response = self.client.get(reverse(page), self.query)
            self.assertContains(response, "data-age-distribution", count=1)
            for nationality in ["all", "overseas", "domestic"]:
                self.assertContains(response, f'data-age-nationality="{nationality}"', count=1)

    def test_ajax_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("dairymetrics_metrics_v2_demo"), {**self.query, "age_nationality": "all"})
        self.assertEqual(response.status_code, 302)
