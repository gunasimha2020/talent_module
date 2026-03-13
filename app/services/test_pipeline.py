"""
Service layer for:
  - Test generation  (API 5)
  - Test evaluation  (API 6)
"""

import json
import logging
from typing import Optional

from openai import OpenAI
from psycopg2.extras import Json

from app.db import get_connection, fetch_one, fetch_all, execute
from app.config import get_settings

logger = logging.getLogger(__name__)


def _get_openai_client() -> Optional[OpenAI]:
    key = get_settings().openai_api_key
    if not key:
        logger.warning("OpenAI API key not configured")
        return None
    return OpenAI(api_key=key)


# ═════════════════════════════════════════════════════════════════════════════
# API 5 – Test Generation (by candidate_job_app_id or email)
# ═════════════════════════════════════════════════════════════════════════════

def _resolve_candidate_job_app_id(conn, candidate_job_app_id: Optional[int], email: Optional[str]) -> int:
    """Resolve to a single candidate_job_app_id from either id or candidate email."""
    if candidate_job_app_id is not None:
        row = fetch_one(
            "SELECT id FROM job_module.candidate_job_app_profiles WHERE id = %s",
            (candidate_job_app_id,),
            conn=conn,
        )
        if row:
            return row["id"]
        raise ValueError(f"Application {candidate_job_app_id} not found")
    if email and str(email).strip():
        candidate = fetch_one(
            "SELECT id FROM job_module.candidates WHERE LOWER(email) = LOWER(%s)",
            (str(email).strip(),),
            conn=conn,
        )
        if not candidate:
            raise ValueError(f"Candidate with email '{email}' not found")
        app_row = fetch_one(
            """
            SELECT id FROM job_module.candidate_job_app_profiles
             WHERE candidate_id = %s AND status IN ('INSERTED', 'SHORTLISTED')
             ORDER BY id ASC LIMIT 1
            """,
            (candidate["id"],),
            conn=conn,
        )
        if not app_row:
            raise ValueError(f"No INSERTED/SHORTLISTED application found for email '{email}'")
        return app_row["id"]
    raise ValueError("Provide either candidate_job_app_id or email")


def generate_test(
    candidate_job_app_id: Optional[int] = None,
    email: Optional[str] = None,
    generated_by: Optional[int] = None,
) -> dict:

    logger.info("generate_test | candidate_job_app_id=%s email=%s", candidate_job_app_id, email)
    with get_connection() as conn:
        app_id = _resolve_candidate_job_app_id(conn, candidate_job_app_id, email)
        candidate_job_app_id = app_id

        app_row = fetch_one(
            "SELECT * FROM job_module.candidate_job_app_profiles WHERE id = %s",
            (candidate_job_app_id,),
            conn=conn,
        )
        if not app_row:
            raise ValueError(f"Application {candidate_job_app_id} not found")

        job_profile = fetch_one(
            "SELECT * FROM job_module.job_profiles WHERE id = %s",
            (app_row["assigned_job_profile_id"],),
            conn=conn,
        )
        if not job_profile:
            raise ValueError("Job profile not found")
        meta = job_profile.get("additional_metadata_json") or {}
        reuse_existing_test = meta.get("reuse_existing_test", True)

        if reuse_existing_test:
            existing = fetch_one(
                """
                SELECT id, questions_json FROM job_module.test_details_profiles
                 WHERE candidate_job_app_id = %s AND status != 'ABANDONED'
                 ORDER BY attempt_no DESC LIMIT 1
                """,
                (candidate_job_app_id,),
                conn=conn,
            )
            if existing:
                q_json = existing["questions_json"]
                questions_list = q_json if isinstance(q_json, list) else []
                q_count = len(questions_list)
                logger.info("generate_test returning existing | test_id=%s question_count=%s (reuse_existing_test=true)", existing["id"], q_count)
                return {
                    "test_id": existing["id"],
                    "candidate_job_app_id": candidate_job_app_id,
                    "question_count": q_count,
                    "mode": "EXISTING",
                    "questions": questions_list,
                }

        candidate = fetch_one(
            "SELECT * FROM job_module.candidates WHERE id = %s",
            (app_row["candidate_id"],),
            conn=conn,
        )
        if not candidate:
            raise ValueError("Candidate not found")

        test_flag_llm = bool(job_profile.get("test_flag_llm"))
        logger.info("generate_test | job_id=%s test_flag_llm=%s", job_profile["id"], test_flag_llm)

        if not test_flag_llm:
            # test_flag_llm = N: get questions from job_profiles, then format via LLM to standard response format
            raw_predefined = _get_predefined_questions(job_profile)
            logger.info("Predefined questions from job profile | raw_count=%s", len(raw_predefined))
            questions = _format_predefined_questions_via_llm(raw_predefined, job_profile)
            mode = "PREDEFINED"
            logger.info("Predefined questions formatted via LLM | count=%s", len(questions))
        else:
            # test_flag_llm = Y: use job + candidate details, LLM creates mixed questionnaire (B.Tech recruitment)
            logger.info("Generating questions via LLM | job_id=%s", job_profile["id"])
            questions = _generate_llm_questions(candidate, job_profile)
            mode = "LLM"
            logger.info("LLM questions generated | count=%s", len(questions))

        if not questions:
            raise ValueError("No questions available for this job profile")

        max_attempt = fetch_one(
            """
            SELECT COALESCE(MAX(attempt_no), 0) AS mx
              FROM job_module.test_details_profiles
             WHERE candidate_job_app_id = %s
            """,
            (candidate_job_app_id,),
            conn=conn,
        )
        attempt_no = (max_attempt["mx"] if max_attempt else 0) + 1

        row = fetch_one(
            """
            INSERT INTO job_module.test_details_profiles
                   (candidate_id, assigned_job_profile_id, candidate_job_app_id,
                    status, attempt_no, questions_json, consolidate_qa_json)
            VALUES (%s, %s, %s,
                    'NOT_STARTED', %s, %s, %s)
            RETURNING id
            """,
            (
                candidate["id"], job_profile["id"], candidate_job_app_id,
                attempt_no, Json(questions),
                Json({"generation_mode": mode, "generated_by": generated_by}),
            ),
            conn=conn,
        )

        execute(
            """
            UPDATE job_module.candidate_job_app_profiles
               SET status = 'TEST_INVITED'
             WHERE id = %s AND status IN ('INSERTED', 'SHORTLISTED')
            """,
            (candidate_job_app_id,),
            conn=conn,
        )

    logger.info("generate_test done | test_id=%s mode=%s question_count=%s", row["id"], mode, len(questions))
    return {
        "test_id": row["id"],
        "candidate_job_app_id": candidate_job_app_id,
        "question_count": len(questions),
        "mode": mode,
        "questions": questions,
    }


def _get_predefined_questions(job_profile: dict) -> list[dict]:
    qs_json = job_profile.get("questionnaire_set_json") or {}
    test_def = qs_json.get("test_definition") or {}
    return test_def.get("questions_json") or []


def _extract_json_array(text: str) -> list:
    """Parse LLM response to a JSON array, stripping markdown if present."""
    if not text or not text.strip():
        return []
    raw = text.strip()
    for prefix in ("```json", "```"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _format_predefined_questions_via_llm(raw_questions: list[dict], job_profile: dict) -> list[dict]:
    """
    Take predefined questions from job profile and send to LLM to return them in the
    standard response format: question_id, question_type (MCQ or SUBJECTIVE), question_text,
    options (array for MCQ, null for SUBJECTIVE), correct_answer (for MCQ), marks.
    """
    if not raw_questions:
        return []
    client = _get_openai_client()
    if not client:
        logger.warning("No OpenAI key – returning predefined questions as-is")
        return raw_questions

    prompt = (
        "Below are assessment questions from a job profile. They may be in varied formats. "
        "Convert them to a single standard JSON array. Each object must have:\n"
        "  question_id (string, e.g. Q1, Q2),\n"
        "  question_type (MCQ or SUBJECTIVE),\n"
        "  question_text (string),\n"
        "  options (array of 4 strings for MCQ, null for SUBJECTIVE),\n"
        "  correct_answer (string for MCQ, null for SUBJECTIVE),\n"
        "  marks (integer)\n"
        "Preserve the meaning and content of each question. For MCQ ensure options and correct_answer are set. "
        "Return ONLY the JSON array, no other text.\n\n"
        f"{json.dumps(raw_questions, default=str, ensure_ascii=False)}"
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        out = _extract_json_array(raw)
        return out if out else raw_questions
    except Exception as exc:
        logger.exception("Format predefined questions via LLM failed | error=%s", str(exc))
        return raw_questions


def _generate_llm_questions(candidate: dict, job_profile: dict) -> list[dict]:
    """
    test_flag_llm = Y: use job profile (title, description, required_skills, min_exp) and
    candidate (skills, exp) to create a mixed questionnaire (MCQ + descriptive/one word) for B.Tech recruitment.
    """
    client = _get_openai_client()
    if not client:
        logger.error("Cannot generate LLM questions – no OpenAI key")
        return []

    skillset = job_profile.get("skillset_required_json") or {}
    mandatory = skillset.get("mandatory_skills") or []
    meta = job_profile.get("additional_metadata_json") or {}
    cand_skills = candidate.get("skillset_json") or {}
    cand_all_skills = cand_skills.get("all_skills") if isinstance(cand_skills, dict) else []
    if not isinstance(cand_all_skills, list):
        cand_all_skills = []
    cand_meta = candidate.get("metadata_details_json") or {}
    cand_exp = cand_meta.get("experience_years") if isinstance(cand_meta, dict) else None
    min_exp = meta.get("experience_min")
    max_exp = meta.get("experience_max")

    prompt = (
        "You are a technical recruiter creating an assessment for B.Tech recruitment. "
        "Generate a mixed-format questionnaire (MCQ and descriptive/one-word-answer questions).\n\n"
        f"Job title: {job_profile.get('title', 'Unknown')}\n"
        f"Job description: {job_profile.get('description', 'N/A')}\n"
        f"Required skills: {', '.join(mandatory) if mandatory else 'Not specified'}\n"
        f"Experience range: {min_exp}-{max_exp} years\n\n"
        f"Candidate skills: {json.dumps(cand_all_skills) if cand_all_skills else 'Not specified'}\n"
        f"Candidate experience (years): {cand_exp}\n\n"
        "Create exactly 10 questions: 5 MCQ and 5 subjective (short descriptive or one-word answers). "
        "Questions should be suitable for B.Tech hiring. "
        "Return ONLY a JSON array of objects with keys:\n"
        "  question_id (string like Q1..Q10),\n"
        "  question_type (MCQ or SUBJECTIVE),\n"
        "  question_text (string),\n"
        "  options (array of 4 strings for MCQ, null for SUBJECTIVE),\n"
        "  correct_answer (string for MCQ, null for SUBJECTIVE),\n"
        "  marks (integer: 2 for MCQ, 4 for SUBJECTIVE)\n"
        "No extra text."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        return _extract_json_array(raw)
    except Exception as exc:
        logger.exception("LLM question generation failed | job_id=%s error=%s", job_profile.get("id"), str(exc))
        return []


# ═════════════════════════════════════════════════════════════════════════════
# API 6 – Test Submit / Evaluate (questionnaire + responses → LLM composite score → tables + audit)
# ═════════════════════════════════════════════════════════════════════════════

def _get_llm_composite_score(
    questions: list[dict],
    answers_json: list[dict],
    job_profile: dict,
) -> dict:
    """
    Send full questionnaire and candidate responses to LLM; return composite score and
    recommendation (SELECT / REJECT) for candidate selection.
    """
    client = _get_openai_client()
    if not client:
        return {}

    qa_list = []
    answer_map = {str(a.get("question_id", "")): a.get("answer", "") for a in answers_json}
    for q in questions:
        qid = str(q.get("question_id", ""))
        qa_list.append({
            "question_id": qid,
            "question_type": q.get("question_type"),
            "question_text": q.get("question_text", ""),
            "correct_answer": q.get("correct_answer"),
            "marks": q.get("marks"),
            "candidate_answer": answer_map.get(qid, ""),
        })

    job_title = job_profile.get("title", "Role")
    job_desc = (job_profile.get("description") or "")[:500]
    meta = job_profile.get("additional_metadata_json") or {}
    test_cutoff = meta.get("test_cutoff") or 60

    prompt = (
        "You are an evaluator for a technical recruitment test. You will receive the full questionnaire "
        "and the candidate's responses. Produce a single composite assessment.\n\n"
        f"Job title: {job_title}\n"
        f"Job context: {job_desc}\n\n"
        "Questionnaire and candidate answers (JSON):\n"
        f"{json.dumps(qa_list, ensure_ascii=False)}\n\n"
        "Consider: correctness (especially MCQ), depth and relevance of subjective answers, clarity, "
        "and fit for the role. Return ONLY a JSON object with these exact keys:\n"
        "  composite_score (number 0-100, overall suitability)\n"
        "  recommendation (string: either \"SELECT\" or \"REJECT\")\n"
        "  justification (string, 1-2 sentences)\n"
        f"Use {test_cutoff} as a rough cutoff: composite_score >= {test_cutoff} should usually be SELECT.\n"
        "No extra text."
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
        logger.exception("LLM composite score failed | error=%s", str(exc))
        return {}


def evaluate_test(test_id: int, answers_json: list[dict],
                  submitted_by: str = "candidate") -> dict:

    logger.info("evaluate_test start | test_id=%s answers_count=%s submitted_by=%s", test_id, len(answers_json), submitted_by)
    audit_steps: list[dict] = []

    with get_connection() as conn:
        # ── Step 1: Load test and related rows ─────────────────────────────────
        test_row = fetch_one(
            "SELECT * FROM job_module.test_details_profiles WHERE id = %s",
            (test_id,),
            conn=conn,
        )
        if not test_row:
            raise ValueError(f"Test {test_id} not found")
        if test_row.get("status") in ("EVALUATED", "SUBMITTED"):
            raise ValueError(f"Test {test_id} already finalised (status={test_row['status']})")

        questions = test_row.get("questions_json") or []
        app_id = test_row["candidate_job_app_id"]
        audit_steps.append({"step": "load", "detail": "test and related rows loaded", "test_id": test_id, "app_id": app_id})

        app_row = fetch_one(
            "SELECT * FROM job_module.candidate_job_app_profiles WHERE id = %s",
            (app_id,),
            conn=conn,
        )
        job_profile = fetch_one(
            "SELECT * FROM job_module.job_profiles WHERE id = %s",
            (test_row["assigned_job_profile_id"],),
            conn=conn,
        )
        candidate = fetch_one(
            "SELECT * FROM job_module.candidates WHERE id = %s",
            (test_row["candidate_id"],),
            conn=conn,
        )
        logger.info("evaluate_test step=load | test_id=%s app_id=%s question_count=%s", test_id, app_id, len(questions))

        answer_map = {str(a["question_id"]): a["answer"] for a in answers_json}

        # ── Step 2: Per-question scoring (MCQ exact match + subjective LLM/heuristic) ──
        total_score = 0.0
        total_possible = 0.0
        evaluation_details: list[dict] = []

        for q in questions:
            qid = str(q.get("question_id", ""))
            q_type = q.get("question_type", "SUBJECTIVE")
            marks = float(q.get("marks", 2))
            total_possible += marks
            candidate_answer = answer_map.get(qid, "")

            if q_type == "MCQ":
                correct = str(q.get("correct_answer", "")).strip().lower()
                given = candidate_answer.strip().lower()
                earned = marks if given == correct else 0.0
                evaluation_details.append({
                    "question_id": qid,
                    "type": "MCQ",
                    "marks": marks,
                    "earned": earned,
                    "correct_answer": q.get("correct_answer"),
                    "candidate_answer": candidate_answer,
                })
                total_score += earned
            else:
                earned = _evaluate_subjective(q, candidate_answer, job_profile)
                evaluation_details.append({
                    "question_id": qid,
                    "type": "SUBJECTIVE",
                    "marks": marks,
                    "earned": earned,
                    "candidate_answer": candidate_answer,
                })
                total_score += earned

        pct = round((total_score / total_possible) * 100, 2) if total_possible > 0 else 0.0
        meta = (job_profile or {}).get("additional_metadata_json") or {}
        test_cutoff = float(meta.get("test_cutoff") or 60)
        audit_steps.append({
            "step": "per_question_scoring",
            "detail": "MCQ and subjective scoring completed",
            "total_score": total_score,
            "total_possible": total_possible,
            "percentage": pct,
            "test_cutoff": test_cutoff,
        })
        logger.info("evaluate_test step=per_question_scoring | test_id=%s total_score=%.2f total_possible=%.2f pct=%.2f cutoff=%.2f", test_id, total_score, total_possible, pct, test_cutoff)

        # ── Step 3: LLM composite score and recommendation ─────────────────────
        llm_result = _get_llm_composite_score(questions, answers_json, job_profile or {})
        if llm_result:
            composite_score = llm_result.get("composite_score", pct)
            recommendation = llm_result.get("recommendation", "REJECT")
            result_label = "PASS" if recommendation == "SELECT" else "FAIL"
            app_status = "SHORTLISTED" if result_label == "PASS" else "REJECTED"
            audit_steps.append({
                "step": "llm_composite",
                "detail": "LLM composite score and recommendation",
                "composite_score": composite_score,
                "recommendation": recommendation,
                "justification": llm_result.get("justification", ""),
                "result": result_label,
                "application_status": app_status,
            })
            logger.info("evaluate_test step=llm_composite | test_id=%s composite_score=%.2f recommendation=%s result=%s", test_id, composite_score, recommendation, result_label)
        else:
            result_label = "PASS" if pct >= test_cutoff else "FAIL"
            app_status = "SHORTLISTED" if result_label == "PASS" else "REJECTED"
            composite_score = pct
            audit_steps.append({
                "step": "fallback_cutoff",
                "detail": "LLM unavailable; using rule-based cutoff",
                "percentage": pct,
                "test_cutoff": test_cutoff,
                "result": result_label,
                "application_status": app_status,
            })
            logger.info("evaluate_test step=fallback_cutoff | test_id=%s pct=%.2f cutoff=%.2f result=%s", test_id, pct, test_cutoff, result_label)

        # Build consolidated Q&A for storage
        consolidate_qa = []
        for q in questions:
            qid = str(q.get("question_id", ""))
            consolidate_qa.append({
                **q,
                "candidate_answer": answer_map.get(qid, ""),
            })

        test_report = {
            "total_score": total_score,
            "total_possible": total_possible,
            "percentage": pct,
            "test_cutoff": test_cutoff,
            "result": result_label,
            "details": evaluation_details,
            "llm_composite_score": llm_result.get("composite_score") if llm_result else None,
            "llm_recommendation": llm_result.get("recommendation") if llm_result else None,
            "llm_justification": llm_result.get("justification") if llm_result else None,
            "audit_steps": audit_steps,
            "submitted_by": submitted_by,
        }

        # ── Step 4: Update test_details_profiles ───────────────────────────────
        execute(
            """
            UPDATE job_module.test_details_profiles
               SET answers_json = %s,
                   test_score = %s,
                   status = 'EVALUATED',
                   test_report_json = %s,
                   consolidate_qa_json = %s,
                   submitted_at = NOW()
             WHERE id = %s
            """,
            (
                Json(answers_json), composite_score,
                Json(test_report), Json(consolidate_qa),
                test_id,
            ),
            conn=conn,
        )
        audit_steps.append({"step": "update_test_details", "detail": "test_details_profiles updated", "status": "EVALUATED"})
        logger.info("evaluate_test step=update_test_details | test_id=%s status=EVALUATED test_score=%.2f", test_id, composite_score)

        # ── Step 5: Update candidate_job_app_profiles ─────────────────────────
        execute(
            """
            UPDATE job_module.candidate_job_app_profiles
               SET status = %s,
                   email_sent_flag = false,
                   email_status = 'PENDING'
             WHERE id = %s
            """,
            (app_status, app_id),
            conn=conn,
        )
        audit_steps.append({"step": "update_application", "detail": "candidate_job_app_profiles updated", "status": app_status})
        logger.info("evaluate_test step=update_application | app_id=%s status=%s", app_id, app_status)

        # ── Step 6: Create audit_report (full audit trail) ─────────────────────
        audit_steps.append({"step": "create_audit_report", "detail": "audit_report row created", "audit_report_id": None})
        audit_steps.append({"step": "create_email_log", "detail": "email_log row created", "email_log_id": None, "email_type": None})
        audit_payload = {
            **test_report,
            "audit_steps": audit_steps,
            "final_result": result_label,
            "final_application_status": app_status,
        }
        audit = fetch_one(
            """
            INSERT INTO job_module.audit_report
                   (candidate_job_app_id, test_id, report_json)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (app_id, test_id, Json(audit_payload)),
            conn=conn,
        )
        audit_id = audit["id"] if audit else None
        audit_steps[-2]["audit_report_id"] = audit_id
        logger.info("evaluate_test step=create_audit_report | audit_report_id=%s", audit_id)

        # ── Step 7: Create email_log ───────────────────────────────────────────
        email_type = "TEST_RESULT" if result_label == "PASS" else "REJECTION"
        cand_email = (candidate or {}).get("email", "")
        job_title = (job_profile or {}).get("title", "")
        stakeholders = (job_profile or {}).get("stakeholders_json") or {}
        cc_emails = stakeholders.get("cc_emails") or []

        email_log_row = fetch_one(
            """
            INSERT INTO job_module.email_log
                   (candidate_job_app_id, audit_id, test_id,
                    email_type, subject, body_json, email_to_json, email_sent)
            VALUES (%s, %s, %s,
                    %s, %s, %s, %s, false)
            RETURNING id
            """,
            (
                app_id, audit_id, test_id,
                email_type,
                f"Test Result for {job_title}",
                Json(test_report),
                Json({"to": [cand_email], "cc": cc_emails}),
            ),
            conn=conn,
        )
        email_log_id = email_log_row["id"] if email_log_row else None
        audit_steps[-1]["email_log_id"] = email_log_id
        audit_steps[-1]["email_type"] = email_type
        logger.info("evaluate_test step=create_email_log | email_log_id=%s email_type=%s", email_log_id, email_type)

        # Persist full audit trail (with ids) into test_report_json
        test_report["audit_steps"] = audit_steps
        execute(
            "UPDATE job_module.test_details_profiles SET test_report_json = %s WHERE id = %s",
            (Json(test_report), test_id),
            conn=conn,
        )
        logger.info("evaluate_test step=audit_persisted | test_id=%s audit_steps_count=%s", test_id, len(audit_steps))

    logger.info("evaluate_test done | test_id=%s score=%.2f result=%s application_status=%s audit_report_id=%s", test_id, composite_score, result_label, app_status, audit_id)
    return {
        "test_id": test_id,
        "score": composite_score,
        "result": result_label,
        "application_status": app_status,
        "audit_report_id": audit_id,
    }


def _evaluate_subjective(question: dict, answer: str, job_profile: dict) -> float:
    """
    Score a subjective answer.
    Uses LLM if available, otherwise falls back to keyword heuristic.
    """
    marks = float(question.get("marks", 4))
    if not answer or not answer.strip():
        return 0.0

    client = _get_openai_client()
    if client:
        return _llm_score_subjective(client, question, answer, marks)

    return _keyword_score_subjective(question, answer, job_profile, marks)


def _llm_score_subjective(client: OpenAI, question: dict, answer: str, marks: float) -> float:
    prompt = (
        f"You are a strict but fair technical evaluator.\n"
        f"Question ({marks} marks): {question.get('question_text', '')}\n"
        f"Candidate answer: {answer}\n\n"
        f"Evaluate on: factual correctness, structure, depth, foresight.\n"
        f"Return ONLY a JSON object: {{\"earned\": <float 0 to {marks}>}}\n"
        f"No extra text."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(raw)
        earned = float(result.get("earned", 0))
        return min(earned, marks)
    except Exception as exc:
        logger.error("LLM subjective scoring failed: %s", exc)
        return marks * 0.5


def _keyword_score_subjective(question: dict, answer: str, job_profile: dict, marks: float) -> float:
    answer_lower = answer.lower()
    word_count = len(answer.split())

    if word_count < 5:
        return marks * 0.1

    keywords: set[str] = set()
    req = (job_profile or {}).get("skillset_required_json") or {}
    for key in ("mandatory_skills", "good_to_have_skills"):
        for s in (req.get(key) or []):
            keywords.add(s.strip().lower())

    q_text = question.get("question_text", "").lower()
    for w in q_text.split():
        cleaned = w.strip(".,;:!?()[]\"'")
        if len(cleaned) > 3:
            keywords.add(cleaned)

    if not keywords:
        length_score = min(1.0, word_count / 50)
        return round(marks * length_score * 0.7, 2)

    matched = sum(1 for kw in keywords if kw in answer_lower)
    kw_score = matched / len(keywords)
    length_bonus = min(0.3, word_count / 100)

    return round(marks * min(1.0, kw_score + length_bonus), 2)
