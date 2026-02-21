from django.http import HttpRequest, HttpResponse


def dashboard_index(request: HttpRequest) -> HttpResponse:
    return HttpResponse("dashboard index")
