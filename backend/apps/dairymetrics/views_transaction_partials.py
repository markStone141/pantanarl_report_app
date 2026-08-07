from django.http import HttpRequest
from django.template.loader import render_to_string


def render_personal_setup_form_partial(request: HttpRequest, context: dict, *, inline: bool) -> str:
    partial_context = {
        **context,
        "department_select_id": "v2-inline-personal-department" if inline else "v2-personal-department",
        "entry_date_id": "v2-inline-personal-date" if inline else "v2-personal-date",
        "location_id": "v2-inline-personal-location" if inline else "v2-personal-location",
        "cs_count_id": "v2-inline-personal-cs-count" if inline else "v2-personal-target-cs-count",
        "refugee_count_id": "v2-inline-personal-refugee-count" if inline else "v2-personal-target-refugee-count",
        "count_select_id": "v2-inline-personal-count-select" if inline else "v2-personal-target-count-select",
        "count_hidden_id": "v2-inline-personal-count-hidden" if inline else "v2-personal-target-count-hidden",
        "count_wrap_id": "v2-inline-personal-count-wrap" if inline else "v2-personal-target-count-wrap",
        "count_custom_id": "v2-inline-personal-count-custom" if inline else "v2-personal-target-count-custom",
        "amount_select_id": "v2-inline-personal-amount-select" if inline else "v2-personal-target-amount-select",
        "amount_hidden_id": "v2-inline-personal-amount-hidden" if inline else "v2-personal-target-amount-hidden",
        "amount_wrap_id": "v2-inline-personal-amount-wrap" if inline else "v2-personal-target-amount-wrap",
        "amount_custom_id": "v2-inline-personal-amount-custom" if inline else "v2-personal-target-amount-custom",
        "submit_label": "修正内容を保存" if inline else "個人の準備を保存",
        "close_button_label": "閉じる" if inline else "",
        "close_button_attr": "data-close-personal-target-edit" if inline else "",
    }
    return render_to_string(
        "dairymetrics/partials/personal_setup_form.html",
        partial_context,
        request=request,
    )


def render_department_target_form_partial(request: HttpRequest, context: dict, *, inline: bool) -> str:
    partial_context = {
        **context,
        "entry_date_id": "v2-inline-target-date" if inline else "v2-dept-target-date",
        "amount_select_id": "v2-inline-target-amount-select" if inline else "v2-dept-target-amount-select",
        "amount_hidden_id": "v2-inline-target-amount-hidden" if inline else "v2-dept-target-amount-hidden",
        "amount_wrap_id": "v2-inline-target-amount-wrap" if inline else "v2-dept-target-amount-wrap",
        "amount_custom_id": "v2-inline-target-amount-custom" if inline else "v2-dept-target-amount-custom",
        "submit_label": "修正内容を保存" if inline else "全体目標を保存",
        "close_button_label": "閉じる" if inline else "",
        "close_button_attr": "data-close-department-target-edit" if inline else "",
        "show_meta": not inline,
    }
    return render_to_string(
        "dairymetrics/partials/department_target_form.html",
        partial_context,
        request=request,
    )
