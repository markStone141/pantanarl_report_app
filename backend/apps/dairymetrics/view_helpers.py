from django.urls import reverse

from apps.accounts.models import Member
from apps.common.target_periods import current_active_period
from apps.targets.models import Period, TARGET_STATUS_PLANNED


def current_period_scope_period(*, today):
    """Current-period screens must never default to finished periods."""
    return current_active_period(target_date=today)


def requested_or_current_period(request, *, today):
    raw_period_id = (request.GET.get("period_id") or "").strip()
    if raw_period_id.isdigit():
        requested_period = Period.objects.exclude(status=TARGET_STATUS_PLANNED).filter(pk=int(raw_period_id)).first()
        if requested_period:
            return requested_period
    return current_period_scope_period(today=today)


def login_redirect_url(user, *, fallback=""):
    if fallback:
        return fallback
    if user.is_staff:
        return reverse("performance_index")
    return reverse("performance_member_dashboard")


def member_directory_queryset():
    return (
        Member.objects.filter(department_links__department__is_active=True)
        .distinct()
        .order_by("name")
        .prefetch_related("department_links__department")
    )
