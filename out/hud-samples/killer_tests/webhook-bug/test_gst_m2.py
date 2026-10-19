import sys, os, json, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))

SCRIPT = r"""
import json
from services.notification_builder import build_notification
out = []
for _ in range(2):
    n = build_notification("task.assigned", "a@ex.com", {}, extra_channels=["slack", "push"])
    out.append(n["channels"])
print(json.dumps(out))
"""


def _run(seed):
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(seed)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    res = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_channel_order_independent_of_hash_seed():
    results = set()
    for seed in range(12):
        out = _run(seed)
        # repeated requests within a process give the same result
        assert out[0] == out[1]
        assert len(out[0]) == len(set(out[0]))
        assert {"email", "slack", "push"} <= set(out[0])
        results.add(tuple(out[0]))
    assert len(results) == 1, f"Channel order varies across runs: {results}"


def test_no_accumulation_across_requests():
    sys.path.insert(0, ROOT)
    from services.notification_builder import build_notification
    build_notification("task.assigned", "a@ex.com", {}, extra_channels=["slack", "push"])
    n = build_notification("task.assigned", "b@ex.com", {})
    assert n["channels"] == ["email"]
