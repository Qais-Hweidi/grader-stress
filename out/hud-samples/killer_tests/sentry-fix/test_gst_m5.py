import pytest
from user_service import get_user_profile


DB = {
    "1": {
        "name": "Delilah",
        "email": "d@example.com",
        "profile": {"display_name": "Dee"},
    },
}


def test_partial_profile_keeps_display_name_with_empty_bio():
    result = get_user_profile("1", DB)
    assert result["name"] == "Dee"
    assert result["bio"] == ""
    assert result["email"] == "d@example.com"
