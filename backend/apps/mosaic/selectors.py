from django.db.models import Count, Q, Sum

from .models import MosaicInteraction


def mosaic_dashboard_payload(*, target_date):
    queryset = MosaicInteraction.objects.filter(interaction_date=target_date).select_related(
        "service_member",
        "credited_member",
        "result",
    ).prefetch_related("trial_model_steps__trial_model")
    total_count = queryset.count()
    payment_count = queryset.filter(payment_amount__gt=0).count()
    total_amount = queryset.aggregate(total=Sum("payment_amount"))["total"] or 0
    close_rate = round(payment_count / total_count * 100, 1) if total_count else None

    member_rows = []
    member_stats = (
        queryset.values("credited_member__name")
        .annotate(
            interaction_count=Count("id"),
            payment_count=Count("id", filter=Q(payment_amount__gt=0)),
            total_amount=Sum("payment_amount"),
        )
        .order_by("-total_amount", "-payment_count", "credited_member__name")
    )
    for row in member_stats:
        member_rows.append(
            {
                "name": row["credited_member__name"] or "未設定",
                "interaction_count": row["interaction_count"],
                "payment_count": row["payment_count"],
                "total_amount": int(row["total_amount"] or 0),
            }
        )

    result_rows = []
    result_stats = queryset.values("result__name").annotate(count=Count("id")).order_by("-count", "result__name")
    for row in result_stats:
        result_rows.append({"name": row["result__name"] or "未設定", "count": row["count"]})

    latest_interactions = list(queryset.order_by("-created_at", "-id")[:10])
    return {
        "target_date": target_date,
        "total_count": total_count,
        "payment_count": payment_count,
        "total_amount": int(total_amount),
        "close_rate": close_rate,
        "member_rows": member_rows,
        "result_rows": result_rows,
        "latest_interactions": latest_interactions,
    }
