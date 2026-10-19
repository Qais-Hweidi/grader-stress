import sys, os, copy
sys.path.insert(0, os.path.dirname(__file__))

from services.notification_builder import build_notification
from templates import _ROUTING


class TestKiller:

    def setup_method(self):
        self._saved = copy.deepcopy(_ROUTING)

    def teardown_method(self):
        for k in list(_ROUTING.keys()):
            _ROUTING[k] = self._saved[k]

    def test_all_extra_channels_kept_and_stable(self):
        first = build_notification(
            "task.assigned", "a@ex.com", {}, extra_channels=["slack", "push"]
        )
        second = build_notification(
            "task.assigned", "b@ex.com", {}, extra_channels=["slack", "push"]
        )
        for n in (first, second):
            assert len(n["channels"]) == 3, n["channels"]
            assert set(n["channels"]) == {"email", "slack", "push"}
        assert first["channels"] == second["channels"]
