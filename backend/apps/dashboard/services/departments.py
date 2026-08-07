from __future__ import annotations

from apps.accounts.models import Department, Member
from apps.targets.models import TargetMetric

from apps.dashboard.forms import DepartmentForm, TargetMetricForm


def department_form(*, data=None, initial=None, edit_department=None) -> DepartmentForm:
    form = DepartmentForm(data=data, initial=initial)
    if edit_department:
        reporter_ids = Member.objects.active().filter(
            department_links__department=edit_department,
        ).values_list("id", flat=True)
        form.fields["default_reporter"].queryset = Member.objects.active().filter(
            id__in=reporter_ids,
        ).order_by("name")
    else:
        form.fields["default_reporter"].queryset = Member.objects.none()
    return form


def target_metric_form(*, data=None, initial=None) -> TargetMetricForm:
    return TargetMetricForm(data=data, initial=initial)


def department_form_initial(department: Department | None) -> dict | None:
    if not department:
        return None
    return {
        "name": department.name,
        "code": department.code,
        "default_reporter": department.default_reporter_id,
        "show_in_dashboard_submission": department.show_in_dashboard_submission,
        "show_in_dashboard_progress": department.show_in_dashboard_progress,
    }


def selected_metric_department(*, raw_department_id: str | None, edit_department: Department | None):
    if raw_department_id and raw_department_id.isdigit():
        department = Department.objects.filter(id=int(raw_department_id)).first()
        if department:
            return department
    return edit_department or Department.objects.order_by("code").first()


def metric_form_for_edit(*, raw_metric_id: str | None, selected_department):
    if not raw_metric_id or not raw_metric_id.isdigit() or not selected_department:
        return None, target_metric_form(initial={"display_order": 1, "is_active": True})

    metric = TargetMetric.objects.filter(
        id=int(raw_metric_id),
        department=selected_department,
    ).first()
    if not metric:
        return None, target_metric_form(initial={"display_order": 1, "is_active": True})

    return metric, target_metric_form(
        initial={
            "label": metric.label,
            "code": metric.code,
            "unit": metric.unit,
            "display_order": metric.display_order,
            "is_active": metric.is_active,
        }
    )
