"""
Query-string PII redaction tests (app.services.pathutil.redact_sensitive_query_params).

Covers:
  1. A sensitive param's value is replaced; the key name is preserved.
  2. Non-sensitive params pass through unchanged.
  3. Matching is case-insensitive on the key.
  4. A path with no query string is returned unchanged.
  5. A path with only non-sensitive params is returned byte-identical (no
     needless re-encoding).
  6. Multiple sensitive params in one query string are all redacted.
"""

from app.services.pathutil import redact_sensitive_query_params


def test_sensitive_param_value_redacted():
    out = redact_sensitive_query_params("/api/users?token=eyJabc123")
    assert "eyJabc123" not in out
    assert "token=REDACTED" in out


def test_non_sensitive_param_passthrough():
    out = redact_sensitive_query_params("/api/users?page=2&limit=10")
    assert "page=2" in out
    assert "limit=10" in out


def test_case_insensitive_key_match():
    out = redact_sensitive_query_params("/api/users?Token=secretvalue")
    assert "secretvalue" not in out


def test_no_query_string_unchanged():
    path = "/api/users/123"
    assert redact_sensitive_query_params(path) == path


def test_only_non_sensitive_params_returned_unchanged():
    path = "/api/users?page=2"
    assert redact_sensitive_query_params(path) == path


def test_multiple_sensitive_params_all_redacted():
    out = redact_sensitive_query_params("/login?password=hunter2&api_key=abcd1234&page=1")
    assert "hunter2" not in out
    assert "abcd1234" not in out
    assert "page=1" in out
