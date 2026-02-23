from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import Member
from .forms import MemberRegistrationForm


def dashboard_index(request: HttpRequest) -> HttpResponse:
    return render(request, "dashboard/admin.html")


def member_settings(request: HttpRequest) -> HttpResponse:
    status_message = None
    edit_member = None

    edit_id = request.GET.get("edit")
    if edit_id and edit_id.isdigit():
        edit_member = Member.objects.filter(id=int(edit_id)).first()

    if request.method == "POST":
        edit_member_id = request.POST.get("edit_member_id")
        form = MemberRegistrationForm(request.POST)
        if form.is_valid():
            login_id = form.cleaned_data["login_id"].strip().lower()
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
                form = MemberRegistrationForm()
                edit_member = None
    else:
        if edit_member:
            form = MemberRegistrationForm(
                initial={
                    "name": edit_member.name,
                    "login_id": edit_member.login_id,
                    "password": edit_member.password,
                }
            )
        else:
            form = MemberRegistrationForm()

    members = Member.objects.all()

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
