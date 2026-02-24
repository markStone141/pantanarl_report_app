from django.test import TestCase
from django.urls import reverse


class LoginFlowTests(TestCase):
    def test_admin_login_redirects_dashboard(self):
        response = self.client.post(
            reverse("home"),
            {
                "login_id": "admin",
                "password": "pnadmin",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard_index"))
        self.assertEqual(self.client.session.get("role"), "admin")

    def test_report_login_redirects_report_index(self):
        response = self.client.post(
            reverse("home"),
            {
                "login_id": "report",
                "password": "0823",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("report_index"))
        self.assertEqual(self.client.session.get("role"), "report")

    def test_wrong_password_shows_error(self):
        response = self.client.post(
            reverse("home"),
            {
                "login_id": "admin",
                "password": "wrong",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "管理者パスワードが違います。")


class RoleGuardTests(TestCase):
    def test_dashboard_requires_admin(self):
        response = self.client.get(reverse("dashboard_index"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

    def test_report_form_requires_login(self):
        response = self.client.get(reverse("report_un"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))
