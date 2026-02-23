from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import Department, Member, MemberDepartment
from .forms import DepartmentForm, MemberRegistrationForm


def dashboard_index(request: HttpRequest) -> HttpResponse:
    return render(request, "dashboard/admin.html")


def _member_form(*, data=None, initial=None) -> MemberRegistrationForm:
    form = MemberRegistrationForm(data=data, initial=initial)
    form.fields["departments"].queryset = Department.objects.filter(is_active=True)
    return form


def _department_form(*, data=None, initial=None, edit_department=None) -> DepartmentForm:
    form = DepartmentForm(data=data, initial=initial)
    if edit_department:
        reporter_ids = Member.objects.filter(
            department_links__department=edit_department
        ).values_list("id", flat=True)
        form.fields["default_reporter"].queryset = Member.objects.filter(
            id__in=reporter_ids
        ).order_by("name")
    else:
        form.fields["default_reporter"].queryset = Member.objects.none()
    return form


def member_settings(request: HttpRequest) -> HttpResponse:
    status_message = None
    edit_member = None

    edit_id = request.GET.get("edit")
    if edit_id and edit_id.isdigit():
        edit_member = Member.objects.filter(id=int(edit_id)).first()

    if request.method == "POST":
        edit_member_id = request.POST.get("edit_member_id")
        form = _member_form(data=request.POST)
        if form.is_valid():
            login_id = form.cleaned_data["login_id"].strip().lower()
            departments = form.cleaned_data["departments"]
            input_password = form.cleaned_data["password"]
            duplicate_query = Member.objects.filter(login_id=login_id)
            if edit_member_id and edit_member_id.isdigit():
                duplicate_query = duplicate_query.exclude(id=int(edit_member_id))

            if duplicate_query.exists():
                form.add_error("login_id", "このログインIDは既に使われています。")
            else:
                if edit_member_id and edit_member_id.isdigit():
                    member = get_object_or_404(Member, id=int(edit_member_id))
                    member.name = form.cleaned_data["name"].strip()
                    member.login_id = login_id
                    update_fields = ["name", "login_id"]
                    if input_password:
                        member.password = input_password
                        update_fields.append("password")
                    member.save(update_fields=update_fields)
                    status_message = f"{member.name}（{member.login_id}）を更新しました。"
                else:
                    if not input_password:
                        form.add_error("password", "新規登録時はパスワードが必須です。")
                        members = Member.objects.prefetch_related("department_links")
                        return render(
                            request,
                            "dashboard/member_settings.html",
                            {
                                "form": form,
                                "members": members,
                                "edit_member": edit_member,
                                "status_message": status_message,
                            },
                        )
                    member = Member.objects.create(
                        name=form.cleaned_data["name"].strip(),
                        login_id=login_id,
                        password=input_password,
                    )
                    status_message = f"{member.name}（{member.login_id}）を登録しました。"

                MemberDepartment.objects.filter(member=member).exclude(
                    department__in=departments
                ).delete()
                existing_departments = set(
                    MemberDepartment.objects.filter(member=member).values_list(
                        "department_id",
                        flat=True,
                    )
                )
                for dept in departments:
                    if dept.id not in existing_departments:
                        MemberDepartment.objects.create(member=member, department=dept)

                form = _member_form()
                edit_member = None
    else:
        if edit_member:
            form = _member_form(
                initial={
                    "name": edit_member.name,
                    "login_id": edit_member.login_id,
                    "departments": list(
                        edit_member.department_links.values_list("department_id", flat=True)
                    ),
                }
            )
        else:
            form = _member_form()

    members = Member.objects.prefetch_related("department_links")

    return render(
        request,
        "dashboard/member_settings.html",
        {
            "form": form,
            "members": members,
            "edit_member": edit_member,
            "status_message": status_message,
        },
    )


def member_delete(request: HttpRequest, member_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("member_settings")

    member = get_object_or_404(Member, id=member_id)
    member.delete()
    return redirect("member_settings")


def department_settings(request: HttpRequest) -> HttpResponse:
    status_message = None
    edit_department = None

    edit_id = request.GET.get("edit")
    if edit_id and edit_id.isdigit():
        edit_department = Department.objects.filter(id=int(edit_id)).first()

    if request.method == "POST":
        edit_department_id = request.POST.get("edit_department_id")
        if edit_department_id and edit_department_id.isdigit():
            edit_department = Department.objects.filter(id=int(edit_department_id)).first()
        form = _department_form(data=request.POST, edit_department=edit_department)
        if form.is_valid():
            code = form.cleaned_data["code"].strip().upper()
            default_reporter = form.cleaned_data["default_reporter"]
            duplicate_query = Department.objects.filter(code=code)
            if edit_department_id and edit_department_id.isdigit():
                duplicate_query = duplicate_query.exclude(id=int(edit_department_id))

            if duplicate_query.exists():
                form.add_error("code", "この部署コードは既に使われています。")
            else:
                if edit_department_id and edit_department_id.isdigit():
                    department = get_object_or_404(Department, id=int(edit_department_id))
                    if default_reporter and not MemberDepartment.objects.filter(
                        member=default_reporter,
                        department=department,
                    ).exists():
                        form.add_error(
                            "default_reporter",
                            "この責任者は選択中の部署に所属していません。",
                        )
                        departments = Department.objects.all()
                        return render(
                            request,
                            "dashboard/department_settings.html",
                            {
                                "form": form,
                                "departments": departments,
                                "edit_department": edit_department,
                                "status_message": status_message,
                            },
                        )
                    department.name = form.cleaned_data["name"].strip()
                    department.code = code
                    department.default_reporter = default_reporter
                    department.save(update_fields=["name", "code", "default_reporter"])
                    status_message = f"{department.name}（{department.code}）を更新しました。"
                else:
                    department = Department.objects.create(
                        name=form.cleaned_data["name"].strip(),
                        code=code,
                        default_reporter=None,
                        is_active=True,
                    )
                    status_message = f"{department.name}（{department.code}）を追加しました。"
                form = _department_form()
                edit_department = None
    else:
        if edit_department:
            form = _department_form(
                initial={
                    "name": edit_department.name,
                    "code": edit_department.code,
                    "default_reporter": edit_department.default_reporter_id,
                },
                edit_department=edit_department,
            )
        else:
            form = _department_form()

    departments = Department.objects.all()
    return render(
        request,
        "dashboard/department_settings.html",
        {
            "form": form,
            "departments": departments,
            "edit_department": edit_department,
            "status_message": status_message,
        },
    )


def department_delete(request: HttpRequest, department_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("department_settings")

    department = get_object_or_404(Department, id=department_id)
    department.delete()
    return redirect("department_settings")
