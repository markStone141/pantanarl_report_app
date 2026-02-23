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
                    member.password = form.cleaned_data["password"]
                    member.save(update_fields=["name", "login_id", "password"])
                    status_message = f"{member.name}（{member.login_id}）を更新しました。"
                else:
                    member = Member.objects.create(
                        name=form.cleaned_data["name"].strip(),
                        login_id=login_id,
                        password=form.cleaned_data["password"],
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
                    "password": edit_member.password,
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
        form = DepartmentForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["code"].strip().upper()
            duplicate_query = Department.objects.filter(code=code)
            if edit_department_id and edit_department_id.isdigit():
                duplicate_query = duplicate_query.exclude(id=int(edit_department_id))

            if duplicate_query.exists():
                form.add_error("code", "この部署コードは既に使われています。")
            else:
                if edit_department_id and edit_department_id.isdigit():
                    department = get_object_or_404(Department, id=int(edit_department_id))
                    department.name = form.cleaned_data["name"].strip()
                    department.code = code
                    department.save(update_fields=["name", "code"])
                    status_message = f"{department.name}（{department.code}）を更新しました。"
                else:
                    department = Department.objects.create(
                        name=form.cleaned_data["name"].strip(),
                        code=code,
                        is_active=True,
                    )
                    status_message = f"{department.name}（{department.code}）を追加しました。"
                form = DepartmentForm()
                edit_department = None
    else:
        if edit_department:
            form = DepartmentForm(
                initial={
                    "name": edit_department.name,
                    "code": edit_department.code,
                }
            )
        else:
            form = DepartmentForm()

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
