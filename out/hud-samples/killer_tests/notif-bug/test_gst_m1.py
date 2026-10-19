import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import database
from services import task_service, notification_service


def setup_function(_):
    database._tasks.clear()
    database._notifications.clear()
    notification_service._instance = None


def test_created_event_type_is_dotted():
    task_service.create_task("Write docs")
    notifs = database.list_notifications()
    assert len(notifs) >= 1
    assert notifs[0]["event_type"] == "task.created"


def test_assigned_event_type_is_dotted():
    task = task_service.create_task("Review PR")
    database._notifications.clear()
    task_service.assign_task(task["id"], "user-456")
    notifs = database.list_notifications()
    assert len(notifs) >= 1
    assert notifs[0]["event_type"] == "task.assigned"


def test_completed_event_type_is_dotted():
    task = task_service.create_task("Ship feature")
    task_service.assign_task(task["id"], "user-999")
    database._notifications.clear()
    task_service.complete_task(task["id"])
    notifs = database.list_notifications()
    assert len(notifs) >= 1
    assert notifs[0]["event_type"] == "task.completed"
