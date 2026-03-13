"""Pydantic models for pipeline APIs (DB-backed)."""

from pydantic import BaseModel, Field, model_validator
from typing import Optional, Any, Union


# ── Generic envelope ─────────────────────────────────────────────────────────

class APIResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None


# ── 1  Bulk Upload ───────────────────────────────────────────────────────────

class BulkUploadData(BaseModel):
    batch_id: int
    total_rows: int
    created_candidates: int
    updated_candidates: int
    failed_rows: int
    applications_created: int
    status: str


# ── 2  Candidate Portal Registration ────────────────────────────────────────

class JobPreference(BaseModel):
    job_profile_id: int
    priority: int = Field(ge=1, le=3)
    response_json: Optional[dict] = None


class CandidateRegisterPayload(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    skills: Optional[list[str]] = None
    experience_years: Optional[float] = None
    location: Optional[str] = None
    id: Optional[str] = None
    source: str = "PORTAL"
    program: Optional[str] = None
    degree: Optional[str] = None
    college_name: Optional[str] = None
    graduation_year: Optional[int] = None
    cgpa: Optional[float] = None
    linkedin_url: Optional[str] = None
    github_or_portfolio_url: Optional[str] = None
    hackathon_preferences: Optional[dict] = None
    candidate_skills: Optional[dict] = None
    availability_and_interest: Optional[dict] = None
    job_preferences: Optional[list[JobPreference]] = None


class CandidateRegisterData(BaseModel):
    candidate_id: int
    applications_created: int


class AddApplicationsPayload(BaseModel):
    """Add job applications for an existing candidate (no manual DB changes). Creates rows in candidate_job_form_responses and candidate_job_app_profiles with status INSERTED."""
    candidate_id: int
    job_preferences: list[JobPreference]
    source: Optional[str] = "API"


class AddApplicationsData(BaseModel):
    candidate_id: int
    applications_created: int


# ── 3  Job Profile Creation ─────────────────────────────────────────────────

class JobProfilePayload(BaseModel):
    job_code: Optional[str] = None
    title: str
    department: str
    stream: str
    location: Optional[str] = None
    employment_type: Optional[str] = "FULL_TIME"
    experience_min: Optional[float] = 0
    experience_max: Optional[float] = None
    number_of_openings: Optional[int] = None
    status: Optional[str] = "OPEN"
    role_summary: Optional[str] = None
    description: Optional[str] = None
    key_responsibilities: Optional[list[str]] = []
    mandatory_skills: Optional[list[str]] = []
    good_to_have_skills: Optional[list[str]] = []
    soft_skills: Optional[list[str]] = []
    certifications_or_qualifications: Optional[list[str]] = []
    screening_cutoff: Optional[float] = None
    test_cutoff: Optional[float] = None
    cc_emails: Optional[list[str]] = []


class TestDefinitionPayload(BaseModel):
    test_name: Optional[str] = None
    description: Optional[str] = None
    duration_minutes: Optional[int] = None
    total_questions: Optional[int] = None
    total_marks: Optional[int] = None
    pass_percentage: Optional[int] = None
    questions_json: Optional[list[dict]] = []


class JobProfileCreateRequest(BaseModel):
    job_profile: JobProfilePayload
    test_by_llm: Optional[Union[str, bool]] = "false"  # "true"/"false" or true/false; maps to test_flag_llm in DB
    test_definition: Optional[TestDefinitionPayload] = None
    company: Optional[str] = "Centific"


class JobProfileCreateData(BaseModel):
    job_profile_id: int
    title: str
    test_by_llm: bool


# ── 4  Composite Score + Notify ──────────────────────────────────────────────

class ScoreAndNotifyRequest(BaseModel):
    application_ids: Optional[list[int]] = None
    batch_id: Optional[int] = None
    run_mode: Optional[str] = "BATCH"
    send_email: Optional[bool] = True
    triggered_by: Optional[int] = None


class ScoreAndNotifyData(BaseModel):
    processed: int
    shortlisted: int
    rejected: int


# ── 4b  Onboarding Score and Evaluate (active candidates, best-preference) ───

class ScoreAndEvaluateRequest(BaseModel):
    """Trigger onboarding score-and-evaluate. Processes INSERTED applications only.
    Optional: restrict to specific candidate_ids. Used by scheduler or manual/Azure Function trigger."""
    send_email: Optional[bool] = True
    candidate_ids: Optional[list[int]] = None


class ScoreAndEvaluateData(BaseModel):
    processed: int
    shortlisted: int
    rejected: int
    candidates_processed: int


# ── 5  Test Generate ────────────────────────────────────────────────────────

class TestGenerateRequest(BaseModel):
    """Provide either candidate_job_app_id or email (candidate email) to identify the application.
    Whether to reuse an existing test or create a new one is read from job profile (additional_metadata_json.reuse_existing_test)."""
    candidate_job_app_id: Optional[int] = None
    email: Optional[str] = None
    generated_by: Optional[int] = None

    @model_validator(mode="after")
    def require_app_id_or_email(self):
        if self.candidate_job_app_id is None and not (self.email and str(self.email).strip()):
            raise ValueError("Provide either candidate_job_app_id or email")
        return self


class TestGenerateData(BaseModel):
    test_id: int
    candidate_job_app_id: int
    question_count: int
    mode: str
    questions: Optional[list[dict]] = None  # list of {question_id, question_type, question_text, options?, correct_answer?, marks}


# ── 6  Test Evaluate ────────────────────────────────────────────────────────

class AnswerItem(BaseModel):
    question_id: str
    answer: str


class TestEvaluateRequest(BaseModel):
    test_id: int
    answers_json: list[AnswerItem]
    submitted_by: Optional[str] = "candidate"


class TestEvaluateData(BaseModel):
    test_id: int
    score: float
    result: str
    application_status: str
    audit_report_id: Optional[int] = None
