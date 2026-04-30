from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import TrafficEvent
from app.schemas import TrafficEventOut
from app.security import Role

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


@router.get("", dependencies=[Depends(require_role(Role.VIEWER))])
def list_anomalies(
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    only_anomalies: bool = True,
) -> dict:
    q = db.query(TrafficEvent)
    if only_anomalies:
        q = q.filter(TrafficEvent.is_anomaly.is_(True))
    total = q.count()
    rows = q.order_by(TrafficEvent.ts.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [TrafficEventOut.model_validate(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
