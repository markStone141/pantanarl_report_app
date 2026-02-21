from django.http import HttpRequest, HttpResponse


def report_index(request: HttpRequest) -> HttpResponse:
    return HttpResponse("reports index")
