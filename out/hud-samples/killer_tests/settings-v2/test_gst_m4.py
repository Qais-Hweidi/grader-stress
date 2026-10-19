import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from utils.types import CompactDict


def make():
    return CompactDict({"zero": 0, "off": False, "blank": "", "none": None, "name": "x"})


def test_falsy_values_kept_in_items():
    d = make()
    items = dict(d.items())
    assert items["zero"] == 0
    assert items["off"] is False
    assert items["blank"] == ""
    assert items["name"] == "x"


def test_none_values_omitted_from_items():
    d = make()
    assert "none" not in dict(d.items())


def test_none_omitted_from_iteration_and_len():
    d = make()
    keys = list(iter(d))
    assert set(keys) == {"zero", "off", "blank", "name"}
    assert len(d) == 4


def test_none_omitted_from_values():
    d = make()
    vals = list(d.values())
    assert None not in vals
    assert len(vals) == 4
