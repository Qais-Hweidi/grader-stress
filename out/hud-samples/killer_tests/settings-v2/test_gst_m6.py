import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from utils.types import CompactDict


def test_iter_and_len_skip_none_but_keep_falsy():
    d = CompactDict({"a": None, "b": 0, "c": False, "d": "", "e": "x"})
    assert sorted(list(d)) == ["b", "c", "d", "e"]
    assert len(d) == 4


def test_iteration_views_consistent():
    d = CompactDict({"a": None, "b": 0})
    assert list(d) == ["b"]
    assert len(d) == 1
    assert [k for k, _ in d.items()] == list(d)
    assert d.values() == [0]


def test_direct_lookup_still_works():
    d = CompactDict({"a": None, "b": 0})
    assert d["b"] == 0
