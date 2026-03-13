# API → database updates (job_module)

This document lists **every table write** (INSERT/UPDATE) performed by each API in the Aegis Archive pipeline. All tables live in schema **`job_module`**. Use it to close gaps in understanding and to verify that the right columns are updated.

---

## Summary: which APIs write to which tables

| Table | POST /employer/create-job | POST /onboarding/register | POST /onboarding/add-applications | POST /onboarding/bulk-register | POST /onboarding/score-and-evaluate | POST /notifier/score-and-notify | POST /tests/generate | POST /tests/submit |
|-------|---------------------------|---------------------------|-----------------------------------|----------------------------------|--------------------------------------|-------------------------------------|----------------------|---------------------|
| **job_profiles** | INSERT | — | — | — | — | — | — | — |
| **bulk_load** | — | — | — | INSERT + UPDATE | — | — | — | — |
| **candidates** | — | INSERT or UPDATE | — | INSERT or UPDATE (per row) | — | — | — | — |
| **candidate_job_form_responses** | — | INSERT/UPDATE | INSERT/UPDATE | INSERT/UPDATE (per row) | — | — | — | — |
| **candidate_job_app_profiles** | — | INSERT | INSERT | INSERT (1 per candidate, assigned_job_profile_id NULL) | UPDATE | UPDATE | UPDATE (when new test) | UPDATE |
| **test_details_profiles** | — | — | — | — | — | — | INSERT (when new test) | UPDATE (×2) |
| **audit_report** | — | — | — | — | — | — | — | INSERT |
| **email_log** | — | — | — | — | INSERT (+ optional UPDATE) | INSERT (+ optional UPDATE) | — | INSERT |

**Note:** `POST /employer/create-job-from-jd` uses `job_service.create_job()` which does **not** write to `job_module` in this codebase (it returns an in-memory/different store job). Only `POST /employer/create-job` writes to `job_module.job_profiles`.

---

## 1. POST /employer/create-job

**Service:** `job_pipeline.create_job_profile`

### job_module.job_profiles — INSERT (1 row)

| Column | Source |
|--------|--------|
| title | payload.job_profile.title |
| department | payload.job_profile.department |
| stream | payload.job_profile.stream |
| description | payload.job_profile.description |
| status | payload.job_profile.status (default OPEN) |
| test_flag_llm | payload.test_by_llm (normalised to bool) |
| cutoff_score | payload.job_profile.screening_cutoff |
| stakeholders_json | `{ company, cc_emails }` |
| skillset_required_json | mandatory_skills, good_to_have_skills, soft_skills, certifications_or_qualifications |
| questionnaire_set_json | test_definition if provided |
| additional_metadata_json | job_code, location, employment_type, experience_min/max, number_of_openings, role_summary, key_responsibilities, test_cutoff |

**No other tables are written.**

---

## 2. POST /onboarding/register

**Service:** `candidate_pipeline.register_candidate_portal`

### job_module.candidates — INSERT or UPDATE

- **If candidate exists (same email):** UPDATE one row by `id`.
  - Set: `name`, `phone`, `source`, `skillset_json`, `metadata_details_json`.
- **If new:** INSERT one row.
  - Columns: `name`, `email`, `phone`, `source`, `skillset_json`, `metadata_details_json`.

### job_module.candidate_job_form_responses — INSERT or UPDATE (per job preference)

- One row per `job_preferences[]` item.
- INSERT with ON CONFLICT (candidate_id, job_profile_id, priority) DO UPDATE.
- Columns: `candidate_id`, `job_profile_id`, `priority`, `response_json`, `raw_json` (payload), `source`.

### job_module.candidate_job_app_profiles — INSERT (per job preference)

- One row per `job_preferences[]` item.
- INSERT with ON CONFLICT (candidate_id, assigned_job_profile_id) DO NOTHING.
- Columns: `candidate_id`, `assigned_job_profile_id`, `source`, `status = 'INSERTED'`, `priority_number`, `email_sent_flag = false`.

**No other tables are written.**

---

## 3. POST /onboarding/add-applications

**Service:** `candidate_pipeline.add_applications_for_candidate`

### job_module.candidate_job_form_responses — INSERT or UPDATE (per preference)

- Same shape as register: `candidate_id`, `job_profile_id`, `priority`, `response_json`, `raw_json`, `source`.
- ON CONFLICT (candidate_id, job_profile_id, priority) DO UPDATE response_json, raw_json.

### job_module.candidate_job_app_profiles — INSERT (per preference)

- One row per preference: `candidate_id`, `assigned_job_profile_id`, `source`, `status = 'INSERTED'`, `priority_number`, `email_sent_flag = false`.
- ON CONFLICT (candidate_id, assigned_job_profile_id) DO NOTHING.

**No updates to candidates, bulk_load, test_details_profiles, audit_report, email_log.**

---

## 4. POST /onboarding/bulk-register

**Service:** `candidate_pipeline.process_bulk_upload`

When **create_applications=true**, job profile IDs are always validated against `job_module.job_profiles`: only IDs that exist in the DB are used. If the Excel has role names (e.g. "Priority Role 1" / "AI Innovation Engineer") instead of numeric IDs, the pipeline resolves **p1_job_profile_id**, **p2_job_profile_id**, **p3_job_profile_id** by matching stream/role name fields against job title/stream/department. Invalid or unresolved IDs are replaced with a default (job_profile_id **1** if it exists, otherwise the first available profile).

**Bulk behaviour:** For each candidate the pipeline inserts **exactly three** rows into **candidate_job_form_responses** (one per priority 1–3; any missing preference uses the default job profile). It inserts **exactly one** row into **candidate_job_app_profiles** with **assigned_job_profile_id = NULL** and status = 'INSERTED'. That row is later updated by **POST /onboarding/score-and-evaluate**, which scores all three preferences from form responses, picks the best, and sets **assigned_job_profile_id** and **composite_score** on that single app row.

### job_module.bulk_load — INSERT then UPDATE

- **INSERT (1 row per upload):** `uploaded_by`, `file_name`, `total_candidate`, `status = 'PROCESSING'`, `metadata_details_json` (source).
- **UPDATE (same row) when done:**
  - Set: `status` (RECORDED or COMPLETED/PARTIAL_FAILED/FAILED), `total_candidate`, `process_json`, `metadata_details_json`.

When **create_applications=true**, for each normalized row:

### job_module.candidates — INSERT or UPDATE (per row)

- **If email exists:** UPDATE by id: `name`, `phone`, `batch_id`, `source`, `skillset_json`, `metadata_details_json`.
- **If new:** INSERT: `name`, `email`, `phone`, `batch_id`, `source`, `skillset_json`, `metadata_details_json`.

### job_module.candidate_job_form_responses — INSERT or UPDATE (exactly 3 per candidate)

- One row per priority (1, 2, 3): candidate_id, job_profile_id, priority, response_json, raw_json, source. Missing preferences use the default job profile so there are always three rows per candidate.
- ON CONFLICT (candidate_id, job_profile_id, priority) DO UPDATE.

### job_module.candidate_job_app_profiles — INSERT (one per candidate for bulk)

- One row per candidate with `assigned_job_profile_id = NULL`, `status = 'INSERTED'`, `source`, `batch_id`, `priority_number = 1`, `email_sent_flag = false`. **POST /onboarding/score-and-evaluate** later sets `assigned_job_profile_id` and `composite_score` from the best of the three preferences.
- Duplicate (candidate_id, NULL) is avoided by checking for an existing row before insert.

When **create_applications=false**, only **bulk_load** is written (INSERT + UPDATE); no candidates/form_responses/app_profiles.

---

## 5. POST /onboarding/score-and-evaluate

**Service:** `job_pipeline.score_and_evaluate_onboarding`

Only processes applications with **status = 'INSERTED'**. For each candidate (grouped by candidate_id): if the application row has **assigned_job_profile_id = NULL** (from bulk upload), preferences are taken from **candidate_job_form_responses** and each is scored; the best preference is chosen and the single app row is updated with **assigned_job_profile_id** and composite score. Otherwise (per-preference app rows), best-preference logic is applied as before.

### job_module.candidate_job_app_profiles — UPDATE (one or more rows per candidate)

- **Best application (if passes cutoff):** UPDATE by `id`: `composite_score`, `status = 'SHORTLISTED'`, `email_sent_flag`, `email_status`, `decision_reason`, `additional_metadata_json`.
- **Other applications of same candidate:** UPDATE by `id`: `composite_score`, `status = 'REJECTED'`, `email_sent_flag`, `email_status`, `decision_reason`, `additional_metadata_json`.
- **If best fails cutoff:** All that candidate’s applications updated to REJECTED with same column set.

### job_module.email_log — INSERT (per email sent/logged)

- Called from `_create_email_log(conn, app_id, email_type, ...)`.
- Columns: `candidate_job_app_id`, `email_type` (TEST_INVITE or REJECTION), `subject`, `body_json`, `email_to_json`, `email_sent = false`.
- **Optional follow-up (when SMTP sends):** UPDATE `email_log` SET `email_sent = true`, `sent_at = NOW()`; UPDATE `candidate_job_app_profiles` SET `email_status = 'SENT'` for that app.

**Not written:** candidates, job_profiles, candidate_job_form_responses, bulk_load, test_details_profiles, audit_report (audit_report is only used in test submit).

---

## 6. POST /notifier/score-and-notify

**Service:** `job_pipeline.score_and_notify`

### job_module.candidate_job_app_profiles — UPDATE (per application processed)

- For each application (by application_ids, batch_id, or all INSERTED): UPDATE by `id`: `composite_score`, `status` (SHORTLISTED or REJECTED), `email_sent_flag`, `email_status`, `decision_reason`, `additional_metadata_json`.

### job_module.email_log — INSERT (per email)

- Same as score-and-evaluate: `candidate_job_app_id`, `email_type`, `subject`, `body_json`, `email_to_json`, `email_sent = false`.
- Optional: UPDATE email_log (email_sent, sent_at) and candidate_job_app_profiles (email_status = 'SENT') when SMTP sends.

**Not written:** candidates, job_profiles, candidate_job_form_responses, bulk_load, test_details_profiles, audit_report.

---

## 7. POST /tests/generate

**Service:** `test_pipeline.generate_test`

When a **new** test is created (not returning EXISTING):

### job_module.test_details_profiles — INSERT (1 row)

- Columns: `candidate_id`, `assigned_job_profile_id`, `candidate_job_app_id`, `status = 'NOT_STARTED'`, `attempt_no`, `questions_json`, `consolidate_qa_json` (generation metadata).

### job_module.candidate_job_app_profiles — UPDATE (1 row)

- WHERE `id = candidate_job_app_id` AND status IN ('INSERTED','SHORTLISTED'): SET `status = 'TEST_INVITED'`.

When **mode = EXISTING** (reuse existing test): **no DB writes**.

**Not written:** candidates, job_profiles, candidate_job_form_responses, bulk_load, email_log, audit_report.

---

## 8. POST /tests/submit

**Service:** `test_pipeline.evaluate_test`

### job_module.test_details_profiles — UPDATE (twice, same row)

- **First UPDATE (by test id):** `answers_json`, `test_score` (composite or rule-based %), `status = 'EVALUATED'`, `test_report_json`, `consolidate_qa_json`, `submitted_at = NOW()`.
- **Second UPDATE (after audit steps built):** `test_report_json` again (full payload including final `audit_steps` with all step ids).

### job_module.candidate_job_app_profiles — UPDATE (1 row)

- By application id: `status` (SHORTLISTED or REJECTED), `email_sent_flag = false`, `email_status = 'PENDING'`.

### job_module.audit_report — INSERT (1 row)

- Columns: `candidate_job_app_id`, `test_id`, `report_json` (full evaluation report including audit_steps, llm_composite_score, etc.).

### job_module.email_log — INSERT (1 row)

- Columns: `candidate_job_app_id`, `audit_id`, `test_id`, `email_type` (TEST_RESULT or REJECTION), `subject`, `body_json`, `email_to_json`, `email_sent = false`.

**Not written:** candidates, job_profiles, candidate_job_form_responses, bulk_load. (Test submit does **not** update `composite_score` or `decision_reason` on candidate_job_app_profiles; those are set by score-and-notify / score-and-evaluate.)

---

## Potential gaps and clarifications

1. **email_log table shape**  
   - Score-and-notify / score-and-evaluate use: `candidate_job_app_id`, `email_type`, `subject`, `body_json`, `email_to_json`, `email_sent`.  
   - Test submit also sets: `audit_id`, `test_id`.  
   So `audit_id` and `test_id` on `email_log` are **NULL** for score-and-notify and score-and-evaluate; only test submit fills them.

2. **candidate_job_app_profiles columns**  
   - **Score flows** set: `composite_score`, `status`, `email_sent_flag`, `email_status`, `decision_reason`, `additional_metadata_json`.  
   - **Test submit** only set: `status`, `email_sent_flag`, `email_status`. It does **not** set `composite_score` or `decision_reason` (test score is stored in test_details_profiles and audit_report).

3. **POST /employer/create-job-from-jd**  
   Does **not** write to `job_module` in the current codebase; it uses `job_service.create_job()`. To persist JD-created jobs to `job_module.job_profiles`, that flow would need to call `job_pipeline.create_job_profile()` (or an equivalent that maps JD output to the same columns as create-job).

4. **Read-only usage**  
   These tables are only **read** by the pipeline (never written by the APIs above): used as lookup/reference only in the flows described — e.g. candidates, job_profiles, candidate_job_form_responses when scoring; no extra tables are updated beyond what is listed per endpoint above.

---

## Quick checklist per table

- **job_profiles:** Only written by `POST /employer/create-job` (INSERT).
- **bulk_load:** Only written by `POST /onboarding/bulk-register` (INSERT + UPDATE).
- **candidates:** Written by `POST /onboarding/register` (INSERT/UPDATE) and `POST /onboarding/bulk-register` (INSERT/UPDATE per row when create_applications=true).
- **candidate_job_form_responses:** Written by register, add-applications, and bulk-register (INSERT/UPDATE); never by score-and-evaluate, score-and-notify, or test endpoints.
- **candidate_job_app_profiles:** Written by register (INSERT), add-applications (INSERT), bulk-register (INSERT), score-and-evaluate (UPDATE), score-and-notify (UPDATE), tests/generate (UPDATE when new test), tests/submit (UPDATE).
- **test_details_profiles:** Written by tests/generate (INSERT when new test) and tests/submit (UPDATE twice).
- **audit_report:** Only written by `POST /tests/submit` (INSERT).
- **email_log:** Written by score-and-evaluate (INSERT, optional UPDATE), score-and-notify (INSERT, optional UPDATE), and tests/submit (INSERT). Columns `audit_id` and `test_id` only set by tests/submit.
