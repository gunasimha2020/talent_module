import logging
import time
from fastapi import APIRouter, HTTPException
from typing import Optional
from app.logging_config import get_request_id
from app.schemas import APIResponse, JobProfileCreateRequest, JobProfileCreateData
from app.services.job_pipeline import create_job_profile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/employer", tags=["Employer"])


@router.post("/create-job", response_model=APIResponse)
def create_job_and_match(payload: JobProfileCreateRequest):
    """
    Create a job profile (DB-backed). Optional test definition and predefined questions.
    """
    request_id = get_request_id() or "-"
    start_ns = time.perf_counter_ns()
    title = payload.job_profile.title if payload.job_profile else ""
    department = getattr(payload.job_profile, "department", "") if payload.job_profile else ""
    stream = getattr(payload.job_profile, "stream", "") if payload.job_profile else ""
    logger.info(
        "Create job started | request_id=%s title=%s department=%s stream=%s test_by_llm=%s",
        request_id, title, department, stream, payload.test_by_llm,
    )
    try:
        result = create_job_profile(payload.model_dump())
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.info(
            "Create job completed | request_id=%s job_profile_id=%s title=%s test_by_llm=%s duration_ms=%.2f",
            request_id, result["job_profile_id"], result["title"], result["test_by_llm"], duration_ms,
        )
    except Exception as exc:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.exception("Create job failed | request_id=%s title=%s error=%s duration_ms=%.2f", request_id, title, str(exc), duration_ms)
        raise HTTPException(status_code=500, detail=str(exc))
    return APIResponse(success=True, message="Job profile created successfully", data=JobProfileCreateData(**result).model_dump())
