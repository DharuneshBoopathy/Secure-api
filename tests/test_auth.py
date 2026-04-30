from app.security import create_access_token, decode_token, hash_password, verify_password


def test_access_token_contains_subject() -> None:
    token, _ = create_access_token("security-admin")
    payload = decode_token(token)
    assert payload["sub"] == "security-admin"
    assert payload["type"] == "access"


def test_password_hash_uses_bcrypt() -> None:
    hashed = hash_password("S3cur3P@ssw0rd!")
    assert hashed.startswith("$2b$"), f"Expected bcrypt hash ($2b$), got: {hashed[:10]}"


def test_password_verify_correct() -> None:
    plaintext = "S3cur3P@ssw0rd!"
    hashed = hash_password(plaintext)
    assert verify_password(plaintext, hashed)


def test_password_verify_wrong_rejected() -> None:
    hashed = hash_password("S3cur3P@ssw0rd!")
    assert not verify_password("wrongpassword", hashed)
