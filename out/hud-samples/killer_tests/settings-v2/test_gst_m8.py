import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from utils.types import CompactDict


def make():
    return CompactDict({"tags": [], "meta": {}, "n": 0, "flag": False, "bio": "", "gone": None})


def test_empty_collections_kept_in_items():
    d = make()
    assert dict(d.items()) == {"tags": [], "meta": {}, "n": 0, "flag": False, "bio": ""}


def test_empty_collections_kept_in_iter_and_len():
    d = make()
    assert set(iter(d)) == {"tags", "meta", "n", "flag", "bio"}
    assert len(d) == 5


def test_empty_collections_kept_in_values():
    d = make()
    vals = d.values()
    assert [] in vals
    assert {} in vals
    assert len(vals) == 5
