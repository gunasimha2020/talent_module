# Swagger UI Test Guide – Aegis Archive Pipeline APIs

Use this guide to test the **pipeline APIs** (DB-backed) from **Swagger UI** at:

**http://localhost:8000/docs**

Enhanced routes live under existing paths: `/onboarding`, `/employer`, `/tests`, `/notifier`. All enhanced endpoints log `request_id` and `duration_ms`. Run steps in order when testing the full flow.

---

## Prerequisites

1. Server running: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
2. Open **http://localhost:8000/docs** in your browser.
3. Optional: set **LOG_LEVEL=DEBUG** in `.env` for more detailed logs.

---

## Step 1: Health Check

- **Endpoint:** `GET /health`
- **Section:** Default (no tag)
- **Action:** Click **Try it out** → **Execute**
- **Expected response (200):**
```json
{
  "status": "ok",
  "version": "2.0.0"
}
```

---

## Step 2: Create Job Profile

Create a job profile first (needed for candidates and tests).

- **Endpoint:** `POST /employer/create-job`
- **Section:** **Employer**
- **Action:** Click **Try it out**
- **Request body:** Use the following (or edit in the JSON box):

```json
{
  "job_profile": {
    "job_code": "JP-CV-001",
    "title": "Computer Vision Engineer",
    "department": "AI Engineering",
    "stream": "Computer Vision",
    "location": "Hyderabad",
    "employment_type": "FULL_TIME",
    "experience_min": 1,
    "experience_max": 5,
    "number_of_openings": 3,
    "status": "OPEN",
    "role_summary": "Build CV solutions",
    "description": "Work on object detection, segmentation, and real-time video analytics using OpenCV, YOLO, PyTorch.",
    "key_responsibilities": ["Build CV pipelines", "Deploy ML models"],
    "mandatory_skills": ["Python", "OpenCV", "PyTorch", "YOLO"],
    "good_to_have_skills": ["TensorFlow", "Docker"],
    "soft_skills": ["Communication"],
    "certifications_or_qualifications": ["B.Tech CS or equivalent"],
    "screening_cutoff": 40,
    "test_cutoff": 60,
    "cc_emails": ["admin@example.com"]
  },
  "test_by_llm": "false",
  "test_definition": {
    "test_name": "CV Assessment",
    "description": "Technical test for CV role",
    "duration_minutes": 60,
    "total_questions": 5,
    "total_marks": 20,
    "pass_percentage": 60,
    "questions_json": [
      {
        "question_id": "Q1",
        "question_type": "MCQ",
        "question_text": "Which is used for real-time object detection?",
        "options": ["Pandas", "YOLO", "NumPy", "Matplotlib"],
        "correct_answer": "YOLO",
        "marks": 2
      },
      {
        "question_id": "Q2",
        "question_type": "MCQ",
        "question_text": "CNN stands for?",
        "options": ["Convolutional Neural Network", "Connected Node Network", "Cascading Neural Network", "Central Network Node"],
        "correct_answer": "Convolutional Neural Network",
        "marks": 2
      },
      {
        "question_id": "Q3",
        "question_type": "SUBJECTIVE",
        "question_text": "Explain YOLO vs R-CNN trade-offs.",
        "marks": 4
      },
      {
        "question_id": "Q4",
        "question_type": "SUBJECTIVE",
        "question_text": "Design a CV pipeline for drone navigation.",
        "marks": 4
      },
      {
        "question_id": "Q5",
        "question_type": "MCQ",
        "question_text": "Most common activation in hidden layers?",
        "options": ["Sigmoid", "ReLU", "Tanh", "Softmax"],
        "correct_answer": "ReLU",
        "marks": 2
      }
    ]
  },
  "company": "Centific"
}
```

- **Execute** → **Expected (200):**
```json
{
  "success": true,
  "message": "Job profile created successfully",
  "data": {
    "job_profile_id": 1,
    "title": "Computer Vision Engineer",
    "test_by_llm": false
  }
}
```
- **Note the `job_profile_id`** (e.g. `1`) for the next steps.

---

## Step 3: Candidate Portal Registration

- **Endpoint:** `POST /onboarding/register`
- **Section:** **Onboarding**
- **Action:** Click **Try it out**
- **Request body:** Replace `job_profile_id` with the ID from Step 2 (e.g. `1`):

```json
{
  "name": "Pradeep Kumar",
  "email": "pradeep.swagger@example.com",
  "phone": "9940462219",
  "skills": ["Python", "OpenCV", "YOLO", "Cloud Computing"],
  "experience_years": 2.0,
  "source": "PORTAL",
  "degree": "B Tech / B.E.",
  "college_name": "JNTU Hyderabad",
  "graduation_year": 2024,
  "cgpa": 8.0,
  "linkedin_url": "https://linkedin.com/in/pradeep",
  "github_or_portfolio_url": null,
  "candidate_skills": {
    "programming_languages": ["Python"],
    "ai_interest_areas": ["OpenCV", "YOLO"],
    "tools_frameworks": ["Cloud Computing", "Docker"]
  },
  "availability_and_interest": {
    "available_full_2_weeks_hyderabad": true
  },
  "job_preferences": [
    {
      "job_profile_id": 1,
      "priority": 1,
      "response_json": {
        "project_summary": "Worked on object detection using YOLO",
        "relevant_experience": 2
      }
    }
  ]
}
```

- **Execute** → **Expected (200):**
```json
{
  "success": true,
  "message": "Candidate registered successfully",
  "data": {
    "candidate_id": 1,
    "applications_created": 1
  }
}
```
- **Note `candidate_id`** if you need it; application IDs can be read from DB or from the score step.

---

## Step 3b: Add applications for an existing candidate (API-only, no manual DB)

Use this when a **candidate already exists** (e.g. in `candidates` table) but has **no applications** yet. This creates application rows with status **INSERTED** so that **POST /onboarding/score-and-evaluate** can process them. No manual database changes needed.

- **Endpoint:** `POST /onboarding/add-applications`
- **Section:** **Onboarding**
- **Request body:** (use the `job_profile_id` from Step 2)
```json
{
  "candidate_id": 6,
  "job_preferences": [
    { "job_profile_id": 1, "priority": 1, "response_json": { "project_summary": "Relevant experience.", "relevant_experience": 2 } }
  ],
  "source": "API"
}
```
  - Add up to 3 preferences (priority 1, 2, 3) with different `job_profile_id` if needed. `response_json` is optional (used by LLM scoring).
- **Execute** → **Expected (200):**
```json
{
  "success": true,
  "message": "Applications added; you can now call POST /onboarding/score-and-evaluate for this candidate.",
  "data": { "candidate_id": 6, "applications_created": 1 }
}
```
- Then call **POST /onboarding/score-and-evaluate** with `"candidate_ids": [6]` to score this candidate.
- **Tables updated:** See **Tables updated by endpoint** below.

---

## Step 4: Bulk Candidate Upload (optional)

- **Endpoint:** `POST /onboarding/bulk-register`
- **Section:** **Onboarding**
- **Behaviour:** The Excel file is parsed, then the **language model (LLM)** normalizes and cleans the data (fixes typos, emails, phones, trim spaces, etc.). The consolidated response is used to create/update candidates in bulk. Uses **gpt-4o-mini** (see code). Requires **OPENAI_API_KEY** in `.env`; if not set, raw parsed rows are used.
- **Sample format:** Tested with the Centific AI Premier Hackathon Participant Registration Form Excel export (columns: Id, Email, Name, Candidate Name, Degree, College Name, Graduation Year, Current CGPA (Out of 10), Candidate Email Address, LinkedIn Profile URL, GitHub/Portfolio Link, Phone Number, first/second/third priority stream and role, etc.). Duplicate form columns (e.g. multiple “first priority” questions) are merged so the first non-empty value is kept; “Candidate Email Address” is used over “Email” when both exist.
- **Action:** Click **Try it out**
- **Parameters:**
  - **file:** Click **Choose File** and select an Excel file (`.xlsx`) matching the hackathon form or with columns: Candidate Name, Candidate Email Address, Phone Number, Degree, College Name, Graduation Year, Current CGPA (Out of 10), LinkedIn, GitHub/Portfolio, priority streams/roles, etc.
  - **uploaded_by_user_id:** leave empty (or set to a valid user id if your DB has an `users` table and FK)
  - **default_source:** `BULK_UPLOAD`
  - **create_applications:** **true** = write to bulk_load and to candidates + form_responses + applications (full load; rows are tagged with source/batch_id). **false** = write only to the **bulk_load** table (batch record only; no candidate or application rows).
- **Logging (in-detail):** For each request the server logs:
  - **Route:** `request_id`, `filename`, `content_type`, `bytes`, file read time, process time, total time.
  - **Service phases:** `phase=parse` (row count, sample headers), `phase=llm` (normalized_rows, llm_ms), `phase=batch_create` (batch_id), `phase=rows progress` every 10 rows, `phase=finalise` (status, counts, raw_rows, normalized_rows). If LLM is unavailable, raw parsed rows are used and a warning is logged.
- **Execute** → **Expected (200):**
  - With **create_applications=true:** `status` is `COMPLETED` or `PARTIAL_FAILED`; `created_candidates`, `updated_candidates`, `applications_created` are populated; rows exist in bulk_load and in candidates (and related tables).
  - With **create_applications=false:** only **bulk_load** is written; `status` is `RECORDED`; `created_candidates`, `updated_candidates`, `failed_rows`, `applications_created` are 0.   
```json
{
  "success": true,
  "message": "Bulk upload accepted and processed",
  "data": {
    "batch_id": 1,
    "total_rows": 10,
    "created_candidates": 8,
    "updated_candidates": 2,
    "failed_rows": 0,
    "applications_created": 20,
    "status": "COMPLETED"
  }
}
```
 (With create_applications=false the same structure applies but status=RECORDED and counts are 0.)

---

## Step 4b: Onboarding Score and Evaluate (optional – active candidates, best-preference)

Use this to score **all INSERTED applications** (or a subset by `candidate_ids`), pick the **best preference** per candidate (highest composite score among up to 3), and shortlist or reject using the job’s cutoff (e.g. 50%). Can be triggered **manually** here or by an **Azure Function** (timer or HTTP). See **docs/ONBOARDING_SCORE_AND_EVALUATE.md** for composite score formula, tables, and Azure Function setup.

**Important:** Only **applications** (rows in `candidate_job_app_profiles`) with **status = 'INSERTED'** are processed. If you pass `candidate_ids` but get `processed=0`, that candidate has no application in INSERTED state. **No manual DB changes:** create applications by (1) registering with job preferences (`POST /onboarding/register`), (2) bulk upload with `create_applications=true`, or (3) **POST /onboarding/add-applications** for that candidate (Step 3b).

- **Endpoint:** `POST /onboarding/score-and-evaluate`
- **Section:** **Onboarding**
- **Request body:**
```json
{
  "send_email": false,
  "candidate_ids": null
}
```
  - Leave `candidate_ids` null to process all INSERTED applications; or pass `[1, 2, 3]` to restrict to those candidates.
- **Execute** → **Expected (200):** `data.processed`, `data.shortlisted`, `data.rejected`, `data.candidates_processed`.
- **In-app scheduler:** Set `SCORE_EVALUATE_INTERVAL_SECONDS=300` in `.env` to run this automatically every 5 minutes when the app is running.
- **Tables updated:** See **Tables updated by endpoint** below.

---

## Step 5: Score and Notify

You need at least one application in status `INSERTED`. If you only did Step 3, that application has ID from the first (and often only) row in `candidate_job_app_profiles`; use that ID. If unsure, use `batch_id` from a bulk upload or leave both empty to process **all** INSERTED applications.

- **Endpoint:** `POST /notifier/score-and-notify`
- **Section:** **Notifier**
- **Action:** Click **Try it out**
- **Request body (by application IDs):**
```json
{
  "application_ids": [1],
  "run_mode": "BATCH",
  "send_email": false,
  "triggered_by": 1
}
```
  - Or by batch: `"batch_id": 1` and omit `application_ids`.
  - Set `send_email`: `true` to send real emails (SMTP must be configured).
- **Execute** → **Expected (200):**
```json
{
  "success": true,
  "message": "Scoring completed",
  "data": {
    "processed": 1,
    "shortlisted": 1,
    "rejected": 0
  }
}
```
- **Tables updated:** See **Tables updated by endpoint** below.

---

## Step 6: Generate Test

Use either a **shortlisted** application ID (e.g. from Step 5) or the candidate **email** (portal or bulk-upload). If email is used, the first INSERTED/SHORTLISTED application for that candidate is used.

- **Endpoint:** `POST /tests/generate`
- **Section:** **Tests**
- **Behaviour:**
  - **Reuse vs new test** is controlled by the job profile in the DB: **`additional_metadata_json.reuse_existing_test`**. If `true` (default), and an existing non-abandoned test exists for this application, that test is returned (`mode`: EXISTING). If `false` or no existing test, a new test is generated.
  - **test_flag_llm = N (false):** Questions are taken from the job profile (`questionnaire_set_json`), then sent to the LLM to return them in the standard format (MCQ: question_id, question_type, question_text, options, correct_answer, marks; SUBJECTIVE: same without options/correct_answer).
  - **test_flag_llm = Y (true):** Job profile (title, description, required_skills, min_exp) and candidate (skills, experience) are sent to the LLM to create a mixed questionnaire (MCQ + descriptive/one-word) for B.Tech recruitment.
- **Action:** Click **Try it out**
- **Request body (by application ID):**
```json
{
  "candidate_job_app_id": 1,
  "generated_by": 1
}
```
- **Or by candidate email:**
```json
{
  "email": "candidate@example.com"
}
```
- **Execute** → **Expected (200):** Response includes `test_id`, `candidate_job_app_id`, `question_count`, `mode` (PREDEFINED, LLM, or EXISTING), and **`questions`** (array of question objects with question_id, question_type, question_text, options, correct_answer, marks).
- **Note `test_id`** and use the returned **`questions`** for Step 7 (answer submission).
- **Tables updated:** See **Tables updated by endpoint** below.

---

## Step 7: Test Submit (Evaluate)

Use the `test_id` from Step 6. Match `question_id` values to the job profile’s `questions_json` (e.g. Q1–Q5). For MCQ use the exact `correct_answer`; for SUBJECTIVE provide any reasonable text.

- **Endpoint:** `POST /tests/submit`
- **Section:** **Tests**
- **Behaviour:**
  - The **questionnaire** (from the test’s `questions_json`) and the **candidate’s responses** (`answers_json`) are used in two ways:
    1. **Per-question scoring:** MCQ is scored by exact match to `correct_answer`; SUBJECTIVE is scored by LLM or keyword heuristic. This gives a rule-based percentage and a per-question breakdown.
    2. **LLM composite evaluation:** The full Q&A (plus job title/context) is sent to the LLM (**gpt-4o-mini**). The LLM returns a **composite score** (0–100), a **recommendation** (`SELECT` or `REJECT`), and a short **justification**. The **final result** (PASS/FAIL and SHORTLISTED/REJECTED) is driven by this recommendation. If the LLM call fails (e.g. no `OPENAI_API_KEY`), the rule-based cutoff is used: PASS if percentage ≥ job’s `test_cutoff`, else FAIL.
  - **Score in response:** `data.score` is the **LLM composite score** when available; otherwise the rule-based percentage.
  - **Tables updated:**  
    - **test_details_profiles:** `answers_json`, `test_score` (composite or rule-based %), `status = EVALUATED`, `test_report_json`, `consolidate_qa_json`, `submitted_at`.  
    - **candidate_job_app_profiles:** `status` (SHORTLISTED / REJECTED), `email_sent_flag = false`, `email_status = PENDING`.  
    - **audit_report:** one row with `report_json` = full evaluation report (including audit trail).  
    - **email_log:** one row for TEST_RESULT or REJECTION email (pending send).
  - **Auditing:** `test_report_json` and `audit_report.report_json` include:
    - **llm_composite_score**, **llm_recommendation**, **llm_justification**
    - **audit_steps:** ordered list of steps (load → per_question_scoring → llm_composite or fallback_cutoff → update_test_details → update_application → create_audit_report → create_email_log), with ids and details for traceability.
  - **Logs:** Each step is logged (e.g. `evaluate_test step=load`, `step=per_question_scoring`, `step=llm_composite`, `step=update_test_details`, …) for debugging and auditing.
- **Action:** Click **Try it out**
- **Request body:** (adjust `question_id` and answers to match the test you generated)
```json
{
  "test_id": 1,
  "answers_json": [
    { "question_id": "Q1", "answer": "YOLO" },
    { "question_id": "Q2", "answer": "Convolutional Neural Network" },
    { "question_id": "Q3", "answer": "YOLO is single-pass and faster; R-CNN is more accurate but slower. Trade-off is speed vs accuracy." },
    { "question_id": "Q4", "answer": "Stereo cameras for depth, YOLO for obstacles, semantic segmentation for terrain, SLAM for mapping, TensorRT on edge." },
    { "question_id": "Q5", "answer": "ReLU" }
  ],
  "submitted_by": "candidate"
}
```
- **Execute** → **Expected (200):**
```json
{
  "success": true,
  "message": "Test evaluated successfully",
  "data": {
    "test_id": 1,
    "score": 85.5,
    "result": "PASS",
    "application_status": "SHORTLISTED",
    "audit_report_id": 1
  }
}
```
  - **Note:** `score` is the LLM composite score when the API key is set; otherwise it is the rule-based percentage. Use `audit_report_id` to fetch the full report (including `audit_steps`, `llm_recommendation`, `llm_justification`) from `job_module.audit_report`.
- **Tables updated:** See **Tables updated by endpoint** below.

---

## Tables updated by endpoint

When you trigger the following endpoints, these **job_module** tables are updated (and in what way). Use this as a checklist for DB state and auditing. **You can run the full flow using only APIs** (no manual DB changes): register or add-applications → score-and-evaluate → generate test → submit test.

**Full reference:** For a detailed, code-level breakdown of every table and column written by each API (including gaps and clarifications), see **docs/API_DATABASE_UPDATES.md**.

### `POST /onboarding/add-applications`

| Table | Action | Columns / details |
|-------|--------|-------------------|
| **candidate_job_form_responses** | INSERT (or UPDATE on conflict) | One row per preference: `candidate_id`, `job_profile_id`, `priority`, `response_json`, `raw_json`, `source`. |
| **candidate_job_app_profiles** | INSERT (or skip on conflict) | One row per preference: `candidate_id`, `assigned_job_profile_id`, `source`, `status = 'INSERTED'`, `priority_number`, `email_sent_flag = false`. |

*Read only:* `candidates` (to verify candidate exists).

---

### `POST /onboarding/score-and-evaluate`

| Table | Action | Columns / details |
|-------|--------|-------------------|
| **candidate_job_app_profiles** | UPDATE | `composite_score`, `status` (SHORTLISTED / REJECTED), `decision_reason`, `additional_metadata_json` (score breakdown; when LLM used: `source`, `llm_recommendation`, `llm_justification`), `email_sent_flag`, `email_status`. One row per application scored. |
| **email_log** | INSERT | One row per email: `candidate_job_app_id`, `email_type` (TEST_INVITE or REJECTION), `subject`, `body_json`, `email_to_json`, `email_sent`. |

*Read from but not written:* `candidates`, `job_profiles`, `candidate_job_form_responses`.

---

### `POST /notifier/score-and-notify`

| Table | Action | Columns / details |
|-------|--------|-------------------|
| **candidate_job_app_profiles** | UPDATE | `composite_score`, `status` (SHORTLISTED / REJECTED), `email_sent_flag`, `email_status`, `decision_reason`, `additional_metadata_json` (score breakdown). One row per application in the request (or all INSERTED if no ids/batch). |
| **email_log** | INSERT | One row per email: `candidate_job_app_id`, `email_type` (TEST_INVITE or REJECTION), `subject`, `body_json`, `email_to_json`, `email_sent`. |

*Read from but not written:* `candidates`, `job_profiles`, `candidate_job_form_responses`.

---

### `POST /tests/generate`

| Table | Action | Columns / details |
|-------|--------|-------------------|
| **test_details_profiles** | INSERT (when new test) | `candidate_id`, `assigned_job_profile_id`, `candidate_job_app_id`, `status`, `attempt_no`, `questions_json`, etc. One new row when a test is generated (not when returning EXISTING). |
| **candidate_job_app_profiles** | UPDATE (when new test) | `status` set to `TEST_INVITED` for the application that got the new test. |

*When mode = EXISTING:* No new rows; existing `test_details_profiles` row is read and returned.

---

### `POST /tests/submit`

| Table | Action | Columns / details |
|-------|--------|-------------------|
| **test_details_profiles** | UPDATE | `answers_json`, `test_score` (composite or rule-based %), `status = EVALUATED`, `test_report_json` (includes `audit_steps`, `llm_composite_score`, `llm_recommendation`, `llm_justification`), `consolidate_qa_json`, `submitted_at`. |
| **candidate_job_app_profiles** | UPDATE | `status` (SHORTLISTED or REJECTED), `email_sent_flag = false`, `email_status = PENDING`. |
| **audit_report** | INSERT | One row: `candidate_job_app_id`, `test_id`, `report_json` (full evaluation report including audit trail). |
| **email_log** | INSERT | One row: `candidate_job_app_id`, `audit_id`, `test_id`, `email_type` (TEST_RESULT or REJECTION), `subject`, `body_json`, `email_to_json`, `email_sent = false`. |

*Read from but not written:* `candidates`, `job_profiles`.

---

## Quick Reference – Endpoints and Order

| Order | Method | Endpoint | Purpose |
|-------|--------|----------|---------|
| 1 | GET | `/health` | Health check |
| 2 | POST | `/employer/create-job` | Create job (get `job_profile_id`) |
| 3 | POST | `/onboarding/register` | Register candidate (get `candidate_id`, creates application) |
| 3b | POST | `/onboarding/add-applications` | Add applications for existing candidate (API-only; then call score-and-evaluate) |
| 4 | POST | `/onboarding/bulk-register` | Bulk upload Excel (optional) |
| 4b | POST | `/onboarding/score-and-evaluate` | Score & evaluate active candidates (best-preference, cutoff); manual or Azure Function |
| 5 | POST | `/notifier/score-and-notify` | Score applications (need `application_ids` or `batch_id`) |
| 6 | POST | `/tests/generate` | Generate test (need shortlisted `candidate_job_app_id`, get `test_id`) |
| 7 | POST | `/tests/submit` | Submit answers; LLM composite score + full audit (need `test_id`, `answers_json`) |

---

## Finding IDs in Swagger / DB

- **job_profile_id:** From Step 2 response `data.job_profile_id`.
- **candidate_id:** From Step 3 response `data.candidate_id`.
- **application id (`candidate_job_app_id`):** After Step 3 or Step 3b there is one row per job preference in `candidate_job_app_profiles`. The first application is often `id = 1` if the DB was empty. After Step 5 you can query the DB for `status = 'SHORTLISTED'` to get the right application ID.
- **Adding applications for an existing candidate:** If you have a `candidate_id` (e.g. 6) but no applications, call **POST /onboarding/add-applications** with that `candidate_id` and `job_preferences` (use `job_profile_id` from Step 2); then call **POST /onboarding/score-and-evaluate** with `candidate_ids: [6]`. No manual DB changes.
- **test_id:** From Step 6 response `data.test_id`.
- **audit_report_id:** From Step 7 response `data.audit_report_id`; use to fetch the full evaluation report (including `audit_steps`, `llm_composite_score`, `llm_recommendation`, `llm_justification`) from `job_module.audit_report`.

---

## Logs and Debugging

- Each request gets an **X-Request-ID** in the response; the same ID appears in logs for that request.
- Log format: `timestamp | level | request_id | logger_name | message`
- To see more detail: set in `.env`: `LOG_LEVEL=DEBUG` and restart the server.
- Logs show: route start/end, service steps (bulk rows, score per app, test generate/evaluate, email send, DB operations, errors with stack traces).
