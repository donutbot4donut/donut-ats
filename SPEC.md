# DonutATS — Lightweight Applicant Tracking System

## Tech Stack
- Backend: Python FastAPI + SQLite (with SQLAlchemy)
- Frontend: Single HTML page (Bootstrap 5 CDN) + vanilla JS
- PDF Parsing: pdfplumber
- DOCX Parsing: python-docx
- Email: Gmail API (or IMAP fallback)
- TG: python-telegram-bot or telethon

## Database Schema (SQLite)

### candidates
- id (INTEGER PK AUTOINCREMENT)
- name (TEXT)
- email (TEXT)
- phone (TEXT)
- age (INTEGER, nullable)
- gender (TEXT, nullable)
- current_location (TEXT, nullable)
- expected_salary_min (INTEGER, nullable)
- expected_salary_max (INTEGER, nullable)
- years_of_experience (INTEGER, nullable)
- resume_path (TEXT) — local file path
- source_channel (TEXT) — e.g. "gmail", "telegram", "manual", "bosszhipin", "linkedin"
- raw_text (TEXT) — full parsed text for search
- created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)

### education
- id (INTEGER PK)
- candidate_id (FK → candidates)
- school (TEXT)
- degree (TEXT) — "大专", "本科", "硕士", "博士"
- major (TEXT)
- graduated_year (INTEGER)
- is_985211 (BOOLEAN, default false)

### work_experience
- id (INTEGER PK)
- candidate_id (FK → candidates)
- company (TEXT)
- role (TEXT)
- start_date (TEXT)
- end_date (TEXT)
- description (TEXT)

### project_experience
- id (INTEGER PK)
- candidate_id (FK → candidates)
- project_name (TEXT)
- role (TEXT)
- description (TEXT)
- tech_stack (TEXT)

### recruitment_criteria
- id (INTEGER PK)
- category (TEXT) — "values", "soft_skills", "technical", "industry"
- name (TEXT) — e.g. "价值观匹配", "学习能力", "AI/ML经验", "Crypto经验"
- description (TEXT)
- weight (REAL, default 1.0)
- is_active (BOOLEAN, default true)
- created_at (TIMESTAMP)

### jobs
- id (INTEGER PK)
- title (TEXT) — e.g. "资深后端工程师"
- department (TEXT)
- jd_content (TEXT) — full JD markdown
- status (TEXT) — "draft", "active", "closed"
- criteria_json (TEXT) — JSON array of criteria weights specific to this job
- created_at (TIMESTAMP)

### applications
- id (INTEGER PK)
- candidate_id (FK → candidates)
- job_id (FK → jobs)
- stage (TEXT) — "screening", "phone_interview", "technical_interview", "final_interview", "offer", "rejected", "withdrawn"
- score (REAL, nullable) — overall match score
- score_detail (TEXT, nullable) — JSON of per-criteria scores
- notes (TEXT)
- created_at (TIMESTAMP)
- updated_at (TIMESTAMP)

### response_templates
- id (INTEGER PK)
- type (TEXT) — "interview_invite", "rejection", "offer_communication", "screening_questions"
- channel (TEXT) — "email", "telegram", "linkedin", "slack"
- title (TEXT)
- subject (TEXT, nullable) — email subject if applicable
- content (TEXT) — template with {{variables}}
- created_at (TIMESTAMP)

### communication_log
- id (INTEGER PK)
- candidate_id (FK → candidates)
- application_id (FK, nullable)
- type (TEXT) — same as template type
- channel (TEXT)
- content (TEXT) — rendered message
- sent_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
- status (TEXT) — "sent", "failed", "draft"

## API Endpoints (RESTful, prefix /api)

### Resume Management
- `GET /api/candidates` — list, with pagination & filters (source, date range, keyword search)
- `GET /api/candidates/{id}` — detail with education, work, projects
- `POST /api/candidates/upload` — manual resume upload (PDF/DOCX), auto-parse
- `POST /api/candidates/email-ingest` — trigger Gmail scan for new resumes
- `POST /api/candidates/tg-ingest` — trigger Telegram scan for new resumes
- `DELETE /api/candidates/{id}` — delete candidate

### Criteria Management
- `GET /api/criteria` — list all criteria
- `POST /api/criteria` — create criteria
- `PUT /api/criteria/{id}` — update criteria
- `DELETE /api/criteria/{id}` — delete

### Job Management
- `GET /api/jobs` — list jobs
- `POST /api/jobs` — create job (generates JD using criteria + company context)
- `GET /api/jobs/{id}` — job detail
- `PUT /api/jobs/{id}` — update job
- `POST /api/jobs/{id}/generate-jd` — regenerate JD with AI assistance (use LLM via API call)
- `DELETE /api/jobs/{id}` — delete

### Application & Scoring
- `POST /api/applications` — create application (match candidate to job)
- `GET /api/applications` — list, with filters (job_id, stage, score min/max)
- `PUT /api/applications/{id}` — update stage/notes
- `POST /api/applications/{id}/score` — trigger scoring for this application
- `GET /api/applications/ranked?job_id=X` — ranked candidates for a job

### Template Management
- `GET /api/templates` — list templates
- `POST /api/templates` — create template
- `PUT /api/templates/{id}` — update
- `DELETE /api/templates/{id}` — delete
- `POST /api/templates/{id}/render` — render with candidate data, get preview

### Communication
- `POST /api/communications` — send message to candidate (uses template or free text)
- `GET /api/communications?candidate_id=X` — communication history for candidate

### Dashboard
- `GET /api/dashboard/stats` — overview statistics (total candidates, by stage, by source, by job)

## Resume Parsing Logic (pdfplumber + python-docx)

Parse the following fields intelligently:
1. **Name** — usually first line or near "姓名"
2. **Email** — regex pattern
3. **Phone** — Chinese (+86) and international format regex
4. **Age** — explicit or calculate from birth year
5. **Education** — school name, degree, major, graduation year. Detect 985/211 flags
6. **Work Experience** — company names, roles, date ranges, descriptions
7. **Project Experience** — project names, tech stack keywords, descriptions
8. **Expected Salary** — look for "期望薪资" patterns (e.g., "15K-20K", "面议")
9. **Years of Experience** — calculate from work history
10. **Skills** — extract technical keywords (Python, Go, Solidity, Rust, ML, etc.)

Use regex + keyword matching. No LLM needed for parsing — keep it fast and deterministic.

## Scoring Engine

Calculate match score (0-100) for each candidate-job pair:

1. Load active `recruitment_criteria` as base weights
2. Load job-specific `criteria_json` as job weights (overrides base)
3. For each criteria, compute a sub-score (0-100):
   - **Education match**: degree level match, 985/211 bonus, major relevance
   - **Skill match**: keyword overlap between resume skills and job requirements
   - **Experience match**: years of experience vs requirement, industry relevance
   - **Values/Soft skills**: heuristic based on resume patterns (e.g., open source contributions = ownership culture)
4. Weighted sum → final score
5. Store score_detail as JSON: `{"criteria_name": {"score": X, "weight": Y, "reason": "..."}}`

## Frontend (Single Page)

Build an `index.html` with Bootstrap 5 CDN. Tabs/sections:
1. **Dashboard** — stats cards (total candidates, by stage, by source) + recent activity
2. **Candidates** — table with search/filter, click for detail modal with all parsed info
3. **Jobs** — job list with JD preview, CRUD, scoring trigger
4. **Applications** — Kanban-like board by stage, drag or button to move stages
5. **Templates** — template CRUD with variable hints and preview
6. **Settings** — criteria management, email/TG config

All using fetch() to call the backend API.

## Email Ingestion (Gmail)

- Use Gmail API with OAuth or app password
- Scan for unread emails with PDF/DOCX attachments
- Download and parse attachments
- Mark as read after processing
- Config via settings page (credentials stored in local config file, not in DB)

## Telegram Ingestion
- Use Telegram Bot API
- Poll for new messages with documents (PDF/DOCX)
- Download files, parse, and add to candidates
- Support forwarding resumes to a dedicated TG bot

## Startup
```bash
cd /app/workspace/agents/dono/workspace/memory/ats
pip install fastapi uvicorn sqlalchemy pdfplumber python-docx aiosqlite
python main.py
```

Access at http://localhost:8000

## Design Philosophy
- Lightweight: one Python file for main logic, modular imports for parsing/scoring
- Offline-first: SQLite, no cloud dependencies
- Fast parsing: regex + heuristics, no LLM calls for resume parsing
- Configurable scoring: weights adjustable via UI, no hardcoded rules
- Progressive: start simple, add features as needed
