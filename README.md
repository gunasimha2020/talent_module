# Talent & Job Module

A lightweight Python (FastAPI) module that provides APIs for **freelancer registration**, **job matching**, and **AI-powered skill assessment**. Designed to be called by an external chat orchestrator.

---

## Quick Start

```bash
python -m venv venv
venv\Scripts\activate            # Windows
pip install -r requirements.txt
copy .env.example .env           # Add your OPENAI_API_KEY
uvicorn app.main:app --reload --port 8000
```

Swagger UI: **http://localhost:8000/docs**

---

## Docker (single image, all endpoints)

Build and run the entire Talent Module as one container. All APIs (onboarding, employer, freelancer, jobs, tests) are served from this image.

**Build (from this directory):**
```bash
docker build -t talent-module:latest .
```

**Run locally:**
```bash
docker run -p 8000:8000 -e OPENAI_API_KEY=your-openai-api-key talent-module:latest
```

**Push to Docker Hub:**
```bash
# Log in (once)
docker login

# Tag with your Docker Hub username and repo name
docker tag talent-module:latest YOUR_DOCKERHUB_USERNAME/talent-module:latest

# Push
docker push YOUR_DOCKERHUB_USERNAME/talent-module:latest
```

Then pull and run anywhere:
```bash
docker pull YOUR_DOCKERHUB_USERNAME/talent-module:latest
docker run -p 8000:8000 -e OPENAI_API_KEY=your-key YOUR_DOCKERHUB_USERNAME/talent-module:latest
```

- **Health:** `GET http://localhost:8000/health`
- **API docs:** `http://localhost:8000/docs`

---

## API Documentation

### 1. Register Freelancer & Match Jobs

Registers the freelancer and returns matched job profiles in a single call.

**Endpoint:** `POST /onboarding/register-and-match`

#### Request

**Headers:**
| Header         | Value              |
|----------------|--------------------|
| Content-Type   | application/json   |

**Body:**
```json
{
  "name": "Jane Doe",
  "email": "jane@example.com",
  "phone": "+1234567890",
  "skills": ["python", "fastapi", "docker", "postgresql"],
  "experience_years": 4,
  "location": "Remote"
}
```

| Field              | Type       | Required | Description                          |
|--------------------|------------|----------|--------------------------------------|
| name               | string     | Yes      | Full name of the freelancer          |
| email              | string     | Yes      | Email address                        |
| phone              | string     | No       | Phone number                         |
| skills             | string[]   | Yes      | List of skills (lowercase preferred) |
| experience_years   | float      | Yes      | Total years of experience            |
| location           | string     | No       | Preferred work location              |

#### Responses

**`200 OK` — Freelancer registered with matched jobs found**
```json
{
  "freelancer": {
    "id": "ed523aaa-f2d5-45d5-a09d-d4e980cd6cac",
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+1234567890",
    "skills": ["python", "fastapi", "docker", "postgresql"],
    "experience_years": 4,
    "location": "Remote"
  },
  "matched_jobs": [
    {
      "id": "job-002",
      "title": "Backend Engineer",
      "company": "Centific",
      "description": "Design and maintain scalable REST APIs and microservices using Python and FastAPI. Work with PostgreSQL and Redis.",
      "required_skills": ["python", "fastapi", "postgresql", "redis", "docker"],
      "min_experience_years": 3,
      "location": "New York, NY",
      "salary_range": "$80,000 - $120,000",
      "match_score": 0.8
    },
    {
      "id": "job-004",
      "title": "DevOps Engineer",
      "company": "Centific",
      "description": "Manage CI/CD pipelines, container orchestration, and cloud infrastructure on AWS.",
      "required_skills": ["aws", "docker", "kubernetes", "terraform", "linux"],
      "min_experience_years": 3,
      "location": "San Francisco, CA",
      "salary_range": "$100,000 - $140,000",
      "match_score": 0.2
    }
  ]
}
```

**`200 OK` — Freelancer registered but no matching jobs**
```json
{
  "freelancer": {
    "id": "a1b2c3d4-...",
    "name": "John Smith",
    "email": "john@example.com",
    "phone": null,
    "skills": ["cobol", "fortran"],
    "experience_years": 10,
    "location": null
  },
  "matched_jobs": []
}
```

**`422 Unprocessable Entity` — Validation error (missing or invalid fields)**
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "name"],
      "msg": "Field required",
      "input": {}
    },
    {
      "type": "missing",
      "loc": ["body", "skills"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

---

### 2. Generate Test

Generates a 5-question test paper (using OpenAI) tailored to the selected job profile.

**Endpoint:** `POST /tests/generate`

#### Request

**Query Parameters:**
| Parameter      | Type   | Required | Description                        |
|----------------|--------|----------|------------------------------------|
| job_id         | string | Yes      | Job ID from matched jobs (e.g. `job-002`) |
| freelancer_id  | string | Yes      | Freelancer UUID from registration  |

**Example:**
```
POST /tests/generate?job_id=job-002&freelancer_id=ed523aaa-f2d5-45d5-a09d-d4e980cd6cac
```

#### Responses

**`200 OK` — Test generated successfully**
```json
{
  "test_id": "f34eaa9f-3482-4b5f-900e-9cf8fdbf5903",
  "job_id": "job-002",
  "freelancer_id": "ed523aaa-f2d5-45d5-a09d-d4e980cd6cac",
  "questions": [
    {
      "id": 1,
      "question": "Explain the difference between a REST API and a GraphQL API. When would you choose one over the other?"
    },
    {
      "id": 2,
      "question": "How would you design a rate-limiting middleware in FastAPI?"
    },
    {
      "id": 3,
      "question": "What are database indexes and how do they improve query performance in PostgreSQL?"
    },
    {
      "id": 4,
      "question": "Describe a caching strategy using Redis for a high-traffic API endpoint."
    },
    {
      "id": 5,
      "question": "How do you containerize a Python FastAPI application with Docker? Walk through the Dockerfile."
    }
  ]
}
```

**`404 Not Found` — Invalid job ID**
```json
{
  "detail": "Job job-999 not found"
}
```

**`422 Unprocessable Entity` — Missing query parameters**
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["query", "job_id"],
      "msg": "Field required"
    }
  ]
}
```

**`500 Internal Server Error` — OpenAI API key not configured**
```json
{
  "detail": "OPENAI_API_KEY is not set. Create a .env file with your key (see .env.example)."
}
```

---

### 3. Submit Test & Get Result

Submits the freelancer's answers for evaluation. The LLM scores each answer (2 marks each, total 10) based on **factual correctness**, **answer structure**, **subject familiarity**, and **foresightedness**.

**Endpoint:** `POST /tests/submit`

#### Request

**Headers:**
| Header         | Value              |
|----------------|--------------------|
| Content-Type   | application/json   |

**Body:**
```json
{
  "test_id": "f34eaa9f-3482-4b5f-900e-9cf8fdbf5903",
  "answers": [
    {"question_id": 1, "answer": "REST uses fixed endpoints with HTTP methods; GraphQL uses a single endpoint with flexible queries. REST is simpler for CRUD; GraphQL is better when clients need varying data shapes."},
    {"question_id": 2, "answer": "Use a middleware with a token bucket backed by Redis. Track request counts per API key with TTL-based expiry."},
    {"question_id": 3, "answer": "Indexes are B-tree structures that allow the database to find rows without scanning the entire table. They speed up WHERE, JOIN, and ORDER BY operations."},
    {"question_id": 4, "answer": "Cache frequently accessed data in Redis with a TTL. Use cache-aside pattern: check Redis first, fall back to DB, then populate cache."},
    {"question_id": 5, "answer": "Use a python:3.11-slim base image, copy requirements.txt, run pip install, copy app code, expose port 8000, and set CMD to uvicorn."}
  ]
}
```

| Field              | Type     | Required | Description                          |
|--------------------|----------|----------|--------------------------------------|
| test_id            | string   | Yes      | Test UUID from `/tests/generate`     |
| answers            | array    | Yes      | Array of 5 answer objects            |
| answers[].question_id | int   | Yes      | Question ID (1-5)                    |
| answers[].answer   | string   | Yes      | Freelancer's answer text             |

#### Responses

**`200 OK` — Score 7-10: Wait for Notification**
```json
{
  "score": "8.5 / 10",
  "verdict": "Wait for Notification",
  "verdict_description": "The candidate has demonstrated strong competence. Please wait for further notification from the project coordinator.",
  "training_suggestions": []
}
```

**`200 OK` — Score 4-6.5: Training Suggested (with training recommendations)**
```json
{
  "score": "5.5 / 10",
  "verdict": "Training Suggested",
  "verdict_description": "The candidate shows potential but needs further training in key areas. Please complete the suggested training modules below before re-assessment.",
  "training_suggestions": [
    {
      "topic": "Advanced PostgreSQL Indexing & Query Optimization",
      "reason": "The candidate's understanding of database indexing lacked depth on composite indexes, partial indexes, and execution plans."
    },
    {
      "topic": "Redis Caching Patterns for Distributed Systems",
      "reason": "The caching answer missed cache invalidation strategies and did not address consistency concerns in distributed environments."
    },
    {
      "topic": "Docker Multi-Stage Builds & Production Best Practices",
      "reason": "The Dockerfile walkthrough was basic and did not cover multi-stage builds, layer optimization, or security hardening."
    }
  ]
}
```

**`200 OK` — Score 0-3.5: Reject**
```json
{
  "score": "2.5 / 10",
  "verdict": "Reject",
  "verdict_description": "The candidate did not demonstrate sufficient knowledge or competence for this role. We recommend exploring other opportunities.",
  "training_suggestions": []
}
```

**`404 Not Found` — Invalid test ID**
```json
{
  "detail": "Test 00000000-0000-0000-0000-000000000000 not found"
}
```

**`422 Unprocessable Entity` — Validation error (missing fields)**
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "test_id"],
      "msg": "Field required"
    }
  ]
}
```

---

## Verdict Scoring Rules

| Total Marks | Verdict                  | Description                                                                 |
|-------------|--------------------------|-----------------------------------------------------------------------------|
| 0 – 3.5     | **Reject**               | Insufficient knowledge. Recommend exploring other opportunities.           |
| 4 – 6.5     | **Training Suggested**   | Shows potential. Training recommendations provided for weak areas.         |
| 7 – 10      | **Wait for Notification**| Strong competence. Await notification from the project coordinator.        |

Each question is scored on 4 criteria (max 2 marks per question):
- **Factual Correctness** — Is the answer technically accurate?
- **Answer Structure** — Is the answer well-organized and clear?
- **Subject Familiarity** — Does the candidate show depth of knowledge?
- **Foresightedness** — Awareness of edge cases, trade-offs, and future considerations?

---

## Typical Flow (Chat Orchestrator → Module)

```
1. POST /onboarding/register-and-match     → Register + get matched jobs
2. POST /tests/generate?job_id=...&...     → Generate 5-question test
3. POST /tests/submit                      → Submit answers → score + verdict
```

---

## Data Storage

All data is stored as JSON files under `app/data/`:
- `jobs.json` — 8 pre-seeded Centific job profiles
- `freelancers.json` — created at runtime on registration
- `tests.json` — generated test papers
- `results.json` — evaluation results

These can be replaced with a database later.
