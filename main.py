"""
DonutATS — Lightweight Applicant Tracking System
FastAPI backend with SQLite, resume parsing, scoring, and JD management.
"""
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager
import json
import os
import shutil

from database import (
    init_db, get_db, Candidate, Education, WorkExperience, ProjectExperience,
    RecruitmentCriteria, Job, Application, ResponseTemplate, CommunicationLog,
)
from resume_parser import parse_resume, save_uploaded_file
from scoring import score_candidate_for_job, rank_candidates
from jd_manager import create_job_with_jd, generate_jd
from email_ingest import scan_gmail_for_resumes
from tg_ingest import scan_telegram_resumes
from llm import smart_parse_resume, smart_score_candidate


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = next(get_db())
    try:
        _seed_defaults(db)
    finally:
        db.close()
    yield

app = FastAPI(title="DonutATS", version="1.0.0", lifespan=lifespan)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _seed_defaults(db: Session):
    """Pre-populate criteria and templates if tables are empty."""
    if db.query(RecruitmentCriteria).count() == 0:
        defaults = [
            ("values", "Owner Mindset", "Takes full ownership of outcomes, proactively flags mistakes, drives results without being asked", 1.0),
            ("values", "First Principles Thinking", "Thinks from fundamentals, questions assumptions, seeks depth over breadth", 0.8),
            ("values", "Learning Agility", "Adapts fast, learns continuously, thrives in ambiguity and rapid change", 0.8),
            ("values", "Crypto Native", "Understands blockchain, DeFi, tokens, wallets; thinks on-chain first", 0.7),
            ("values", "AI Native", "Uses AI tools daily, understands LLM capabilities and limitations, prompt-engineering fluent", 0.7),
            ("soft_skills", "Communication", "Clear written and verbal communication, proactively shares context", 0.6),
            ("soft_skills", "Collaboration", "Works well in cross-functional teams, gives and receives feedback well", 0.5),
            ("technical", "Go", "Golang proficiency — the Donut backend language", 0.8),
            ("technical", "Python", "Python proficiency — AI/data/scripting", 0.7),
            ("technical", "TypeScript/React", "Frontend skills for webapp development", 0.6),
            ("technical", "Rust/Solana", "Solana program development and Rust low-level skills", 0.7),
            ("technical", "Solidity/EVM", "EVM smart contract development", 0.6),
            ("technical", "ML/AI Engineering", "Machine learning, LLM fine-tuning, agent architecture", 0.8),
            ("technical", "System Design", "Distributed systems, microservices, high-concurrency architecture", 0.7),
            ("experience", "Industry Experience", "Relevant years of experience in target domain", 0.6),
            ("experience", "Startup Experience", "Experience in early-stage startups (0→1)", 0.5),
            ("education", "Education Level", "Degree level and institution quality (985/211 bonus)", 0.4),
            ("industry", "Crypto/Web3 Experience", "Hands-on crypto product or protocol experience", 0.6),
            ("industry", "FinTech/Trading Experience", "Financial technology or trading systems background", 0.5),
        ]
        for cat, name, desc, weight in defaults:
            db.add(RecruitmentCriteria(category=cat, name=name, description=desc, weight=weight))
        db.commit()

    if db.query(ResponseTemplate).count() == 0:
        templates = [
            ("interview_invite", "email", "面试邀请",
             "面试邀请 — {{candidate_name}}",
             """Hi {{candidate_name}},

感谢你对 Donut Labs {{job_title}} 职位的兴趣！

我们仔细看了你的背景，认为值得进一步了解。我们希望邀请你参加一次约 30 分钟的初步沟通。

可选时间如下（北京时间）：
- {{time_option_1}}
- {{time_option_2}}
- {{time_option_3}}

如果以上时间不方便，请告诉我你的可用时间。

期待与你交流！

Best,
{{sender_name}}
Donut Labs | {{sender_email}}"""),
            ("rejection", "email", "婉拒通知",
             "关于 {{job_title}} 职位的进展 — Donut Labs",
             """Hi {{candidate_name}},

感谢你对 Donut Labs {{job_title}} 职位的关注，以及你在面试中投入的时间。

经过慎重考虑，我们决定本轮不继续推进。这并不代表你的能力不够——我们目前阶段的需求非常具体，有时候只是时机和方向不太匹配。

如果你愿意，我们会将你的资料保留在人才库中，未来有更适合的机会时会联系你。

也欢迎持续关注 Donut 的产品进展——D0 的每一次更新，都是我们共同的努力。

祝你接下来的求职顺利！

Best,
{{sender_name}}
Donut Labs"""),
            ("offer_communication", "email", "Offer 沟通",
             "Donut Labs — Offer Letter — {{job_title}}",
             """Hi {{candidate_name}},

非常高兴向你发出正式的 offer！

**职位:** {{job_title}}
**部门:** {{department}}
**入职日期:** {{start_date}}
**薪资:** ¥{{salary}}/月（{{salary_term}}薪）
**期权:** {{equity}} 股（4年 vesting，1年 cliff）

完整的 offer letter 和入职指南会在你确认意向后发送。

请在 {{offer_expiry_date}} 前回复此邮件确认是否接受。

期待与你一起 build the future of agentic trading！

Best,
{{sender_name}}
Co-founder, Donut Labs"""),
        ]
        for ttype, channel, title, subject, content in templates:
            db.add(ResponseTemplate(type=ttype, channel=channel, title=title, subject=subject, content=content))
        db.commit()


# ─── Static files ───
if os.path.exists("templates"):
    app.mount("/static", StaticFiles(directory="templates"), name="static")


@app.get("/")
def serve_frontend():
    path = "templates/index.html"
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"message": "DonutATS API is running. Frontend not found."})


# ═══════════ CANDIDATE ENDPOINTS ═══════════

@app.get("/api/candidates")
def list_candidates(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    source: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: Optional[str] = "asc",
):
    query = db.query(Candidate)
    if search:
        q = f"%{search}%"
        query = query.filter(
            (Candidate.name.ilike(q)) |
            (Candidate.email.ilike(q)) |
            (Candidate.raw_text.ilike(q))
        )
    if source:
        query = query.filter(Candidate.source_channel == source)
    if date_from:
        query = query.filter(Candidate.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(Candidate.created_at <= datetime.fromisoformat(date_to))

    # Sorting
    sort_column = Candidate.created_at
    if sort_by:
        col_map = {
            "name": Candidate.name,
            "age": Candidate.age,
            "email": Candidate.email,
            "years_of_experience": Candidate.years_of_experience,
            "created_at": Candidate.created_at,
        }
        sort_column = col_map.get(sort_by, Candidate.created_at)
    if sort_dir == "desc":
        sort_column = sort_column.desc()

    total = query.count()
    candidates = query.order_by(sort_column).offset((page - 1) * per_page).limit(per_page).all()

    # Get scores for all candidates
    candidate_ids = [c.id for c in candidates]
    from sqlalchemy import func as sa_func
    scores = {}
    if candidate_ids:
        score_rows = db.query(
            Application.candidate_id,
            sa_func.avg(Application.score).label("avg_score")
        ).filter(Application.candidate_id.in_(candidate_ids)).group_by(Application.candidate_id).all()
        scores = {row[0]: round(row[1], 1) if row[1] else None for row in score_rows}

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [_candidate_dict(c, scores) for c in candidates],
    }


@app.get("/api/candidates/{candidate_id}")
def get_candidate(candidate_id: int, db: Session = Depends(get_db)):
    c = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not c:
        raise HTTPException(404, "Candidate not found")
    return _candidate_dict(c)


@app.post("/api/candidates/upload")
async def upload_resume(
    file: UploadFile = File(...),
    source: str = "manual",
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(400, "No file provided")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".pdf", ".docx", ".doc"):
        raise HTTPException(400, f"Unsupported format: {ext}. Only PDF and DOCX are supported.")

    filepath = save_uploaded_file(file, UPLOAD_DIR)
    parsed = smart_parse_resume(filepath)

    candidate = Candidate(
        name=parsed.get("name"),
        email=parsed.get("email"),
        phone=parsed.get("phone"),
        age=parsed.get("age"),
        expected_salary_min=parsed.get("expected_salary_min"),
        expected_salary_max=parsed.get("expected_salary_max"),
        years_of_experience=parsed.get("years_of_experience"),
        resume_path=filepath,
        source_channel=source,
        raw_text=parsed.get("raw_text", ""),
        skills_json=json.dumps(parsed.get("skills", []), ensure_ascii=False),
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)

    # Save education entries
    for edu in parsed.get("educations", []):
        if edu.get("school") or edu.get("degree"):
            db.add(Education(
                candidate_id=candidate.id,
                school=edu.get("school"),
                degree=edu.get("degree"),
                major=edu.get("major"),
                graduated_year=edu.get("graduated_year"),
                is_985211=edu.get("is_985211", False),
            ))

    # Save work experience
    for we in parsed.get("work_experiences", []):
        if we.get("company") or we.get("role"):
            db.add(WorkExperience(
                candidate_id=candidate.id,
                company=we.get("company"),
                role=we.get("role"),
                start_date=we.get("start_date"),
                end_date=we.get("end_date"),
                description=we.get("description"),
            ))

    # Save project experience
    for pe in parsed.get("project_experiences", []):
        if pe.get("project_name"):
            db.add(ProjectExperience(
                candidate_id=candidate.id,
                project_name=pe.get("project_name"),
                role=pe.get("role", ""),
                description=pe.get("description", ""),
                tech_stack=pe.get("tech_stack", ""),
            ))

    db.commit()
    return {"status": "ok", "candidate": _candidate_dict(db.query(Candidate).filter(Candidate.id == candidate.id).first())}


@app.post("/api/candidates/email-ingest")
def email_ingest(db: Session = Depends(get_db)):
    results = scan_gmail_for_resumes(db)
    return {"results": results}


@app.post("/api/candidates/tg-ingest")
def tg_ingest(db: Session = Depends(get_db)):
    results = scan_telegram_resumes(db)
    return {"results": results}


@app.delete("/api/candidates/{candidate_id}")
def delete_candidate(candidate_id: int, db: Session = Depends(get_db)):
    c = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not c:
        raise HTTPException(404, "Candidate not found")
    # Clean up resume file
    if c.resume_path and os.path.exists(c.resume_path):
        os.remove(c.resume_path)
    db.delete(c)
    db.commit()
    return {"status": "deleted"}


# ═══════════ CRITERIA ENDPOINTS ═══════════

@app.get("/api/criteria")
def list_criteria(category: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(RecruitmentCriteria)
    if category:
        query = query.filter(RecruitmentCriteria.category == category)
    return [{
        "id": c.id, "category": c.category, "name": c.name,
        "description": c.description, "weight": c.weight, "is_active": c.is_active,
    } for c in query.all()]


@app.post("/api/criteria")
def create_criteria(body: dict, db: Session = Depends(get_db)):
    c = RecruitmentCriteria(
        category=body.get("category", "technical"),
        name=body["name"],
        description=body.get("description", ""),
        weight=body.get("weight", 1.0),
        is_active=body.get("is_active", True),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"status": "created", "id": c.id}


@app.put("/api/criteria/{criteria_id}")
def update_criteria(criteria_id: int, body: dict, db: Session = Depends(get_db)):
    c = db.query(RecruitmentCriteria).filter(RecruitmentCriteria.id == criteria_id).first()
    if not c:
        raise HTTPException(404, "Criteria not found")
    for key in ("category", "name", "description", "weight", "is_active"):
        if key in body:
            setattr(c, key, body[key])
    db.commit()
    return {"status": "updated"}


@app.delete("/api/criteria/{criteria_id}")
def delete_criteria(criteria_id: int, db: Session = Depends(get_db)):
    c = db.query(RecruitmentCriteria).filter(RecruitmentCriteria.id == criteria_id).first()
    if not c:
        raise HTTPException(404, "Criteria not found")
    db.delete(c)
    db.commit()
    return {"status": "deleted"}


# ═══════════ JOB ENDPOINTS ═══════════

@app.get("/api/jobs")
def list_jobs(db: Session = Depends(get_db)):
    return [{
        "id": j.id, "title": j.title, "department": j.department,
        "status": j.status, "jd_content": j.jd_content,
        "criteria_json": json.loads(j.criteria_json) if j.criteria_json else {},
        "created_at": j.created_at.isoformat() if j.created_at else None,
    } for j in db.query(Job).order_by(Job.created_at.desc()).all()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    j = db.query(Job).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(404, "Job not found")
    return {
        "id": j.id, "title": j.title, "department": j.department,
        "status": j.status, "jd_content": j.jd_content,
        "criteria_json": json.loads(j.criteria_json) if j.criteria_json else {},
        "created_at": j.created_at.isoformat() if j.created_at else None,
    }


@app.post("/api/jobs")
def create_job(body: dict, db: Session = Depends(get_db)):
    job = create_job_with_jd(
        db,
        title=body["title"],
        department=body.get("department", "Engineering"),
        responsibilities=body.get("responsibilities"),
        requirements=body.get("requirements"),
        nice_to_have=body.get("nice_to_have"),
        criteria_weights=body.get("criteria_weights"),
    )
    return {
        "status": "created", "id": job.id,
        "jd_content": job.jd_content,
    }


@app.put("/api/jobs/{job_id}")
def update_job(job_id: int, body: dict, db: Session = Depends(get_db)):
    j = db.query(Job).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(404, "Job not found")
    for key in ("title", "department", "jd_content", "status"):
        if key in body:
            setattr(j, key, body[key])
    if "criteria_weights" in body:
        j.criteria_json = json.dumps(body["criteria_weights"])
    if "responsibilities" in body or "requirements" in body:
        j.jd_content = generate_jd(
            db, j.title, j.department,
            body.get("responsibilities"),
            body.get("requirements"),
            body.get("nice_to_have"),
        )
    db.commit()
    return {"status": "updated"}


@app.post("/api/jobs/{job_id}/generate-jd")
def regenerate_jd(job_id: int, db: Session = Depends(get_db)):
    j = db.query(Job).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(404, "Job not found")
    j.jd_content = generate_jd(db, j.title, j.department)
    db.commit()
    return {"status": "regenerated", "jd_content": j.jd_content}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    j = db.query(Job).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(404, "Job not found")
    db.delete(j)
    db.commit()
    return {"status": "deleted"}


# ═══════════ APPLICATION & SCORING ═══════════

@app.post("/api/applications")
def create_application(body: dict, db: Session = Depends(get_db)):
    candidate_id = body["candidate_id"]
    job_id = body["job_id"]
    existing = db.query(Application).filter(
        Application.candidate_id == candidate_id,
        Application.job_id == job_id,
    ).first()
    if existing:
        return {"status": "exists", "application_id": existing.id, "message": "Application already exists"}

    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    job = db.query(Job).filter(Job.id == job_id).first()
    if not candidate or not job:
        raise HTTPException(404, "Candidate or Job not found")

    result = smart_score_candidate(db, candidate, job)
    
    # Upsert application with LLM result
    app = db.query(Application).filter(
        Application.candidate_id == candidate_id,
        Application.job_id == job_id,
    ).first()

    if not app:
        app = Application(
            candidate_id=candidate_id,
            job_id=job_id,
            stage="screening",
        )
        db.add(app)

    app.score = result["total_score"]
    app.score_detail = json.dumps(result.get("detail", {}), ensure_ascii=False)
    if result.get("overall_reason"):
        app.notes = result.get("overall_reason", "")
    db.commit()
    
    return {"status": "created", **result}


@app.get("/api/applications")
def list_applications(
    db: Session = Depends(get_db),
    job_id: Optional[int] = None,
    stage: Optional[str] = None,
    score_min: Optional[float] = None,
):
    query = db.query(Application)
    if job_id:
        query = query.filter(Application.job_id == job_id)
    if stage:
        query = query.filter(Application.stage == stage)
    if score_min is not None:
        query = query.filter(Application.score >= score_min)

    apps = query.order_by(Application.score.desc()).all()
    return [{
        "id": a.id,
        "candidate_id": a.candidate_id,
        "candidate_name": a.candidate.name if a.candidate else "",
        "job_id": a.job_id,
        "job_title": a.job.title if a.job else "",
        "stage": a.stage,
        "score": a.score,
        "score_detail": json.loads(a.score_detail) if a.score_detail else {},
        "notes": a.notes,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    } for a in apps]


@app.put("/api/applications/{application_id}")
def update_application(application_id: int, body: dict, db: Session = Depends(get_db)):
    a = db.query(Application).filter(Application.id == application_id).first()
    if not a:
        raise HTTPException(404, "Application not found")
    for key in ("stage", "notes"):
        if key in body:
            setattr(a, key, body[key])
    a.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "updated"}


@app.post("/api/applications/{application_id}/score")
def rescore_application(application_id: int, db: Session = Depends(get_db)):
    a = db.query(Application).filter(Application.id == application_id).first()
    if not a:
        raise HTTPException(404, "Application not found")
    result = smart_score_candidate(db, a.candidate, a.job)
    a.score = result["total_score"]
    a.score_detail = json.dumps(result.get("detail", {}), ensure_ascii=False)
    if result.get("overall_reason"):
        a.notes = result.get("overall_reason", "")
    a.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "rescored", **result}


@app.get("/api/applications/ranked")
def ranked_applications(job_id: int = Query(...), db: Session = Depends(get_db)):
    return rank_candidates(db, job_id)


# ═══════════ TEMPLATE ENDPOINTS ═══════════

@app.get("/api/templates")
def list_templates(db: Session = Depends(get_db)):
    return [{
        "id": t.id, "type": t.type, "channel": t.channel,
        "title": t.title, "subject": t.subject, "content": t.content,
    } for t in db.query(ResponseTemplate).all()]


@app.post("/api/templates")
def create_template(body: dict, db: Session = Depends(get_db)):
    t = ResponseTemplate(
        type=body.get("type", "interview_invite"),
        channel=body.get("channel", "email"),
        title=body["title"],
        subject=body.get("subject"),
        content=body["content"],
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"status": "created", "id": t.id}


@app.put("/api/templates/{template_id}")
def update_template(template_id: int, body: dict, db: Session = Depends(get_db)):
    t = db.query(ResponseTemplate).filter(ResponseTemplate.id == template_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    for key in ("type", "channel", "title", "subject", "content"):
        if key in body:
            setattr(t, key, body[key])
    db.commit()
    return {"status": "updated"}


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    t = db.query(ResponseTemplate).filter(ResponseTemplate.id == template_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    db.delete(t)
    db.commit()
    return {"status": "deleted"}


@app.post("/api/templates/{template_id}/render")
def render_template(template_id: int, body: dict, db: Session = Depends(get_db)):
    """Preview rendered template with candidate data."""
    t = db.query(ResponseTemplate).filter(ResponseTemplate.id == template_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    candidate = db.query(Candidate).filter(Candidate.id == body.get("candidate_id")).first()
    job = db.query(Job).filter(Job.id == body.get("job_id")).first() if body.get("job_id") else None

    content = t.content
    substitutions = {
        "{{candidate_name}}": candidate.name or "Candidate" if candidate else "Candidate",
        "{{job_title}}": job.title if job else body.get("job_title", "Unknown Position"),
        "{{department}}": job.department if job else body.get("department", "Engineering"),
        "{{sender_name}}": body.get("sender_name", "Donut Labs HR"),
        "{{sender_email}}": body.get("sender_email", "careers@donutbrowser.ai"),
        "{{time_option_1}}": body.get("time_option_1", ""),
        "{{time_option_2}}": body.get("time_option_2", ""),
        "{{time_option_3}}": body.get("time_option_3", ""),
        "{{salary}}": body.get("salary", ""),
        "{{salary_term}}": body.get("salary_term", "14"),
        "{{equity}}": body.get("equity", ""),
        "{{start_date}}": body.get("start_date", ""),
        "{{offer_expiry_date}}": body.get("offer_expiry_date", ""),
    }
    for key, val in substitutions.items():
        content = content.replace(key, str(val))

    return {
        "subject": t.subject,
        "content": content,
        "rendered": True,
    }


# ═══════════ COMMUNICATION ENDPOINTS ═══════════

@app.post("/api/communications")
def send_communication(body: dict, db: Session = Depends(get_db)):
    """Record a communication sent to a candidate."""
    candidate_id = body["candidate_id"]
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(404, "Candidate not found")

    log = CommunicationLog(
        candidate_id=candidate_id,
        application_id=body.get("application_id"),
        type=body.get("type", "interview_invite"),
        channel=body.get("channel", "email"),
        content=body["content"],
        status="sent",
    )
    db.add(log)
    db.commit()
    return {"status": "sent", "id": log.id}


@app.get("/api/communications")
def list_communications(
    candidate_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    query = db.query(CommunicationLog)
    if candidate_id:
        query = query.filter(CommunicationLog.candidate_id == candidate_id)
    return [{
        "id": c.id, "candidate_id": c.candidate_id,
        "application_id": c.application_id,
        "type": c.type, "channel": c.channel,
        "content": c.content[:300] + ("..." if len(c.content) > 300 else ""),
        "sent_at": c.sent_at.isoformat() if c.sent_at else None,
        "status": c.status,
    } for c in query.order_by(CommunicationLog.sent_at.desc()).limit(50).all()]


# ═══════════ ADMIN ═══════════

@app.post("/api/admin/clear-all")
def clear_all_resumes(db: Session = Depends(get_db)):
    """Delete all candidates, their related records, and resume files."""
    import shutil
    from database import Education, WorkExperience, ProjectExperience, Application, CommunicationLog
    
    count = db.query(Candidate).count()
    
    # Delete resume files
    candidates = db.query(Candidate).all()
    for c in candidates:
        if c.resume_path and os.path.exists(c.resume_path):
            try:
                os.remove(c.resume_path)
            except OSError:
                pass
    
    # Cascade delete (rely on cascade rules)
    db.query(CommunicationLog).delete()
    db.query(Application).delete()
    db.query(ProjectExperience).delete()
    db.query(WorkExperience).delete()
    db.query(Education).delete()
    db.query(Candidate).delete()
    
    # Clean uploads directory
    upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
    if os.path.exists(upload_dir):
        shutil.rmtree(upload_dir)
        os.makedirs(upload_dir, exist_ok=True)
    
    # Reset DB sequences
    from sqlalchemy import text
    for table in ["candidates", "education", "work_experience", "project_experience", "applications", "communication_log"]:
        try:
            db.execute(text(f"DELETE FROM sqlite_sequence WHERE name='{table}'"))
        except:
            pass
    
    db.commit()
    return {"status": "cleared", "deleted_candidates": count}


# ═══════════ DASHBOARD ═══════════

@app.get("/api/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)):
    total_candidates = db.query(Candidate).count()
    total_jobs = db.query(Job).count()
    total_applications = db.query(Application).count()

    # By source
    source_counts = {}
    for row in db.query(Candidate.source_channel, __import__("sqlalchemy").func.count(Candidate.id)).group_by(Candidate.source_channel).all():
        source_counts[row[0] or "unknown"] = row[1]

    # By stage
    stage_counts = {}
    for row in db.query(Application.stage, __import__("sqlalchemy").func.count(Application.id)).group_by(Application.stage).all():
        stage_counts[row[0] or "unknown"] = row[1]

    # Recent candidates (last 7 days)
    from datetime import timedelta
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent = db.query(Candidate).filter(Candidate.created_at >= week_ago).count()

    return {
        "total_candidates": total_candidates,
        "total_jobs": total_jobs,
        "total_applications": total_applications,
        "recent_7d": recent,
        "by_source": source_counts,
        "by_stage": stage_counts,
    }


# ═══════════ HELPERS ═══════════

def _candidate_dict(c: Candidate, scores: dict = None) -> dict:
    score = (scores or {}).get(c.id, None)
    return {
        "id": c.id,
        "name": c.name,
        "email": c.email,
        "phone": c.phone,
        "age": c.age,
        "expected_salary_min": c.expected_salary_min,
        "expected_salary_max": c.expected_salary_max,
        "years_of_experience": c.years_of_experience,
        "source_channel": c.source_channel,
        "avg_score": score,
        "skills": json.loads(c.skills_json) if c.skills_json else [],
        "educations": [{
            "school": e.school, "degree": e.degree,
            "major": e.major, "graduated_year": e.graduated_year,
            "is_985211": e.is_985211,
        } for e in getattr(c, 'educations', [])],
        "work_experiences": [{
            "company": w.company, "role": w.role,
            "start_date": w.start_date, "end_date": w.end_date,
            "description": w.description,
        } for w in getattr(c, 'work_experiences', [])],
        "project_experiences": [{
            "project_name": p.project_name, "role": p.role,
            "description": p.description, "tech_stack": p.tech_stack,
        } for p in getattr(c, 'project_experiences', [])],
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)