"""Constants and helpers shared across the API tests."""

ACTIVE_USER_ID = "1234567890"
ACTIVE_SECRET = "correct-horse-battery-staple"
DISABLED_USER_ID = "0987654321"
DISABLED_SECRET = "disabled-user-secret"


def bearer(token):
    return {"Authorization": f"Bearer {token}"}
