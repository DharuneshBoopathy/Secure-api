import threading
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import get_cors_origins, get_settings, validate_security_settings
from app.database import Base, engine, ensure_phase1_schema, wait_for_database
from app.jobs.scheduler import register_jobs, run_bootstrap_training
from app.problem import generic_exception_handler, http_exception_handler
from app.routers import alerts, anomalies, audit, auth, demo_api, health, ingest, inventory, openapi_registry, shadow, traffic, zombie
from app.routers.auth import ensure_default_admin, limiter as auth_limiter
from app.routers.ingest import PCAP_MAX_BYTES

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_security_settings()
    wait_for_database()
    Base.metadata.create_all(bind=engine)
    ensure_phase1_schema()
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        ensure_default_admin(db)
    finally:
        db.close()
    sched = BackgroundScheduler()
    register_jobs(sched)
    sched.start()
    app.state.scheduler = sched
    threading.Thread(target=run_bootstrap_training, daemon=True).start()
    yield
    sched.shutdown(wait=False)


app = FastAPI(
    title="API Security Monitor",
    description=(
        "Runtime API discovery, shadow API detection, idle-route monitoring, and "
        "scikit-learn anomaly scoring — similar in spirit to Levo.ai-style continuous "
        "governance (inventory + drift + high-signal alerts)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Monitor-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-RateLimit-Remaining", "Retry-After"],
)
app.state.limiter = auth_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)


_BODY_SIZE_LIMIT = 10 * 1024 * 1024  # 10 MB — /api/ingest/pcap has its own 50 MB check


@app.middleware("http")
async def body_size_limit_middleware(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if request.url.path.startswith("/api/ingest/pcap"):
        # PCAP gets a higher cap, but still enforce one up-front when the
        # client sends Content-Length so oversized bodies are rejected
        # before any data is read.
        if content_length:
            try:
                if int(content_length) > PCAP_MAX_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"error": "PCAP too large (max 50 MB)."},
                    )
            except ValueError:
                pass
    elif content_length:
        try:
            if int(content_length) > _BODY_SIZE_LIMIT:
                return JSONResponse(
                    status_code=413,
                    content={"error": "Request body too large. Maximum allowed size is 10 MB."},
                )
        except ValueError:
            pass
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if "server" in response.headers:
        del response.headers["server"]
    return response

app.include_router(health.router)

api = APIRouter(prefix="/api")
api.include_router(auth.router)
if get_settings().enable_demo:
    api.include_router(demo_api.router)
api.include_router(ingest.router)
api.include_router(openapi_registry.router)
api.include_router(inventory.router)
api.include_router(alerts.router)
api.include_router(audit.router)
api.include_router(shadow.router)
api.include_router(zombie.router)
api.include_router(anomalies.router)
api.include_router(traffic.router)
app.include_router(api)


def _spa_index():
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse(
        {
            "service": "api-security-monitor",
            "docs": "/docs",
            "health": "/health",
            "metrics": "/metrics",
            "api": "/api",
            "ui": "Build the frontend (npm run build in frontend/) or run Vite on :5173.",
        }
    )


@app.get("/", include_in_schema=False)
def root():
    return _spa_index()


_assets = FRONTEND_DIST / "assets"
if _assets.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    """
    Serve built Vite files or index.html for client-side routes (/alerts, /shadow, …).
    /api/*, /docs, /health, etc. are handled by routes registered before this one.
    """
    head = full_path.split("/", 1)[0]
    if head in ("api", "assets"):
        raise HTTPException(status_code=404, detail="Not found")

    safe_root = FRONTEND_DIST.resolve()
    candidate = (FRONTEND_DIST / full_path).resolve()
    try:
        candidate.relative_to(safe_root)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found") from None
    if candidate.is_file():
        return FileResponse(candidate)

    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Not found")
