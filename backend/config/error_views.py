from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def _render_error(
    request: HttpRequest,
    *,
    status: int,
    title: str,
    message: str,
    guidance: str,
) -> HttpResponse:
    return render(
        request,
        f"{status}.html",
        {
            "error_status": status,
            "error_title": title,
            "error_message": message,
            "error_guidance": guidance,
        },
        status=status,
    )


def permission_denied(request: HttpRequest, exception=None) -> HttpResponse:
    return _render_error(
        request,
        status=403,
        title="この操作は許可されていません",
        message="現在のアカウントでは、このページまたは操作を利用できません。",
        guidance="前の画面へ戻るか、トップ画面から利用できる機能を選び直してください。",
    )


def page_not_found(request: HttpRequest, exception=None) -> HttpResponse:
    return _render_error(
        request,
        status=404,
        title="ページが見つかりません",
        message="URLが変更されたか、ページが削除された可能性があります。",
        guidance="前の画面へ戻るか、トップ画面から目的の機能を開いてください。",
    )


def server_error(request: HttpRequest) -> HttpResponse:
    return _render_error(
        request,
        status=500,
        title="ページを表示できませんでした",
        message="一時的な問題が発生しています。入力内容は再送信せず、少し時間をおいてください。",
        guidance="トップ画面へ戻って操作をやり直し、解消しない場合は管理者へ連絡してください。",
    )
