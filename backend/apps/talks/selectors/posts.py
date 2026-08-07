from __future__ import annotations

from collections import Counter
from datetime import datetime

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpRequest
from django.utils import timezone

from apps.accounts.models import Member

from ..models import (
    KnowledgePost,
    KnowledgePostFavorite,
    KnowledgePostRead,
    KnowledgeTag,
    KnowledgeUserPreference,
)
from ..services.display import format_post_created_display, talks_author_name


REACTION_CODES = ("good", "keep", "retry", "question")
SORT_NEWEST = "newest"
SORT_COMMENTS = "comments"
SORT_VIEWS = "views"
SORT_DATE_ASC = "date_asc"
SORT_DATE_DESC = "date_desc"
SORT_OPTIONS = (
    (SORT_NEWEST, "新しい順"),
    (SORT_COMMENTS, "コメントが多い順"),
    (SORT_VIEWS, "閲覧数が多い順"),
    (SORT_DATE_ASC, "日付が古い順"),
    (SORT_DATE_DESC, "日付が新しい順"),
)


def _post_to_list_item(post: KnowledgePost) -> dict:
    reactions = Counter()
    for comment in post.comments.all():
        code = comment.reaction_type.code if comment.reaction_type else ""
        if code in REACTION_CODES:
            reactions[code] += 1

    return {
        "id": post.id,
        "title": post.title,
        "author": talks_author_name(post.author_member, post.author_name_snapshot),
        "summary": post.body,
        "tags": [tag.name for tag in post.tags.all()],
        "comment_count": post.comments.count(),
        "good_count": reactions["good"],
        "keep_count": reactions["keep"],
        "retry_count": reactions["retry"],
        "question_count": reactions["question"],
        "created_display": format_post_created_display(post.created_at),
        "view_count": post.view_count,
        "updated_at": post.updated_at,
        "author_member_id": post.author_member_id,
    }


def _selected_tags_from_request(request: HttpRequest, *, has_explicit_tag_query: bool) -> list[str]:
    selected_tags = []
    for tag in request.GET.getlist("tag"):
        clean_tag = (tag or "").strip()
        if clean_tag and clean_tag not in selected_tags:
            selected_tags.append(clean_tag)

    if not request.user.is_authenticated:
        return selected_tags

    preference, _ = KnowledgeUserPreference.objects.get_or_create(user=request.user)
    if has_explicit_tag_query:
        if selected_tags:
            preferred_tags = KnowledgeTag.objects.filter(
                is_active=True,
                name__in=selected_tags,
            )
            preference.preferred_tags.set(preferred_tags)
        else:
            preference.preferred_tags.clear()
    elif not selected_tags:
        selected_tags = list(
            preference.preferred_tags.filter(is_active=True).values_list("name", flat=True)
        )
    return selected_tags


def _parse_date_from(raw_value: str) -> tuple[datetime | None, str]:
    date_from_raw = (raw_value or "").strip()
    if not date_from_raw:
        return None, ""
    try:
        parsed_date = datetime.strptime(date_from_raw, "%Y-%m-%d").date()
    except ValueError:
        return None, ""
    return (
        timezone.make_aware(
            datetime.combine(parsed_date, datetime.min.time()),
            timezone.get_current_timezone(),
        ),
        date_from_raw,
    )


def _base_posts_queryset():
    return (
        KnowledgePost.objects.filter(
            status=KnowledgePost.Status.PUBLISHED,
            is_deleted=False,
        )
        .annotate(
            top_comment_count=Count(
                "comments",
                filter=Q(comments__is_deleted=False, comments__parent__isnull=True),
            )
        )
        .select_related("author_member")
        .prefetch_related("tags", "comments__reaction_type", "reads")
    )


def _apply_sort(posts, selected_sort: str):
    if selected_sort == SORT_COMMENTS:
        return posts.order_by("-top_comment_count", "-updated_at")
    if selected_sort == SORT_VIEWS:
        return posts.order_by("-view_count", "-updated_at")
    if selected_sort == SORT_DATE_ASC:
        return posts.order_by("created_at")
    if selected_sort == SORT_DATE_DESC:
        return posts.order_by("-created_at")
    return posts.order_by("-updated_at")


def _apply_user_flags(request: HttpRequest, thread_items: list[dict]) -> None:
    for item in thread_items:
        item["is_unread"] = False
        item["is_favorite"] = False

    if not request.user.is_authenticated or not thread_items:
        return

    post_ids = [item["id"] for item in thread_items]
    favorite_post_ids = set(
        KnowledgePostFavorite.objects.filter(
            user=request.user,
            post_id__in=post_ids,
        ).values_list("post_id", flat=True)
    )
    read_map = {
        read.post_id: read.read_at
        for read in KnowledgePostRead.objects.filter(
            user=request.user,
            post_id__in=post_ids,
        ).only("post_id", "read_at")
    }
    for item in thread_items:
        item["is_favorite"] = item["id"] in favorite_post_ids
        read_at = read_map.get(item["id"])
        item["is_unread"] = read_at is None or read_at < item["updated_at"]


def _append_preferred_tags(query_params, *, has_explicit_tag_query: bool, selected_tags: list[str]) -> None:
    if not has_explicit_tag_query and selected_tags:
        for tag in selected_tags:
            query_params.appendlist("tag", tag)


def build_talks_index_context(
    request: HttpRequest,
    *,
    talks_member: Member | None,
    talks_is_admin: bool,
) -> dict:
    has_explicit_tag_query = "tag" in request.GET or (request.GET.get("tag_filter_applied") or "").strip() == "1"
    selected_tags = _selected_tags_from_request(request, has_explicit_tag_query=has_explicit_tag_query)
    selected_author = (request.GET.get("author") or "").strip()
    selected_unread_only = (request.GET.get("unread") or "").strip() == "1"
    selected_favorite_only = (request.GET.get("favorite") or "").strip() == "1"
    selected_sort = (request.GET.get("sort") or SORT_NEWEST).strip()
    if selected_sort not in {key for key, _ in SORT_OPTIONS}:
        selected_sort = SORT_NEWEST
    date_from_dt, date_from_raw = _parse_date_from(request.GET.get("date_from") or "")

    posts = _base_posts_queryset()
    if selected_tags:
        for tag_name in selected_tags:
            posts = posts.filter(tags__name=tag_name)
        posts = posts.distinct()
    if date_from_dt:
        posts = posts.filter(created_at__gte=date_from_dt)
    posts = _apply_sort(posts, selected_sort)

    thread_items = [_post_to_list_item(post) for post in posts]
    author_pool = sorted({item["author"] for item in thread_items})
    if selected_author:
        thread_items = [item for item in thread_items if item["author"] == selected_author]

    _apply_user_flags(request, thread_items)
    if selected_unread_only:
        thread_items = [item for item in thread_items if item["is_unread"]]
    if selected_favorite_only:
        thread_items = [item for item in thread_items if item["is_favorite"]]

    paginator = Paginator(thread_items, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_threads = list(page_obj.object_list)
    for item in page_threads:
        item["can_manage"] = talks_is_admin or (
            talks_member is not None and item.get("author_member_id") == talks_member.id
        )

    query_params = request.GET.copy()
    _append_preferred_tags(query_params, has_explicit_tag_query=has_explicit_tag_query, selected_tags=selected_tags)
    query_params.pop("page", None)
    pagination_query = query_params.urlencode()

    unread_toggle_params = request.GET.copy()
    _append_preferred_tags(unread_toggle_params, has_explicit_tag_query=has_explicit_tag_query, selected_tags=selected_tags)
    unread_toggle_params.pop("page", None)
    if selected_unread_only:
        unread_toggle_params.pop("unread", None)
    else:
        unread_toggle_params["unread"] = "1"
    unread_toggle_query = unread_toggle_params.urlencode()

    favorite_toggle_params = request.GET.copy()
    _append_preferred_tags(favorite_toggle_params, has_explicit_tag_query=has_explicit_tag_query, selected_tags=selected_tags)
    favorite_toggle_params.pop("page", None)
    if selected_favorite_only:
        favorite_toggle_params.pop("favorite", None)
    else:
        favorite_toggle_params["favorite"] = "1"
    favorite_toggle_query = favorite_toggle_params.urlencode()

    available_tags = list(
        KnowledgeTag.objects.filter(is_active=True)
        .annotate(post_count=Count("posts", filter=Q(posts__is_deleted=False)))
        .order_by("-post_count", "name")
        .values_list("name", flat=True)
    )

    return {
        "threads": page_threads,
        "page_obj": page_obj,
        "paginator": paginator,
        "pagination_query": pagination_query,
        "selected_tags": selected_tags,
        "selected_author": selected_author,
        "selected_unread_only": selected_unread_only,
        "selected_favorite_only": selected_favorite_only,
        "selected_sort": selected_sort,
        "sort_options": SORT_OPTIONS,
        "date_from": date_from_raw,
        "available_tags": available_tags,
        "available_authors": author_pool,
        "unread_toggle_query": unread_toggle_query,
        "favorite_toggle_query": favorite_toggle_query,
    }
