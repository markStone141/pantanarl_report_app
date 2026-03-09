from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Department, Member, MemberDepartment
from apps.dairymetrics.models import MemberDailyMetricEntry, MemberMonthMetricTarget, MemberPeriodMetricTarget
from apps.targets.models import Period, TARGET_STATUS_ACTIVE, TARGET_STATUS_FINISHED


DEMO_PASSWORD = "demo1234"


class Command(BaseCommand):
    help = "Seed local DairyMetrics demo data for visual confirmation."

    def handle(self, *args, **options):
        today = timezone.localdate()
        current_month = today.replace(day=1)
        User = get_user_model()

        departments = {
            "UN": self._upsert_department("UN", "UN"),
            "WV": self._upsert_department("WV", "WV"),
        }
        periods = self._ensure_periods(current_month=current_month)

        member_specs = [
            {"username": "dm_admin", "name": "Demo Admin", "is_staff": True, "departments": []},
            {"username": "dm_un_lead", "name": "UN Leader", "departments": ["UN"]},
            {"username": "dm_un_hana", "name": "花山", "departments": ["UN"]},
            {"username": "dm_un_sora", "name": "空野", "departments": ["UN"]},
            {"username": "dm_un_mio", "name": "美桜", "departments": ["UN"], "is_active": False},
            {"username": "dm_wv_lead", "name": "WV Leader", "departments": ["WV"]},
            {"username": "dm_wv_rin", "name": "凛", "departments": ["WV"]},
            {"username": "dm_wv_yu", "name": "悠", "departments": ["WV"]},
        ]

        members = {}
        for spec in member_specs:
            user = self._upsert_user(
                User=User,
                username=spec["username"],
                is_staff=spec.get("is_staff", False),
            )
            member = self._upsert_member(
                name=spec["name"],
                user=user if not spec.get("is_staff") else None,
                is_active=spec.get("is_active", True),
            )
            for code in spec.get("departments", []):
                MemberDepartment.objects.get_or_create(member=member, department=departments[code])
            members[spec["username"]] = member

        departments["UN"].default_reporter = members["dm_un_lead"]
        departments["UN"].save(update_fields=["default_reporter"])
        departments["WV"].default_reporter = members["dm_wv_lead"]
        departments["WV"].save(update_fields=["default_reporter"])

        self._seed_targets(
            today=today,
            current_month=current_month,
            periods=periods,
            departments=departments,
            members=members,
        )
        self._seed_entries(today=today, departments=departments, members=members)

        self.stdout.write(self.style.SUCCESS("DairyMetrics demo seed completed."))
        self.stdout.write("Login credentials:")
        self.stdout.write(f"  admin    : dm_admin / {DEMO_PASSWORD}")
        self.stdout.write(f"  UN lead  : dm_un_lead / {DEMO_PASSWORD}")
        self.stdout.write(f"  WV lead  : dm_wv_lead / {DEMO_PASSWORD}")
        self.stdout.write(f"  members  : dm_un_hana, dm_un_sora, dm_wv_rin, dm_wv_yu / {DEMO_PASSWORD}")

    def _upsert_department(self, code: str, name: str):
        department, _ = Department.objects.update_or_create(
            code=code,
            defaults={"name": name, "is_active": True},
        )
        return department

    def _upsert_user(self, *, User, username: str, is_staff: bool):
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={"is_staff": is_staff, "is_superuser": is_staff, "is_active": True},
        )
        updated = False
        if user.is_staff != is_staff:
            user.is_staff = is_staff
            updated = True
        if user.is_superuser != is_staff:
            user.is_superuser = is_staff
            updated = True
        if not user.is_active:
            user.is_active = True
            updated = True
        user.set_password(DEMO_PASSWORD)
        user.save()
        return user

    def _upsert_member(self, *, name: str, user, is_active: bool):
        member, _ = Member.objects.get_or_create(
            name=name,
            defaults={"user": user, "is_active": is_active},
        )
        changed = False
        if member.user_id != (user.id if user else None):
            member.user = user
            changed = True
        if member.is_active != is_active:
            member.is_active = is_active
            changed = True
        if changed:
            member.save(update_fields=["user", "is_active"])
        return member

    def _ensure_periods(self, *, current_month):
        statuses = [TARGET_STATUS_FINISHED, TARGET_STATUS_FINISHED, TARGET_STATUS_FINISHED, TARGET_STATUS_ACTIVE]
        periods = []
        for index in range(4):
            start_day = (index * 7) + 1
            end_day = min(start_day + 6, 28)
            period, _ = Period.objects.update_or_create(
                month=current_month,
                name=f"{index + 1}路程",
                defaults={
                    "status": statuses[index],
                    "start_date": current_month.replace(day=start_day),
                    "end_date": current_month.replace(day=end_day),
                },
            )
            periods.append(period)
        return periods

    def _seed_targets(self, *, today, current_month, periods, departments, members):
        target_specs = [
            ("dm_un_lead", "UN", 20, 50000, 6, 14000),
            ("dm_un_hana", "UN", 16, 42000, 5, 12000),
            ("dm_un_sora", "UN", 14, 36000, 4, 10000),
            ("dm_wv_lead", "WV", 18, 48000, 5, 13000),
            ("dm_wv_rin", "WV", 15, 39000, 4, 11000),
            ("dm_wv_yu", "WV", 12, 30000, 3, 9000),
        ]
        current_period = next(
            (period for period in periods if period.start_date <= today <= period.end_date),
            periods[-1],
        )
        for username, department_code, month_count, month_amount, period_count, period_amount in target_specs:
            member = members[username]
            department = departments[department_code]
            MemberMonthMetricTarget.objects.update_or_create(
                member=member,
                department=department,
                target_month=current_month,
                defaults={"target_count": month_count, "target_amount": month_amount},
            )
            MemberPeriodMetricTarget.objects.update_or_create(
                member=member,
                department=department,
                period=current_period,
                defaults={"target_count": period_count, "target_amount": period_amount},
            )

    def _seed_entries(self, *, today, departments, members):
        base_dates = [today - timedelta(days=offset) for offset in range(0, 14)]
        for offset, entry_date in enumerate(reversed(base_dates), start=1):
            self._upsert_un_entry(
                member=members["dm_un_lead"],
                department=departments["UN"],
                entry_date=entry_date,
                approach=10 + (offset % 4),
                communication=4 + (offset % 3),
                result=1 + (offset % 2),
                amount=2500 + (offset * 170),
                closed=True,
                daily_target_count=2 if entry_date == today else 0,
                daily_target_amount=5000 if entry_date == today else 0,
            )
            self._upsert_un_entry(
                member=members["dm_un_hana"],
                department=departments["UN"],
                entry_date=entry_date,
                approach=8 + (offset % 5),
                communication=3 + (offset % 4),
                result=offset % 3,
                amount=1800 + (offset * 120),
                closed=entry_date < today or False,
                daily_target_count=2 if entry_date == today else 0,
                daily_target_amount=4500 if entry_date == today else 0,
            )
            self._upsert_un_entry(
                member=members["dm_un_sora"],
                department=departments["UN"],
                entry_date=entry_date,
                approach=6 + (offset % 4),
                communication=2 + (offset % 3),
                result=1 if offset % 4 == 0 else 0,
                amount=1200 + (offset * 90),
                closed=entry_date < today,
            )
            self._upsert_wv_entry(
                member=members["dm_wv_lead"],
                department=departments["WV"],
                entry_date=entry_date,
                approach=11 + (offset % 5),
                communication=5 + (offset % 3),
                cs=1 + (offset % 2),
                refugee=1 if offset % 3 == 0 else 0,
                amount=2700 + (offset * 180),
                closed=True,
                daily_target_count=3 if entry_date == today else 0,
                daily_target_amount=5500 if entry_date == today else 0,
            )
            self._upsert_wv_entry(
                member=members["dm_wv_rin"],
                department=departments["WV"],
                entry_date=entry_date,
                approach=9 + (offset % 4),
                communication=3 + (offset % 3),
                cs=offset % 2,
                refugee=1 if offset % 4 == 0 else 0,
                amount=1900 + (offset * 140),
                closed=entry_date < today,
                daily_target_count=2 if entry_date == today else 0,
                daily_target_amount=4200 if entry_date == today else 0,
            )
            self._upsert_wv_entry(
                member=members["dm_wv_yu"],
                department=departments["WV"],
                entry_date=entry_date,
                approach=7 + (offset % 3),
                communication=2 + (offset % 2),
                cs=0 if offset % 3 else 1,
                refugee=0,
                amount=1000 + (offset * 100),
                closed=entry_date < today,
            )

        today_un_hana = MemberDailyMetricEntry.objects.get(
            member=members["dm_un_hana"],
            department=departments["UN"],
            entry_date=today,
        )
        today_un_hana.activity_closed = False
        today_un_hana.activity_closed_at = None
        today_un_hana.save(update_fields=["activity_closed", "activity_closed_at"])

        today_wv_rin = MemberDailyMetricEntry.objects.get(
            member=members["dm_wv_rin"],
            department=departments["WV"],
            entry_date=today,
        )
        today_wv_rin.activity_closed = False
        today_wv_rin.activity_closed_at = None
        today_wv_rin.save(update_fields=["activity_closed", "activity_closed_at"])

        MemberDailyMetricEntry.objects.filter(
            member__in=[members["dm_un_sora"], members["dm_wv_yu"]],
            entry_date=today,
        ).delete()

    def _upsert_un_entry(
        self,
        *,
        member,
        department,
        entry_date,
        approach,
        communication,
        result,
        amount,
        closed,
        daily_target_count=0,
        daily_target_amount=0,
    ):
        MemberDailyMetricEntry.objects.update_or_create(
            member=member,
            department=department,
            entry_date=entry_date,
            defaults={
                "approach_count": approach,
                "communication_count": communication,
                "result_count": result,
                "support_amount": amount,
                "daily_target_count": daily_target_count,
                "daily_target_amount": daily_target_amount,
                "cs_count": 0,
                "refugee_count": 0,
                "location_name": "",
                "memo": "",
                "activity_closed": closed,
                "activity_closed_at": timezone.now() if closed else None,
            },
        )

    def _upsert_wv_entry(
        self,
        *,
        member,
        department,
        entry_date,
        approach,
        communication,
        cs,
        refugee,
        amount,
        closed,
        daily_target_count=0,
        daily_target_amount=0,
    ):
        MemberDailyMetricEntry.objects.update_or_create(
            member=member,
            department=department,
            entry_date=entry_date,
            defaults={
                "approach_count": approach,
                "communication_count": communication,
                "result_count": 0,
                "support_amount": amount,
                "daily_target_count": daily_target_count,
                "daily_target_amount": daily_target_amount,
                "cs_count": cs,
                "refugee_count": refugee,
                "location_name": "",
                "memo": "",
                "activity_closed": closed,
                "activity_closed_at": timezone.now() if closed else None,
            },
        )
