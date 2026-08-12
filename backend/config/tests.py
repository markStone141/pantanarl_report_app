from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from .error_views import page_not_found, permission_denied, server_error


class ErrorPageTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/missing/")
        self.request.user = AnonymousUser()

    def test_cross_application_error_pages_have_recovery_actions(self):
        cases = (
            (permission_denied, 403, "この操作は許可されていません"),
            (page_not_found, 404, "ページが見つかりません"),
            (server_error, 500, "ページを表示できませんでした"),
        )

        for view, expected_status, expected_title in cases:
            with self.subTest(status=expected_status):
                response = view(self.request)
                content = response.content.decode()
                self.assertEqual(response.status_code, expected_status)
                self.assertIn(expected_title, content)
                self.assertIn("前の画面へ戻る", content)
                self.assertIn(f'href="{reverse("home")}"', content)
