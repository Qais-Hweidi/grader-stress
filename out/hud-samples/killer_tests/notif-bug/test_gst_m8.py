import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import database
from services import task_service, notification_service


def setup_function(_):
    database._tasks.clear()
    database._notifications.clear()
    notification_service._instance = None


def test_underscore_assigned_event_not_routed_directly():
    captured = []
    cls = notification_service.NotificationService
    orig = cls.handle_event

    def spy(self, event):
        captured.append(dict(event))
        return orig(self, event)

    cls.handle_event = spy
    try:
        task = task_service.create_task("Review PR")
        database._notifications.clear()
        task_service.assign_task(task["id"], "user-456")
    finally:
        cls.handle_event = orig

    # The real pipeline must have produced an assignment notification
    assert len(database.list_notifications()) >= 1
    assigned = [e for e in captured if e["type"].endswith("assigned")]
    assert assigned

    # Feed a legacy underscore-style assigned event directly to a fresh service
    database._notifications.clear()
    ev = dict(assigned[0])
    ev["type"] = "task_assigned"
    svc = cls()
    svc.handle_event(ev)
    assert database.list_notifications() == []
