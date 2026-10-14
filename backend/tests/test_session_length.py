"""A sign-in lasts until logout or 24 hours (tracker No. 100).

It used to last 30 minutes, which signed people out in the middle of their
work. The length is SESSION_HOURS; the old JWT_ACCESS_TOKEN_EXPIRE_MINUTES
is no longer read, so a leftover 30 in an env file cannot bring it back.
"""

from datetime import datetime, timezone

from jose import jwt

from app.config import Settings, get_settings
from app.services import jwt_service


def _hours_left(token: str) -> float:
    s = get_settings()
    claims = jwt.decode(token, s.jwt_secret_key, algorithms=[s.jwt_algorithm])
    left = datetime.fromtimestamp(claims["exp"], timezone.utc) - datetime.now(timezone.utc)
    return left.total_seconds() / 3600


def test_a_sign_in_lasts_24_hours():
    token = jwt_service.create_access_token({"sub": "rm@eko.co.in", "role": "rm"})
    assert 23.9 < _hours_left(token) <= 24
    assert jwt_service.decode_token(token)["sub"] == "rm@eko.co.in"


def test_the_old_30_minute_setting_is_ignored(monkeypatch):
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.delenv("SESSION_HOURS", raising=False)
    assert Settings(_env_file=None).session_hours == 24


def test_an_expired_sign_in_is_refused():
    from datetime import timedelta
    token = jwt_service.create_access_token(
        {"sub": "rm@eko.co.in"}, expires_delta=timedelta(seconds=-1))
    assert jwt_service.decode_token(token) is None
