"""
Phase 4.6 (broader registry ingestion formats): Postman Collection import and
curl command parsing, alongside the existing OpenAPI upload.

Covers:
  1. postman_parse.extract_paths_from_postman walks nested folders, prefers
     the structured `url.path` array, handles plain-string urls, and
     converts both {{var}} and :var markers into wildcard templates.
  2. curl_parse.parse_curl_command handles -X/--request, implicit POST from
     -d/--data (matching curl's real default), quoted headers/data that
     must not be mistaken for the URL, and returns None with no URL.
  3. curl_parse.extract_paths_from_curl_text skips non-curl lines and dedupes.
  4. POST /registry/postman and POST /registry/curl register KnownEndpoint
     rows scoped to the caller's org, matching the existing /registry/openapi
     dedupe + audit-log behavior.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.deps import OrgContext
from app.models import AuditLog, Base, DiscoveredEndpoint, KnownEndpoint, Organization, OrgMembership, User
from app.routers.openapi_registry import upload_curl, upload_postman
from app.schemas import CurlUpload, PostmanUpload
from app.security import OrgRole, hash_password
from app.services.curl_parse import extract_paths_from_curl_text, parse_curl_command
from app.services.postman_parse import extract_paths_from_postman

_TABLES = [
    User.__table__, Organization.__table__, OrgMembership.__table__, AuditLog.__table__,
    KnownEndpoint.__table__, DiscoveredEndpoint.__table__,
]


class _FakeRequest:
    class client:
        host = "127.0.0.1"

    class headers:
        @staticmethod
        def get(key, default=None):
            return default


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


# ---------------------------------------------------------------------------
# postman_parse
# ---------------------------------------------------------------------------

def test_postman_parse_walks_nested_folders_and_dedupes():
    doc = {
        "item": [
            {
                "name": "Users folder",
                "item": [
                    {"name": "Get user", "request": {"method": "GET", "url": {"path": ["users", "12345"]}}},
                    {"name": "Get user dup", "request": {"method": "get", "url": {"path": ["users", "999"]}}},
                ],
            },
            {"name": "List users", "request": {"method": "GET", "url": "https://api.example.com/users"}},
        ]
    }
    result = extract_paths_from_postman(doc)
    assert result == [("GET", "/users/{id}"), ("GET", "/users")]


def test_postman_parse_converts_double_brace_and_colon_variables():
    doc = {
        "item": [
            {"name": "a", "request": {"method": "POST", "url": {"raw": "https://x/users/{{userId}}/profile", "path": ["users", "{{userId}}", "profile"]}}},
            {"name": "b", "request": {"method": "GET", "url": {"raw": "https://x/orders/:orderId", "path": ["orders", ":orderId"]}}},
        ]
    }
    assert extract_paths_from_postman(doc) == [("POST", "/users/{uuid}/profile"), ("GET", "/orders/{uuid}")]


def test_postman_parse_ignores_malformed_items():
    assert extract_paths_from_postman({}) == []
    assert extract_paths_from_postman({"item": [{"name": "no request here"}]}) == []
    assert extract_paths_from_postman({"item": "not-a-list"}) == []


# ---------------------------------------------------------------------------
# curl_parse
# ---------------------------------------------------------------------------

def test_parse_curl_explicit_method():
    assert parse_curl_command("curl -X DELETE https://api.example.com/users/42") == ("DELETE", "/users/{id}")


def test_parse_curl_data_flag_implies_post_like_real_curl():
    assert parse_curl_command('curl https://api.example.com/orders -d \'{"a":1}\'') == ("POST", "/orders")


def test_parse_curl_no_method_no_data_defaults_get():
    assert parse_curl_command("curl https://api.example.com/health") == ("GET", "/health")


def test_parse_curl_quoted_header_and_data_not_mistaken_for_url():
    cmd = "curl -X POST 'https://api.example.com/login' -H 'Content-Type: application/json' -d '{\"user\":\"a\"}'"
    assert parse_curl_command(cmd) == ("POST", "/login")


def test_parse_curl_double_brace_variable_in_path():
    assert parse_curl_command("curl https://api.example.com/secure/{{token}}") == ("GET", "/secure/{uuid}")


def test_parse_curl_no_url_returns_none():
    assert parse_curl_command("curl -X GET -H 'Accept: application/json'") is None


def test_extract_paths_from_curl_text_skips_non_curl_lines_and_dedupes():
    text = """
    # a comment, not a curl line
    curl https://api.example.com/health
    curl https://api.example.com/health
    curl -X POST https://api.example.com/orders/1 -d '{}'
    """
    assert extract_paths_from_curl_text(text) == [("GET", "/health"), ("POST", "/orders/{id}")]


# ---------------------------------------------------------------------------
# POST /registry/postman, POST /registry/curl
# ---------------------------------------------------------------------------

def test_upload_postman_registers_known_endpoints(db, org_and_editor):
    org, user = org_and_editor
    ctx = OrgContext(org_id=org.id, role=OrgRole.EDITOR)
    body = PostmanUpload(
        title="My Collection",
        collection_json='{"item":[{"name":"a","request":{"method":"GET","url":{"path":["ping"]}}}]}',
    )
    result = upload_postman(upload=body, request=_FakeRequest(), current_user=user, ctx=ctx, db=db)
    assert result == {"paths_registered": 1, "paths_found": 1}

    row = db.query(KnownEndpoint).filter(KnownEndpoint.org_id == org.id).one()
    assert (row.method, row.path_template, row.source) == ("GET", "/ping", "postman")

    audit_row = db.query(AuditLog).filter(AuditLog.event_type == "postman_registered").one()
    assert audit_row.target == "My Collection"


def test_upload_postman_rejects_invalid_json(db, org_and_editor):
    from fastapi import HTTPException

    org, user = org_and_editor
    ctx = OrgContext(org_id=org.id, role=OrgRole.EDITOR)
    body = PostmanUpload(title="Bad", collection_json="{not json")
    with pytest.raises(HTTPException) as exc_info:
        upload_postman(upload=body, request=_FakeRequest(), current_user=user, ctx=ctx, db=db)
    assert exc_info.value.status_code == 400


def test_upload_curl_registers_known_endpoints_and_dedupes_against_existing(db, org_and_editor):
    org, user = org_and_editor
    db.add(KnownEndpoint(org_id=org.id, method="GET", path_template="/health", source="openapi"))
    db.commit()

    ctx = OrgContext(org_id=org.id, role=OrgRole.EDITOR)
    body = CurlUpload(
        title="My curl exports",
        commands="curl https://api.example.com/health\ncurl -X POST https://api.example.com/orders/1 -d '{}'",
    )
    result = upload_curl(upload=body, request=_FakeRequest(), current_user=user, ctx=ctx, db=db)
    assert result == {"paths_registered": 1, "paths_found": 2}  # /health already existed

    rows = {(r.method, r.path_template) for r in db.query(KnownEndpoint).filter(KnownEndpoint.org_id == org.id).all()}
    assert rows == {("GET", "/health"), ("POST", "/orders/{id}")}


def test_upload_curl_rejects_when_nothing_parses(db, org_and_editor):
    from fastapi import HTTPException

    org, user = org_and_editor
    ctx = OrgContext(org_id=org.id, role=OrgRole.EDITOR)
    body = CurlUpload(title="Empty", commands="not a curl command at all")
    with pytest.raises(HTTPException) as exc_info:
        upload_curl(upload=body, request=_FakeRequest(), current_user=user, ctx=ctx, db=db)
    assert exc_info.value.status_code == 400
