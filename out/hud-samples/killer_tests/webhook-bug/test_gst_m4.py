import sys, os, copy
sys.path.insert(0, os.path.dirname(__file__))

from services.notification_builder import build_notification
from templates import _ROUTING


class TestSortStable:

    def setup_method(self):
        self._saved = copy.deepcopy(_ROUTING)

    def teardown_method(self):
        for k in list(_ROUTING.keys()):
            _ROUTING[k] = self._saved[k]

    def test_urgent_with_slack_sorted_by_weight_and_repeatable(self):
        n1 = build_notification("task.urgent", "a@ex.com", {}, extra_channels=["slack"])
        n2 = build_notification("task.urgent", "b@ex.com", {}, extra_channels=["slack"])
        n3 = build_notification("task.urgent", "c@ex.com", {}, extra_channels=["slack"])
        assert n1["channels"] == ["email", "slack", "sms"]
        assert n2["channels"] == n1["channels"]
        assert n3["channels"] == n1["channels"]
