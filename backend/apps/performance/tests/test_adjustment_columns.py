from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.dairymetrics.models import MetricAdjustment, WVMetricCancellation
from .base import PerformanceTestBase


class AdjustmentColumnsTests(PerformanceTestBase):
    def create_record(self, source, *, location="現場", day=0, department=None):
        return MetricAdjustment.objects.create(
            member=self.member, department=department or self.department,
            source_type=source, target_date=timezone.localdate() - timedelta(days=day),
            location_name=location, support_amount=2000,
        )

    def test_three_types_are_separate_and_each_is_newest_first(self):
        for source in ["postal", "qr", "increase"]:
            self.create_record(source, location=f"{source}-旧", day=1)
            self.create_record(source, location=f"{source}-新")
        response = self.client.get(reverse("performance_adjustments"))
        groups = response.context["adjustment_groups"]
        self.assertEqual([g["code"] for g in groups[:3]], ["postal", "qr", "increase"])
        for group in groups[:3]:
            self.assertEqual([r["location_name"] for r in group["rows"]], [f'{group["code"]}-新', f'{group["code"]}-旧'])
            self.assertTrue(all(r["source_type"] == group["code"] for r in group["rows"]))
            self.assertTrue(all(r["edit_url"] and r["delete_url"] for r in group["rows"]))

    def test_each_type_has_its_own_twenty_record_page(self):
        for source in ["postal", "qr", "increase"]:
            for day in range(21):
                self.create_record(source, location=f"{source}-{day}", day=day)
        response = self.client.get(reverse("performance_adjustments"))
        self.assertEqual([len(g["rows"]) for g in response.context["adjustment_groups"][:3]], [20, 20, 20])
        self.assertTrue(response.context["adjustments_has_more"])
        response = self.client.get(reverse("performance_adjustments"), {"page": 2})
        self.assertEqual([len(g["rows"]) for g in response.context["adjustment_groups"][:3]], [1, 1, 1])
        self.assertFalse(response.context["adjustments_has_more"])
        for group in response.context["adjustment_groups"][:3]:
            self.assertEqual(group["rows"][0]["location_name"], f'{group["code"]}-20')

    def test_wv_adjustments_and_cancellations_are_in_separate_list(self):
        wv = self.create_department("WV")
        self.create_record("cs", department=wv)
        cancellation = WVMetricCancellation.objects.create(
            member=self.member, department=wv, target_date=timezone.localdate(),
            cs_count=1, support_amount=1000,
        )
        response = self.client.get(reverse("performance_adjustments"))
        groups = response.context["adjustment_groups"]
        self.assertEqual([len(g["rows"]) for g in groups[:3]], [0, 0, 0])
        rows = next(g for g in groups if g["code"] == "wv")["rows"]
        self.assertEqual({r["source_label"] for r in rows}, {"CS", "キャンセル"})
        self.assertIn(reverse("performance_cancellation_delete", args=[cancellation.pk]), [r["delete_url"] for r in rows])

    def test_search_and_department_filter_apply_to_all_columns_and_ajax(self):
        self.create_record("postal", location="検索対象")
        self.create_record("qr", location="対象外")
        response = self.client.get(reverse("performance_adjustments"), {
            "q": "検索対象", "department": self.department.pk,
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        html = response.json()["list_html"]
        self.assertIn('data-source-type="postal"', html)
        self.assertIn('data-source-type="qr"', html)
        self.assertIn("検索対象", html)
        self.assertNotIn("対象外", html)

    def test_form_order_matches_input_workflow_and_legacy_records_remain_visible(self):
        self.create_record("other", location="以前のその他実績")
        response = self.client.get(reverse("performance_adjustments"))
        html = response.content.decode()
        labels = ['for="id_source_type"', 'for="id_department"', 'for="id_target_date"',
                  'for="id_location_name"', 'for="id_member"', 'for="id_amount_choice"']
        positions = [html.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertContains(response, "以前のその他実績")
