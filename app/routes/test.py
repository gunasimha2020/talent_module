import logging
import time
from fastapi import APIRouter, HTTPException
from app.logging_config import get_request_id
from app.schemas import (
    APIResponse,
    TestGenerateRequest,
    TestGenerateData,
    TestEvaluateRequest,
    TestEvaluateData,
)
from app.services.test_pipeline import generate_test, evaluate_test

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tests", tags=["Tests"])


@router.post("/generate", response_model=APIResponse)
def generate_test_endpoint(req: TestGenerateRequest):
    """
    Generate a test for a candidate application. Accept either candidate_job_app_id or email.
    If test_flag_llm=N on job profile: uses questions from job profile, formatted via LLM to standard shape.
    If test_flag_llm=Y: LLM generates mixed questionnaire (B.Tech, job + candidate details).
    Returns test_id, mode, question_count, and questions array.
    """
    request_id = get_request_id() or "-"
    start_ns = time.perf_counter_ns()
    logger.info(
        "Test generate started | request_id=%s candidate_job_app_id=%s email=%s",
        request_id, req.candidate_job_app_id, getattr(req, "email", None),
    )
    try:
        result = generate_test(
            candidate_job_app_id=req.candidate_job_app_id,
            email=req.email,
            generated_by=req.generated_by,
        )
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.info(
            "Test generate completed | request_id=%s test_id=%s mode=%s question_count=%s duration_ms=%.2f",
            request_id, result["test_id"], result["mode"], result["question_count"], duration_ms,
        )
    except ValueError as exc:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        msg = str(exc)
        if "Provide either" in msg:
            raise HTTPException(status_code=400, detail=msg)
        logger.warning("Test generate not found | request_id=%s detail=%s duration_ms=%.2f", request_id, msg, duration_ms)
        raise HTTPException(status_code=404, detail=msg)
    except Exception as exc:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.exception("Test generation failed | request_id=%s error=%s duration_ms=%.2f", request_id, str(exc), duration_ms)
        raise HTTPException(status_code=500, detail=str(exc))
    return APIResponse(success=True, message="Test generated successfully", data=TestGenerateData(**result).model_dump())


@router.post("/submit", response_model=APIResponse)
def submit_test_endpoint(req: TestEvaluateRequest):
    """
    Submit answers and evaluate test (DB-backed). Updates application status,
    creates audit report and email log.
    """
    request_id = get_request_id() or "-"
    start_ns = time.perf_counter_ns()
    submitted_by = req.submitted_by or "candidate"
    logger.info(
        "Test submit started | request_id=%s test_id=%s answers_count=%s submitted_by=%s",
        request_id, req.test_id, len(req.answers_json), submitted_by,
    )
    try:
        answers = [a.model_dump() for a in req.answers_json]
        result = evaluate_test(test_id=req.test_id, answers_json=answers, submitted_by=submitted_by)
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.info(
            "Test submit completed | request_id=%s test_id=%s score=%s result=%s application_status=%s audit_report_id=%s duration_ms=%.2f",
            request_id, result["test_id"], result["score"], result["result"], result["application_status"], result.get("audit_report_id"), duration_ms,
        )
    except ValueError as exc:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.warning("Test submit validation error | request_id=%s test_id=%s detail=%s duration_ms=%.2f", request_id, req.test_id, str(exc), duration_ms)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.exception("Test submit failed | request_id=%s test_id=%s error=%s duration_ms=%.2f", request_id, req.test_id, str(exc), duration_ms)
        raise HTTPException(status_code=500, detail=str(exc))
    return APIResponse(success=True, message="Test evaluated successfully", data=TestEvaluateData(**result).model_dump())
