"""Key-based API onboarding (app/routers/connections.py).

Covers:
  1. crypto round-trips a credential and reports a rotated key as a typed,
     recoverable error rather than an exception nobody handles.
  2. provider_catalog key-format validation per provider.
  3. provider_probe classifies upstream responses, and refuses to send a
     credential to a non-public or plaintext target (SSRF guard).
  4. POST /connections seeds KnownEndpoint rows tagged to the connection,
     stores only ciphertext + a mask, and rejects malformed keys/duplicates.
  5. DELETE /connections/{id} removes exactly the endpoints it seeded.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.deps import OrgContext
from app.models import (
    AuditLog,
    Base,
    DiscoveredEndpoint,
    KnownEndpoint,
    MonitoredApi,
    Organization,
    OrgMembership,
    User,
)
from app.routers.connections import (
    create_connection,
    delete_connection,
    list_connections,
    verify_connection,
)
from app.schemas import ConnectedApiCreate
from app.security import OrgRole, hash_password
from app.services import provider_probe
from app.services.crypto import DecryptionError, decrypt_secret, encrypt_secret, mask_secret
from app.services.provider_catalog import get_provider, validate_key_format
from app.services.provider_probe import (
    STATUS_ACTIVE,
    STATUS_ERROR,
    STATUS_INVALID,
    UnsafeTargetError,
    assert_safe_target,
)

_TABLES = [
    User.__table__, Organization.__table__, OrgMembership.__table__, AuditLog.__table__,
    KnownEndpoint.__table__, DiscoveredEndpoint.__table__, MonitoredApi.__table__,
]

# Valid-shaped but non-functional keys - format checks only, never sent anywhere.
FAKE_ANTHROPIC_KEY = "sk-ant-api03-" + "A" * 32  # nosec B105
FAKE_GOOGLE_KEY = "AIza" + "B" * 35  # nosec B105


class _FakeRequest:
    class client:
        host = "127.0.0.1"

    class headers:
        @staticmethod
        def get(key, default=None):
            return default


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


# These routes carry @limiter.limit, whose wrapper insists on a real starlette
# Request. __wrapped__ reaches the undecorated function, the same approach
# test_alerts_stream.py and test_ingest_queue.py use.
_create_connection = create_connection.__wrapped__
_list_connections = list_connections.__wrapped__
_delete_connection = delete_connection.__wrapped__
_verify_connection = verify_connection.__wrapped__


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def org_and_editor(db):
    user = User(username="editor", password_hash=hash_password("P@ssw0rd123!"), role="editor", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    org = Organization(name="Acme", slug="acme", owner_user_id=user.id)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org, user


@pytest.fixture()
def allow_target(monkeypatch):
    """Skip the create-time SSRF check so custom-provider tests don't depend
    on DNS. The check itself is covered by its own tests below."""
    import app.routers.connections as connections_router

    monkeypatch.setattr(connections_router, "assert_safe_target", lambda _url: None)


@pytest.fixture()
def stub_probe(monkeypatch):
    """Report an 'active' probe without touching the network. The router
    imported `probe` by name, so that binding is the one that matters."""
    import app.routers.connections as connections_router

    monkeypatch.setattr(connections_router, "probe", lambda *a, **k: (STATUS_ACTIVE, "HTTP 200 - key accepted."))


# ---------------------------------------------------------------------------
# crypto
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_round_trip():
    assert decrypt_secret(encrypt_secret(FAKE_ANTHROPIC_KEY)) == FAKE_ANTHROPIC_KEY


def test_ciphertext_does_not_contain_plaintext():
    assert FAKE_ANTHROPIC_KEY not in encrypt_secret(FAKE_ANTHROPIC_KEY)


def test_decrypt_with_rotated_key_raises_typed_error(monkeypatch):
    from app.services import crypto

    token = encrypt_secret(FAKE_ANTHROPIC_KEY)
    crypto._fernet.cache_clear()
    monkeypatch.setattr(crypto, "_fernet_key_from_passphrase", lambda _p: crypto.base64.urlsafe_b64encode(b"z" * 32))
    try:
        with pytest.raises(DecryptionError):
            crypto.decrypt_secret(token)
    finally:
        crypto._fernet.cache_clear()


def test_mask_secret_keeps_prefix_and_last4():
    prefix, last4 = mask_secret(FAKE_ANTHROPIC_KEY)
    assert prefix == FAKE_ANTHROPIC_KEY[:8]
    assert last4 == FAKE_ANTHROPIC_KEY[-4:]


# ---------------------------------------------------------------------------
# provider_catalog
# ---------------------------------------------------------------------------

def test_validate_key_format_accepts_well_formed_keys():
    assert validate_key_format(get_provider("anthropic"), FAKE_ANTHROPIC_KEY) is None
    assert validate_key_format(get_provider("google"), FAKE_GOOGLE_KEY) is None
    assert validate_key_format(get_provider("openai"), "sk-" + "C" * 32) is None


def test_validate_key_format_rejects_wrong_provider_prefix():
    reason = validate_key_format(get_provider("anthropic"), FAKE_GOOGLE_KEY)
    assert reason is not None and "Anthropic" in reason


def test_validate_key_format_rejects_whitespace_and_blank():
    assert validate_key_format(get_provider("custom"), "  ") is not None
    assert "spaces" in validate_key_format(get_provider("custom"), "abc def ghijkl")


def test_gemini_templates_match_method_style_paths():
    """Gemini's ':generateContent' suffix lives inside the model segment, so
    only a whole-segment wildcard matches it - guard that assumption."""
    from app.services.pathutil import is_documented

    templates = list(get_provider("google").endpoints)
    assert is_documented("POST", "/v1beta/models/gemini-2.5-pro:generateContent", templates)


# ---------------------------------------------------------------------------
# provider_probe
# ---------------------------------------------------------------------------

def _stub_httpx(monkeypatch, status_code, captured=None):
    monkeypatch.setattr(provider_probe, "assert_safe_target", lambda _url: None)

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers):
            if captured is not None:
                captured["url"] = url
                captured["headers"] = headers
            return _FakeResponse(status_code)

    monkeypatch.setattr(provider_probe.httpx, "Client", lambda **kw: _Client())


@pytest.mark.parametrize(
    "code,expected",
    [(200, STATUS_ACTIVE), (204, STATUS_ACTIVE), (429, STATUS_ACTIVE),
     (401, STATUS_INVALID), (403, STATUS_INVALID), (404, STATUS_ERROR), (500, STATUS_ERROR)],
)
def test_probe_classifies_status_codes(monkeypatch, code, expected):
    _stub_httpx(monkeypatch, code)
    status, detail = provider_probe.probe(get_provider("anthropic"), FAKE_ANTHROPIC_KEY, "https://api.anthropic.com")
    assert status == expected
    assert detail


def test_probe_sends_provider_specific_auth_header(monkeypatch):
    captured = {}
    _stub_httpx(monkeypatch, 200, captured)

    provider_probe.probe(get_provider("anthropic"), FAKE_ANTHROPIC_KEY, "https://api.anthropic.com")
    assert captured["url"] == "https://api.anthropic.com/v1/models"
    assert captured["headers"]["x-api-key"] == FAKE_ANTHROPIC_KEY
    assert captured["headers"]["anthropic-version"] == "2023-06-01"

    provider_probe.probe(get_provider("openai"), "sk-" + "C" * 32, "https://api.openai.com")
    assert captured["headers"]["Authorization"].startswith("Bearer ")

    provider_probe.probe(get_provider("google"), FAKE_GOOGLE_KEY, "https://generativelanguage.googleapis.com")
    assert captured["headers"]["x-goog-api-key"] == FAKE_GOOGLE_KEY
    # Never in the query string - proxy access logs would capture it there.
    assert FAKE_GOOGLE_KEY not in captured["url"]


def test_assert_safe_target_rejects_plaintext_http():
    with pytest.raises(UnsafeTargetError, match="https"):
        assert_safe_target("http://api.example.com/v1/models")


@pytest.mark.parametrize("addr", ["127.0.0.1", "169.254.169.254", "10.0.0.5"])
def test_assert_safe_target_rejects_private_and_metadata_addresses(monkeypatch, addr):
    monkeypatch.setattr(
        provider_probe.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (addr, 443))]
    )
    with pytest.raises(UnsafeTargetError, match="non-public"):
        assert_safe_target("https://internal.example.com/")


def test_probe_returns_error_instead_of_raising_on_unsafe_target():
    status, detail = provider_probe.probe(get_provider("custom"), "abcdefghij", "http://localhost:8000")
    assert status == STATUS_ERROR
    assert "https" in detail


# ---------------------------------------------------------------------------
# POST /connections
# ---------------------------------------------------------------------------

def _create(db, org, user, **overrides):
    body = ConnectedApiCreate(
        **{
            "provider": "anthropic",
            "name": "Claude prod",
            "api_key": FAKE_ANTHROPIC_KEY,
            "verify": False,
            **overrides,
        }
    )
    return _create_connection(
        body=body,
        request=_FakeRequest(),
        current_user=user,
        ctx=OrgContext(org_id=org.id, role=OrgRole.EDITOR),
        db=db,
    )


def test_create_connection_registers_catalog_endpoints(db, org_and_editor):
    org, user = org_and_editor
    out = _create(db, org, user)

    catalog = get_provider("anthropic")
    assert out.endpoints_registered == len(catalog.endpoints)
    assert out.status == "unverified"
    assert out.base_url == "https://api.anthropic.com"

    rows = db.query(KnownEndpoint).filter(KnownEndpoint.org_id == org.id).all()
    assert {(r.method, r.path_template) for r in rows} == {(m.upper(), p) for m, p in catalog.endpoints}
    assert {r.source for r in rows} == {f"connection:{out.id}"}


def test_create_connection_stores_ciphertext_and_never_returns_the_key(db, org_and_editor):
    org, user = org_and_editor
    out = _create(db, org, user)

    row = db.query(MonitoredApi).one()
    assert row.credential_ciphertext != FAKE_ANTHROPIC_KEY
    assert decrypt_secret(row.credential_ciphertext) == FAKE_ANTHROPIC_KEY
    assert FAKE_ANTHROPIC_KEY not in out.model_dump_json()
    assert out.key_masked.startswith(FAKE_ANTHROPIC_KEY[:8])
    assert out.key_masked.endswith(FAKE_ANTHROPIC_KEY[-4:])


def test_create_connection_probes_when_verify_requested(db, org_and_editor, stub_probe):
    org, user = org_and_editor
    out = _create(db, org, user, verify=True)
    assert out.status == STATUS_ACTIVE
    assert out.last_checked_at is not None


def test_create_connection_rejects_malformed_key(db, org_and_editor):
    from fastapi import HTTPException

    org, user = org_and_editor
    with pytest.raises(HTTPException) as exc:
        _create(db, org, user, api_key="not-a-real-anthropic-key")
    assert exc.value.status_code == 400


def test_create_connection_rejects_unknown_provider(db, org_and_editor):
    from fastapi import HTTPException

    org, user = org_and_editor
    with pytest.raises(HTTPException) as exc:
        _create(db, org, user, provider="mistral")
    assert exc.value.status_code == 400


def test_create_connection_rejects_duplicate_name(db, org_and_editor):
    from fastapi import HTTPException

    org, user = org_and_editor
    _create(db, org, user)
    with pytest.raises(HTTPException) as exc:
        _create(db, org, user)
    assert exc.value.status_code == 409


def test_duplicate_name_race_is_409_not_500(db, org_and_editor, monkeypatch):
    """The pre-insert existence check narrows the duplicate window but can't
    close it. If two creates interleave, the unique index fires and the loser
    must still surface a conflict rather than an unhandled 500."""
    from fastapi import HTTPException

    org, user = org_and_editor
    _create(db, org, user)

    # Simulate the interleaving: the SELECT sees nothing, the INSERT collides.
    import app.routers.connections as connections_router

    monkeypatch.setattr(
        connections_router,
        "_name_taken",
        lambda *a, **k: False,
    )
    with pytest.raises(HTTPException) as exc:
        _create(db, org, user)
    assert exc.value.status_code == 409
    assert "already exists" in exc.value.detail


def test_custom_provider_rejects_plaintext_base_url(db, org_and_editor):
    from fastapi import HTTPException

    org, user = org_and_editor
    with pytest.raises(HTTPException, match="https"):
        _create(db, org, user, provider="custom", api_key="abcdefghij",
                base_url="http://api.example.com", endpoints="GET /health")


def test_custom_provider_rejects_non_public_base_url_at_creation(db, org_and_editor, monkeypatch):
    """A target we would always refuse to send credentials to is a bad
    request, not a saved row stuck in the 'error' state."""
    from fastapi import HTTPException

    org, user = org_and_editor
    # assert_safe_target resolves through provider_probe's globals even though
    # the router imported the function by name.
    monkeypatch.setattr(
        provider_probe.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("169.254.169.254", 443))]
    )
    with pytest.raises(HTTPException, match="non-public") as exc:
        _create(db, org, user, provider="custom", api_key="abcdefghij",
                base_url="https://metadata.internal", endpoints="GET /latest/meta-data")
    assert exc.value.status_code == 400
    assert db.query(MonitoredApi).count() == 0
    assert db.query(KnownEndpoint).count() == 0


def test_custom_provider_requires_at_least_one_endpoint(db, org_and_editor, allow_target):
    from fastapi import HTTPException

    org, user = org_and_editor
    with pytest.raises(HTTPException, match="at least one endpoint"):
        _create(db, org, user, provider="custom", api_key="abcdefghij",
                base_url="https://api.example.com", endpoints="")


def test_custom_provider_parses_endpoint_lines(db, org_and_editor, allow_target):
    org, user = org_and_editor
    out = _create(
        db, org, user,
        provider="custom",
        name="Internal billing",
        api_key="abcdefghijklmnop",
        base_url="https://billing.example.com",
        endpoints="# comment\nGET /v1/health\npost /v1/charges\nGET /v1/charges/{id}\n",
    )
    assert out.endpoints_registered == 3
    rows = {(r.method, r.path_template) for r in db.query(KnownEndpoint).all()}
    assert rows == {("GET", "/v1/health"), ("POST", "/v1/charges"), ("GET", "/v1/charges/{id}")}


def test_custom_provider_rejects_unparseable_endpoint_line(db, org_and_editor, allow_target):
    from fastapi import HTTPException

    org, user = org_and_editor
    with pytest.raises(HTTPException, match="Cannot parse"):
        _create(db, org, user, provider="custom", api_key="abcdefghij",
                base_url="https://api.example.com", endpoints="GET health")


def test_create_connection_writes_audit_event(db, org_and_editor):
    org, user = org_and_editor
    _create(db, org, user)
    row = db.query(AuditLog).filter(AuditLog.event_type == "api_connection_created").one()
    assert row.target == "Claude prod"
    assert row.details["provider"] == "anthropic"


# ---------------------------------------------------------------------------
# POST /connections/{id}/verify
# ---------------------------------------------------------------------------

def _verify(db, org, user, connection_id):
    return _verify_connection(
        connection_id=connection_id,
        request=_FakeRequest(),
        current_user=user,
        ctx=OrgContext(org_id=org.id, role=OrgRole.EDITOR),
        db=db,
    )


def test_verify_replays_the_stored_key_and_records_the_outcome(db, org_and_editor, monkeypatch):
    import app.routers.connections as connections_router

    org, user = org_and_editor
    out = _create(db, org, user)

    seen = {}

    def _fake_probe(provider, api_key, base_url, verify_path):
        seen["key"] = api_key
        seen["base_url"] = base_url
        return STATUS_INVALID, "HTTP 401 from GET /v1/models - the provider rejected this key."

    monkeypatch.setattr(connections_router, "probe", _fake_probe)
    refreshed = _verify(db, org, user, out.id)

    assert seen["key"] == FAKE_ANTHROPIC_KEY  # decrypted from storage, not re-supplied
    assert seen["base_url"] == "https://api.anthropic.com"
    assert refreshed.status == STATUS_INVALID
    assert "401" in refreshed.last_check_detail
    assert refreshed.last_checked_at is not None


def test_verify_reports_409_when_the_encryption_key_rotated(db, org_and_editor, monkeypatch):
    from fastapi import HTTPException

    import app.routers.connections as connections_router

    org, user = org_and_editor
    out = _create(db, org, user)

    def _boom(_ciphertext):
        raise DecryptionError("Stored credential could not be decrypted")

    monkeypatch.setattr(connections_router, "decrypt_secret", _boom)
    with pytest.raises(HTTPException) as exc:
        _verify(db, org, user, out.id)
    assert exc.value.status_code == 409


def test_verify_404s_for_another_org(db, org_and_editor):
    from fastapi import HTTPException

    org, user = org_and_editor
    out = _create(db, org, user)
    other = Organization(name="Other", slug="other", owner_user_id=user.id)
    db.add(other)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        _verify_connection(
            connection_id=out.id,
            request=_FakeRequest(),
            current_user=user,
            ctx=OrgContext(org_id=other.id, role=OrgRole.EDITOR),
            db=db,
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# GET / DELETE /connections
# ---------------------------------------------------------------------------

def test_list_connections_is_org_scoped(db, org_and_editor):
    org, user = org_and_editor
    _create(db, org, user)
    other = Organization(name="Other", slug="other", owner_user_id=user.id)
    db.add(other)
    db.commit()

    mine = _list_connections(request=_FakeRequest(), ctx=OrgContext(org_id=org.id, role=OrgRole.VIEWER), db=db)
    theirs = _list_connections(request=_FakeRequest(), ctx=OrgContext(org_id=other.id, role=OrgRole.VIEWER), db=db)
    assert [c.name for c in mine] == ["Claude prod"]
    assert theirs == []


def test_delete_connection_removes_only_its_own_endpoints(db, org_and_editor):
    org, user = org_and_editor
    db.add(KnownEndpoint(org_id=org.id, method="GET", path_template="/from-spec", source="openapi"))
    db.commit()
    out = _create(db, org, user)

    result = _delete_connection(
        connection_id=out.id,
        request=_FakeRequest(),
        current_user=user,
        ctx=OrgContext(org_id=org.id, role=OrgRole.EDITOR),
        db=db,
    )
    assert result["endpoints_removed"] == len(get_provider("anthropic").endpoints)
    remaining = db.query(KnownEndpoint).all()
    assert [(r.method, r.path_template) for r in remaining] == [("GET", "/from-spec")]
    assert db.query(MonitoredApi).count() == 0


def test_delete_connection_404s_for_another_org(db, org_and_editor):
    from fastapi import HTTPException

    org, user = org_and_editor
    out = _create(db, org, user)
    other = Organization(name="Other", slug="other", owner_user_id=user.id)
    db.add(other)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        _delete_connection(
            connection_id=out.id,
            request=_FakeRequest(),
            current_user=user,
            ctx=OrgContext(org_id=other.id, role=OrgRole.EDITOR),
            db=db,
        )
    assert exc.value.status_code == 404
