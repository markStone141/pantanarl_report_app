from apps.accounts.models import Department, Member


def department_member_options(*, department_id, un_code_prefix="", active_only=False):
    if not str(department_id or "").isdigit():
        return []
    if not Department.objects.filter(pk=int(department_id), is_active=True).exists():
        return []

    members = Member.objects.filter(department_links__department_id=int(department_id))
    if active_only:
        members = members.active()
    normalized_code = "".join(character for character in str(un_code_prefix).strip() if character.isdigit())[:5]
    if normalized_code:
        members = members.filter(un_activity_code__startswith=normalized_code)
    return list(
        members.distinct()
        .order_by("name", "id")
        .values("id", "name", "un_activity_code")
    )


def adjustment_member_options(*, department_id):
    if not str(department_id or "").isdigit():
        return {}
    options = department_member_options(
        department_id=department_id,
        active_only=True,
    )
    for option in options:
        option["un_activity_code"] = option["un_activity_code"] or ""
    return {str(department_id): options}


def active_department_code_map():
    return {
        str(department_id): code
        for department_id, code in Department.objects.filter(is_active=True)
        .order_by("code")
        .values_list("id", "code")
    }
