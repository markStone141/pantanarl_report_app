from __future__ import annotations

from collections import Counter

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from .models import KnowledgeComment, KnowledgePost, KnowledgeTag


REACTION_CODES = ("good", "keep", "retry", "question")


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
    }


def _serialize_comment(comment: KnowledgeComment) -> dict:
    return {
        "id": comment.id,
        "author": _author_name(comment.author_member, comment.author_name_snapshot),
        "created_at": timezone.localtime(comment.created_at).strftime("%Y-%m-%d %H:%M"),
        "body": comment.body,
        "kind": comment.reaction_type.code,
    }


def talks_index(request: HttpRequest) -> HttpResponse:
    selected_tags = [tag for tag in request.GET.getlist("tag") if tag]
    selected_author = (request.GET.get("author") or "").strip()

    posts = (
        KnowledgePost.objects.filter(
            status=KnowledgePost.Status.PUBLISHED,
            is_deleted=False,
        )
        .select_related("author_member")
        .prefetch_related("tags", "comments__reaction_type")
        .order_by("-updated_at")
    )
    if selected_tags:
        posts = posts.filter(tags__name__in=selected_tags).distinct()

    thread_items = [_post_to_list_item(post) for post in posts]
    author_pool = sorted({item["author"] for item in thread_items})
    if selected_author:
        thread_items = [item for item in thread_items if item["author"] == selected_author]

    available_tags = list(
        KnowledgeTag.objects.filter(is_active=True).order_by("sort_order", "name").values_list("name", flat=True)
    )
    available_authors = author_pool

    return render(
        request,
        "talks/thread_index.html",
        {
            "threads": thread_items,
            "selected_tags": selected_tags,
            "selected_author": selected_author,
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
        },
    )
