import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import database
from services import task_service, notification_service


def setup_function(_):
    database._tasks.clear()
    database._notifications.clear()
    notification_service._instance = None


def test_assignment_notification_uses_dotted_event_type():
    task = task_service.create_task("Deploy fix")
    database._notifications.clear()

    task_service.assign_task(task["id"], "user-789")

    notifs = database.list_notifications()
    assert len(notifs) >= 1
    assert notifs[0]["recipient_id"] == "user-789"
    assert notifs[0]["event_type"] == "task.assigned"


def test_creation_notification_uses_dotted_event_type():
    task_service.create_task("Write docs")
    notifs = database.list_notifications()
    assert len(notifs) >= 1
    assert notifs[0]["event_type"] == "task.created"
