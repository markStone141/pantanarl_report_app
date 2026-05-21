from __future__ import annotations

from django.contrib.auth import get_user_model

from apps.accounts.models import Department, Member, MemberDepartment


class AppTestMixin:
    DEFAULT_PASSWORD = "pass1234"

    def create_user(self, username: str, *, password: str | None = None, **kwargs):
        user_model = get_user_model()
        return user_model.objects.create_user(
            username=username,
            password=password or self.DEFAULT_PASSWORD,
            **kwargs,
        )

    def create_department(self, code: str, *, name: str | None = None, **kwargs) -> Department:
        return Department.objects.create(code=code, name=name or code, **kwargs)

    def create_member(
        self,
        *,
        name: str,
        user=None,
        department: Department | None = None,
        default_department: Department | None = None,
        email: str = "",
        **kwargs,
    ) -> Member:
        member = Member.objects.create(
            name=name,
            user=user,
            default_department=default_department or department,
            email=email,
            **kwargs,
        )
        if department:
            MemberDepartment.objects.get_or_create(member=member, department=department)
        return member

    def create_member_user(
        self,
        *,
        username: str,
        name: str,
        department: Department | None = None,
        password: str | None = None,
        is_staff: bool = False,
        email: str = "",
        default_department: Department | None = None,
        **member_kwargs,
    ):
        user = self.create_user(username, password=password, is_staff=is_staff)
        member = self.create_member(
            name=name,
            user=user,
            department=department,
            default_department=default_department,
            email=email,
            **member_kwargs,
        )
        return user, member

    def login(self, user) -> None:
        self.client.force_login(user)
