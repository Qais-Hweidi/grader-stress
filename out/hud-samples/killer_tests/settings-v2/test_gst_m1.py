import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from utils.types import CompactDict


def test_iter_keeps_falsy_values():
    d = CompactDict({"a": 0, "b": False, "c": "", "d": 5})
    assert set(list(d)) == {"a", "b", "c", "d"}


def test_len_counts_falsy_values():
    d = CompactDict({"a": 0, "b": False, "c": "", "d": 5})
    assert len(d) == 4


def test_values_keep_falsy_values():
    d = CompactDict({"a": 0, "b": False, "c": "", "d": 5})
    vals = d.values()
    assert len(vals) == 4
    assert 0 in vals and "" in vals and 5 in vals


def test_items_keep_falsy_values():
    d = CompactDict({"a": 0, "b": False, "c": ""})
    assert dict(d.items()) == {"a": 0, "b": False, "c": ""}


def test_none_still_dropped_in_iteration():
    d = CompactDict({"a": 0, "n": None})
    assert list(d) == ["a"]
    assert len(d) == 1
