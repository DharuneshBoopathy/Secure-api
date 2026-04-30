import json
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.routers.auth import limiter
from app.schemas import IngestBatch, NginxAccessLog
from app.security import Role
from app.services.discovery_service import get_known_templates
from app.services.ml_anomaly import load_model
from app.services.pcap_ingest import iter_http_requests_from_pcap
from app.services.traffic_processor import process_single_event, refresh_gauges

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])

PCAP_MAX_BYTES = 50 * 1024 * 1024
_PCAP_CHUNK = 1024 * 1024


def _apply_nginx_log(db: Session, log: NginxAccessLog) -> None:
    model = load_model(db)
    auth_present = bool(log.auth and log.auth.strip() and log.auth.strip().lower() != "null")
    process_single_event(
        db,
        method=log.method,
        path=log.uri,
        status_code=log.status,
        latency_ms=(log.request_time or 0) * 1000.0,
        client_ip=log.remote_addr,
        user_agent=log.user_agent,
        auth_present=auth_present,
        body_bytes=log.body_bytes_sent or 0,
        request_size_bytes=0,
        response_size_bytes=log.body_bytes_sent or 0,
        content_type=None,
        x_forwarded_for=None,
        referer=None,
        monitor_key=None,
        session_id=None,
        gateway=log.gateway or "nginx",
        raw_ref=log.ts,
        model=model,
    )


@router.post("/nginx-json", dependencies=[Depends(require_role(Role.EDITOR))])
@limiter.limit("500/minute")
def ingest_nginx_json(request: Request, log: NginxAccessLog, db: Session = Depends(get_db)):
    """JSON object as produced by nginx `log_format apimonitor_json`."""
    # Gauge refresh is handled by the 2-min scheduler job; avoid hammering
    # inventory tables at the 500/min ingest rate.
    _apply_nginx_log(db, log)
    return {"status": "ok"}


@router.post("/nginx-json-raw", dependencies=[Depends(require_role(Role.EDITOR))])
@limiter.limit("500/minute")
async def ingest_nginx_raw_line(request: Request, db: Session = Depends(get_db)):
    raw = (await request.body()).decode("utf-8", errors="replace").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty body")
    try:
        data = json.loads(raw)
        log = NginxAccessLog.model_validate(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid log line: {e}") from e
    _apply_nginx_log(db, log)
    return {"status": "ok"}


@router.post("/batch", dependencies=[Depends(require_role(Role.EDITOR))])
@limiter.limit("500/minute")
def ingest_batch(request: Request, batch: IngestBatch, db: Session = Depends(get_db)):
    model = load_model(db)
    templates = get_known_templates(db)
    ingested = 0
    skipped = 0
    for ev in batch.events:
        ap = ev.auth_present if ev.auth_present is not None else False
        # Each event runs inside its own SAVEPOINT so that a single bad row
        # (IntegrityError, constraint violation, etc.) does not poison the
        # rest of the batch.  The outer transaction is still committed once.
        try:
            with db.begin_nested():
                process_single_event(
                    db,
                    method=ev.method,
                    path=ev.path,
                    status_code=ev.status_code,
                    latency_ms=ev.latency_ms,
                    client_ip=ev.client_ip,
                    user_agent=ev.user_agent,
                    auth_present=ap,
                    body_bytes=ev.body_bytes,
                    request_size_bytes=ev.request_size_bytes,
                    response_size_bytes=ev.response_size_bytes,
                    content_type=ev.content_type,
                    x_forwarded_for=ev.x_forwarded_for,
                    referer=ev.referer,
                    monitor_key=ev.monitor_key,
                    session_id=ev.session_id,
                    gateway=ev.gateway,
                    raw_ref=ev.raw_ref,
                    model=model,
                    commit=False,  # defer commit for batch performance
                    templates=templates,
                )
            ingested += 1
        except SQLAlchemyError:
            log.exception(
                "skipping bad event method=%s path=%s", ev.method, ev.path[:120]
            )
            skipped += 1
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Batch commit failed")
    refresh_gauges(db)
    return {"ingested": ingested, "skipped": skipped}


@router.post("/pcap", dependencies=[Depends(require_role(Role.EDITOR))])
@limiter.limit("120/minute")
async def ingest_pcap(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload a `.pcap` from Wireshark or `tshark`. Cleartext HTTP only; HTTPS requires
    gateway logs (nginx) or TLS termination visibility.
    """
    # Stream the upload and enforce the cap during read so an attacker cannot
    # buffer an arbitrarily large body into memory before the size check fires.
    buf = bytearray()
    while True:
        chunk = await file.read(_PCAP_CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > PCAP_MAX_BYTES:
            raise HTTPException(status_code=413, detail="PCAP too large (max 50MB)")
    data = bytes(buf)
    model = load_model(db)
    templates = get_known_templates(db)
    parsed = 0
    skipped = 0
    for method, path in iter_http_requests_from_pcap(data):
        try:
            with db.begin_nested():
                process_single_event(
                    db,
                    method=method,
                    path=path,
                    status_code=0,
                    latency_ms=0.0,
                    client_ip=None,
                    user_agent="pcap",
                    auth_present=False,
                    body_bytes=0,
                    request_size_bytes=0,
                    response_size_bytes=0,
                    content_type=None,
                    x_forwarded_for=None,
                    referer=None,
                    monitor_key=None,
                    session_id=None,
                    gateway="pcap",
                    raw_ref=file.filename,
                    model=model,
                    commit=False,  # defer commit for batch performance
                    templates=templates,
                )
            parsed += 1
        except SQLAlchemyError:
            log.exception("skipping bad pcap event %s %s", method, path[:120])
            skipped += 1
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="PCAP commit failed")
    refresh_gauges(db)
    return {"parsed_http_requests": parsed, "skipped": skipped, "filename": file.filename}
