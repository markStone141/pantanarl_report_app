from __future__ import annotations

from collections import Counter
from datetime import datetime

from django.core.paginator import Paginator
from django.http import Http404, HttpRequest, HttpResponse
from django.db.models import Count, F, Q
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone

from .models import KnowledgeComment, KnowledgePost, KnowledgeTag
from .models import KnowledgePostRead
from .models import KnowledgeReactionType


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


def _author_name(member_obj, snapshot: str) -> str:
    if member_obj and member_obj.name:
        return member_obj.name
    return snapshot or "不明"


def _format_created_display(dt) -> str:
    local_dt = timezone.localtime(dt)
    if local_dt.date() == timezone.localdate():
        return local_dt.strftime("%H:%M")
    return local_dt.strftime("%Y-%m-%d")


def _post_to_list_item(post: KnowledgePost) -> dict:
    reactions = Counter()
    for comment in post.comments.all():
        code = comment.reaction_type.code if comment.reaction_type else ""
        if code in REACTION_CODES:
            reactions[code] += 1

    return {
        "id": post.id,
        "title": post.title,
        "author": _author_name(post.author_member, post.author_name_snapshot),
        "summary": post.body,
        "tags": [tag.name for tag in post.tags.all()],
        "comment_count": post.comments.count(),
        "good_count": reactions["good"],
        "keep_count": reactions["keep"],
        "retry_count": reactions["retry"],
        "question_count": reactions["question"],
        "created_display": _format_created_display(post.created_at),
        "view_count": post.view_count,
        "updated_at": post.updated_at,
    }


def _serialize_comment(comment: KnowledgeComment) -> dict:
    return {
        "id": comment.id,
        "author": _author_name(comment.author_member, comment.author_name_snapshot),
        "created_at": timezone.localtime(comment.created_at).strftime("%Y-%m-%d %H:%M"),
        "body": comment.body,
        "kind": comment.reaction_type.code,
    }


def _resolve_author_from_request(request: HttpRequest) -> tuple[object | None, str]:
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        member = getattr(user, "member_profile", None)
        if member:
            return member, member.name
        return None, user.get_username() or "匿名"
    return None, "匿名"


def _create_comment_from_post(request: HttpRequest, post: KnowledgePost) -> None:
    body = (request.POST.get("body") or "").strip()
    if not body:
        return

    reaction = None

    parent = None
    parent_id = (request.POST.get("parent_id") or "").strip()
    if parent_id.isdigit():
        parent = (
            KnowledgeComment.objects.filter(
                id=int(parent_id),
                post=post,
                parent__isnull=True,
                is_deleted=False,
            )
            .select_related("reaction_type", "author_member")
            .first()
        )
    if parent:
        reaction = parent.reaction_type
    else:
        reaction_code = (request.POST.get("reaction_code") or "").strip()
        reaction = (
            KnowledgeReactionType.objects.filter(code=reaction_code, is_active=True)
            .order_by("sort_order", "id")
            .first()
        )
        if not reaction:
            reaction = (
                KnowledgeReactionType.objects.filter(is_active=True)
                .order_by("sort_order", "id")
                .first()
            )
    if not reaction:
        return

    author_member, author_snapshot = _resolve_author_from_request(request)
    KnowledgeComment.objects.create(
        post=post,
        parent=parent,
        author_member=author_member,
        author_name_snapshot=author_snapshot,
        body=body,
        reaction_type=reaction,
        is_deleted=False,
    )


def talks_index(request: HttpRequest) -> HttpResponse:
    selected_tags = [tag for tag in request.GET.getlist("tag") if tag]
    selected_author = (request.GET.get("author") or "").strip()
    selected_sort = (request.GET.get("sort") or SORT_NEWEST).strip()
    if selected_sort not in {key for key, _ in SORT_OPTIONS}:
        selected_sort = SORT_NEWEST
    date_from_raw = (request.GET.get("date_from") or "").strip()

    date_from_dt = None
    if date_from_raw:
        try:
            parsed_date = datetime.strptime(date_from_raw, "%Y-%m-%d").date()
            date_from_dt = timezone.make_aware(
                datetime.combine(parsed_date, datetime.min.time()),
                timezone.get_current_timezone(),
            )
        except ValueError:
            date_from_raw = ""

    posts = (
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
    if selected_tags:
        posts = posts.filter(tags__name__in=selected_tags).distinct()
    if date_from_dt:
        posts = posts.filter(created_at__gte=date_from_dt)

    if selected_sort == SORT_COMMENTS:
        posts = posts.order_by("-top_comment_count", "-updated_at")
    elif selected_sort == SORT_VIEWS:
        posts = posts.order_by("-view_count", "-updated_at")
    elif selected_sort == SORT_DATE_ASC:
        posts = posts.order_by("created_at")
    elif selected_sort == SORT_DATE_DESC:
        posts = posts.order_by("-created_at")
    else:
        posts = posts.order_by("-updated_at")

    thread_items = [_post_to_list_item(post) for post in posts]
    for item in thread_items:
        item["is_unread"] = False

    author_pool = sorted({item["author"] for item in thread_items})
    if selected_author:
        thread_items = [item for item in thread_items if item["author"] == selected_author]

    paginator = Paginator(thread_items, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    page_threads = list(page_obj.object_list)

    if request.user.is_authenticated and page_threads:
        read_map = {
            read.post_id: read.read_at
            for read in KnowledgePostRead.objects.filter(
                user=request.user,
                post_id__in=[item["id"] for item in page_threads],
            ).only("post_id", "read_at")
        }
        for item in page_threads:
            read_at = read_map.get(item["id"])
            item["is_unread"] = read_at is None or read_at < item["updated_at"]

    query_params = request.GET.copy()
    query_params.pop("page", None)
    pagination_query = query_params.urlencode()

    available_tags = list(
        KnowledgeTag.objects.filter(is_active=True).order_by("sort_order", "name").values_list("name", flat=True)
    )
    available_authors = author_pool

    return render(
        request,
        "talks/thread_index.html",
        {
            "threads": page_threads,
            "page_obj": page_obj,
            "paginator": paginator,
            "pagination_query": pagination_query,
            "selected_tags": selected_tags,
            "selected_author": selected_author,
            "selected_sort": selected_sort,
            "sort_options": SORT_OPTIONS,
            "date_from": date_from_raw,
            "available_tags": available_tags,
            "available_authors": available_authors,
        },
    )


def talks_detail(request: HttpRequest, thread_id: int) -> HttpResponse:
    post = (
        KnowledgePost.objects.filter(
            id=thread_id,
            status=KnowledgePost.Status.PUBLISHED,
            is_deleted=False,
        )
        .select_related("author_member")
        .prefetch_related(
            "tags",
            "comments__reaction_type",
            "comments__author_member",
            "comments__replies__reaction_type",
            "comments__replies__author_member",
        )
        .first()
    )
    if not post:
        raise Http404("Thread not found")

    if request.method == "POST":
        _create_comment_from_post(request, post)
        return redirect("talks_detail", thread_id=thread_id)

    KnowledgePost.objects.filter(id=post.id).update(view_count=F("view_count") + 1)
    if request.user.is_authenticated:
        KnowledgePostRead.objects.update_or_create(
            user=request.user,
            post=post,
            defaults={},
        )

    top_level_comments = [c for c in post.comments.all() if c.parent_id is None and not c.is_deleted]
    top_level_comments.sort(key=lambda c: c.created_at)

    reaction_counts = Counter()
    comments = []
    for comment in top_level_comments:
        code = comment.reaction_type.code if comment.reaction_type else ""
        if code in REACTION_CODES:
            reaction_counts[code] += 1

        replies = [
            {
                "author": _author_name(reply.author_member, reply.author_name_snapshot),
                "created_at": timezone.localtime(reply.created_at).strftime("%Y-%m-%d %H:%M"),
                "body": reply.body,
            }
            for reply in sorted(
                [r for r in comment.replies.all() if not r.is_deleted],
                key=lambda r: r.created_at,
            )
        ]
        serialized = _serialize_comment(comment)
        serialized["replies"] = replies
        comments.append(serialized)

    return render(
        request,
        "talks/thread_detail.html",
        {
            "thread": post,
            "thread_author": _author_name(post.author_member, post.author_name_snapshot),
            "thread_created_at": timezone.localtime(post.created_at).strftime("%Y-%m-%d %H:%M"),
            "comments": comments,
            "good_count": reaction_counts["good"],
            "keep_count": reaction_counts["keep"],
            "retry_count": reaction_counts["retry"],
            "question_count": reaction_counts["question"],
            "reaction_types": KnowledgeReactionType.objects.filter(is_active=True).order_by("sort_order", "id"),
        },
    )
