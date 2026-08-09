import json

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import OrgContext, get_current_user, require_org_role
from app.models import OpenAPISnapshot, User
from app.schemas import CurlUpload, OpenAPIUpload, PostmanUpload
from app.security import OrgRole
from app.services.curl_parse import extract_paths_from_curl_text
from app.services.openapi_parse import extract_paths_from_openapi
from app.services.postman_parse import extract_paths_from_postman
from app.services.registry_service import register_paths as _register_paths

router = APIRouter(prefix="/registry", tags=["registry"])


@router.post("/openapi")
def upload_openapi(
    spec: OpenAPIUpload,
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(require_org_role(OrgRole.EDITOR)),
    db: Session = Depends(get_db),
):
    try:
        doc = yaml.safe_load(spec.spec_yaml)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}") from e
    if not isinstance(doc, dict):
        raise HTTPException(status_code=400, detail="OpenAPI root must be a mapping")
    paths = extract_paths_from_openapi(doc)
    if not paths:
        raise HTTPException(status_code=400, detail="No paths found in specification")

    snap = OpenAPISnapshot(
        org_id=ctx.org_id,
        title=spec.title,
        version=spec.version or doc.get("info", {}).get("version"),
        raw_yaml=spec.spec_yaml,
    )
    db.add(snap)
    db.flush()

    result = _register_paths(
        db, ctx=ctx, current_user=current_user, request=request, title=spec.title,
        paths=paths, source="openapi", event_type="openapi_registered",
    )
    return {"snapshot_id": snap.id, "paths_registered": result["paths_registered"], "paths_in_spec": result["paths_found"]}


@router.post("/postman")
def upload_postman(
    upload: PostmanUpload,
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(require_org_role(OrgRole.EDITOR)),
    db: Session = Depends(get_db),
):
    """Import a Postman Collection v2.x export. The raw artifact isn't
    archived (unlike OpenAPI's OpenAPISnapshot) — a Postman collection is
    just a source for KnownEndpoint templates here, not a spec of record
    worth versioning."""
    try:
        doc = json.loads(upload.collection_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e
    if not isinstance(doc, dict):
        raise HTTPException(status_code=400, detail="Postman collection root must be a JSON object")
    paths = extract_paths_from_postman(doc)
    if not paths:
        raise HTTPException(status_code=400, detail="No requests found in collection")

    result = _register_paths(
        db, ctx=ctx, current_user=current_user, request=request, title=upload.title,
        paths=paths, source="postman", event_type="postman_registered",
    )
    return result


@router.post("/curl")
def upload_curl(
    upload: CurlUpload,
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(require_org_role(OrgRole.EDITOR)),
    db: Session = Depends(get_db),
):
    """Import one or more `curl ...` command lines (newline-separated,
    backslash line-continuations supported)."""
    paths = extract_paths_from_curl_text(upload.commands)
    if not paths:
        raise HTTPException(status_code=400, detail="No curl commands with a recognizable URL found")

    result = _register_paths(
        db, ctx=ctx, current_user=current_user, request=request, title=upload.title,
        paths=paths, source="curl", event_type="curl_registered",
    )
    return result


@router.get("/openapi/latest")
def latest_openapi(ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER)), db: Session = Depends(get_db)):
    row = (
        db.query(OpenAPISnapshot)
        .filter(OpenAPISnapshot.org_id == ctx.org_id)
        .order_by(OpenAPISnapshot.id.desc())
        .first()
    )
    if not row:
        return {"snapshot": None}
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat(),
        "title": row.title,
        "version": row.version,
    }
