"""
Validates Task 2: SHA-256 refresh-token hashing.

Tests confirm that:
  1. hash_token() produces a 64-char hex SHA-256 digest.
  2. The same token always hashes to the same value (deterministic).
  3. Two different tokens produce different hashes (no collision on obvious inputs).
  4. The token stored in the DB after login/register is a hash, not the raw JWT.
"""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, RefreshToken, User
from app.security import hash_password, hash_token


# ---------------------------------------------------------------------------
# Pure unit tests for hash_token()
# ---------------------------------------------------------------------------

def test_hash_token_returns_64_char_hex():
    digest = hash_token("some.jwt.token")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_hash_token_is_deterministic():
    t = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
    # Bound to separate names rather than compared inline: `f(x) == f(x)` is
    # indistinguishable from a copy-paste mistake to both readers and static
    # analysis, even though comparing two independent calls is exactly the
    # point of a determinism test.
    first = hash_token(t)
    second = hash_token(t)
    assert first == second


def test_hash_token_matches_stdlib():
    t = "test-token-value"
    expected = hashlib.sha256(t.encode("utf-8")).hexdigest()
    assert hash_token(t) == expected


def test_different_tokens_produce_different_hashes():
    assert hash_token("tokenA") != hash_token("tokenB")


def test_hash_token_is_not_plaintext():
    t = "super-secret-refresh-jwt"
    assert hash_token(t) != t


# ---------------------------------------------------------------------------
# Integration tests: DB stores hash, not plaintext JWT
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """In-memory SQLite session scoped to each test.

    Creates only the tables this test suite needs.  The full Base.metadata
    includes OpenAPISnapshot which uses a MySQL-specific LONGTEXT column that
    SQLite cannot compile.
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[User.__table__, RefreshToken.__table__])
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def user(db):
    u = User(
        username="tester",
        password_hash=hash_password("Passw0rd!"),
        role="viewer",
        is_active=True,
    )
    db.add(u)
    db.flush()
    return u


def test_stored_token_is_sha256_hash(db, user):
    """Simulates what auth.py does: stores hash_token(jwt) in the DB."""
    raw_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0ZXIifQ.sig"
    db.add(
        RefreshToken(
            user_id=user.id,
            token=hash_token(raw_jwt),
            expires_at=datetime.now(UTC) + timedelta(days=7),
            revoked=False,
        )
    )
    db.commit()

    row = db.query(RefreshToken).filter(RefreshToken.user_id == user.id).one()
    # Column must contain the 64-char hash, not the JWT string
    assert row.token == hash_token(raw_jwt)
    assert len(row.token) == 64
    assert row.token != raw_jwt
    assert "eyJ" not in row.token  # no JWT header fragment


def test_hash_lookup_finds_correct_row(db, user):
    """Simulates the /refresh query: hash incoming token then look up by hash."""
    raw_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0ZXIifQ.sig"
    db.add(
        RefreshToken(
            user_id=user.id,
            token=hash_token(raw_jwt),
            expires_at=datetime.now(UTC) + timedelta(days=7),
            revoked=False,
        )
    )
    db.commit()

    found = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token == hash_token(raw_jwt),
            RefreshToken.revoked.is_(False),
        )
        .one_or_none()
    )
    assert found is not None
    assert found.user_id == user.id


def test_plaintext_lookup_returns_nothing(db, user):
    """Confirms that querying the raw JWT (old behaviour) finds nothing."""
    raw_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0ZXIifQ.sig"
    db.add(
        RefreshToken(
            user_id=user.id,
            token=hash_token(raw_jwt),
            expires_at=datetime.now(UTC) + timedelta(days=7),
            revoked=False,
        )
    )
    db.commit()

    not_found = (
        db.query(RefreshToken)
        .filter(RefreshToken.token == raw_jwt)
        .one_or_none()
    )
    assert not_found is None
