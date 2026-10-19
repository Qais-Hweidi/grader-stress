import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from utils.types import CompactDict


def make():
    return CompactDict({"zero": 0, "off": False, "empty": "", "name": "x"})


def test_items_keep_falsy_values():
    d = make()
    assert dict(d.items()) == {"zero": 0, "off": False, "empty": "", "name": "x"}


def test_iteration_keeps_falsy_keys():
    d = make()
    assert set(list(d)) == {"zero", "off", "empty", "name"}


def test_values_keep_falsy_values():
    d = make()
    vals = d.values()
    assert 0 in vals and "" in vals and any(v is False for v in vals)
    assert len(vals) == 4


def test_len_counts_falsy_values():
    assert len(make()) == 4


def test_dict_conversion_keeps_falsy():
    d = make()
    assert dict(d) == {"zero": 0, "off": False, "empty": "", "name": "x"}
