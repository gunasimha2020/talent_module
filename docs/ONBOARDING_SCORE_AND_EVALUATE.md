# Onboarding Score and Evaluate

This document describes the **onboarding score-and-evaluate** flow: how the composite score is calculated, which tables are used, and how to run it **on a schedule** (in-app or via Azure Function) or **manually**.

---

## What it does

1. **Finds active candidates**  
   Applications in status **INSERTED** (not yet scored) in `job_module.candidate_job_app_profiles` are treated as “active” for scoring. Optionally you can restrict by `candidate_ids`.

2. **Composite score per application**  
   For each application (candidate + job preference), a **composite score** (0–100) is computed:
   - **When `OPENAI_API_KEY` is set:** An **LLM** (gpt-4o-mini) is used. It receives: job (title, description, required skills), candidate skills from `candidates.skillset_json`, candidate metadata (e.g. experience, degree from `metadata_details_json`), and the candidate’s **form answers** from `candidate_job_form_responses.response_json`. The LLM returns `composite_score`, `recommendation` (SELECT/REJECT), and `justification`. Status (SHORTLISTED/REJECTED) follows the LLM recommendation.
   - **When LLM is unavailable:** The formula-based score is used: **skill match (60%)** + **response match (40%)** (keyword overlap of form response vs job). Status is based on score vs job cutoff.

   So **candidate_job_form_responses** (the answers the candidate submitted for this application) are always used: in the LLM prompt when available, and in the response-match term in the formula otherwise.

3. **Best preference (bulk / 3 preferences)**  
   For each candidate, all their INSERTED applications (1 to 3, by priority) are scored. The application with the **highest composite score** is the “best preference.”

4. **Cutoff (e.g. 50%)**  
   Each job has a **cutoff** (`job_profiles.cutoff_score`; default 50):
   - If **best score ≥ cutoff:** that application is set to **SHORTLISTED**, others to **REJECTED**. A **shortlist / test-invite** email is sent for that role.
   - If **best score < cutoff:** all applications for that candidate are set to **REJECTED**. A **rejection** email is sent (per rejected application, or you can adjust to one per candidate).

5. **Tables updated**  
   - **candidate_job_app_profiles:** `composite_score`, `status` (SHORTLISTED / REJECTED), `decision_reason`, `additional_metadata_json` (score breakdown: when LLM used includes `source`, `llm_recommendation`, `llm_justification`; when formula includes `skill_match`, `response_match`, `formula`), `email_sent_flag`, `email_status`.  
   - **email_log:** one row per email (TEST_INVITE or REJECTION), with `candidate_job_app_id`, `email_type`, `subject`, `body_json`, `email_to_json`, `email_sent`.

---

## Running it

### Option A: In-app scheduler (when Flask/FastAPI is running)

Set in `.env`:

```env
SCORE_EVALUATE_INTERVAL_SECONDS=300
```

- **300** = run every 5 minutes.  
- **0** or unset = disabled (only manual or HTTP trigger).

On startup, the app starts a background task that calls the score-and-evaluate logic at that interval. No separate Azure Function is required.

### Option B: Manual trigger (HTTP)

Call the API from Swagger or any HTTP client:

- **Method:** `POST`
- **URL:** `http://<your-host>:8000/onboarding/score-and-evaluate`
- **Body (JSON):**

```json
{
  "send_email": true,
  "candidate_ids": null
}
```

- **Response:** `{ "success": true, "data": { "processed", "shortlisted", "rejected", "candidates_processed" } }`

Use `candidate_ids: [1, 2, 3]` to restrict to specific candidates (only their INSERTED applications are processed).

### Option C: Azure Function (timer + manual HTTP trigger)

If you want a **separate Azure Function** to run at a fixed interval and/or to be triggered manually:

1. **Create an Azure Function** with:
   - **Timer trigger:** e.g. NCRONTAB `0 */5 * * * *` (every 5 minutes) or your desired schedule.
   - **HTTP trigger:** for manual run (e.g. from Logic App or browser).

2. **What the Azure Function must do**  
   Call your FastAPI app’s score-and-evaluate endpoint:

   - **URL:** `https://<your-fastapi-host>/onboarding/score-and-evaluate`  
     (Replace with your real base URL, e.g. `https://yourapp.azurewebsites.net` or `http://localhost:8000` for local.)
   - **Method:** `POST`
   - **Headers:** `Content-Type: application/json`
   - **Body:** `{"send_email": true, "candidate_ids": null}`

3. **Details you need to run the Azure Function**

   | Detail | Example / description |
   |--------|------------------------|
   | **FastAPI base URL** | `https://your-api.azurewebsites.net` or `http://localhost:8000` |
   | **Score-and-evaluate path** | `/onboarding/score-and-evaluate` |
   | **HTTP method** | `POST` |
   | **Request body** | `{"send_email": true, "candidate_ids": null}` |
   | **Timer schedule** | NCRONTAB, e.g. `0 */5 * * * *` (every 5 min) |
   | **Auth (if any)** | If your API uses API key or OAuth, add the same header in the Azure Function (e.g. `Authorization: Bearer <token>` or `X-API-Key: <key>`). |

4. **Example Azure Function (Python)**  
   - **Timer trigger:** in the timer function, use `httpx` or `requests` to `POST` to `BASE_URL + "/onboarding/score-and-evaluate"` with the JSON body above.  
   - **HTTP trigger:** in the HTTP function, do the same POST (or return a link that triggers it).  
   - Store `BASE_URL` (and optional API key) in the function’s **Application settings** (environment variables).

5. **Enabling both**  
   - **Automatic:** Use the in-app scheduler (Option A) **or** the Azure Function timer (Option C), not necessarily both.  
   - **Manual:** Use Swagger/Postman (Option B) **or** the Azure Function HTTP trigger (Option C).

---

## Summary

- **Score:** Composite = 40% response match + 60% skill match; same as used for test/notifier.  
- **Best preference:** Among up to 3 applications per candidate, the one with the highest score is shortlisted if ≥ cutoff; others are rejected.  
- **Tables:** `candidates`, `candidate_job_app_profiles`, `candidate_job_form_responses`, `job_profiles`, `email_log`.  
- **Run:** In-app scheduler (`SCORE_EVALUATE_INTERVAL_SECONDS`), manual `POST /onboarding/score-and-evaluate`, or an Azure Function that calls that endpoint on a timer and via HTTP.
