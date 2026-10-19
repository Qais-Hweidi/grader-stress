import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import database
from services import task_service, notification_service


def setup_function(_):
    database._tasks.clear()
    database._notifications.clear()
    notification_service._instance = None


def _delim(event_type):
    if "." in event_type:
        return "."
    if "_" in event_type:
        return "_"
    return None


def test_created_and_assigned_event_types_use_same_convention():
    task = task_service.create_task("Consistent types")
    created = database.list_notifications()
    assert len(created) >= 1
    created_type = created[0]["event_type"]

    database._notifications.clear()
    task_service.assign_task(task["id"], "user-1")
    assigned = database.list_notifications()
    assert len(assigned) >= 1
    assigned_type = assigned[0]["event_type"]

    assert _delim(created_type) is not None
    assert _delim(created_type) == _delim(assigned_type), (
        f"Inconsistent event type delimiters: {created_type!r} vs {assigned_type!r}"
    )
