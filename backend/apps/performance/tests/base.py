from django.test import TestCase
from apps.common.test_helpers import AppTestMixin

class PerformanceTestBase(AppTestMixin, TestCase):
    DEFAULT_PASSWORD = "pass1234"

    def setUp(self):
        self.user = self.create_user("perf-admin", is_staff=True)
        self.login(self.user)
        self.department = self.create_department("UN")
        self.member = self.create_member(name="Alice", department=self.department)
