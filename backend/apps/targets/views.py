from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def target_index(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "targets/target_dashboard.html",
        {
            "current_month_label": "2026年2月度",
            "current_period_label": "第一次路程（2/10〜2/15）",
            "month_targets": [
                {"department": "UN", "count": 180, "amount": 280000},
                {"department": "WV", "count": 150, "amount": 180000},
                {"department": "Style1", "count": 120, "amount": 400000},
                {"department": "Style2", "count": 90, "amount": 450000},
            ],
            "period_targets": [
                {"department": "UN", "count": 45, "amount": 88000},
                {"department": "WV", "count": 39, "amount": 60000},
                {"department": "Style1", "count": 28, "amount": 136000},
                {"department": "Style2", "count": 30, "amount": 150000},
            ],
        },
    )


def target_month_settings(request: HttpRequest) -> HttpResponse:
    return render(request, "targets/target_month_settings.html")


def target_period_settings(request: HttpRequest) -> HttpResponse:
    return render(request, "targets/target_period_settings.html")
