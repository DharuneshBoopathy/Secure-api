import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import require_role
from app.models import TrafficEvent
from app.routers.auth import limiter
from app.security import Role, utc_now

router = APIRouter(prefix="/traffic", tags=["traffic"])


@router.get("/stream")
@limiter.limit("30/minute")
def stream_traffic(
    request: Request,
    db: Session = Depends(get_db),
    auth: str | None = Query(default=None),
    _user=Depends(require_role(Role.VIEWER)),
):
    settings = get_settings()
    if auth and not auth.startswith("Bearer ") and auth != settings.monitor_api_key:
        raise HTTPException(status_code=401, detail="Invalid stream auth token")

    async def event_stream():
        last_seen_id = 0
        while True:
            # Run the blocking SQLAlchemy query in a thread-pool worker so that
            # the async event loop is never stalled while waiting for the DB.
            rows = await run_in_threadpool(
                lambda lid=last_seen_id: db.query(TrafficEvent)
                .filter(TrafficEvent.id > lid)
                .order_by(TrafficEvent.id.asc())
                .limit(25)
                .all()
            )
            for row in rows:
                last_seen_id = row.id
                payload = {
                    "id": row.id,
                    "ts": row.ts.isoformat(),
                    "method": row.method,
                    "path": row.path,
                    "status_code": row.status_code,
                    "response_time_ms": row.response_time_ms,
                    "source_ip": row.source_ip,
                    "is_anomaly": row.is_anomaly,
                    "anomaly_score": row.anomaly_score,
                }
                yield f"data: {json.dumps(payload)}\n\n"
            if not rows:
                yield f"event: heartbeat\ndata: {utc_now().isoformat()}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
