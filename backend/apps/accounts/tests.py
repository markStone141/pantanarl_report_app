from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model


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

    def test_admin_login_uses_django_user_password_if_present(self):
        user_model = get_user_model()
        user_model.objects.create_user(username="admin", password="new-admin-pass")
        response = self.client.post(
            reverse("home"),
            {
                "login_id": "admin",
                "password": "new-admin-pass",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard_index"))
        self.assertEqual(self.client.session.get("role"), "admin")
        self.assertIn("_auth_user_id", self.client.session)

    def test_report_login_uses_django_user_password_if_present(self):
        user_model = get_user_model()
        user_model.objects.create_user(username="report", password="new-report-pass")
        response = self.client.post(
            reverse("home"),
            {
                "login_id": "report",
                "password": "new-report-pass",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("report_index"))
        self.assertEqual(self.client.session.get("role"), "report")
        self.assertIn("_auth_user_id", self.client.session)


class RoleGuardTests(TestCase):
    def test_dashboard_requires_admin(self):
        response = self.client.get(reverse("dashboard_index"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

    def test_report_form_requires_login(self):
        response = self.client.get(reverse("report_un"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

    def test_dashboard_allows_staff_user_without_session_role(self):
        user_model = get_user_model()
        admin_user = user_model.objects.create_user(username="staff_admin", password="x", is_staff=True)
        self.client.force_login(admin_user)

        response = self.client.get(reverse("dashboard_index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session.get("role"), "admin")

    def test_report_allows_authenticated_non_staff_without_session_role(self):
        user_model = get_user_model()
        report_user = user_model.objects.create_user(username="report_user", password="x", is_staff=False)
        self.client.force_login(report_user)

        response = self.client.get(reverse("report_un"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session.get("role"), "report")

    def test_dashboard_denies_non_staff_user(self):
        user_model = get_user_model()
        report_user = user_model.objects.create_user(username="report_user2", password="x", is_staff=False)
        self.client.force_login(report_user)

        response = self.client.get(reverse("dashboard_index"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))
