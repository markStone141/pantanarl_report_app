from django.db.models import Prefetch
from django.utils import timezone

from apps.accounts.models import Member

from ..models import (
    MemberMetricTransaction,
    MemberMetricTransactionNotificationState,
    MemberMetricTransactionReaction,
)
from .entry_context import member_departments
from .entry_v2 import transaction_result_type_label


def _today_transaction_queryset(member: Member, *, today, unread_only: bool = False):
    state = getattr(member, "metric_transaction_notification_state", None)
    department_ids = list(member_departments(member).values_list("id", flat=True))
    queryset = MemberMetricTransaction.objects.filter(
        entry__entry_date=today,
        entry__department_id__in=department_ids,
    ).exclude(entry__member=member)
    if unread_only and state and state.last_seen_at:
        queryset = queryset.filter(created_at__gt=state.last_seen_at)
    return queryset


def _serialize_transaction_items(*, member: Member, queryset, limit: int) -> list[dict]:
    items = []
    reaction_choices = list(MemberMetricTransactionReaction.REACTION_CHOICES)
    for transaction in (
        queryset.select_related("entry", "entry__member", "entry__department")
        .prefetch_related(
            Prefetch(
                "reactions",
                queryset=MemberMetricTransactionReaction.objects.select_related("member"),
            )
        )
        .order_by("-created_at", "-id")[:limit]
    ):
        reaction_counts = {reaction_type: 0 for reaction_type, _label in reaction_choices}
        current_reaction_type = ""
        for reaction in transaction.reactions.all():
            reaction_counts[reaction.reaction_type] = reaction_counts.get(reaction.reaction_type, 0) + 1
            if reaction.member_id == member.id:
                current_reaction_type = reaction.reaction_type
        items.append(
            {
                "id": transaction.id,
                "member_name": transaction.entry.member.name,
                "department_code": transaction.entry.department.code,
                "time_label": timezone.localtime(transaction.created_at).strftime("%H:%M"),
                "amount": int(transaction.support_amount or 0),
                "age_band": transaction.get_age_band_display(),
                "gender": transaction.get_gender_display(),
                "nationality": transaction.get_nationality_type_display(),
                "result_type_label": transaction_result_type_label(transaction),
                "is_wv": transaction.entry.department.code.upper() == "WV",
                "location": transaction.location,
                "comment": transaction.comment,
                "reaction_options": [
                    {
                        "type": reaction_type,
                        "label": label,
                        "count": reaction_counts.get(reaction_type, 0),
                        "is_selected": current_reaction_type == reaction_type,
                    }
                    for reaction_type, label in reaction_choices
                ],
            }
        )
    return items


def unread_today_transaction_notification(*, member: Member, url: str = "", today=None, limit: int = 10) -> dict:
    if member is None:
        return {"count": 0, "url": url, "items": []}

    today = today or timezone.localdate()
    queryset = _today_transaction_queryset(member, today=today, unread_only=True)
    return {
        "count": queryset.count(),
        "url": url,
        "items": _serialize_transaction_items(member=member, queryset=queryset, limit=limit),
    }


def today_transaction_history(*, member: Member, today=None, limit: int = 10) -> dict:
    if member is None:
        return {"count": 0, "items": []}
    today = today or timezone.localdate()
    queryset = _today_transaction_queryset(member, today=today, unread_only=False)
    return {
        "count": queryset.count(),
        "items": _serialize_transaction_items(member=member, queryset=queryset, limit=limit),
    }


def mark_today_transaction_notifications_seen(*, member: Member) -> None:
    if member is None:
        return
    MemberMetricTransactionNotificationState.objects.update_or_create(
        member=member,
        defaults={"last_seen_at": timezone.now()},
    )
