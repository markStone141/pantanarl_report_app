from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class LoginFlowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        user_model.objects.create_user(username="admin", password="admin-pass", is_staff=True)
        user_model.objects.create_user(username="report", password="report-pass", is_staff=False)

    def test_admin_login_redirects_dashboard(self):
        response = self.client.post(
            reverse("home"),
            {
                "login_id": "admin",
                "password": "admin-pass",
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
                "password": "report-pass",
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
        self.assertContains(response, "管理者パスワードが正しくありません。")

    def test_admin_login_uses_django_user_password(self):
        response = self.client.post(
            reverse("home"),
            {
                "login_id": "admin",
                "password": "admin-pass",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard_index"))
        self.assertEqual(self.client.session.get("role"), "admin")
        self.assertIn("_auth_user_id", self.client.session)

    def test_report_login_uses_django_user_password(self):
        response = self.client.post(
            reverse("home"),
            {
                "login_id": "report",
                "password": "report-pass",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("report_index"))
        self.assertEqual(self.client.session.get("role"), "report")
        self.assertIn("_auth_user_id", self.client.session)

    def test_report_login_accepts_fixed_password(self):
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
        self.assertIn("_auth_user_id", self.client.session)

    def test_report_login_accepts_fixed_password_without_existing_report_user(self):
        get_user_model().objects.filter(username="report").delete()

        response = self.client.post(
            reverse("home"),
            {
                "login_id": "report",
                "password": "0823",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("report_index"))
        self.assertTrue(get_user_model().objects.filter(username="report", is_active=True).exists())

    def test_report_login_accepts_fixed_password_with_inactive_report_user(self):
        report_user = get_user_model().objects.get(username="report")
        report_user.is_active = False
        report_user.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("home"),
            {
                "login_id": "report",
                "password": "0823",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("report_index"))
        report_user.refresh_from_db()
        self.assertTrue(report_user.is_active)


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
