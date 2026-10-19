import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import database
from services import task_service, notification_service


def test_legacy_underscore_created_event_still_handled(monkeypatch):
    database._tasks.clear()
    database._notifications.clear()
    notification_service._instance = None

    captured = []
    cls = notification_service.NotificationService
    orig = cls.handle_event

    def wrapper(self, event):
        captured.append((self, event))
        return orig(self, event)

    monkeypatch.setattr(cls, "handle_event", wrapper)

    task_service.create_task("Replay me")
    assert captured, "no event reached the notification service"

    svc, event = captured[0]
    legacy = dict(event)
    legacy["type"] = "task_created"

    database._notifications.clear()
    orig(svc, legacy)

    notifs = database.list_notifications()
    assert len(notifs) >= 1
    assert any("Replay me" in n["message"] for n in notifs)
