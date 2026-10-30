"""Unit tests for utils/models.py."""
import pytest
from pydantic import ValidationError

from utils.models import BatchLookup, LoginRequest, User, UsernameLookup


def test_user_defaults_to_enabled():
    assert User(user_id="a", secret="b").disabled is False


@pytest.mark.parametrize("model, data", [
    (User, {"user_id": "a"}),
    (UsernameLookup, {}),
    (UsernameLookup, {"username": 1}),
    (BatchLookup, {"usernames": "a"}),
    (BatchLookup, {"usernames": [1]}),
    (LoginRequest, {"user_id": "a"}),
])
def test_invalid_data_is_rejected(model, data):
    with pytest.raises(ValidationError):
        model(**data)


def test_batch_preserves_order_and_duplicates():
    assert BatchLookup(usernames=["b", "a", "b"]).usernames == ["b", "a", "b"]
