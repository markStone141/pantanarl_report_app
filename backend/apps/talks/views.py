from django.http import HttpRequest, HttpResponse


def talks_index(request: HttpRequest) -> HttpResponse:
    return HttpResponse("talks index")
