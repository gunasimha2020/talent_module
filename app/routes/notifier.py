import logging
import time
from fastapi import APIRouter, HTTPException
from app.logging_config import get_request_id
from app.schemas import APIResponse, ScoreAndNotifyRequest, ScoreAndNotifyData
from app.services.job_pipeline import score_and_notify

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifier", tags=["Notifier"])


@router.post("/score-and-notify", response_model=APIResponse)
def score_and_notify_endpoint(req: ScoreAndNotifyRequest):
    """
    Evaluate candidate applications, compute composite scores,
    update statuses and create email log entries (DB-backed).
    """
    request_id = get_request_id() or "-"
    start_ns = time.perf_counter_ns()
    logger.info(
        "Score and notify started | request_id=%s application_ids=%s batch_id=%s send_email=%s triggered_by=%s",
        request_id, req.application_ids, req.batch_id, req.send_email, req.triggered_by,
    )
    try:
        result = score_and_notify(
            application_ids=req.application_ids,
            batch_id=req.batch_id,
            send_email=req.send_email or False,
            triggered_by=req.triggered_by,
        )
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.info(
            "Score and notify completed | request_id=%s processed=%s shortlisted=%s rejected=%s duration_ms=%.2f",
            request_id, result["processed"], result["shortlisted"], result["rejected"], duration_ms,
        )
    except Exception as exc:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.exception("Score and notify failed | request_id=%s error=%s duration_ms=%.2f", request_id, str(exc), duration_ms)
        raise HTTPException(status_code=500, detail=str(exc))
    return APIResponse(success=True, message="Scoring completed", data=ScoreAndNotifyData(**result).model_dump())
