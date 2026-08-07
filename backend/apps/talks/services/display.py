from django.utils import timezone


def talks_author_name(member_obj, snapshot: str) -> str:
    if member_obj and member_obj.name:
        return member_obj.name
    return snapshot or "不明"


def format_post_created_display(dt) -> str:
    local_dt = timezone.localtime(dt)
    if local_dt.date() == timezone.localdate():
        return local_dt.strftime("%H:%M")
    return local_dt.strftime("%Y-%m-%d")
