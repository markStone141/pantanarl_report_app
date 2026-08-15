from functools import wraps

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import urlencode

from apps.accounts.models import Department
from apps.dairymetrics.models import MemberDailyMetricEntry, MemberMetricTransaction, MetricAdjustment
from apps.performance.services.navigation import performance_nav_items
from .models import ActivitySite, ActivitySiteAlias, ActivitySiteDepartment, ActivitySiteProposal, normalize_site_name
from .selectors import SORT_FIELDS, activity_site_history_queryset, build_activity_site_comparison


ADJUSTMENT_SOURCE_LABELS = dict(MetricAdjustment.SOURCE_CHOICES)


def staff_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('performance_login')}?next={request.get_full_path()}")
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapper


def _activity_site_filter_context(request):
    today = timezone.localdate()
    default_start = today.replace(day=1)
    start_date = parse_date(request.GET.get("start_date") or "") or default_start
    end_date = parse_date(request.GET.get("end_date") or "") or today
    error_message = ""
    if start_date > end_date:
        start_date, end_date = default_start, today
        error_message = "期間の開始日は終了日以前にしてください。今月の期間で表示しています。"

    department_id = request.GET.get("department") or None
    departments = Department.objects.filter(is_active=True).order_by("code")
    if department_id and (not department_id.isdigit() or not departments.filter(pk=department_id).exists()):
        department_id = None
    return {
        "start_date": start_date,
        "end_date": end_date,
        "department_id": department_id,
        "departments": departments,
        "selected_department_id": str(department_id or ""),
        "error_message": error_message,
    }


def _site_for_name(canonical_name, *, reviewer):
    normalized_name = normalize_site_name(canonical_name)
    site = ActivitySite.objects.filter(normalized_name=normalized_name).first()
    merged = site is not None
    if site is None:
        alias = ActivitySiteAlias.objects.select_related("site").filter(normalized_name=normalized_name).first()
        site = alias.site if alias else None
        merged = site is not None
    if site is None:
        site = ActivitySite.objects.create(canonical_name=canonical_name, created_by=reviewer, approved_by=reviewer)
    return site, merged


def _attach_proposal_alias(*, proposal, site):
    alias_key = normalize_site_name(proposal.proposed_name)
    if alias_key == site.normalized_name:
        return
    canonical_owner = ActivitySite.objects.filter(normalized_name=alias_key).first()
    existing = ActivitySiteAlias.objects.filter(normalized_name=alias_key).first()
    owner_id = canonical_owner.id if canonical_owner else (existing.site_id if existing else None)
    if owner_id and owner_id != site.id:
        raise ValidationError("申請名は別の正式現場に使用されているため統合先を確認してください。")
    if existing is None:
        ActivitySiteAlias.objects.create(
            site=site,
            alias_name=proposal.proposed_name,
            source=ActivitySiteAlias.SOURCE_PROPOSAL,
        )


def _resolve_proposal(request, proposal):
    action = (request.POST.get("action") or "").strip()
    review_note = (request.POST.get("review_note") or "").strip()
    if action == "reject":
        proposal.status = ActivitySiteProposal.STATUS_REJECTED
        proposal.reviewed_by = request.user
        proposal.review_note = review_note
        proposal.reviewed_at = timezone.now()
        proposal.save(update_fields=["status", "reviewed_by", "review_note", "reviewed_at", "updated_at"])
        return "rejected"

    if action == "merge":
        resolved_site_id = (request.POST.get("resolved_site") or "").strip()
        if not resolved_site_id.isdigit():
            raise ValidationError("統合先の現場を選択してください。")
        site = get_object_or_404(ActivitySite, pk=resolved_site_id, is_active=True)
        merged = True
    elif action == "approve":
        canonical_name = (request.POST.get("canonical_name") or "").strip()
        if not canonical_name:
            raise ValidationError("正式な現場名を入力してください。")
        site, merged = _site_for_name(canonical_name, reviewer=request.user)
    else:
        raise ValidationError("申請の操作を確認してください。")

    ActivitySiteDepartment.objects.get_or_create(site=site, department=proposal.department)
    _attach_proposal_alias(proposal=proposal, site=site)
    proposal.status = ActivitySiteProposal.STATUS_MERGED if merged else ActivitySiteProposal.STATUS_APPROVED
    proposal.resolved_site = site
    proposal.reviewed_by = request.user
    proposal.review_note = review_note
    proposal.reviewed_at = timezone.now()
    proposal.save(
        update_fields=["status", "resolved_site", "reviewed_by", "review_note", "reviewed_at", "updated_at"]
    )
    MemberDailyMetricEntry.objects.filter(activity_site_proposal=proposal).update(activity_site=site)
    MemberMetricTransaction.objects.filter(entry__activity_site_proposal=proposal).update(activity_site=site)
    return "merged" if merged else "approved"


@staff_required
def activity_site_proposals_manage(request):
    error_message = ""
    if request.method == "POST":
        try:
            proposal_id = (request.POST.get("proposal_id") or "").strip()
            if not proposal_id.isdigit():
                raise ValidationError("対象の申請を確認してください。")
            with transaction.atomic():
                proposal = get_object_or_404(
                    ActivitySiteProposal.objects.select_for_update().select_related("department"),
                    pk=proposal_id,
                )
                if proposal.status != ActivitySiteProposal.STATUS_PENDING:
                    return redirect(f"{reverse('performance_activity_site_proposals')}?updated=already-reviewed")
                result = _resolve_proposal(request, proposal)
            return redirect(f"{reverse('performance_activity_site_proposals')}?updated={result}")
        except ValidationError as exc:
            error_message = " ".join(exc.messages)

    proposals = list(
        ActivitySiteProposal.objects.filter(status=ActivitySiteProposal.STATUS_PENDING)
        .select_related("department", "proposed_by")
        .order_by("created_at", "id")
    )
    return render(
        request,
        "activity_sites/proposal_manage.html",
        {
            "nav_items": performance_nav_items(),
            "proposals": proposals,
            "active_sites": ActivitySite.objects.filter(is_active=True).order_by("canonical_name", "id"),
            "error_message": error_message,
            "updated": request.GET.get("updated") or "",
        },
    )


@staff_required
def activity_site_comparison(request):
    filters = _activity_site_filter_context(request)
    sort = request.GET.get("sort") or "support_amount"
    sort = sort if sort in SORT_FIELDS else "support_amount"
    direction = request.GET.get("direction") or "desc"
    direction = direction if direction in {"asc", "desc"} else "desc"
    rows = build_activity_site_comparison(
        start_date=filters["start_date"],
        end_date=filters["end_date"],
        department_id=filters["department_id"],
        sort=sort,
        direction=direction,
    )
    page = Paginator(rows, 24).get_page(request.GET.get("page"))
    return render(
        request,
        "activity_sites/comparison.html",
        {
            "nav_items": performance_nav_items(),
            "page": page,
            "sort": sort,
            "direction": direction,
            **filters,
        },
    )


@staff_required
def activity_site_detail(request, site_id):
    site = get_object_or_404(ActivitySite, pk=site_id)
    filters = _activity_site_filter_context(request)
    summary_rows = build_activity_site_comparison(
        start_date=filters["start_date"],
        end_date=filters["end_date"],
        department_id=filters["department_id"],
        site_id=site.id,
    )
    history = activity_site_history_queryset(
        site_id=site.id,
        start_date=filters["start_date"],
        end_date=filters["end_date"],
        department_id=filters["department_id"],
    )
    page = Paginator(history, 20).get_page(request.GET.get("page"))
    for row in page.object_list:
        if row["history_source"] == "補正":
            row["history_source"] = f"補正（{ADJUSTMENT_SOURCE_LABELS.get(row['history_source_code'], 'その他')}）"

    comparison_query = urlencode(
        {
            "start_date": filters["start_date"].isoformat(),
            "end_date": filters["end_date"].isoformat(),
            "department": filters["selected_department_id"],
            "sort": request.GET.get("sort") or "support_amount",
            "direction": request.GET.get("direction") or "desc",
        }
    )
    return render(
        request,
        "activity_sites/detail.html",
        {
            "nav_items": performance_nav_items(),
            "site": site,
            "summary": summary_rows[0] if summary_rows else None,
            "page": page,
            "comparison_query": comparison_query,
            "sort": request.GET.get("sort") or "support_amount",
            "direction": request.GET.get("direction") or "desc",
            **filters,
        },
    )
