from django.shortcuts import redirect
from django.urls import reverse


def performance_redirect_for_user(user, *, fallback=""):
    if fallback and isinstance(fallback, str) and fallback.startswith("/performance/"):
        return redirect(fallback)
    if user.is_staff or user.is_superuser:
        return redirect("performance_index")
    return redirect("performance_member_dashboard")


def performance_next_url(next_url: str, *, fallback: str) -> str:
    if next_url and isinstance(next_url, str) and next_url.startswith("/performance/"):
        return next_url
    return fallback


def can_edit_member_performance(*, is_admin: bool, readonly_member_view: bool) -> bool:
    return bool(is_admin or not readonly_member_view)


def performance_nav_items():
    return [
        ("performance_index", "実績管理ダッシュボード"),
        ("dairymetrics_entry_v2_transaction_demo", "決済入力"),
        ("performance_history", "過去の実績を見る"),
        ("performance_admin_entries", "全体エントリー管理"),
        ("performance_closeout_notes", "今日のあと一歩ノート"),
        ("performance_past_entry_create", "過去実績入力"),
        ("performance_adjustments", "戻り・増額登録"),
        ("testimony_article_list", "証を見る"),
        ("talks_index", "お知らせ"),
        ("dashboard_index", "総合管理者ページ"),
    ]


def performance_member_nav_items(*, is_admin=False):
    if is_admin:
        return [
            ("performance_index", "実績管理ダッシュボード"),
            ("dairymetrics_entry_v2_transaction_demo", "決済入力"),
            ("performance_closeout_notes", "今日のあと一歩ノート"),
            ("performance_history", "過去の実績を見る"),
            ("testimony_article_list", "証を見る"),
            ("talks_index", "お知らせ"),
        ]
    return [
        ("performance_member_dashboard", "実績管理ダッシュボード"),
        ("dairymetrics_entry_v2_transaction_demo", "決済入力"),
        ("performance_closeout_notes", "今日のあと一歩ノート"),
        ("performance_index", "全体実績"),
        ("performance_member_history", "過去の実績を見る"),
        ("testimony_article_list", "証を見る"),
        ("talks_index", "お知らせ"),
    ]


def performance_member_page_nav_links(*, member, department, is_admin=False, readonly_member_view=False):
    links = []
    if is_admin:
        links.append(
            {
                "href": reverse("performance_index"),
                "label": "管理者用ダッシュボード",
            }
        )
    if readonly_member_view:
        links.extend(
            [
                {
                    "href": reverse("performance_member_insight", args=[member.id, department.id]),
                    "label": "実績管理ダッシュボード",
                },
                {
                    "href": reverse("performance_member_history_insight", args=[member.id, department.id]),
                    "label": "過去の実績を見る",
                },
                {
                    "href": reverse("performance_closeout_notes"),
                    "label": "今日のあと一歩ノート",
                },
                {
                    "href": reverse("testimony_article_list"),
                    "label": "証を見る",
                },
                {
                    "href": reverse("talks_index"),
                    "label": "お知らせ",
                },
            ]
        )
        return links
    if is_admin:
        links.extend(
            [
                {
                    "href": reverse("performance_member_detail", args=[member.id, department.id]),
                    "label": "実績管理ダッシュボード",
                },
                {
                    "href": reverse("performance_member_history_detail", args=[member.id, department.id]),
                    "label": "過去の実績を見る",
                },
                {
                    "href": reverse("performance_closeout_notes"),
                    "label": "今日のあと一歩ノート",
                },
                {
                    "href": reverse("testimony_article_list"),
                    "label": "証を見る",
                },
                {
                    "href": reverse("talks_index"),
                    "label": "お知らせ",
                },
            ]
        )
        return links
    return [
        {
            "href": reverse("performance_member_dashboard"),
            "label": "実績管理ダッシュボード",
        },
        {
            "href": reverse("performance_index"),
            "label": "全体実績",
        },
        {
            "href": reverse("performance_member_history"),
            "label": "過去の実績を見る",
        },
        {
            "href": reverse("performance_closeout_notes"),
            "label": "今日のあと一歩ノート",
        },
        {
            "href": reverse("testimony_article_list"),
            "label": "証を見る",
        },
        {
            "href": reverse("talks_index"),
            "label": "お知らせ",
        },
    ]
