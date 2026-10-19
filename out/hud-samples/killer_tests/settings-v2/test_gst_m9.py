import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from utils.types import CompactDict


def _make():
    return CompactDict({"zero": 0, "flag": False, "empty": "", "name": "x"})


def test_items_keep_falsy_values():
    d = _make()
    assert dict(d.items()) == {"zero": 0, "flag": False, "empty": "", "name": "x"}


def test_iteration_keeps_falsy_keys():
    d = _make()
    assert set(iter(d)) == {"zero", "flag", "empty", "name"}


def test_values_keep_falsy_values():
    d = _make()
    vals = d.values()
    assert len(vals) == 4
    assert 0 in vals and "" in vals and False in vals


def test_len_counts_falsy_values():
    assert len(_make()) == 4


def test_direct_lookup_still_works():
    d = _make()
    assert d["zero"] == 0
    assert d["flag"] is False
    assert d["empty"] == ""
