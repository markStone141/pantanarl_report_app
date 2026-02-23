import re
from datetime import date

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import Department

from .models import DepartmentMonthTarget, DepartmentPeriodTarget, Period

TARGET_DEPARTMENTS = [
    ("UN", "UN"),
    ("WV", "WV"),
    ("STYLE1", "Style1"),
    ("STYLE2", "Style2"),
]

PERIOD_SEQUENCE_OPTIONS = list(range(1, 11))


def _month_value_from_date(value: date) -> str:
    return value.strftime("%Y-%m")


def _month_start(month_value: str | None) -> date:
    if not month_value:
        today = timezone.localdate()
        return today.replace(day=1)
    try:
        year_str, month_str = month_value.split("-", 1)
        return date(int(year_str), int(month_str), 1)
    except (TypeError, ValueError):
        today = timezone.localdate()
        return today.replace(day=1)


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


def _month_target_rows(target_month: date):
    existing = {
        target.department.code: target
        for target in DepartmentMonthTarget.objects.filter(target_month=target_month).select_related("department")
    }
    rows = []
    for code, label in TARGET_DEPARTMENTS:
        target = existing.get(code)
        rows.append(
            {
                "code": code,
                "label": label,
                "count": target.target_count if target else 0,
                "amount": target.target_amount if target else 0,
            }
        )
    return rows


def _period_target_rows(period: Period | None):
    if not period:
        return [{"code": code, "label": label, "count": 0, "amount": 0} for code, label in TARGET_DEPARTMENTS]
    existing = {
        target.department.code: target
        for target in DepartmentPeriodTarget.objects.filter(period=period).select_related("department")
    }
    rows = []
    for code, label in TARGET_DEPARTMENTS:
        target = existing.get(code)
        rows.append(
            {
                "code": code,
                "label": label,
                "count": target.target_count if target else 0,
                "amount": target.target_amount if target else 0,
            }
        )
    return rows


def _period_label(period: Period | None) -> str:
    if not period:
        return "未設定"
    return f"{period.name} ({period.start_date:%m/%d} - {period.end_date:%m/%d})"


def _sequence_from_period_name(name: str) -> int:
    match = re.match(r"^第(\d+)次路程$", name)
    if not match:
        return 1
    return int(match.group(1))


def target_index(request: HttpRequest) -> HttpResponse:
    current_month = (
        DepartmentMonthTarget.objects.order_by("-target_month").values_list("target_month", flat=True).first()
    )
    if not current_month:
        current_month = timezone.localdate().replace(day=1)
    current_period = Period.objects.order_by("-month", "start_date", "id").first()

    return render(
        request,
        "targets/target_dashboard.html",
        {
            "current_month_label": f"{current_month.year}年{current_month.month}月",
            "current_period_label": _period_label(current_period),
            "month_targets": _month_target_rows(current_month),
            "period_targets": _period_target_rows(current_period),
        },
    )


def target_month_settings(request: HttpRequest) -> HttpResponse:
    month_param = request.GET.get("month")
    selected_month = _month_start(month_param)

    if request.method == "POST" and request.POST.get("action") == "save_month_targets":
        selected_month = _month_start(request.POST.get("month"))
        for code, label in TARGET_DEPARTMENTS:
            department = _department_by_code(code=code, label=label)
            DepartmentMonthTarget.objects.update_or_create(
                department=department,
                target_month=selected_month,
                defaults={
                    "target_count": _to_int(request.POST.get(f"count_{code}")),
                    "target_amount": _to_int(request.POST.get(f"amount_{code}")),
                },
            )
        return redirect(f"{request.path}?month={_month_value_from_date(selected_month)}&saved=1")

    all_months = (
        DepartmentMonthTarget.objects.order_by("-target_month").values_list("target_month", flat=True).distinct()[:6]
    )
    recent_month_rows = []
    for month in all_months:
        row = {"month_label": f"{month.year}年{month.month}月"}
        values = {
            target.department.code: target.target_count
            for target in DepartmentMonthTarget.objects.filter(target_month=month).select_related("department")
        }
        for code, _ in TARGET_DEPARTMENTS:
            row[code] = values.get(code, 0)
        recent_month_rows.append(row)

    return render(
        request,
        "targets/target_month_settings.html",
        {
            "selected_month": _month_value_from_date(selected_month),
            "selected_month_label": f"{selected_month.year}年{selected_month.month}月",
            "rows": _month_target_rows(selected_month),
            "recent_month_rows": recent_month_rows,
            "saved": request.GET.get("saved") == "1",
        },
    )


def target_period_settings(request: HttpRequest) -> HttpResponse:
    selected_period = None
    period_id = request.GET.get("period")
    if period_id and period_id.isdigit():
        selected_period = Period.objects.filter(id=int(period_id)).first()

    period_saved = False
    target_saved = False
    form_error = None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_period":
            edit_id = request.POST.get("edit_period_id")
            period_month = _month_start(request.POST.get("period_month"))
            sequence_str = (request.POST.get("period_sequence") or "").strip()
            start_date_str = request.POST.get("start_date")
            end_date_str = request.POST.get("end_date")
            try:
                start_date = date.fromisoformat(start_date_str or "")
                end_date = date.fromisoformat(end_date_str or "")
            except ValueError:
                form_error = "開始日と終了日の形式が不正です。"
            else:
                if not sequence_str.isdigit():
                    form_error = "路程番号を選択してください。"
                else:
                    sequence = int(sequence_str)
                    if sequence not in PERIOD_SEQUENCE_OPTIONS:
                        form_error = "路程番号が不正です。"
                    elif start_date > end_date:
                        form_error = "開始日は終了日以前を指定してください。"
                    else:
                        name = f"第{sequence}次路程"
                        if edit_id and edit_id.isdigit():
                            selected_period = get_object_or_404(Period, id=int(edit_id))
                            selected_period.month = period_month
                            selected_period.name = name
                            selected_period.start_date = start_date
                            selected_period.end_date = end_date
                            selected_period.save(
                                update_fields=["month", "name", "start_date", "end_date", "updated_at"]
                            )
                        else:
                            selected_period = Period.objects.create(
                                month=period_month,
                                name=name,
                                start_date=start_date,
                                end_date=end_date,
                            )
                        period_saved = True
        elif action == "save_period_targets":
            selected_id = request.POST.get("selected_period_id")
            if selected_id and selected_id.isdigit():
                selected_period = get_object_or_404(Period, id=int(selected_id))
                for code, label in TARGET_DEPARTMENTS:
                    department = _department_by_code(code=code, label=label)
                    DepartmentPeriodTarget.objects.update_or_create(
                        period=selected_period,
                        department=department,
                        defaults={
                            "target_count": _to_int(request.POST.get(f"count_{code}")),
                            "target_amount": _to_int(request.POST.get(f"amount_{code}")),
                        },
                    )
                target_saved = True
            else:
                form_error = "対象の路程を選択してください。"

    if not selected_period:
        selected_period = Period.objects.order_by("-month", "start_date", "id").first()

    periods = Period.objects.order_by("-month", "start_date", "id")
    selected_month = timezone.localdate().replace(day=1)
    selected_sequence = 1
    selected_start = ""
    selected_end = ""
    selected_id = ""
    if selected_period:
        selected_month = selected_period.month
        selected_sequence = _sequence_from_period_name(selected_period.name)
        selected_start = selected_period.start_date.isoformat()
        selected_end = selected_period.end_date.isoformat()
        selected_id = str(selected_period.id)

    period_options = [
        {
            "id": period.id,
            "label": f"{period.name} ({period.start_date:%Y/%m/%d} - {period.end_date:%Y/%m/%d})",
        }
        for period in periods
    ]

    return render(
        request,
        "targets/target_period_settings.html",
        {
            "selected_period": selected_period,
            "selected_period_label": _period_label(selected_period),
            "rows": _period_target_rows(selected_period),
            "period_options": period_options,
            "period_sequence_options": PERIOD_SEQUENCE_OPTIONS,
            "form_month": _month_value_from_date(selected_month),
            "form_sequence": selected_sequence,
            "form_start_date": selected_start,
            "form_end_date": selected_end,
            "form_edit_period_id": selected_id,
            "period_saved": period_saved or request.GET.get("period_saved") == "1",
            "target_saved": target_saved or request.GET.get("target_saved") == "1",
            "form_error": form_error,
        },
    )
