import pytest

from app.auth.errors import InvalidAccessToken
from app.auth.tokens import create_access_token, decode_access_token


def test_roundtrip():
    claims = decode_access_token(create_access_token("user-123", "admin"))
    assert claims.user_id == "user-123"
    assert claims.role == "admin"


def test_bad_signature_rejected():
    token = create_access_token("u", "scorekeeper")
    with pytest.raises(InvalidAccessToken):
        decode_access_token(token + "tampered")


def test_garbage_rejected():
    with pytest.raises(InvalidAccessToken):
        decode_access_token("not.a.jwt")
