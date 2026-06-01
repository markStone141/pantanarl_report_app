from apps.targets.models import Period, TARGET_STATUS_ACTIVE


def current_active_period(*, target_date):
    return (
        Period.objects.filter(
            status=TARGET_STATUS_ACTIVE,
            start_date__lte=target_date,
            end_date__gte=target_date,
        )
        .order_by("-month", "start_date", "id")
        .first()
    )
