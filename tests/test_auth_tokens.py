from app.security import create_access_token, create_refresh_token, decode_token


def test_access_token_roundtrip() -> None:
    token, _exp = create_access_token("admin")
    payload = decode_token(token)
    assert payload["sub"] == "admin"
    assert payload["type"] == "access"


def test_refresh_token_roundtrip() -> None:
    token, _exp = create_refresh_token("admin")
    payload = decode_token(token)
    assert payload["sub"] == "admin"
    assert payload["type"] == "refresh"
