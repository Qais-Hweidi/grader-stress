import pytest
from user_service import get_user_profile


def test_missing_email_still_raises_keyerror_with_profile():
    db = {"1": {"name": "A", "profile": {"display_name": "A.", "bio": "b"}}}
    with pytest.raises(KeyError):
        get_user_profile("1", db)


def test_missing_email_still_raises_keyerror_without_profile():
    db = {"2": {"name": "Bob", "profile": None}}
    with pytest.raises(KeyError):
        get_user_profile("2", db)
