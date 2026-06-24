from apps.targets.models import Period, TARGET_STATUS_ACTIVE, TARGET_STATUS_PLANNED


def current_active_period(*, target_date):
    active_in_range = (
        Period.objects.filter(
            status=TARGET_STATUS_ACTIVE,
            start_date__lte=target_date,
            end_date__gte=target_date,
        )
        .order_by("-start_date", "-end_date", "-id")
        .first()
    )
    if active_in_range:
        return active_in_range
    return Period.objects.filter(status=TARGET_STATUS_ACTIVE).order_by("-start_date", "-end_date", "-id").first()


def period_options_active_first(*, target_date, limit=24):
    active_period = current_active_period(target_date=target_date)
    periods = []
    seen_ids = set()
    if active_period:
        periods.append(active_period)
        seen_ids.add(active_period.id)
    for period in Period.objects.exclude(status=TARGET_STATUS_PLANNED).order_by("-end_date", "-start_date", "-id"):
        if period.id in seen_ids:
            continue
        periods.append(period)
        if len(periods) >= limit:
            break
    return periods
