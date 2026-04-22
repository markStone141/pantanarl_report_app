from django.test import TestCase
from django.urls import reverse


class MonthlyGuideTests(TestCase):
    def test_monthly_guide_page_renders(self):
        response = self.client.get(reverse("monthly_guide_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ユニセフ・マンスリーガイド")
        self.assertContains(response, "日本語")
        self.assertContains(response, "英語")
        self.assertContains(response, "インドネシア語")
        self.assertContains(response, "クメール語")
        self.assertContains(response, "タイ語")
        self.assertContains(response, "タガログ語")
        self.assertContains(response, "ベトナム語")
        self.assertContains(response, "ミャンマー語")
        self.assertContains(response, "中国語")
        self.assertContains(response, "<option", count=8)

    def test_monthly_guide_page_contains_sample_sections(self):
        response = self.client.get(reverse("monthly_guide_index"))

        self.assertContains(response, "ユニセフ・マンスリーサポートとは")
        self.assertContains(response, "支援の方法")
        self.assertContains(response, "途中で変更や停止はできますか")
        self.assertContains(response, "日本で開設した銀行口座")
        self.assertContains(response, "日本語をコピー")

    def test_monthly_guide_page_shows_japanese_and_selected_language(self):
        response = self.client.get(reverse("monthly_guide_index"))

        self.assertContains(response, "日本語")
        self.assertContains(response, "英語")
        self.assertContains(response, "What is UNICEF Monthly Support?")
