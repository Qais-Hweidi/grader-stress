import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import database
from services import task_service, notification_service


def setup_function(_):
    database._tasks.clear()
    database._notifications.clear()
    notification_service._instance = None


def _get_service():
    # Trigger lazy initialization through the normal path.
    task_service.create_task("Init task")
    svc = getattr(notification_service, "_instance", None)
    if svc is None:
        svc = notification_service.NotificationService()
    return svc


def test_unknown_event_type_is_ignored():
    svc = _get_service()
    database._notifications.clear()

    # Must not raise and must not generate a notification.
    svc.handle_event({
        "type": "user.created",
        "timestamp": "2024-01-01T00:00:00",
        "data": {"user": "bob"},
    })

    assert database.list_notifications() == []


def test_unknown_assigned_like_type_is_ignored():
    svc = _get_service()
    database._notifications.clear()

    svc.handle_event({
        "type": "project.completed",
        "timestamp": "2024-01-01T00:00:00",
        "data": {"project": "x"},
    })

    assert database.list_notifications() == []


def test_task_events_still_notify():
    task = task_service.create_task("Real task")
    database._notifications.clear()
    task_service.assign_task(task["id"], "user-1")
    notifs = database.list_notifications()
    assert len(notifs) >= 1
    assert notifs[0]["recipient_id"] == "user-1"
