from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.security import Role
from app.services.metrics import metrics_response

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db": "unreachable"},
        )


@router.get("/metrics", dependencies=[Depends(require_role(Role.ADMIN))])
def metrics():
    body, ctype = metrics_response()
    return Response(content=body, media_type=ctype)
