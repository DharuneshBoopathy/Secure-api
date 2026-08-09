import re

from app.services.pathutil import normalize_path_for_discovery

# Any variable marker (Postman collection variable {{id}} or path-variable
# :id) is replaced with a UUID-shaped placeholder before normalization, so
# it reliably falls into normalize_path_for_discovery's {uuid} bucket
# alongside concrete example values (e.g. a literal /users/12345 pasted into
# a collection) — reusing that logic rather than re-implementing path
# templating here. The exact placeholder name doesn't matter: KnownEndpoint
# matching (see app.services.pathutil.path_matches_template) treats any
# "{...}" segment as a wildcard regardless of its contents.
_POSTMAN_VAR_RE = re.compile(r"\{\{[^{}]+\}\}")
_UUID_PLACEHOLDER = "00000000-0000-0000-0000-000000000000"
_SCHEME_HOST_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^/]+")


def _mark_variables(path: str) -> str:
    path = _POSTMAN_VAR_RE.sub(_UUID_PLACEHOLDER, path)
    segments = [
        _UUID_PLACEHOLDER if seg.startswith(":") and len(seg) > 1 else seg
        for seg in path.split("/")
    ]
    return "/".join(segments)


def path_to_template(path: str) -> str:
    return normalize_path_for_discovery(_mark_variables(path))


def path_from_raw_url(raw: str) -> str:
    return _SCHEME_HOST_RE.sub("", raw) or "/"


def _extract_path(url: object) -> str | None:
    if isinstance(url, str):
        return path_from_raw_url(url)
    if isinstance(url, dict):
        path_parts = url.get("path")
        if isinstance(path_parts, list) and path_parts:
            return "/" + "/".join(str(p) for p in path_parts)
        raw = url.get("raw")
        if isinstance(raw, str):
            return path_from_raw_url(raw)
    return None


def extract_paths_from_postman(doc: dict) -> list[tuple[str, str]]:
    """Recursively walk a Postman Collection v2.x ``item`` tree (folders
    nest further ``item`` lists) and return deduplicated (METHOD, path
    template) tuples, mirroring app.services.openapi_parse's contract."""
    if not isinstance(doc, dict):
        return []

    found: list[tuple[str, str]] = []

    def walk(items: object) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("item"), list):
                walk(item["item"])
                continue
            request = item.get("request")
            if not isinstance(request, dict):
                continue
            method = request.get("method") or "GET"
            raw_path = _extract_path(request.get("url"))
            if raw_path is None:
                continue
            found.append((str(method).upper(), path_to_template(raw_path)))

    walk(doc.get("item"))

    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str]] = []
    for pair in found:
        if pair not in seen:
            seen.add(pair)
            deduped.append(pair)
    return deduped
