from django.http import HttpRequest, HttpResponse


def target_index(request: HttpRequest) -> HttpResponse:
    return HttpResponse("targets index")
