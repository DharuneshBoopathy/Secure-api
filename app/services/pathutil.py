import re
from urllib.parse import parse_qsl, urlencode

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_NUM_RE = re.compile(r"^\d+$")
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){2,}$")

# Query parameter names whose values are redacted before a captured path is
# ever persisted — query strings routinely carry bearer tokens, API keys, and
# passwords (e.g. `?token=eyJ...`), and this is a monitoring tool that must
# not become a second place those secrets get stored in plaintext.
DEFAULT_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "token", "access_token", "refresh_token", "id_token", "api_key", "apikey",
        "password", "passwd", "pwd", "secret", "client_secret", "auth", "session", "jwt", "key",
    }
)


def redact_sensitive_query_params(
    path: str, sensitive_keys: frozenset[str] = DEFAULT_SENSITIVE_QUERY_KEYS
) -> str:
    """Replace the values of sensitive query-string params with a fixed marker.

    The parameter name is kept (useful for shadow/anomaly analysis); only the
    value — the part that can actually be a live credential — is redacted.
    """
    if "?" not in path:
        return path
    base, _, query = path.partition("?")
    if not query:
        return path
    pairs = parse_qsl(query, keep_blank_values=True)
    if not any(k.lower() in sensitive_keys for k, _ in pairs):
        return path
    redacted = [(k, "REDACTED" if k.lower() in sensitive_keys else v) for k, v in pairs]
    return f"{base}?{urlencode(redacted)}"


def normalize_path_for_discovery(path: str) -> str:
    """Group dynamic segments so shadow APIs cluster (Levo-style inventory)."""
    if not path:
        return "/"
    p = path.split("?", 1)[0].rstrip("/") or "/"
    parts = p.split("/")
    out: list[str] = []
    for seg in parts:
        if not seg:
            continue
        if _NUM_RE.match(seg):
            out.append("{id}")
        elif _UUID_RE.match(seg):
            out.append("{uuid}")
        elif _SLUG_RE.match(seg):
            out.append("{slug}")
        elif len(seg) > 24 and all(c in "0123456789abcdef-" for c in seg.lower()):
            out.append("{hash}")
        else:
            out.append(seg)
    return "/" + "/".join(out) if out else "/"


def path_matches_template(actual_path: str, template: str) -> bool:
    """Match /users/5 against /users/{userId}."""
    a = (actual_path.split("?", 1)[0].rstrip("/") or "/").split("/")
    t = (template.rstrip("/") or "/").split("/")
    if len(a) != len(t):
        return False
    for ac, tc in zip(a, t):
        if not ac and not tc:
            continue
        if tc.startswith("{") and tc.endswith("}"):
            continue
        if ac != tc:
            return False
    return True


def is_documented(method: str, path: str, templates: list[tuple[str, str]]) -> bool:
    m = method.upper()
    ap = path.split("?", 1)[0].rstrip("/") or "/"
    for tm, tp in templates:
        if tm.upper() != m:
            continue
        if path_matches_template(ap, tp):
            return True
    return False
