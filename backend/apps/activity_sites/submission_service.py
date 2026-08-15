from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q

from .models import ActivitySite, ActivitySiteAlias, ActivitySiteProposal, normalize_site_name


@dataclass(frozen=True)
class ActivitySiteSubmission:
    site: ActivitySite | None
    proposal: ActivitySiteProposal | None
    location_name: str


def available_activity_sites(department):
    return (
        ActivitySite.objects.filter(
            Q(department_links__department=department) | Q(department_links__isnull=True),
            is_active=True,
        )
        .distinct()
        .order_by("canonical_name", "id")
    )


@transaction.atomic
def resolve_activity_site_submission(*, department, proposed_by, selected_site=None, new_name="", legacy_name=""):
    if selected_site is not None:
        return ActivitySiteSubmission(selected_site, None, selected_site.canonical_name)

    proposed_name = str(new_name or "").strip()
    if proposed_name:
        normalized_name = normalize_site_name(proposed_name)
        site = ActivitySite.objects.filter(normalized_name=normalized_name, is_active=True).first()
        if site is None:
            alias = ActivitySiteAlias.objects.select_related("site").filter(normalized_name=normalized_name).first()
            site = alias.site if alias and alias.site.is_active else None
        if site is not None:
            return ActivitySiteSubmission(site, None, site.canonical_name)
        proposal, _ = ActivitySiteProposal.objects.get_or_create(
            department=department,
            normalized_name=normalized_name,
            status=ActivitySiteProposal.STATUS_PENDING,
            defaults={"proposed_name": proposed_name, "proposed_by": proposed_by},
        )
        return ActivitySiteSubmission(None, proposal, proposal.proposed_name)

    raw_name = str(legacy_name or "").strip()
    return ActivitySiteSubmission(None, None, raw_name)
