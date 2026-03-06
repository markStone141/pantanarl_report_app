import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Set password for a Django user (create user if missing)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default=os.getenv("ADMIN_LOGIN_USERNAME", "admin"),
            help="Target username (default: ADMIN_LOGIN_USERNAME or admin).",
        )
        parser.add_argument(
            "--password",
            default="",
            help="New password. If omitted, USER_PASSWORD env is used.",
        )
        parser.add_argument(
            "--staff",
            action="store_true",
            help="Set is_staff=True for the user.",
        )
        parser.add_argument(
            "--superuser",
            action="store_true",
            help="Set is_superuser=True for the user.",
        )

    def handle(self, *args, **options):
        username = (options["username"] or "").strip()
        password = options["password"] or os.getenv("USER_PASSWORD", "")
        is_staff = bool(options["staff"] or options["superuser"])
        is_superuser = bool(options["superuser"])

        if not username:
            raise CommandError("username is required.")
        if not password:
            raise CommandError("password is required.")

        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(username=username)
        user.set_password(password)
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        user.save(update_fields=["password", "is_staff", "is_superuser"])

        status = "created" if created else "updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"user {status}: username={username}, is_staff={user.is_staff}, is_superuser={user.is_superuser}"
            )
        )
