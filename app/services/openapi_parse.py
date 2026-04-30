from typing import Any

import yaml


def extract_paths_from_openapi(doc: dict[str, Any]) -> list[tuple[str, str]]:
    """Return list of (METHOD, path_template) from OpenAPI 3.x or Swagger 2."""
    out: list[tuple[str, str]] = []
    paths = doc.get("paths") or {}
    for path_item, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, _op in methods.items():
            m = method.upper()
            if m in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                out.append((m, path_item))
    return out
