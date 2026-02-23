from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def target_index(request: HttpRequest) -> HttpResponse:
    return render(request, "targets/target_settings.html")
