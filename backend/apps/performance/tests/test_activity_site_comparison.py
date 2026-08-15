from datetime import date

from django.core.paginator import Paginator
from django.urls import reverse

from apps.activity_sites.models import ActivitySite
from apps.activity_sites.selectors import activity_site_history_queryset, build_activity_site_comparison
from apps.dairymetrics.models import (
    MemberDailyMetricEntry,
    MemberMetricTransaction,
    MetricAdjustment,
    WVMetricCancellation,
)
from .base import PerformanceTestBase


class ActivitySiteComparisonTests(PerformanceTestBase):
    def setUp(self):
        super().setUp()
        self.site_a = ActivitySite.objects.create(canonical_name="青山現場")
        self.site_b = ActivitySite.objects.create(canonical_name="池袋現場")

    def _entry(self, site, activity_date, *, member=None, department=None, count=0, amount=0):
        return MemberDailyMetricEntry.objects.create(
            member=member or self.member,
            department=department or self.department,
            entry_date=activity_date,
            activity_site=site,
            location_name=site.canonical_name,
            result_count=count,
            support_amount=amount,
            approach_count=4,
            communication_count=3,
        )

    def test_selector_uses_final_actual_rule_and_does_not_count_unlinked_records(self):
        self._entry(self.site_a, date(2026, 8, 4), count=3, amount=10000)
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 8, 5),
            activity_site=self.site_a,
            result_count=2,
            support_amount=2000,
            approach_count=1,
            communication_count=1,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 8, 5),
            activity_site=self.site_a,
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=500,
        )
        transaction_entry = self._entry(self.site_b, date(2026, 8, 6), count=1, amount=500)
        MemberMetricTransaction.objects.create(
            entry=transaction_entry,
            activity_site=self.site_b,
            support_amount=500,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
        )
        self._entry(ActivitySite.objects.create(canonical_name="期間外"), date(2026, 7, 31), count=99, amount=99999)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 8, 7),
            location_name="未整理の現場",
            result_count=80,
        )

        rows = build_activity_site_comparison(
            start_date=date(2026, 8, 1), end_date=date(2026, 8, 31), sort="support_amount", direction="desc"
        )

        self.assertEqual([row["site_name"] for row in rows], ["青山現場", "池袋現場"])
        self.assertEqual(rows[0]["result_count"], 6)
        self.assertEqual(rows[0]["support_amount"], 12500)
        self.assertEqual(rows[0]["activity_days"], 2)
        self.assertEqual(rows[0]["member_count"], 1)
        self.assertEqual(rows[0]["latest_activity_date"], date(2026, 8, 5))
        self.assertEqual(rows[1]["result_count"], 2)
        self.assertEqual(rows[1]["support_amount"], 1000)

    def test_cancellation_is_subtracted_from_wv_site(self):
        department = self.create_department("WV")
        member = self.create_member(name="WV担当", department=department)
        unit_amount = MemberMetricTransaction.WV_CS_UNIT_AMOUNT
        self._entry(
            self.site_a,
            date(2026, 8, 3),
            member=member,
            department=department,
            count=2,
            amount=unit_amount * 2,
        )
        WVMetricCancellation.objects.create(
            member=member,
            department=department,
            target_date=date(2026, 8, 3),
            activity_site=self.site_a,
            location_name=self.site_a.canonical_name,
            wv_cs_count=1,
        )

        row = build_activity_site_comparison(
            start_date=date(2026, 8, 1), end_date=date(2026, 8, 31), department_id=department.id
        )[0]

        self.assertEqual(row["result_count"], 1)
        self.assertEqual(row["support_amount"], unit_amount)

    def test_selector_query_count_is_fixed(self):
        self._entry(self.site_a, date(2026, 8, 1), count=1, amount=100)
        self._entry(self.site_b, date(2026, 8, 2), count=2, amount=200)

        with self.assertNumQueries(6):
            rows = build_activity_site_comparison(start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))

        self.assertEqual(len(rows), 2)

    def test_comparison_page_filters_and_renders_mobile_friendly_cards(self):
        self._entry(self.site_a, date(2026, 8, 4), count=3, amount=10000)

        response = self.client.get(
            reverse("performance_activity_site_comparison"),
            {"start_date": "2026-08-01", "end_date": "2026-08-31", "department": self.department.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "青山現場")
        self.assertContains(response, "10000円")
        self.assertNotContains(response, "<table", html=False)

    def test_comparison_page_is_staff_only(self):
        self.client.logout()
        user = self.create_user("site-comparison-user", is_staff=False)
        self.login(user)

        response = self.client.get(reverse("performance_activity_site_comparison"))

        self.assertEqual(response.status_code, 403)

    def test_history_combines_sources_in_date_order_and_negates_cancellation(self):
        self._entry(self.site_a, date(2026, 8, 2), count=2, amount=2000)
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 8, 3),
            activity_site=self.site_a,
            source_type=MetricAdjustment.SOURCE_POSTAL,
            return_postal_count=1,
            return_postal_amount=500,
            note="郵送分",
        )
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV履歴担当", department=wv_department)
        WVMetricCancellation.objects.create(
            member=wv_member,
            department=wv_department,
            target_date=date(2026, 8, 4),
            activity_site=self.site_a,
            wv_cs_count=1,
            comment="取消確認",
        )

        rows = list(
            activity_site_history_queryset(
                site_id=self.site_a.id,
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 31),
            )
        )

        self.assertEqual([row["history_source"] for row in rows], ["WVキャンセル", "補正", "日次入力"])
        self.assertEqual(rows[0]["history_result"], -1)
        self.assertEqual(rows[0]["history_amount"], -MemberMetricTransaction.WV_CS_UNIT_AMOUNT)
        self.assertEqual(rows[1]["history_source_code"], MetricAdjustment.SOURCE_POSTAL)
        self.assertEqual(rows[1]["history_result"], 1)
        self.assertEqual(rows[1]["history_amount"], 500)
        self.assertEqual(rows[1]["history_note"], "郵送分")

    def test_history_pagination_uses_two_queries_independent_of_source_rows(self):
        self._entry(self.site_a, date(2026, 8, 2), count=2, amount=2000)
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 8, 3),
            activity_site=self.site_a,
        )
        history = activity_site_history_queryset(
            site_id=self.site_a.id,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )

        with self.assertNumQueries(2):
            page = Paginator(history, 20).get_page(1)
            rows = list(page.object_list)

        self.assertEqual(len(rows), 2)

    def test_detail_page_filters_site_and_preserves_comparison_conditions(self):
        self._entry(self.site_a, date(2026, 8, 4), count=3, amount=10000)
        self._entry(self.site_b, date(2026, 8, 5), count=9, amount=90000)

        response = self.client.get(
            reverse("performance_activity_site_detail", args=[self.site_a.id]),
            {
                "start_date": "2026-08-01",
                "end_date": "2026-08-31",
                "department": self.department.id,
                "sort": "result_count",
                "direction": "asc",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "青山現場")
        self.assertContains(response, "Alice")
        self.assertNotContains(response, "池袋現場")
        self.assertContains(response, "sort=result_count&amp;direction=asc")

    def test_detail_page_is_staff_only(self):
        self.client.logout()
        user = self.create_user("site-history-user", is_staff=False)
        self.login(user)

        response = self.client.get(reverse("performance_activity_site_detail", args=[self.site_a.id]))

        self.assertEqual(response.status_code, 403)
