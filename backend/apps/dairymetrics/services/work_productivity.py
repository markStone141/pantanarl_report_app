from collections import defaultdict

from django.db.models import Count, Sum

from apps.dairymetrics.models import MemberDailyMetricEntry


def build_normal_work_productivity(*, department, start_date, end_date):
    """Normal entry amounts per member-day, including zero-payment workers."""
    days = MemberDailyMetricEntry.objects.filter(
        department=department, entry_date__range=(start_date, end_date),
    ).values("entry_date").annotate(
        amount=Sum("support_amount"), workers=Count("member_id", distinct=True),
    ).order_by("entry_date")

    def row(label, amount, workers):
        average = round(amount / workers, 2) if workers else None
        return {
            "label": label, "amount": amount, "workers": workers, "average": average,
            "amount_text": f"{amount:,}円", "workers_text": f"{workers:,}",
            "average_text": f"{average:,.0f}円" if average is not None else "—",
        }

    daily = []
    months = defaultdict(lambda: {"amount": 0, "workers": 0})
    for day in days:
        amount = int(day["amount"] or 0)
        workers = int(day["workers"] or 0)
        daily.append(row(day["entry_date"].isoformat(), amount, workers))
        month = months[day["entry_date"].strftime("%Y/%m")]
        month["amount"] += amount
        month["workers"] += workers
    monthly = [row(label, values["amount"], values["workers"]) for label, values in months.items()]
    return {
        "summary": row("選択期間", sum(r["amount"] for r in daily), sum(r["workers"] for r in daily)),
        "daily": daily, "monthly": monthly,
    }
