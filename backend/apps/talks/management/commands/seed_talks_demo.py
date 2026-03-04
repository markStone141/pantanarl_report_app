from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Member
from apps.talks.models import (
    KnowledgeComment,
    KnowledgePost,
    KnowledgePostTag,
    KnowledgeReactionType,
    KnowledgeTag,
    KnowledgeUserPreference,
)


class Command(BaseCommand):
    help = "Seed demo data for talks app (tags, reaction types, posts, comments)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing talks data before seeding.",
        )
        parser.add_argument(
            "--file",
            type=str,
            default="demo_data.json",
            help="Seed json file name under apps/talks/seed.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        seed_file = options["file"]
        data = self._load_seed(seed_file)

        if options["reset"]:
            self._reset_talks_data()
            self.stdout.write(self.style.WARNING("Existing talks data was reset."))

        active_members = {
            m.name: m for m in Member.objects.filter(is_active=True).only("id", "name")
        }
        tag_map = self._seed_tags(data.get("tags", []))
        reaction_map = self._seed_reaction_types(data.get("reaction_types", []))
        post_map = self._seed_posts(data.get("posts", []), tag_map, active_members)
        self._seed_comments(
            data.get("comments", []),
            post_map,
            reaction_map,
            active_members,
        )

        self.stdout.write(self.style.SUCCESS("Talks demo seed completed."))

    def _load_seed(self, seed_file: str) -> dict:
        seed_path = Path(__file__).resolve().parents[2] / "seed" / seed_file
        if not seed_path.exists():
            raise CommandError(f"Seed file not found: {seed_path}")
        with seed_path.open("r", encoding="utf-8") as fp:
            return json.load(fp)

    def _reset_talks_data(self) -> None:
        KnowledgeComment.objects.all().delete()
        KnowledgePostTag.objects.all().delete()
        KnowledgePost.objects.all().delete()
        KnowledgeUserPreference.objects.all().delete()
        KnowledgeReactionType.objects.all().delete()
        KnowledgeTag.objects.all().delete()

    def _seed_tags(self, payload: list[dict]) -> dict[str, KnowledgeTag]:
        tag_map: dict[str, KnowledgeTag] = {}
        for idx, item in enumerate(payload, start=1):
            name = (item.get("name") or "").strip()
            if not name:
                continue
            tag, _ = KnowledgeTag.objects.update_or_create(
                name=name,
                defaults={
                    "sort_order": int(item.get("sort_order", idx * 10)),
                    "is_active": bool(item.get("is_active", True)),
                },
            )
            tag_map[name] = tag
        return tag_map

    def _seed_reaction_types(self, payload: list[dict]) -> dict[str, KnowledgeReactionType]:
        reaction_map: dict[str, KnowledgeReactionType] = {}
        for idx, item in enumerate(payload, start=1):
            code = (item.get("code") or "").strip()
            if not code:
                continue
            reaction, _ = KnowledgeReactionType.objects.update_or_create(
                code=code,
                defaults={
                    "label": item.get("label") or code,
                    "icon_class": item.get("icon_class") or "fa-solid fa-circle",
                    "color": item.get("color") or "#126e82",
                    "sort_order": int(item.get("sort_order", idx * 10)),
                    "is_active": bool(item.get("is_active", True)),
                },
            )
            reaction_map[code] = reaction
        return reaction_map

    def _seed_posts(
        self,
        payload: list[dict],
        tag_map: dict[str, KnowledgeTag],
        member_map: dict[str, Member],
    ) -> dict[str, KnowledgePost]:
        post_map: dict[str, KnowledgePost] = {}
        for item in payload:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            author_name = (item.get("author_name") or "").strip()
            member = member_map.get(author_name)
            post, _ = KnowledgePost.objects.update_or_create(
                title=title,
                defaults={
                    "body": item.get("body") or "",
                    "status": item.get("status") or KnowledgePost.Status.PUBLISHED,
                    "is_deleted": False,
                    "author_member": member,
                    "author_name_snapshot": author_name,
                },
            )
            tags = [tag_map[name] for name in item.get("tags", []) if name in tag_map]
            post.tags.set(tags)
            post_key = (item.get("key") or "").strip()
            if post_key:
                post_map[post_key] = post
        return post_map

    def _seed_comments(
        self,
        payload: list[dict],
        post_map: dict[str, KnowledgePost],
        reaction_map: dict[str, KnowledgeReactionType],
        member_map: dict[str, Member],
    ) -> None:
        comment_key_map: dict[str, KnowledgeComment] = {}
        for item in payload:
            post_key = (item.get("post_key") or "").strip()
            post = post_map.get(post_key)
            if not post:
                continue
            reaction_code = (item.get("reaction_code") or "").strip()
            reaction_type = reaction_map.get(reaction_code)
            if not reaction_type:
                continue

            parent = None
            parent_key = (item.get("parent_key") or "").strip()
            if parent_key:
                parent = comment_key_map.get(parent_key)
                if not parent:
                    continue

            author_name = (item.get("author_name") or "").strip()
            member = member_map.get(author_name)
            body = item.get("body") or ""
            comment, _ = KnowledgeComment.objects.get_or_create(
                post=post,
                parent=parent,
                author_name_snapshot=author_name,
                body=body,
                defaults={
                    "author_member": member,
                    "reaction_type": reaction_type,
                    "is_deleted": False,
                },
            )
            if comment.reaction_type_id != reaction_type.id or comment.author_member_id != (member.id if member else None):
                comment.reaction_type = reaction_type
                comment.author_member = member
                comment.is_deleted = False
                comment.save(update_fields=["reaction_type", "author_member", "is_deleted", "updated_at"])

            comment_key = (item.get("key") or "").strip()
            if comment_key:
                comment_key_map[comment_key] = comment
