from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.talks.models import (
    KnowledgeComment,
    KnowledgePost,
    KnowledgePostTag,
    KnowledgeReactionType,
    KnowledgeTag,
    KnowledgeUserPreference,
)


class Command(BaseCommand):
    help = "Clear talks data. By default clears all talks tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-master",
            action="store_true",
            help="Keep tag/reaction master tables and clear only post/comment/preference data.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        keep_master = bool(options.get("keep_master"))

        KnowledgeComment.objects.all().delete()
        KnowledgePostTag.objects.all().delete()
        KnowledgePost.objects.all().delete()
        KnowledgeUserPreference.objects.all().delete()

        if keep_master:
            self.stdout.write(self.style.SUCCESS("Cleared talks post/comment/preference data. Kept tag/reaction masters."))
            return

        KnowledgeReactionType.objects.all().delete()
        KnowledgeTag.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("Cleared all talks data (including tag/reaction masters)."))
