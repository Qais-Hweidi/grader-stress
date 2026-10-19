import sys, os, copy
sys.path.insert(0, os.path.dirname(__file__))

from services.notification_builder import build_notification
from templates import _ROUTING


class TestTieOrder:

    def setup_method(self):
        self._saved = copy.deepcopy(_ROUTING)

    def teardown_method(self):
        for k in list(_ROUTING.keys()):
            _ROUTING[k] = self._saved[k]

    def test_equal_weight_channels_keep_requested_order(self):
        n = build_notification(
            "task.assigned", "a@ex.com", {}, extra_channels=["slack", "push"]
        )
        ch = n["channels"]
        assert "slack" in ch and "push" in ch
        assert ch.index("slack") < ch.index("push"), ch

    def test_repeated_requests_stable(self):
        first = build_notification(
            "task.assigned", "a@ex.com", {}, extra_channels=["slack", "push"]
        )["channels"]
        second = build_notification(
            "task.assigned", "b@ex.com", {}, extra_channels=["slack", "push"]
        )["channels"]
        assert first == second
        assert first.index("slack") < first.index("push")
