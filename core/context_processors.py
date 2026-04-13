from django.db.models import Q

from .models import Notification, NotificationRead


def notification_badge(request):
    if not request.user.is_authenticated:
        return {"notifications_unread_count": 0}

    notifications = (
        Notification.objects
        .filter(
            Q(users=request.user) |
            Q(target_groups__in=request.user.groups.all())
        )
        .distinct()
    )

    read_ids = NotificationRead.objects.filter(
        user=request.user,
        notification__in=notifications
    ).values_list("notification_id", flat=True)

    unread_count = notifications.exclude(id__in=read_ids).count()

    return {"notifications_unread_count": unread_count}