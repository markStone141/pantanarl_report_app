import logging

from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from apps.performance.services.activity_reminders import send_pending_activity_close_reminders


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send automatic reminders to active members who have not closed today's activity."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Send even before the fixed 19:00 reminder time.")
        parser.add_argument("--dry-run", action="store_true", help="Show target counts without sending mail.")
        parser.add_argument("--date", help="Target activity date in YYYY-MM-DD format. Defaults to today.")

    def handle(self, *args, **options):
        target_date = None
        raw_date = options.get("date")
        if raw_date:
            target_date = parse_date(raw_date)
            if target_date is None:
                message = "activity_reminder_job invalid_date date=%s"
                logger.error(message, raw_date)
                self.stderr.write(self.style.ERROR("Invalid --date. Use YYYY-MM-DD."))
                return

        result = send_pending_activity_close_reminders(
            target_date=target_date,
            force=options["force"],
            dry_run=options["dry_run"],
        )
        if result.reason == "before_reminder_time":
            message = "activity_reminder_job skipped reason=before_reminder_time dry_run=%s"
            logger.info(message, result.dry_run)
            self.stdout.write("Skipped because 19:00 has not passed.")
            return
        message = (
            "activity_reminder_job complete "
            "checked=%s sent=%s failed=%s skipped=%s dry_run=%s"
        )
        logger.info(message, result.checked, result.sent, result.failed, result.skipped, result.dry_run)
        self.stdout.write(
            "Activity reminder check complete: "
            f"checked={result.checked}, sent={result.sent}, failed={result.failed}, "
            f"skipped={result.skipped}, dry_run={result.dry_run}"
        )
