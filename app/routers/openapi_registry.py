import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import KnownEndpoint, OpenAPISnapshot, User
from app.schemas import OpenAPIUpload
from app.security import Role
from app.services.discovery_service import recompute_discovered_documented_flags
from app.services.openapi_parse import extract_paths_from_openapi
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/registry", tags=["registry"])


@router.post("/openapi")
def upload_openapi(
    spec: OpenAPIUpload,
    request: Request,
    current_user: User = Depends(require_role(Role.EDITOR)),
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
        title=spec.title,
        version=spec.version or doc.get("info", {}).get("version"),
        raw_yaml=spec.spec_yaml,
    )
    db.add(snap)
    db.flush()

    added = 0
    for method, path_template in paths:
        exists = (
            db.query(KnownEndpoint)
            .filter(
                KnownEndpoint.method == method.upper(),
                KnownEndpoint.path_template == path_template,
            )
            .first()
        )
        if exists:
            continue
        db.add(
            KnownEndpoint(
                method=method.upper(),
                path_template=path_template,
                source="openapi",
            )
        )
        added += 1
    db.commit()
    recompute_discovered_documented_flags(db)
    log_audit_event(
        db,
        event_type="openapi_registered",
        actor=current_user.username,
        target=spec.title,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"paths_registered": added, "paths_in_spec": len(paths)},
        success=True,
    )
    return {"snapshot_id": snap.id, "paths_registered": added, "paths_in_spec": len(paths)}


@router.get("/openapi/latest", dependencies=[Depends(require_role(Role.VIEWER))])
def latest_openapi(db: Session = Depends(get_db)):
    row = db.query(OpenAPISnapshot).order_by(OpenAPISnapshot.id.desc()).first()
    if not row:
        return {"snapshot": None}
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat(),
        "title": row.title,
        "version": row.version,
    }
