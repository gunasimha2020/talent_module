"""
Service layer for:
  - Job profile creation  (API 3)
  - Composite scoring + shortlisting  (API 4) – LLM when available, else formula
"""

import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from openai import OpenAI
from psycopg2.extras import Json

from app.db import get_connection, fetch_one, fetch_all, execute
from app.config import get_settings

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# API 3 – Job Profile Creation
# ═════════════════════════════════════════════════════════════════════════════

def _normalise_test_by_llm(value) -> bool:
    """Convert request test_by_llm (str or bool) to a single boolean for test_flag_llm column."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    return raw in ("true", "yes", "1")


def create_job_profile(payload: dict) -> dict:
    jp = payload["job_profile"]
    test_by_llm = _normalise_test_by_llm(payload.get("test_by_llm"))
    test_def = payload.get("test_definition")
    company = payload.get("company", "Centific")

    title = jp["title"]
    logger.info("create_job_profile | title=%s department=%s stream=%s test_by_llm=%s", title, jp.get("department"), jp.get("stream"), test_by_llm)
    department = jp["department"]
    stream = jp["stream"]
    description = jp.get("description") or ""
    status = jp.get("status", "OPEN")
    cutoff_score = jp.get("screening_cutoff")

    stakeholders_json = {
        "company": company,
        "cc_emails": jp.get("cc_emails") or [],
    }

    skillset_required_json = {
        "mandatory_skills": jp.get("mandatory_skills") or [],
        "good_to_have_skills": jp.get("good_to_have_skills") or [],
        "soft_skills": jp.get("soft_skills") or [],
        "certifications_or_qualifications": jp.get("certifications_or_qualifications") or [],
    }

    questionnaire_set_json = {}
    if test_def:
        questionnaire_set_json["test_definition"] = test_def

    additional_metadata_json = {
        "job_code": jp.get("job_code"),
        "location": jp.get("location"),
        "employment_type": jp.get("employment_type"),
        "experience_min": jp.get("experience_min"),
        "experience_max": jp.get("experience_max"),
        "number_of_openings": jp.get("number_of_openings"),
        "role_summary": jp.get("role_summary"),
        "key_responsibilities": jp.get("key_responsibilities") or [],
        "test_cutoff": jp.get("test_cutoff"),
    }

    # Ensure boolean for DB (test_flag_llm column)
    test_flag_llm = bool(test_by_llm)
    row = fetch_one(
        """
        INSERT INTO job_module.job_profiles
               (title, department, stream, description, status,
                test_flag_llm, cutoff_score,
                stakeholders_json, skillset_required_json,
                questionnaire_set_json, additional_metadata_json)
        VALUES (%s, %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s)
        RETURNING id
        """,
        (
            title, department, stream, description, status,
            test_flag_llm, cutoff_score,
            Json(stakeholders_json), Json(skillset_required_json),
            Json(questionnaire_set_json), Json(additional_metadata_json),
        ),
    )

    logger.info("create_job_profile done | job_profile_id=%s title=%s", row["id"], title)
    return {
        "job_profile_id": row["id"],
        "title": title,
        "test_by_llm": test_by_llm,
    }


# ═════════════════════════════════════════════════════════════════════════════
# API 4 – Composite Score Calculation + Shortlist / Rejection
# ═════════════════════════════════════════════════════════════════════════════

SKILL_MATCH_WEIGHT = 0.60
RESPONSE_MATCH_WEIGHT = 0.40
DEFAULT_CUTOFF = 50.0


def _extract_skill_list(skillset_json) -> list[str]:
    if not skillset_json:
        return []
    if isinstance(skillset_json, list):
        return [str(s) for s in skillset_json]
    if isinstance(skillset_json, dict):
        out = skillset_json.get("all_skills") or []
        if not out:
            for key in ("programming_languages", "ai_interest_areas",
                        "tools_frameworks", "advanced_ai_exposure",
                        "mandatory_skills", "good_to_have_skills"):
                out.extend(skillset_json.get(key) or [])
        return [str(s) for s in out]
    return []


def _compute_skill_match(candidate_skills: list[str], required_json: dict) -> float:
    mandatory = required_json.get("mandatory_skills") or []
    good_to_have = required_json.get("good_to_have_skills") or []
    if not mandatory and not good_to_have:
        return 50.0

    cand_set = {s.strip().lower() for s in candidate_skills if s}
    mand_set = {s.strip().lower() for s in mandatory if s}
    opt_set = {s.strip().lower() for s in good_to_have if s}

    mand_score = (len(cand_set & mand_set) / len(mand_set) * 70) if mand_set else 35
    opt_score = (len(cand_set & opt_set) / len(opt_set) * 30) if opt_set else 15

    return round(mand_score + opt_score, 2)


def _compute_response_match(response_json, job_profile: dict) -> float:
    if not response_json:
        return 0.0

    response_text = json.dumps(response_json).lower()
    keywords: set[str] = set()
    req = job_profile.get("skillset_required_json") or {}
    for key in ("mandatory_skills", "good_to_have_skills"):
        for s in (req.get(key) or []):
            keywords.add(s.strip().lower())

    desc = (job_profile.get("description") or "").lower()
    for word in desc.split():
        cleaned = word.strip(".,;:!?()[]\"'")
        if len(cleaned) > 4:
            keywords.add(cleaned)

    if not keywords:
        return 50.0

    matched = sum(1 for kw in keywords if kw in response_text)
    return round(min(100.0, (matched / len(keywords)) * 100), 2)


def _composite_score(candidate, job_profile, form_response=None) -> tuple[float, dict]:
    cand_skills = _extract_skill_list(candidate.get("skillset_json"))
    req_json = job_profile.get("skillset_required_json") or {}

    skill_score = _compute_skill_match(cand_skills, req_json)
    resp_score = _compute_response_match(
        form_response.get("response_json") if form_response else None,
        job_profile,
    )

    composite = round(resp_score * RESPONSE_MATCH_WEIGHT + skill_score * SKILL_MATCH_WEIGHT, 2)

    breakdown = {
        "skill_match": skill_score,
        "response_match": resp_score,
        "composite": composite,
        "formula": f"({resp_score}×0.40) + ({skill_score}×0.60) = {composite}",
    }
    return composite, breakdown


def _get_openai_client() -> Optional[OpenAI]:
    key = get_settings().openai_api_key
    if not key or not key.strip():
        return None
    return OpenAI(api_key=key.strip())


def _get_llm_screening_score(
    candidate: dict,
    job_profile: dict,
    form_response: Optional[dict],
) -> dict:
    """
    Use LLM to score candidate for screening: candidate skills + metadata,
    job requirements, and candidate_job_form_responses (answers). Returns
    composite_score (0-100), recommendation (SELECT/REJECT), justification.
    """
    client = _get_openai_client()
    if not client:
        return {}

    cand_skills = _extract_skill_list(candidate.get("skillset_json"))
    meta = candidate.get("metadata_details_json") or {}
    job_title = job_profile.get("title", "Role")
    job_desc = (job_profile.get("description") or "")[:600]
    req = job_profile.get("skillset_required_json") or {}
    mandatory = req.get("mandatory_skills") or []
    good_to_have = req.get("good_to_have_skills") or []
    cutoff = float(job_profile.get("cutoff_score") or DEFAULT_CUTOFF)
    response_json = (form_response or {}).get("response_json") if form_response else None
    response_text = json.dumps(response_json) if response_json else "{}"

    prompt = (
        "You are a recruitment screener. Evaluate the candidate for the role using:\n"
        f"1) Job: {job_title}\nDescription: {job_desc}\n"
        f"Required skills: {mandatory}\nGood to have: {good_to_have}\n\n"
        f"2) Candidate skills: {cand_skills}\n"
        f"Candidate metadata (e.g. experience, degree): {json.dumps(meta, ensure_ascii=False)}\n\n"
        f"3) Candidate form responses / answers for this application:\n{response_text}\n\n"
        "Return ONLY a JSON object with these keys:\n"
        "  composite_score (number 0-100, overall fit for the role)\n"
        "  recommendation (string: \"SELECT\" or \"REJECT\")\n"
        "  justification (string, 1-2 sentences)\n"
        f"Use {cutoff} as cutoff: score >= {cutoff} should usually be SELECT. No extra text."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        for prefix in ("```json", "```"):
            if raw.startswith(prefix):
                raw = raw[len(prefix):].strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
        out = json.loads(raw)
        score = float(out.get("composite_score", 0))
        rec = str(out.get("recommendation", "REJECT")).strip().upper()
        if rec not in ("SELECT", "REJECT"):
            rec = "REJECT"
        return {
            "composite_score": round(score, 2),
            "recommendation": rec,
            "justification": str(out.get("justification", "")).strip(),
        }
    except Exception as exc:
        logger.exception("LLM screening score failed | error=%s", str(exc))
        return {}


def _score_application(candidate, job_profile, form_response=None) -> tuple[float, dict]:
    """
    Score one application: use LLM when available (skills + form responses);
    else use formula (skill_match + response_match). Returns (score, breakdown).
    Breakdown includes source (llm | formula), and when LLM: recommendation, justification.
    """
    llm_result = _get_llm_screening_score(candidate, job_profile, form_response)
    if llm_result:
        score = llm_result.get("composite_score", 0)
        breakdown = {
            "source": "llm",
            "composite": score,
            "skill_match": None,
            "response_match": None,
            "formula": None,
            "llm_recommendation": llm_result.get("recommendation"),
            "llm_justification": llm_result.get("justification"),
        }
        return score, breakdown
    score, breakdown = _composite_score(candidate, job_profile, form_response)
    breakdown["source"] = "formula"
    return score, breakdown


def score_and_notify(
    application_ids: Optional[list[int]] = None,
    batch_id: Optional[int] = None,
    send_email: bool = True,
    triggered_by: Optional[int] = None,
) -> dict:
    logger.info(
        "score_and_notify | application_ids=%s batch_id=%s send_email=%s",
        application_ids, batch_id, send_email,
    )
    with get_connection() as conn:
        if application_ids:
            apps = fetch_all(
                "SELECT * FROM job_module.candidate_job_app_profiles WHERE id = ANY(%s)",
                (application_ids,),
                conn=conn,
            )
        elif batch_id:
            apps = fetch_all(
                "SELECT * FROM job_module.candidate_job_app_profiles WHERE batch_id = %s",
                (batch_id,),
                conn=conn,
            )
        else:
            apps = fetch_all(
                "SELECT * FROM job_module.candidate_job_app_profiles WHERE status = 'INSERTED'",
                conn=conn,
            )

        logger.info("score_and_notify | applications_to_process=%d", len(apps))
        processed = shortlisted = rejected = 0

        for app in apps:
            try:
                candidate = fetch_one(
                    "SELECT * FROM job_module.candidates WHERE id = %s",
                    (app["candidate_id"],),
                    conn=conn,
                )
                job_profile = fetch_one(
                    "SELECT * FROM job_module.job_profiles WHERE id = %s",
                    (app["assigned_job_profile_id"],),
                    conn=conn,
                )
                if not candidate or not job_profile:
                    logger.warning("score_and_notify skip | app_id=%s reason=candidate_or_job_missing", app["id"])
                    continue

                form_resp = fetch_one(
                    """
                    SELECT * FROM job_module.candidate_job_form_responses
                     WHERE candidate_id = %s AND job_profile_id = %s
                     ORDER BY priority LIMIT 1
                    """,
                    (app["candidate_id"], app["assigned_job_profile_id"]),
                    conn=conn,
                )

                score, breakdown = _score_application(candidate, job_profile, form_resp)
                cutoff = float(job_profile.get("cutoff_score") or DEFAULT_CUTOFF)
                use_llm = breakdown.get("source") == "llm"

                if use_llm and breakdown.get("llm_recommendation"):
                    new_status = "SHORTLISTED" if breakdown["llm_recommendation"] == "SELECT" else "REJECTED"
                else:
                    new_status = "SHORTLISTED" if score >= cutoff else "REJECTED"

                if new_status == "SHORTLISTED":
                    email_type = "TEST_INVITE"
                    shortlisted += 1
                    logger.info("score_and_notify shortlisted | app_id=%s candidate_id=%s job_id=%s score=%.2f cutoff=%.2f", app["id"], app["candidate_id"], app["assigned_job_profile_id"], score, cutoff)
                else:
                    email_type = "REJECTION"
                    rejected += 1
                    logger.info("score_and_notify rejected | app_id=%s candidate_id=%s job_id=%s score=%.2f cutoff=%.2f", app["id"], app["candidate_id"], app["assigned_job_profile_id"], score, cutoff)

                if use_llm and breakdown.get("llm_justification"):
                    decision_reason = f"LLM: {breakdown['llm_justification']} (score={score:.1f}, cutoff={cutoff:.1f})"
                else:
                    sk, rp = breakdown.get("skill_match"), breakdown.get("response_match")
                    decision_reason = (
                        f"Composite score {score:.1f} vs cutoff {cutoff:.1f}. "
                        f"Skill={sk if sk is not None else 0:.1f}, Response={rp if rp is not None else 0:.1f}"
                    )

                execute(
                    """
                    UPDATE job_module.candidate_job_app_profiles
                       SET composite_score = %s,
                           status = %s,
                           email_sent_flag = %s,
                           email_status = %s,
                           decision_reason = %s,
                           additional_metadata_json = %s
                     WHERE id = %s
                    """,
                    (
                        score, new_status,
                        send_email, "PENDING" if send_email else None,
                        decision_reason, Json(breakdown), app["id"],
                    ),
                    conn=conn,
                )

                if send_email:
                    _create_email_log(
                        conn, app["id"], email_type, candidate, job_profile, score, new_status,
                    )

                processed += 1
            except Exception as exc:
                logger.exception("score_and_notify app failed | app_id=%s error=%s", app["id"], str(exc))

    logger.info("score_and_notify done | processed=%s shortlisted=%s rejected=%s", processed, shortlisted, rejected)
    return {"processed": processed, "shortlisted": shortlisted, "rejected": rejected}


# ═════════════════════════════════════════════════════════════════════════════
# Onboarding Score and Evaluate (active candidates, best-preference, cutoff)
# ═════════════════════════════════════════════════════════════════════════════

def score_and_evaluate_onboarding(
    send_email: bool = True,
    candidate_ids: Optional[list[int]] = None,
) -> dict:
    """
    For candidates with applications in INSERTED (active/pending) state:
    - Compute composite score per application (skills + form response vs job).
    - For each candidate with multiple preferences (up to 3), pick the application
      with the highest composite score as their best preference.
    - If best score >= job cutoff (default 50%): shortlist that application only,
      reject the others; send shortlist email for that role.
    - If best score < cutoff: reject all applications; send rejection email.
    Uses job_module.candidates, candidate_job_app_profiles, candidate_job_form_responses.
    """
    logger.info(
        "score_and_evaluate_onboarding | send_email=%s candidate_ids=%s",
        send_email, candidate_ids,
    )
    with get_connection() as conn:
        if candidate_ids:
            apps = fetch_all(
                """
                SELECT * FROM job_module.candidate_job_app_profiles
                 WHERE status = 'INSERTED' AND candidate_id = ANY(%s)
                 ORDER BY candidate_id, priority_number
                """,
                (candidate_ids,),
                conn=conn,
            )
        else:
            apps = fetch_all(
                """
                SELECT * FROM job_module.candidate_job_app_profiles
                 WHERE status = 'INSERTED'
                 ORDER BY candidate_id, priority_number
                """,
                (),
                conn=conn,
            )

        if not apps:
            if candidate_ids:
                logger.info(
                    "score_and_evaluate_onboarding | no INSERTED applications for candidate_ids=%s. "
                    "Ensure each candidate has at least one row in candidate_job_app_profiles with status='INSERTED' (e.g. from register or bulk-upload with job preferences).",
                    candidate_ids,
                )
            else:
                logger.info("score_and_evaluate_onboarding | no INSERTED applications")
            return {"processed": 0, "shortlisted": 0, "rejected": 0, "candidates_processed": 0}

        # Group by candidate_id
        by_candidate: dict[int, list[dict]] = {}
        for app in apps:
            cid = app["candidate_id"]
            if cid not in by_candidate:
                by_candidate[cid] = []
            by_candidate[cid].append(app)

        processed = shortlisted = rejected = 0
        for candidate_id, candidate_apps in by_candidate.items():
            try:
                candidate = fetch_one(
                    "SELECT * FROM job_module.candidates WHERE id = %s",
                    (candidate_id,),
                    conn=conn,
                )
                if not candidate:
                    continue

                # scored_apps: (app, score, breakdown, job_profile_id) so we can set assigned_job_profile_id when it was NULL (bulk)
                scored_apps: list[tuple[dict, float, dict, Optional[int]]] = []
                for app in candidate_apps:
                    if app.get("assigned_job_profile_id") is None:
                        # Bulk upload: one app row per candidate with NULL; score from candidate_job_form_responses
                        form_responses = fetch_all(
                            """
                            SELECT * FROM job_module.candidate_job_form_responses
                             WHERE candidate_id = %s ORDER BY priority
                            """,
                            (candidate_id,),
                            conn=conn,
                        )
                        for fr in form_responses:
                            jid = fr.get("job_profile_id")
                            job_profile = fetch_one(
                                "SELECT * FROM job_module.job_profiles WHERE id = %s",
                                (jid,),
                                conn=conn,
                            )
                            if not job_profile:
                                continue
                            score, breakdown = _score_application(candidate, job_profile, fr)
                            scored_apps.append((app, score, breakdown, jid))
                    else:
                        job_profile = fetch_one(
                            "SELECT * FROM job_module.job_profiles WHERE id = %s",
                            (app["assigned_job_profile_id"],),
                            conn=conn,
                        )
                        if not job_profile:
                            continue
                        form_resp = fetch_one(
                            """
                            SELECT * FROM job_module.candidate_job_form_responses
                             WHERE candidate_id = %s AND job_profile_id = %s
                             ORDER BY priority LIMIT 1
                            """,
                            (candidate_id, app["assigned_job_profile_id"]),
                            conn=conn,
                        )
                        score, breakdown = _score_application(candidate, job_profile, form_resp)
                        scored_apps.append((app, score, breakdown, app["assigned_job_profile_id"]))

                if not scored_apps:
                    continue

                best = max(scored_apps, key=lambda x: x[1])
                best_app, best_score, best_breakdown, best_job_id = best
                job_profile_best = fetch_one(
                    "SELECT * FROM job_module.job_profiles WHERE id = %s",
                    (best_job_id,),
                    conn=conn,
                )
                cutoff = float((job_profile_best or {}).get("cutoff_score") or DEFAULT_CUTOFF)
                use_llm = best_breakdown.get("source") == "llm"
                if use_llm and best_breakdown.get("llm_justification"):
                    decision_reason = f"LLM: {best_breakdown['llm_justification']} (score={best_score:.1f}, cutoff={cutoff:.1f})"
                else:
                    sk, rp = best_breakdown.get("skill_match"), best_breakdown.get("response_match")
                    decision_reason = (
                        f"Composite score {best_score:.1f} vs cutoff {cutoff:.1f}. "
                        f"Skill={sk if sk is not None else 0:.1f}, Response={rp if rp is not None else 0:.1f}"
                    )

                if use_llm and best_breakdown.get("llm_recommendation"):
                    best_passes = best_breakdown["llm_recommendation"] == "SELECT"
                else:
                    best_passes = best_score >= cutoff

                if best_passes:
                    execute(
                        """
                        UPDATE job_module.candidate_job_app_profiles
                           SET assigned_job_profile_id = COALESCE(assigned_job_profile_id, %s),
                               composite_score = %s, status = 'SHORTLISTED',
                               email_sent_flag = %s, email_status = %s,
                               decision_reason = %s, additional_metadata_json = %s
                         WHERE id = %s
                        """,
                        (
                            best_job_id, best_score, send_email,
                            "PENDING" if send_email else None,
                            decision_reason, Json(best_breakdown), best_app["id"],
                        ),
                        conn=conn,
                    )
                    if send_email:
                        _create_email_log(
                            conn, best_app["id"], "TEST_INVITE",
                            candidate, job_profile_best, best_score, "SHORTLISTED",
                        )
                    shortlisted += 1
                    processed += 1
                    for app, score, breakdown, jid in scored_apps:
                        if app["id"] != best_app["id"]:
                            jp = fetch_one(
                                "SELECT * FROM job_module.job_profiles WHERE id = %s",
                                (jid,),
                                conn=conn,
                            )
                            execute(
                                """
                                UPDATE job_module.candidate_job_app_profiles
                                   SET assigned_job_profile_id = COALESCE(assigned_job_profile_id, %s),
                                       composite_score = %s, status = 'REJECTED',
                                       email_sent_flag = %s, email_status = %s,
                                       decision_reason = %s, additional_metadata_json = %s
                                 WHERE id = %s
                                """,
                                (
                                    jid, score, send_email, "PENDING" if send_email else None,
                                    f"Not best preference; best was app {best_app['id']}. Score={score:.1f}.",
                                    Json(breakdown), app["id"],
                                ),
                                conn=conn,
                            )
                            if send_email and jp:
                                _create_email_log(
                                    conn, app["id"], "REJECTION",
                                    candidate, jp, score, "REJECTED",
                                )
                            rejected += 1
                else:
                    processed += 1
                    # Bulk: one app row; update it once. Non-bulk: one update per app.
                    seen_app_ids: set[int] = set()
                    for app, score, breakdown, jid in scored_apps:
                        if app["id"] in seen_app_ids:
                            continue
                        seen_app_ids.add(app["id"])
                        jp = fetch_one(
                            "SELECT * FROM job_module.job_profiles WHERE id = %s",
                            (jid,),
                            conn=conn,
                        )
                        execute(
                            """
                            UPDATE job_module.candidate_job_app_profiles
                               SET assigned_job_profile_id = COALESCE(assigned_job_profile_id, %s),
                                   composite_score = %s, status = 'REJECTED',
                                   email_sent_flag = %s, email_status = %s,
                                   decision_reason = %s, additional_metadata_json = %s
                             WHERE id = %s
                            """,
                            (
                                jid, score, send_email, "PENDING" if send_email else None,
                                decision_reason, Json(breakdown), app["id"],
                            ),
                            conn=conn,
                        )
                        if send_email and jp:
                            _create_email_log(
                                conn, app["id"], "REJECTION",
                                candidate, jp, score, "REJECTED",
                            )
                        rejected += 1
            except Exception as exc:
                logger.exception(
                    "score_and_evaluate_onboarding candidate failed | candidate_id=%s error=%s",
                    candidate_id, str(exc),
                )

    logger.info(
        "score_and_evaluate_onboarding done | processed=%s shortlisted=%s rejected=%s candidates=%s",
        processed, shortlisted, rejected, len(by_candidate),
    )
    return {
        "processed": processed,
        "shortlisted": shortlisted,
        "rejected": rejected,
        "candidates_processed": len(by_candidate),
    }


def _create_email_log(conn, app_id, email_type, candidate, job_profile, score, status):
    stakeholders = job_profile.get("stakeholders_json") or {}
    cc_emails = stakeholders.get("cc_emails") or []
    to_email = candidate.get("email", "")

    subject_map = {
        "TEST_INVITE": f"You've been shortlisted for {job_profile.get('title', 'a role')} - Take your test",
        "REJECTION": f"Your application for {job_profile.get('title', 'a role')} - Decision",
    }

    body = {
        "candidate_name": candidate.get("name"),
        "job_title": job_profile.get("title"),
        "score": score,
        "status": status,
    }

    email_to = {"to": [to_email], "cc": cc_emails}

    row = fetch_one(
        """
        INSERT INTO job_module.email_log
               (candidate_job_app_id, email_type, subject, body_json, email_to_json, email_sent)
        VALUES (%s, %s, %s, %s, %s, false)
        RETURNING id
        """,
        (app_id, email_type, subject_map.get(email_type, ""), Json(body), Json(email_to)),
        conn=conn,
    )
    log_id = row["id"] if row else None

    sent = _try_send_email(to_email, subject_map.get(email_type, ""), body, email_type)

    if log_id and sent:
        execute(
            "UPDATE job_module.email_log SET email_sent = true, sent_at = NOW() WHERE id = %s",
            (log_id,),
            conn=conn,
        )
        execute(
            "UPDATE job_module.candidate_job_app_profiles SET email_status = 'SENT' WHERE id = %s",
            (app_id,),
            conn=conn,
        )


def _try_send_email(to_addr: str, subject: str, body: dict, email_type: str) -> bool:
    settings = get_settings()
    if not settings.smtp_user or not settings.smtp_password:
        logger.info("SMTP not configured - email to %s logged but not sent", to_addr)
        return False

    try:
        sender = settings.smtp_from or settings.smtp_user
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_addr

        html = f"<p>Dear {body.get('candidate_name', 'Candidate')},</p>"
        if email_type == "TEST_INVITE":
            html += (
                f"<p>Congratulations! Your profile has been shortlisted for "
                f"<strong>{body.get('job_title', 'the role')}</strong> "
                f"with a match score of <strong>{body.get('score', 0):.1f}%</strong>.</p>"
                f"<p>Please log in to the Aegis platform to take your test.</p>"
            )
        else:
            html += (
                f"<p>After reviewing your profile for "
                f"<strong>{body.get('job_title', 'the role')}</strong>, "
                f"we regret to inform you that your application was not successful.</p>"
            )
        html += "<p>Regards,<br>Centific Talent Team</p>"

        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(sender, [to_addr], msg.as_string())
        logger.info("Email sent | to=%s type=%s", to_addr, email_type)
        return True
    except Exception as exc:
        logger.error("Email send failed | to=%s type=%s error=%s", to_addr, email_type, str(exc), exc_info=True)
        return False
