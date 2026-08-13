from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class LoginFlowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        user_model.objects.create_user(username="admin", password="admin-pass", is_staff=True)
        user_model.objects.create_user(username="report", password="report-pass", is_staff=False)

    def test_login_credentials_set_session_and_redirect_by_role(self):
        cases = (
            ("admin", "admin-pass", "dashboard_index", "admin"),
            ("report", "report-pass", "report_index", "report"),
            ("report", "0823", "report_index", "report"),
        )

        for login_id, password, redirect_name, expected_role in cases:
            with self.subTest(login_id=login_id, password_kind="fixed" if password == "0823" else "user"):
                self.client.logout()
                response = self.client.post(
                    reverse("home"),
                    {"login_id": login_id, "password": password},
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse(redirect_name))
                self.assertEqual(self.client.session.get("role"), expected_role)
                self.assertIn("_auth_user_id", self.client.session)

    def test_authenticated_users_open_report_home_without_reentering_password(self):
        report_user = get_user_model().objects.create_user(
            username="member_report_shortcut",
            password="x",
            is_staff=False,
        )
        cases = (
            (get_user_model().objects.get(username="admin"), "dashboard_index", "admin"),
            (report_user, "report_index", "report"),
        )

        for user, redirect_name, expected_role in cases:
            with self.subTest(username=user.username):
                self.client.logout()
                self.client.force_login(user)
                response = self.client.get(reverse("home"))
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse(redirect_name))
                self.assertEqual(self.client.session.get("role"), expected_role)

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

    def test_login_page_links_to_performance_login_instead_of_dairymetrics_login(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("performance_login"))
        self.assertNotContains(response, reverse("dairymetrics_login"))

    def test_all_login_pages_use_shared_form_state_contract(self):
        login_urls = (
            "home",
            "performance_login",
            "dairymetrics_login",
            "talks_login",
            "testimony_login",
            "mosaic_login",
        )

        for url_name in login_urls:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-auth-login-form", html=False)
                self.assertContains(response, "data-auth-submit-status", html=False)
                self.assertContains(response, "auth-login-card", html=False)

    def test_base_does_not_build_legacy_topbar_menu(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "topbar-menu-toggle", html=False)
        self.assertNotContains(response, "menu-collapsible", html=False)


class RoleGuardTests(TestCase):
    def test_protected_pages_redirect_anonymous_users_to_home(self):
        for url_name in ("dashboard_index", "report_un"):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
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
