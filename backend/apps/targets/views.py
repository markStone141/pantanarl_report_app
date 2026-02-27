import re
from datetime import date

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.auth import ROLE_ADMIN, require_roles
from apps.accounts.models import Department
from apps.common.report_metrics import format_metric_value

from .models import (
    MonthTargetMetricValue,
    Period,
    PeriodTargetMetricValue,
    TargetMetric,
    TARGET_STATUS_ACTIVE,
    TARGET_STATUS_CHOICES,
    TARGET_STATUS_FINISHED,
    TARGET_STATUS_PLANNED,
)

TARGET_DEPARTMENTS = [
    ("UN", "UN"),
    ("WV", "WV"),
    ("STYLE1", "Style1"),
    ("STYLE2", "Style2"),
]

DEFAULT_METRICS_BY_DEPT = {
    "UN": [("count", "件数", "件"), ("amount", "金額", "円")],
    "WV": [("cs_count", "CS件数", "件"), ("refugee_count", "難民支援件数", "件")],
    "STYLE1": [("amount", "金額", "円")],
    "STYLE2": [("amount", "金額", "円")],
}

PERIOD_SEQUENCE_OPTIONS = list(range(1, 11))
STATUS_OPTIONS = [{"value": value, "label": value} for value, _ in TARGET_STATUS_CHOICES]


def _month_value_from_date(value: date) -> str:
    return value.strftime("%Y-%m")


def _month_start(month_value: str | None) -> date:
    if not month_value:
        return timezone.localdate().replace(day=1)
    try:
        year_str, month_str = month_value.split("-", 1)
        return date(int(year_str), int(month_str), 1)
    except (TypeError, ValueError):
        return timezone.localdate().replace(day=1)


def _to_int(value: str | None) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _department_by_code(*, code: str, label: str) -> Department:
    department = Department.objects.filter(code=code).first()
    if department:
        return department
    return Department.objects.create(code=code, name=label)


def _ensure_default_metrics() -> None:
    for dept_code, dept_label in TARGET_DEPARTMENTS:
        department = _department_by_code(code=dept_code, label=dept_label)
        for order, (metric_code, metric_label, metric_unit) in enumerate(
            DEFAULT_METRICS_BY_DEPT[dept_code],
            start=1,
        ):
            TargetMetric.objects.update_or_create(
                department=department,
                code=metric_code,
                defaults={
                    "label": metric_label,
                    "unit": metric_unit,
                    "display_order": order,
                    "is_active": True,
                },
            )


def _department_configs():
    _ensure_default_metrics()
    configs = []
    for code, fallback_label in TARGET_DEPARTMENTS:
        department = _department_by_code(code=code, label=fallback_label)
        metrics = list(
            TargetMetric.objects.filter(department=department, is_active=True).order_by("display_order", "id")
        )
        configs.append(
            {
                "code": code,
                "label": department.name,
                "department": department,
                "metrics": metrics,
            }
        )
    return configs


def _month_status(target_month: date, today: date | None = None) -> str:
    base = today or timezone.localdate()
    current_month = base.replace(day=1)
    if target_month == current_month:
        return TARGET_STATUS_ACTIVE
    if target_month > current_month:
        return TARGET_STATUS_PLANNED
    return TARGET_STATUS_FINISHED


def _period_status(start_date: date, end_date: date, today: date | None = None) -> str:
    base = today or timezone.localdate()
    if start_date <= base <= end_date:
        return TARGET_STATUS_ACTIVE
    if base < start_date:
        return TARGET_STATUS_PLANNED
    return TARGET_STATUS_FINISHED


def _build_target_rows(*, configs, values):
    rows = []
    for config in configs:
        metric_rows = []
        for metric in config["metrics"]:
            metric_rows.append(
                {
                    "id": metric.id,
                    "label": metric.label,
                    "unit": metric.unit,
                    "value": values.get(metric.id, 0),
                    "value_text": format_metric_value(metric_code=metric.code, value=values.get(metric.id, 0)),
                    "input_name": f"metric_{metric.id}",
                }
            )
        rows.append({"label": config["label"], "metrics": metric_rows})
    return rows


def _build_month_rows(*, target_month: date, configs):
    values = {
        value.metric_id: value.value
        for value in MonthTargetMetricValue.objects.filter(
            target_month=target_month,
            metric__is_active=True,
        ).select_related("metric")
    }
    return _build_target_rows(configs=configs, values=values)


def _build_period_rows(*, period: Period | None, configs):
    values = {}
    if period:
        values = {
            value.metric_id: value.value
            for value in PeriodTargetMetricValue.objects.filter(
                period=period,
                metric__is_active=True,
            ).select_related("metric")
        }
    return _build_target_rows(configs=configs, values=values)


def _period_name(*, month: date, sequence: int) -> str:
    return f"{month.year}年度{month.month}月 第{sequence}次路程"


def _period_label(period: Period | None) -> str:
    if not period:
        return "未設定"
    return f"{period.name} ({period.start_date:%m/%d} - {period.end_date:%m/%d})"


def _sequence_from_period_name(name: str) -> int:
    match = re.search(r"第(\d+)次路程", name)
    if not match:
        return 1
    return int(match.group(1))


def _month_history_rows(selected_month: date | None = None, include_selected: bool = False):
    months = (
        MonthTargetMetricValue.objects.order_by("-target_month")
        .values_list("target_month", flat=True)
        .distinct()
    )
    rows = []
    month_set = set(months)
    if selected_month and include_selected:
        month_set.add(selected_month)
    for month in sorted(month_set, reverse=True):
        rows.append(
            {
                "month": month,
                "month_label": f"{month.year}年{month.month}月",
                "status": _month_status(month),
                "month_param": _month_value_from_date(month),
            }
        )
    return rows


def _period_history_rows():
    rows = []
    for period in Period.objects.order_by("-month", "start_date", "id"):
        rows.append(
            {
                "id": period.id,
                "name": period.name,
                "status": _period_status(period.start_date, period.end_date),
                "month_label": f"{period.month.year}年{period.month.month}月",
                "month_param": _month_value_from_date(period.month),
                "start_date": period.start_date.isoformat(),
                "end_date": period.end_date.isoformat(),
                "range_label": f"{period.start_date:%Y/%m/%d} - {period.end_date:%Y/%m/%d}",
            }
        )
    return rows


def _current_month() -> date:
    return timezone.localdate().replace(day=1)


def _current_period() -> Period | None:
    today = timezone.localdate()
    active = Period.objects.filter(start_date__lte=today, end_date__gte=today).order_by("-month", "start_date", "id").first()
    if active:
        return active
    return Period.objects.order_by("-month", "start_date", "id").first()


def _save_month_targets(*, selected_month: date, configs, post_data) -> None:
    status = _month_status(selected_month)
    for config in configs:
        for metric in config["metrics"]:
            MonthTargetMetricValue.objects.update_or_create(
                department=config["department"],
                target_month=selected_month,
                metric=metric,
                defaults={
                    "value": _to_int(post_data.get(f"metric_{metric.id}")),
                    "status": status,
                },
            )


def _parse_period_form(post_data):
    period_month = _month_start(post_data.get("period_month"))
    sequence_str = (post_data.get("period_sequence") or "").strip()
    start_date_str = post_data.get("start_date")
    end_date_str = post_data.get("end_date")
    try:
        start_date = date.fromisoformat(start_date_str or "")
        end_date = date.fromisoformat(end_date_str or "")
    except ValueError:
        return None, "開始日と終了日の形式が不正です。"

    if not sequence_str.isdigit():
        return None, "路程番号を選択してください。"

    sequence = int(sequence_str)
    if sequence not in PERIOD_SEQUENCE_OPTIONS:
        return None, "路程番号が不正です。"
    if start_date > end_date:
        return None, "開始日は終了日以前を指定してください。"

    return {
        "period_month": period_month,
        "sequence": sequence,
        "start_date": start_date,
        "end_date": end_date,
    }, None


def _save_period_definition(*, post_data):
    edit_id = post_data.get("edit_period_id")
    force_overwrite = post_data.get("force_overwrite") == "1"
    overwrite_period_id = post_data.get("overwrite_period_id")
    parsed, error = _parse_period_form(post_data)
    if error:
        return None, False, error

    period_month = parsed["period_month"]
    sequence = parsed["sequence"]
    start_date = parsed["start_date"]
    end_date = parsed["end_date"]
    name = _period_name(month=period_month, sequence=sequence)
    status = _period_status(start_date, end_date)

    if edit_id and edit_id.isdigit():
        selected_period = get_object_or_404(Period, id=int(edit_id))
    else:
        selected_period = Period.objects.filter(month=period_month, name=name).first()
        if selected_period and not force_overwrite:
            return selected_period, False, "同じ名前の路程が既にあります。上書きする場合は確認してください。"

    if (
        not selected_period
        and force_overwrite
        and overwrite_period_id
        and overwrite_period_id.isdigit()
    ):
        selected_period = Period.objects.filter(id=int(overwrite_period_id)).first()

    duplicate_name_query = Period.objects.filter(month=period_month, name=name)
    if selected_period:
        duplicate_name_query = duplicate_name_query.exclude(id=selected_period.id)
    if duplicate_name_query.exists():
        return selected_period, False, "同じ対象月・路程番号の路程が既にあります。"

    overlap_query = Period.objects.filter(
        start_date__lte=end_date,
        end_date__gte=start_date,
    )
    if selected_period:
        overlap_query = overlap_query.exclude(id=selected_period.id)
    if overlap_query.exists():
        return selected_period, False, "指定の期間と重複する路程が既に存在します。上書きする場合は確認してください。"

    if selected_period:
        selected_period.month = period_month
        selected_period.name = name
        selected_period.status = status
        selected_period.start_date = start_date
        selected_period.end_date = end_date
        selected_period.save(
            update_fields=["month", "name", "status", "start_date", "end_date", "updated_at"]
        )
    else:
        selected_period = Period.objects.create(
            month=period_month,
            name=name,
            status=status,
            start_date=start_date,
            end_date=end_date,
        )
    return selected_period, True, None


def _save_period_targets(*, selected_period: Period, configs, post_data) -> None:
    for config in configs:
        for metric in config["metrics"]:
            PeriodTargetMetricValue.objects.update_or_create(
                period=selected_period,
                department=config["department"],
                metric=metric,
                defaults={"value": _to_int(post_data.get(f"metric_{metric.id}"))},
            )


def _period_form_values(selected_period: Period | None, *, include_edit_id: bool = False):
    selected_month = timezone.localdate().replace(day=1)
    selected_sequence = 1
    selected_status = TARGET_STATUS_PLANNED
    selected_start = ""
    selected_end = ""
    selected_id = ""
    if selected_period:
        selected_month = selected_period.month
        selected_sequence = _sequence_from_period_name(selected_period.name)
        selected_status = _period_status(selected_period.start_date, selected_period.end_date)
        selected_start = selected_period.start_date.isoformat()
        selected_end = selected_period.end_date.isoformat()
        if include_edit_id:
            selected_id = str(selected_period.id)
    return {
        "form_month": _month_value_from_date(selected_month),
        "form_sequence": selected_sequence,
        "form_status": selected_status,
        "form_start_date": selected_start,
        "form_end_date": selected_end,
        "form_edit_period_id": selected_id,
    }


def _period_options():
    periods = Period.objects.order_by("-month", "start_date", "id")
    return [
        {
            "id": period.id,
            "label": (
                f"{period.name} "
                f"[{_period_status(period.start_date, period.end_date)}] "
                f"({period.start_date:%Y/%m/%d} - {period.end_date:%Y/%m/%d})"
            ),
        }
        for period in periods
    ]


@require_roles(ROLE_ADMIN)
def target_index(request: HttpRequest) -> HttpResponse:
    configs = _department_configs()
    current_month = _current_month()
    current_period = _current_period()
    return render(
        request,
        "targets/target_dashboard.html",
        {
            "current_month_label": f"{current_month.year}年{current_month.month}月",
            "current_month_status": _month_status(current_month),
            "current_period_label": _period_label(current_period),
            "current_period_status": _period_status(current_period.start_date, current_period.end_date)
            if current_period
            else TARGET_STATUS_PLANNED,
            "month_rows": _build_month_rows(target_month=current_month, configs=configs),
            "period_rows": _build_period_rows(period=current_period, configs=configs),
            "month_history_rows": _month_history_rows(),
            "period_history_rows": _period_history_rows(),
        },
    )


@require_roles(ROLE_ADMIN)
def target_month_settings(request: HttpRequest) -> HttpResponse:
    configs = _department_configs()
    selected_month = _month_start(request.GET.get("month"))
    month_deleted = False

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_month_targets":
            selected_month = _month_start(request.POST.get("month"))
            _save_month_targets(selected_month=selected_month, configs=configs, post_data=request.POST)
            return redirect(f"{request.path}?month={_month_value_from_date(selected_month)}&saved=1")
        if action == "delete_month_targets":
            target_month = _month_start(request.POST.get("delete_month"))
            MonthTargetMetricValue.objects.filter(target_month=target_month).delete()
            selected_month = _current_month()
            month_deleted = True

    history_rows = _month_history_rows()
    return render(
        request,
        "targets/target_month_settings.html",
        {
            "selected_month": _month_value_from_date(selected_month),
            "selected_month_label": f"{selected_month.year}年{selected_month.month}月",
            "selected_status": _month_status(selected_month),
            "status_options": STATUS_OPTIONS,
            "rows": _build_month_rows(target_month=selected_month, configs=configs),
            "history_rows": history_rows,
            "saved": request.GET.get("saved") == "1",
            "month_deleted": month_deleted,
        },
    )


@require_roles(ROLE_ADMIN)
def target_period_settings(request: HttpRequest) -> HttpResponse:
    configs = _department_configs()
    selected_period = None
    is_edit_mode = False
    period_id = request.GET.get("period")
    if period_id and period_id.isdigit():
        selected_period = Period.objects.filter(id=int(period_id)).first()
        is_edit_mode = selected_period is not None

    period_saved = False
    period_deleted = False
    target_saved = False
    form_error = None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_period":
            saved_period, period_saved, form_error = _save_period_definition(post_data=request.POST)
            if saved_period is not None:
                selected_period = saved_period
            posted_edit_id = request.POST.get("edit_period_id")
            is_edit_mode = bool(posted_edit_id and posted_edit_id.isdigit())

        elif action == "save_period_targets":
            selected_id = request.POST.get("selected_period_id")
            if selected_id and selected_id.isdigit():
                selected_period = get_object_or_404(Period, id=int(selected_id))
                _save_period_targets(selected_period=selected_period, configs=configs, post_data=request.POST)
                target_saved = True
            else:
                form_error = "対象の路程を選択してください。"
        elif action == "delete_period":
            delete_period_id = request.POST.get("delete_period_id")
            if delete_period_id and delete_period_id.isdigit():
                deleting_period = Period.objects.filter(id=int(delete_period_id)).first()
                if deleting_period:
                    deleting_period.delete()
                    period_deleted = True
                    if selected_period and str(selected_period.id) == delete_period_id:
                        selected_period = None

    if not selected_period:
        selected_period = _current_period()

    form_values = _period_form_values(selected_period, include_edit_id=is_edit_mode)

    return render(
        request,
        "targets/target_period_settings.html",
        {
            "selected_period": selected_period,
            "selected_period_label": _period_label(selected_period),
            "rows": _build_period_rows(period=selected_period, configs=configs),
            "period_options": _period_options(),
            "period_sequence_options": PERIOD_SEQUENCE_OPTIONS,
            "status_options": STATUS_OPTIONS,
            **form_values,
            "period_saved": period_saved or request.GET.get("period_saved") == "1",
            "period_deleted": period_deleted,
            "target_saved": target_saved or request.GET.get("target_saved") == "1",
            "form_error": form_error,
            "history_rows": _period_history_rows(),
        },
    )
