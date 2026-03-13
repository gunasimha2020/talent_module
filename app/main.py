import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_pool, close_pool, get_db_verify
from app.logging_config import setup_logging, set_request_id, get_request_id

from app.routes import onboarding, employer, test, notifier
from app.services.job_pipeline import score_and_evaluate_onboarding

logger = logging.getLogger(__name__)


def _run_score_and_evaluate_onboarding() -> None:
    """Run onboarding score-and-evaluate (for scheduler or Azure Function)."""
    try:
        score_and_evaluate_onboarding(send_email=True, candidate_ids=None)
    except Exception as exc:
        logger.exception("Score-and-evaluate onboarding error: %s", exc)


async def _score_evaluate_loop(interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await asyncio.to_thread(_run_score_and_evaluate_onboarding)
        except Exception as exc:
            logger.error("Score-evaluate loop error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(
        level=settings.log_level,
        log_file=settings.log_file,
        log_file_level=settings.log_file_level,
        include_location=settings.log_include_location,
    )
    logger.info(
        "Application starting | log_level=%s | log_file=%s | log_include_location=%s",
        settings.log_level, settings.log_file or "none", settings.log_include_location,
    )

    try:
        init_pool(settings)
        logger.info("Database pool initialised")
    except Exception as exc:
        logger.error("DB pool init failed (DB-backed endpoints will be unavailable): %s", exc, exc_info=True)

    score_eval_interval = getattr(settings, "score_evaluate_interval_seconds", 0) or 0
    score_eval_task = None
    if score_eval_interval > 0:
        score_eval_task = asyncio.create_task(_score_evaluate_loop(score_eval_interval))
        logger.info("Background score-and-evaluate task started (interval=%ss)", score_eval_interval)

    yield

    if score_eval_task:
        score_eval_task.cancel()
        try:
            await score_eval_task
        except asyncio.CancelledError:
            pass
    close_pool()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="Talent & Job Module – Aegis Archive",
    description=(
        "Backend module for candidate hiring pipeline: "
        "bulk upload, registration, job profiles, scoring, "
        "test generation and evaluation. DB-backed (PostgreSQL/Azure)."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Assign request_id and log every request with method, path, client, status, duration."""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    set_request_id(request_id)
    client = request.client.host if request.client else "-"
    path = request.url.path
    query = request.url.query
    path_and_query = f"{path}?{query}" if query else path
    start = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Request completed | request_id=%s method=%s path=%s client=%s status=%s duration_ms=%.2f",
            request_id, request.method, path_and_query, client, response.status_code, duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.error(
            "Request failed | request_id=%s method=%s path=%s client=%s error=%s duration_ms=%.2f",
            request_id, request.method, path_and_query, client, str(exc), duration_ms,
            exc_info=True,
        )
        raise


# ── Routes (DB-backed pipeline) ──────────────────────────────────────────────
app.include_router(onboarding.router)
app.include_router(employer.router)
app.include_router(test.router)
app.include_router(notifier.router)


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


@app.get("/db-verify")
def db_verify():
    """Cross-verify DB connection: credentials (masked), schema, and job_module.job_profiles count/max id."""
    return get_db_verify(get_settings())
