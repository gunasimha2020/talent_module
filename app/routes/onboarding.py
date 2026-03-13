"""
Onboarding routes: bulk candidate upload, candidate registration, score-and-evaluate.
Enhanced with DB pipeline and structured logging.
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile, HTTPException

from app.logging_config import get_request_id
from app.schemas import (
    APIResponse,
    AddApplicationsData,
    AddApplicationsPayload,
    BulkUploadData,
    CandidateRegisterPayload,
    CandidateRegisterData,
    ScoreAndEvaluateRequest,
    ScoreAndEvaluateData,
)
from app.services.candidate_pipeline import add_applications_for_candidate, process_bulk_upload, register_candidate_portal
from app.services.job_pipeline import score_and_evaluate_onboarding

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


@router.post("/bulk-register", response_model=APIResponse)
async def bulk_register(
    file: UploadFile = File(..., description="Excel file (.xlsx)"),
    uploaded_by_user_id: Optional[int] = Form(None),
    default_source: str = Form("BULK_UPLOAD"),
    create_applications: bool = Form(True),
):
    """
    Bulk upload from Excel. When create_applications=true, writes to bulk_load and to
    candidates, form_responses, and applications (with source/batch_id from bulk).
    When create_applications=false, writes only to bulk_load (batch record only).
    """
    request_id = get_request_id() or "-"
    start_ns = time.perf_counter_ns()
    content_type = getattr(file, "content_type", None) or "-"
    logger.info(
        "Bulk register started | request_id=%s filename=%s content_type=%s uploaded_by=%s source=%s create_applications=%s",
        request_id, file.filename, content_type, uploaded_by_user_id, default_source, create_applications,
    )
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        logger.warning("Bulk register rejected | request_id=%s reason=unsupported_file_type filename=%s", request_id, file.filename)
        raise HTTPException(status_code=400, detail="Only .xlsx / .xls files are supported")

    raw_bytes = await file.read()
    read_ms = (time.perf_counter_ns() - start_ns) / 1e6
    logger.info("Bulk register file read | request_id=%s filename=%s bytes=%d read_ms=%.2f", request_id, file.filename, len(raw_bytes), read_ms)
    if not raw_bytes:
        logger.warning("Bulk register rejected | request_id=%s reason=empty_file filename=%s", request_id, file.filename)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        process_start_ns = time.perf_counter_ns()
        result = process_bulk_upload(
            file_bytes=raw_bytes,
            filename=file.filename,
            uploaded_by_user_id=uploaded_by_user_id,
            default_source=default_source,
            create_applications=create_applications,
        )
        process_ms = (time.perf_counter_ns() - process_start_ns) / 1e6
        total_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.info(
            "Bulk register completed | request_id=%s batch_id=%s total_rows=%s created=%s updated=%s failed=%s applications=%s status=%s process_ms=%.2f total_ms=%.2f",
            request_id, result.get("batch_id"), result.get("total_rows"), result.get("created_candidates"),
            result.get("updated_candidates"), result.get("failed_rows"), result.get("applications_created"),
            result.get("status"), process_ms, total_ms,
        )
    except Exception as exc:
        total_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.exception("Bulk register failed | request_id=%s filename=%s error=%s total_ms=%.2f", request_id, file.filename, str(exc), total_ms)
        raise HTTPException(status_code=500, detail=str(exc))

    return APIResponse(success=True, message="Bulk upload accepted and processed", data=BulkUploadData(**result).model_dump())


@router.post("/register", response_model=APIResponse)
def register_candidate(payload: CandidateRegisterPayload):
    """
    Candidate self-registers through the portal. Creates candidate,
    job form responses and application rows.
    """
    request_id = get_request_id() or "-"
    start_ns = time.perf_counter_ns()
    job_prefs = len(payload.job_preferences) if payload.job_preferences else 0
    logger.info(
        "Candidate register started | request_id=%s email=%s name=%s source=%s job_preferences_count=%s",
        request_id, payload.email, payload.name, payload.source, job_prefs,
    )
    try:
        result = register_candidate_portal(payload.model_dump())
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.info(
            "Candidate register completed | request_id=%s candidate_id=%s applications_created=%s duration_ms=%.2f",
            request_id, result["candidate_id"], result["applications_created"], duration_ms,
        )
    except Exception as exc:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.exception("Candidate registration failed | request_id=%s email=%s error=%s duration_ms=%.2f", request_id, payload.email, str(exc), duration_ms)
        raise HTTPException(status_code=500, detail=str(exc))

    return APIResponse(success=True, message="Candidate registered successfully", data=CandidateRegisterData(**result).model_dump())


@router.post("/add-applications", response_model=APIResponse)
def add_applications(payload: AddApplicationsPayload):
    """
    Add job applications for an existing candidate (API-only, no manual DB).
    Creates rows in candidate_job_form_responses and candidate_job_app_profiles
    with status INSERTED so that POST /onboarding/score-and-evaluate can process them.
    Call this when the candidate already exists (e.g. in candidates table) but has
    no applications yet.
    """
    request_id = get_request_id() or "-"
    start_ns = time.perf_counter_ns()
    logger.info(
        "Add applications started | request_id=%s candidate_id=%s job_preferences_count=%s",
        request_id, payload.candidate_id, len(payload.job_preferences or []),
    )
    try:
        result = add_applications_for_candidate(
            candidate_id=payload.candidate_id,
            job_preferences=[p.model_dump() for p in (payload.job_preferences or [])],
            source=payload.source or "API",
        )
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.info(
            "Add applications completed | request_id=%s candidate_id=%s applications_created=%s duration_ms=%.2f",
            request_id, result["candidate_id"], result["applications_created"], duration_ms,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.exception("Add applications failed | request_id=%s error=%s duration_ms=%.2f", request_id, str(exc), duration_ms)
        raise HTTPException(status_code=500, detail=str(exc))
    return APIResponse(
        success=True,
        message="Applications added; you can now call POST /onboarding/score-and-evaluate for this candidate.",
        data=AddApplicationsData(**result).model_dump(),
    )


@router.post("/score-and-evaluate", response_model=APIResponse)
def score_and_evaluate(req: ScoreAndEvaluateRequest):
    """
    Score and evaluate onboarding candidates (active = applications in INSERTED state).
    For each candidate, composite score is computed per preference (job application);
    the best-preference (highest score) is chosen. If best score >= job cutoff (e.g. 50%):
    that application is shortlisted and a test-invite email is sent; others are rejected.
    If best score < cutoff: all applications for that candidate are rejected.
    Call this endpoint manually or from an Azure Function (timer or HTTP trigger).
    """
    request_id = get_request_id() or "-"
    start_ns = time.perf_counter_ns()
    logger.info(
        "Score and evaluate started | request_id=%s send_email=%s candidate_ids=%s",
        request_id, req.send_email, req.candidate_ids,
    )
    try:
        result = score_and_evaluate_onboarding(
            send_email=req.send_email or False,
            candidate_ids=req.candidate_ids,
        )
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.info(
            "Score and evaluate completed | request_id=%s processed=%s shortlisted=%s rejected=%s candidates=%s duration_ms=%.2f",
            request_id, result["processed"], result["shortlisted"], result["rejected"],
            result.get("candidates_processed", 0), duration_ms,
        )
    except Exception as exc:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1e6
        logger.exception(
            "Score and evaluate failed | request_id=%s error=%s duration_ms=%.2f",
            request_id, str(exc), duration_ms,
        )
        raise HTTPException(status_code=500, detail=str(exc))
    return APIResponse(
        success=True,
        message="Score and evaluate completed",
        data=ScoreAndEvaluateData(**result).model_dump(),
    )
