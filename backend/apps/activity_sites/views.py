from functools import wraps

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.dairymetrics.models import MemberDailyMetricEntry, MemberMetricTransaction
from apps.performance.services.navigation import performance_nav_items
from .models import ActivitySite, ActivitySiteAlias, ActivitySiteDepartment, ActivitySiteProposal, normalize_site_name


def staff_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('performance_login')}?next={request.get_full_path()}")
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapper


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
