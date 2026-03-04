from __future__ import annotations

from collections import Counter
from datetime import datetime
import os

from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login, logout as auth_logout
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.auth import ROLE_ADMIN, ROLE_REPORT, SESSION_ROLE_KEY
from apps.accounts.models import Member

from .forms import CommentEditForm, PostEditForm, TagManageForm, TalksLoginForm
from .models import KnowledgeComment, KnowledgePost, KnowledgePostTag, KnowledgeTag
from .models import KnowledgePostRead
from .models import KnowledgeReactionType


TALKS_SESSION_MEMBER_ID_KEY = "talks_member_id"
TALKS_SESSION_MEMBER_NAME_KEY = "talks_member_name"
TALKS_SESSION_IS_ADMIN_KEY = "talks_is_admin"
TALKS_ADMIN_LOGIN_ID = os.getenv("TALKS_ADMIN_LOGIN_ID", "admin")
TALKS_ADMIN_PASSWORD = os.getenv("TALKS_ADMIN_PASSWORD", "pnadmin")

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
        "author_member_id": post.author_member_id,
    }


def _serialize_comment(comment: KnowledgeComment) -> dict:
    return {
        "id": comment.id,
        "author": _author_name(comment.author_member, comment.author_name_snapshot),
        "author_member_id": comment.author_member_id,
        "created_at": timezone.localtime(comment.created_at).strftime("%Y-%m-%d %H:%M"),
        "body": comment.body,
        "kind": comment.reaction_type.code,
    }


def _resolve_author_from_request(request: HttpRequest) -> tuple[object | None, str]:
    talks_member = _get_talks_member(request)
    if talks_member:
        return talks_member, talks_member.name

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


def _create_post_from_request(request: HttpRequest) -> tuple[KnowledgePost | None, str | None]:
    title = (request.POST.get("title") or "").strip()
    body = (request.POST.get("body") or "").strip()
    selected_tag_names = []
    for raw in request.POST.getlist("tags"):
        name = (raw or "").strip()
        if name and name not in selected_tag_names:
            selected_tag_names.append(name)

    if not title:
        return None, "タイトルを入力してください。"
    if not body:
        return None, "本文を入力してください。"
    if not selected_tag_names:
        return None, "タグを1つ以上選択してください。"

    tags_by_name = {
        tag.name: tag
        for tag in KnowledgeTag.objects.filter(is_active=True, name__in=selected_tag_names)
    }
    ordered_tags = [tags_by_name[name] for name in selected_tag_names if name in tags_by_name]
    if not ordered_tags:
        return None, "有効なタグが選択されていません。"

    author_member, author_snapshot = _resolve_author_from_request(request)
    post = KnowledgePost.objects.create(
        title=title,
        body=body,
        author_member=author_member,
        author_name_snapshot=author_snapshot,
        status=KnowledgePost.Status.PUBLISHED,
        is_deleted=False,
        published_at=timezone.now(),
    )
    for tag in ordered_tags:
        KnowledgePostTag.objects.create(post=post, tag=tag)
    return post, None


def _get_talks_member(request: HttpRequest) -> Member | None:
    member_id = request.session.get(TALKS_SESSION_MEMBER_ID_KEY)
    if not member_id:
        return None

    member = Member.objects.active().filter(id=member_id).first()
    if not member:
        request.session.pop(TALKS_SESSION_MEMBER_ID_KEY, None)
        request.session.pop(TALKS_SESSION_MEMBER_NAME_KEY, None)
        return None
    return member


def _is_talks_admin(request: HttpRequest) -> bool:
    role = request.session.get(SESSION_ROLE_KEY)
    return role == ROLE_ADMIN or bool(request.session.get(TALKS_SESSION_IS_ADMIN_KEY))


def _get_talks_display_name(request: HttpRequest, member: Member | None) -> str:
    if _is_talks_admin(request):
        return request.session.get(TALKS_SESSION_MEMBER_NAME_KEY, "管理者")
    if member:
        return member.name
    return ""


def _ensure_admin_user():
    User = get_user_model()
    user = User.objects.filter(username="talks_admin").first()
    if user:
        return user
    user = User.objects.create(username="talks_admin", is_staff=True)
    user.set_unusable_password()
    user.save(update_fields=["password"])
    return user


def _can_manage_post(member: Member | None, is_admin: bool, post: KnowledgePost) -> bool:
    return is_admin or (member is not None and post.author_member_id == member.id)


def _can_manage_comment(member: Member | None, is_admin: bool, comment: KnowledgeComment) -> bool:
    return is_admin or (member is not None and comment.author_member_id == member.id)


def _ensure_member_user(member: Member):
    if member.user:
        return member.user

    User = get_user_model()
    base_username = member.login_id
    username = base_username
    suffix = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}_{suffix}"
        suffix += 1

    user = User.objects.create(username=username)
    user.set_unusable_password()
    user.save(update_fields=["password"])
    member.user = user
    member.save(update_fields=["user"])
    return user


def _replace_post_tags(post: KnowledgePost, selected_tag_names: list[str]) -> None:
    tags_by_name = {
        tag.name: tag for tag in KnowledgeTag.objects.filter(is_active=True, name__in=selected_tag_names)
    }
    ordered_tags = [tags_by_name[name] for name in selected_tag_names if name in tags_by_name]
    KnowledgePostTag.objects.filter(post=post).delete()
    for tag in ordered_tags:
        KnowledgePostTag.objects.create(post=post, tag=tag)


def talks_login(request: HttpRequest) -> HttpResponse:
    member = _get_talks_member(request)
    if member or _is_talks_admin(request):
        return redirect("talks_index")

    if request.method == "POST":
        login_id = (request.POST.get("login_id") or "").strip()
        password = request.POST.get("password") or ""

        if login_id == TALKS_ADMIN_LOGIN_ID and password == TALKS_ADMIN_PASSWORD:
            admin_user = _ensure_admin_user()
            auth_login(request, admin_user, backend="django.contrib.auth.backends.ModelBackend")
            request.session[SESSION_ROLE_KEY] = ROLE_ADMIN
            request.session[TALKS_SESSION_IS_ADMIN_KEY] = True
            request.session[TALKS_SESSION_MEMBER_ID_KEY] = None
            request.session[TALKS_SESSION_MEMBER_NAME_KEY] = "管理者"
            return redirect("talks_index")

        form = TalksLoginForm(request.POST)
        if form.is_valid() and form.member:
            user = _ensure_member_user(form.member)
            auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            request.session[SESSION_ROLE_KEY] = ROLE_REPORT
            request.session[TALKS_SESSION_IS_ADMIN_KEY] = False
            request.session[TALKS_SESSION_MEMBER_ID_KEY] = form.member.id
            request.session[TALKS_SESSION_MEMBER_NAME_KEY] = form.member.name
            return redirect("talks_index")
    else:
        form = TalksLoginForm()

    return render(request, "talks/login.html", {"form": form})


def talks_logout(request: HttpRequest) -> HttpResponse:
    auth_logout(request)
    request.session.pop(SESSION_ROLE_KEY, None)
    request.session.pop(TALKS_SESSION_IS_ADMIN_KEY, None)
    request.session.pop(TALKS_SESSION_MEMBER_ID_KEY, None)
    request.session.pop(TALKS_SESSION_MEMBER_NAME_KEY, None)
    return redirect("talks_login")


def talks_index(request: HttpRequest) -> HttpResponse:
    talks_member = _get_talks_member(request)
    talks_is_admin = _is_talks_admin(request)
    if not talks_member and not talks_is_admin:
        return redirect("talks_login")

    if request.method == "POST" and request.POST.get("action") == "create_post":
        post, error = _create_post_from_request(request)
        if post:
            messages.success(request, "新規投稿を作成しました。")
            return redirect("talks_detail", thread_id=post.id)
        if error:
            messages.error(request, error)
        return redirect("talks_index")

    selected_tags = []
    for tag in request.GET.getlist("tag"):
        clean_tag = (tag or "").strip()
        if clean_tag and clean_tag not in selected_tags:
            selected_tags.append(clean_tag)
    selected_author = (request.GET.get("author") or "").strip()
    selected_unread_only = (request.GET.get("unread") or "").strip() == "1"
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
        for tag_name in selected_tags:
            posts = posts.filter(tags__name=tag_name)
        posts = posts.distinct()
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

    if request.user.is_authenticated and thread_items:
        read_map = {
            read.post_id: read.read_at
            for read in KnowledgePostRead.objects.filter(
                user=request.user,
                post_id__in=[item["id"] for item in thread_items],
            ).only("post_id", "read_at")
        }
        for item in thread_items:
            read_at = read_map.get(item["id"])
            item["is_unread"] = read_at is None or read_at < item["updated_at"]

    if selected_unread_only:
        thread_items = [item for item in thread_items if item["is_unread"]]

    paginator = Paginator(thread_items, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    page_threads = list(page_obj.object_list)
    for item in page_threads:
        item["can_manage"] = talks_is_admin or (
            talks_member is not None and item.get("author_member_id") == talks_member.id
        )

    query_params = request.GET.copy()
    query_params.pop("page", None)
    pagination_query = query_params.urlencode()
    unread_toggle_params = request.GET.copy()
    unread_toggle_params.pop("page", None)
    if selected_unread_only:
        unread_toggle_params.pop("unread", None)
    else:
        unread_toggle_params["unread"] = "1"
    unread_toggle_query = unread_toggle_params.urlencode()

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
            "selected_unread_only": selected_unread_only,
            "selected_sort": selected_sort,
            "sort_options": SORT_OPTIONS,
            "date_from": date_from_raw,
            "available_tags": available_tags,
            "available_authors": available_authors,
            "talks_member_name": _get_talks_display_name(request, talks_member),
            "talks_is_admin": talks_is_admin,
            "unread_toggle_query": unread_toggle_query,
        },
    )


def talks_detail(request: HttpRequest, thread_id: int) -> HttpResponse:
    talks_member = _get_talks_member(request)
    talks_is_admin = _is_talks_admin(request)
    if not talks_member and not talks_is_admin:
        return redirect("talks_login")

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
                "id": reply.id,
                "author": _author_name(reply.author_member, reply.author_name_snapshot),
                "author_member_id": reply.author_member_id,
                "created_at": timezone.localtime(reply.created_at).strftime("%Y-%m-%d %H:%M"),
                "body": reply.body,
            }
            for reply in sorted(
                [r for r in comment.replies.all() if not r.is_deleted],
                key=lambda r: r.created_at,
            )
        ]
        serialized = _serialize_comment(comment)
        serialized["can_manage"] = _can_manage_comment(member=talks_member, is_admin=talks_is_admin, comment=comment)
        for reply_item in replies:
            reply_item["can_manage"] = talks_is_admin or (
                talks_member is not None and reply_item.get("author_member_id") == talks_member.id
            )
        serialized["replies"] = replies
        comments.append(serialized)

    return render(
        request,
        "talks/thread_detail.html",
        {
            "thread": post,
            "can_manage_thread": _can_manage_post(member=talks_member, is_admin=talks_is_admin, post=post),
            "thread_author": _author_name(post.author_member, post.author_name_snapshot),
            "thread_created_at": timezone.localtime(post.created_at).strftime("%Y-%m-%d %H:%M"),
            "comments": comments,
            "good_count": reaction_counts["good"],
            "keep_count": reaction_counts["keep"],
            "retry_count": reaction_counts["retry"],
            "question_count": reaction_counts["question"],
            "reaction_types": KnowledgeReactionType.objects.filter(is_active=True).order_by("sort_order", "id"),
            "talks_member_name": _get_talks_display_name(request, talks_member),
            "talks_is_admin": talks_is_admin,
        },
    )


def talks_tag_manage(request: HttpRequest) -> HttpResponse:
    talks_member = _get_talks_member(request)
    talks_is_admin = _is_talks_admin(request)
    if not talks_is_admin:
        messages.error(request, "タグ管理は管理者のみ実行できます。")
        return redirect("talks_index")

    edit_id_raw = (request.GET.get("edit") or "").strip()
    editing_tag = None

    if request.method == "POST":
        action = (request.POST.get("action") or "save").strip()

        if action == "toggle":
            tag_id_raw = (request.POST.get("tag_id") or "").strip()
            if tag_id_raw.isdigit():
                tag = KnowledgeTag.objects.filter(id=int(tag_id_raw)).first()
                if tag:
                    tag.is_active = not tag.is_active
                    tag.save(update_fields=["is_active", "updated_at"])
            return redirect("talks_tag_manage")

        form = TagManageForm(request.POST)
        if form.is_valid():
            tag_id = form.cleaned_data.get("tag_id")
            name = form.cleaned_data["name"]
            sort_order = form.cleaned_data["sort_order"]
            is_active = form.cleaned_data["is_active"]

            if tag_id:
                tag = KnowledgeTag.objects.filter(id=tag_id).first()
                if not tag:
                    messages.error(request, "編集対象のタグが見つかりません。")
                    return redirect("talks_tag_manage")

                duplicated = KnowledgeTag.objects.filter(name=name).exclude(id=tag.id).exists()
                if duplicated:
                    messages.error(request, "同じタグ名が既に存在します。")
                else:
                    tag.name = name
                    tag.sort_order = sort_order
                    tag.is_active = is_active
                    tag.save(update_fields=["name", "sort_order", "is_active", "updated_at"])
                    messages.success(request, "タグを更新しました。")
                    return redirect("talks_tag_manage")
            else:
                if KnowledgeTag.objects.filter(name=name).exists():
                    messages.error(request, "同じタグ名が既に存在します。")
                else:
                    KnowledgeTag.objects.create(
                        name=name,
                        sort_order=sort_order,
                        is_active=is_active,
                    )
                    messages.success(request, "タグを追加しました。")
                    return redirect("talks_tag_manage")
    else:
        if edit_id_raw.isdigit():
            editing_tag = KnowledgeTag.objects.filter(id=int(edit_id_raw)).first()
        if editing_tag:
            form = TagManageForm(
                initial={
                    "tag_id": editing_tag.id,
                    "name": editing_tag.name,
                    "sort_order": editing_tag.sort_order,
                    "is_active": editing_tag.is_active,
                }
            )
        else:
            form = TagManageForm(initial={"sort_order": 0, "is_active": True})

    tags = (
        KnowledgeTag.objects.annotate(
            post_count=Count("posts", filter=Q(posts__is_deleted=False)),
        )
        .order_by("sort_order", "name")
    )

    return render(
        request,
        "talks/tag_manage.html",
        {
            "form": form,
            "tags": tags,
            "editing_tag": editing_tag,
            "talks_member_name": _get_talks_display_name(request, talks_member),
            "talks_is_admin": talks_is_admin,
        },
    )


def talks_deleted_posts_manage(request: HttpRequest) -> HttpResponse:
    talks_member = _get_talks_member(request)
    talks_is_admin = _is_talks_admin(request)
    if not talks_is_admin:
        messages.error(request, "削除済みトークの管理は管理者のみ実行できます。")
        return redirect("talks_index")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        post_id_raw = (request.POST.get("post_id") or "").strip()
        if post_id_raw.isdigit():
            post = KnowledgePost.objects.filter(id=int(post_id_raw), is_deleted=True).first()
            if post:
                if action == "restore":
                    post.is_deleted = False
                    post.save(update_fields=["is_deleted", "updated_at"])
                    messages.success(request, "投稿を復元しました。")
                elif action == "hard_delete":
                    post.delete()
                    messages.success(request, "投稿を完全削除しました。")
        return redirect("talks_deleted_posts_manage")

    deleted_posts = (
        KnowledgePost.objects.filter(is_deleted=True)
        .select_related("author_member")
        .prefetch_related("tags")
        .annotate(
            comment_count=Count("comments"),
        )
        .order_by("-updated_at", "-id")
    )
    return render(
        request,
        "talks/deleted_posts_manage.html",
        {
            "deleted_posts": deleted_posts,
            "talks_member_name": _get_talks_display_name(request, talks_member),
            "talks_is_admin": talks_is_admin,
        },
    )


def talks_post_edit(request: HttpRequest, post_id: int) -> HttpResponse:
    talks_member = _get_talks_member(request)
    talks_is_admin = _is_talks_admin(request)
    if not talks_member and not talks_is_admin:
        return redirect("talks_login")

    post = KnowledgePost.objects.filter(id=post_id, is_deleted=False).prefetch_related("tags").first()
    if not post:
        raise Http404("Post not found")
    if not _can_manage_post(member=talks_member, is_admin=talks_is_admin, post=post):
        raise Http404("Post not found")

    if request.method == "POST":
        form = PostEditForm(request.POST)
        if form.is_valid():
            post.title = form.cleaned_data["title"]
            post.body = form.cleaned_data["body"]
            post.save()
            _replace_post_tags(post, form.cleaned_data["tags"])
            messages.success(request, "投稿を更新しました。")
            return redirect("talks_detail", thread_id=post.id)
        selected_tag_names = [str(name) for name in request.POST.getlist("tags") if str(name).strip()]
    else:
        form = PostEditForm(
            initial={
                "title": post.title,
                "body": post.body,
                "tags": [tag.name for tag in post.tags.all()],
            }
        )
        selected_tag_names = [tag.name for tag in post.tags.all()]

    available_tag_names = [name for name, _ in form.fields["tags"].choices]

    return render(
        request,
        "talks/post_edit.html",
        {
            "form": form,
            "post": post,
            "talks_member_name": _get_talks_display_name(request, talks_member),
            "talks_is_admin": talks_is_admin,
            "available_tag_names": available_tag_names,
            "selected_tag_names": selected_tag_names,
        },
    )


def talks_post_delete(request: HttpRequest, post_id: int) -> HttpResponse:
    talks_member = _get_talks_member(request)
    talks_is_admin = _is_talks_admin(request)
    if not talks_member and not talks_is_admin:
        return redirect("talks_login")
    if request.method != "POST":
        return redirect("talks_index")

    post = KnowledgePost.objects.filter(id=post_id, is_deleted=False).first()
    if post and _can_manage_post(member=talks_member, is_admin=talks_is_admin, post=post):
        post.is_deleted = True
        post.save(update_fields=["is_deleted", "updated_at"])
        messages.success(request, "投稿を削除しました。")
    return redirect("talks_index")


def talks_comment_edit(request: HttpRequest, comment_id: int) -> HttpResponse:
    talks_member = _get_talks_member(request)
    talks_is_admin = _is_talks_admin(request)
    if not talks_member and not talks_is_admin:
        return redirect("talks_login")

    comment = (
        KnowledgeComment.objects.select_related("post")
        .filter(id=comment_id, is_deleted=False)
        .first()
    )
    if not comment:
        raise Http404("Comment not found")
    if not _can_manage_comment(member=talks_member, is_admin=talks_is_admin, comment=comment):
        raise Http404("Comment not found")

    if request.method == "POST":
        form = CommentEditForm(request.POST)
        if form.is_valid():
            comment.body = form.cleaned_data["body"]
            comment.save()
            messages.success(request, "コメントを更新しました。")
            return redirect("talks_detail", thread_id=comment.post_id)
    else:
        form = CommentEditForm(initial={"body": comment.body})

    return render(
        request,
        "talks/comment_edit.html",
        {
            "form": form,
            "comment": comment,
            "talks_member_name": _get_talks_display_name(request, talks_member),
            "talks_is_admin": talks_is_admin,
        },
    )


def talks_comment_delete(request: HttpRequest, comment_id: int) -> HttpResponse:
    talks_member = _get_talks_member(request)
    talks_is_admin = _is_talks_admin(request)
    if not talks_member and not talks_is_admin:
        return redirect("talks_login")
    if request.method != "POST":
        return redirect("talks_index")

    comment = (
        KnowledgeComment.objects.select_related("post")
        .filter(id=comment_id, is_deleted=False)
        .first()
    )
    if not comment:
        return redirect("talks_index")
    if not _can_manage_comment(member=talks_member, is_admin=talks_is_admin, comment=comment):
        return redirect("talks_detail", thread_id=comment.post_id)

    thread_id = comment.post_id
    comment.is_deleted = True
    comment.save(update_fields=["is_deleted", "updated_at"])
    messages.success(request, "コメントを削除しました。")
    return redirect("talks_detail", thread_id=thread_id)

