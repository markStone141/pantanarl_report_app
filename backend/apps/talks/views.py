from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone


@dataclass(frozen=True)
class Reply:
    author: str
    body: str
    created_at: str


@dataclass(frozen=True)
class Comment:
    author: str
    body: str
    created_at: str
    kind: str
    replies: tuple[Reply, ...] = ()


@dataclass(frozen=True)
class Thread:
    id: int
    title: str
    author: str
    created_at: str
    summary: str
    tags: tuple[str, ...]
    comment_count: int
    good_count: int
    keep_count: int
    retry_count: int
    question_count: int
    last_activity: str


THREADS: tuple[Thread, ...] = (
    Thread(
        id=1,
        title="朝の5分ロールプレイを導入したら会話の入りが安定した",
        author="前田",
        created_at="2026-03-02 18:30",
        summary="朝礼の後に1人30秒で声かけ練習。WVでもUNでも初回トークの失敗が減った。",
        tags=("声かけ", "UN", "WV", "朝礼"),
        comment_count=8,
        good_count=4,
        keep_count=2,
        retry_count=1,
        question_count=1,
        last_activity="2026-03-04 09:12",
    ),
    Thread(
        id=2,
        title="断られた直後の切り返しテンプレート",
        author="為廣",
        created_at="2026-03-01 21:10",
        summary="断り文句を3パターンに分類し、切り返しを固定したら件数が落ちにくくなった。",
        tags=("切り返し", "UN", "実践共有"),
        comment_count=5,
        good_count=2,
        keep_count=1,
        retry_count=1,
        question_count=1,
        last_activity="2026-03-03 22:05",
    ),
)


COMMENTS_BY_THREAD_ID: dict[int, tuple[Comment, ...]] = {
    1: (
        Comment(
            author="内藤",
            body="南町田でも同じ型で試したら、最初の1時間の沈黙が減りました。",
            created_at="2026-03-03 10:20",
            kind="good",
            replies=(
                Reply(author="前田", body="共有ありがとう。冒頭の質問文だけ変えた版も試してみます。", created_at="2026-03-03 10:42"),
            ),
        ),
        Comment(
            author="角田",
            body="WVだと『難民支援』の説明順だけ変えた方が入りやすかったです。",
            created_at="2026-03-03 12:08",
            kind="keep",
        ),
    ),
    2: (
        Comment(
            author="早坂",
            body="2パターン目の切り返しは良かったですが、3パターン目は逆に離脱が増えました。",
            created_at="2026-03-02 19:03",
            kind="retry",
        ),
    ),
}


def _parse_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def _format_created_display(value: str) -> str:
    created = _parse_datetime(value)
    if created.date() == timezone.localdate():
        return created.strftime("%H:%M")
    return created.strftime("%Y-%m-%d")


def _find_thread(thread_id: int) -> Thread:
    for thread in THREADS:
        if thread.id == thread_id:
            return thread
    raise Http404("Thread not found")


def talks_index(request: HttpRequest) -> HttpResponse:
    selected_tags = [tag for tag in request.GET.getlist("tag") if tag]
    selected_author = (request.GET.get("author") or "").strip()

    tag_counter = Counter(tag for thread in THREADS for tag in thread.tags)
    available_tags = [tag for tag, _ in tag_counter.most_common()]
    available_authors = sorted({thread.author for thread in THREADS})

    filtered_threads = []
    for thread in THREADS:
        if selected_author and thread.author != selected_author:
            continue
        if selected_tags and not all(tag in thread.tags for tag in selected_tags):
            continue
        filtered_threads.append(thread)

    filtered_threads.sort(key=lambda item: _parse_datetime(item.last_activity), reverse=True)
    display_threads = [
        {
            "id": thread.id,
            "title": thread.title,
            "author": thread.author,
            "summary": thread.summary,
            "tags": thread.tags,
            "good_count": thread.good_count,
            "keep_count": thread.keep_count,
            "retry_count": thread.retry_count,
            "question_count": thread.question_count,
            "comment_count": thread.comment_count,
            "created_display": _format_created_display(thread.created_at),
        }
        for thread in filtered_threads
    ]

    return render(
        request,
        "talks/thread_index.html",
        {
            "threads": display_threads,
            "selected_tags": selected_tags,
            "selected_author": selected_author,
            "available_tags": available_tags,
            "available_authors": available_authors,
        },
    )


def talks_detail(request: HttpRequest, thread_id: int) -> HttpResponse:
    thread = _find_thread(thread_id)
    comments = COMMENTS_BY_THREAD_ID.get(thread_id, ())

    return render(
        request,
        "talks/thread_detail.html",
        {
            "thread": thread,
            "comments": comments,
        },
    )
