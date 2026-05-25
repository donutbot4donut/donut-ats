"""
Scoring engine: match candidates to jobs using weighted multi-dimensional criteria.
Returns 0-100 composite score with per-criteria breakdown.
"""
from typing import Optional
from sqlalchemy.orm import Session
from database import Candidate, Job, Application, RecruitmentCriteria
import json


# Company context for Donut Labs
COMPANY_CONTEXT = {
    "industry": "AI x Crypto FinTech",
    "product": "D0 Agent — AI-powered autonomous trading platform",
    "mission": "Build the market infrastructure for zero-human funds",
    "values": [
        "Owner Mindset — own outcomes, flag mistakes",
        "First Principles Thinking — depth over breadth",
        "Learning Agility — adapt fast, learn continuously",
        "Overcommunicated — surface problems immediately",
        "Directed Progress — ship working code over perfect code",
    ],
}

CORE_TECH_STACK = {"Go", "Python", "TypeScript", "Rust", "Solidity", "React", "PostgreSQL", "Kubernetes", "Solana", "Move"}


def get_active_criteria(db: Session) -> list:
    return db.query(RecruitmentCriteria).filter(RecruitmentCriteria.is_active == True).all()


def skill_keyword_score(candidate_skills: list[str], job_keywords: list[str]) -> float:
    """Simple keyword overlap score (0-100)."""
    if not job_keywords:
        return 50.0
    cset = set(s.lower() for s in candidate_skills)
    jset = set(k.lower() for k in job_keywords)
    overlap = cset & jset
    return min(100.0, (len(overlap) / len(jset)) * 100.0)


def education_score(education, desired_degree: Optional[str] = None) -> float:
    """Score education level (0-100). Accepts dict or SQLAlchemy object."""
    score = 0.0
    if isinstance(education, dict):
        degree = (education.get("degree") or "").lower()
        is_985 = education.get("is_985211", False)
    else:
        degree = (getattr(education, "degree", "") or "").lower()
        is_985 = getattr(education, "is_985211", False)

    if "博士" in degree or "phd" in degree:
        score = 95.0
    elif "硕士" in degree or "master" in degree:
        score = 80.0
    elif "本科" in degree or "bachelor" in degree:
        score = 60.0
    elif "大专" in degree:
        score = 40.0
    else:
        score = 30.0

    if is_985:
        score += 10.0

    return min(100.0, score)


def experience_years_score(years: Optional[int], required_min: int = 0, required_max: int = 99) -> float:
    """Score years of experience."""
    if years is None:
        return 30.0
    if years < required_min:
        return max(10.0, (years / max(1, required_min)) * 50.0)
    if years > required_max:
        return max(60.0, 100.0 - (years - required_max) * 5)
    return 70.0 + (years - required_min) / max(1, required_max - required_min + 1) * 30.0


def values_score(raw_text: str) -> float:
    """Heuristic values alignment score based on resume text patterns."""
    score = 40.0  # base

    patterns = {
        "open_source": r"open\s*source|github\.com|开源|贡献|community|contribution",
        "ownership": r"独立负责|owner|ownership|end.to.end|全栈|从零|from scratch",
        "learning": r"自学|self.taught|持续学习|coursera|udemy|certification|论文|paper",
        "communication": r"跨部门|cross.functional|collabora|团队合作|沟通",
        "crypto_native": r"web3|blockchain|crypto|defi|nft|token|smart contract|wallet",
    }

    bonuses = {
        "open_source": 15,
        "ownership": 15,
        "learning": 10,
        "communication": 10,
        "crypto_native": 10,
    }

    for key, pattern in patterns.items():
        if re.search(pattern, raw_text, re.IGNORECASE):
            score += bonuses[key]

    return min(100.0, score)


import re  # need at module level


def score_candidate_for_job(
    db: Session,
    candidate: Candidate,
    job: Job,
    save: bool = True,
) -> dict:
    """
    Score a candidate against a job. Returns score and detailed breakdown.
    If save=True, upserts an Application record.
    """
    all_criteria = get_active_criteria(db)
    job_weights = {}
    if job.criteria_json:
        try:
            job_weights = json.loads(job.criteria_json)
        except json.JSONDecodeError:
            job_weights = {}

    candidate_skills = json.loads(candidate.skills_json) if candidate.skills_json else []
    educations = candidate.educations or []
    top_edu = educations[0] if educations else {}

    detail = {}
    total_weight = 0.0
    weighted_sum = 0.0

    job_title_lower = (job.title or "").lower()
    job_jd_lower = (job.jd_content or "").lower()

    for c in all_criteria:
        weight = job_weights.get(str(c.id), c.weight)
        if weight <= 0:
            continue

        # Compute sub-score based on category
        cat = c.category.lower()
        if cat == "technical":
            # Extract relevant keywords from criteria name/desc
            tech_kws = set()
            for kw in CORE_TECH_STACK:
                if kw.lower() in (c.name + c.description).lower() or kw.lower() in job_jd_lower:
                    tech_kws.add(kw)
            sub_score = skill_keyword_score(candidate_skills, list(tech_kws) if tech_kws else list(CORE_TECH_STACK))

        elif cat == "education":
            sub_score = education_score(top_edu)

        elif cat == "experience":
            sub_score = experience_years_score(candidate.years_of_experience)

        elif cat == "values":
            sub_score = values_score(candidate.raw_text or "")

        elif cat == "soft_skills":
            # Heuristic from resume patterns
            soft_patterns = {
                "collaboration": r"团队|team|collaborat|配合",
                "leadership": r"leader|lead|带领|负责|manage",
                "communication": r"沟通|communicat|跨部门|cross.functional",
            }
            sub_score = 40.0
            for k, p in soft_patterns.items():
                if re.search(p, candidate.raw_text or "", re.IGNORECASE):
                    sub_score += 15.0
            sub_score = min(100.0, sub_score)

        elif cat == "industry":
            industry_kws = ["blockchain", "crypto", "defi", "web3", "trading", "finance", "金融", "交易"]
            sub_score = skill_keyword_score(candidate_skills, industry_kws)

        else:
            sub_score = 50.0  # default neutral

        detail[c.name] = {
            "score": round(sub_score, 1),
            "weight": weight,
            "category": c.category,
        }
        weighted_sum += sub_score * weight
        total_weight += weight

    final_score = round(weighted_sum / total_weight, 1) if total_weight > 0 else 50.0

    # Upsert application
    app = db.query(Application).filter(
        Application.candidate_id == candidate.id,
        Application.job_id == job.id,
    ).first()

    if not app:
        app = Application(
            candidate_id=candidate.id,
            job_id=job.id,
            stage="screening",
        )
        db.add(app)

    app.score = final_score
    app.score_detail = json.dumps(detail, ensure_ascii=False)
    db.commit()

    return {
        "candidate_id": candidate.id,
        "candidate_name": candidate.name,
        "job_id": job.id,
        "job_title": job.title,
        "total_score": final_score,
        "detail": detail,
    }


def rank_candidates(db: Session, job_id: int) -> list[dict]:
    """Return all candidates ranked by score for a job."""
    apps = db.query(Application).filter(Application.job_id == job_id).order_by(Application.score.desc()).all()
    results = []
    for app in apps:
        results.append({
            "application_id": app.id,
            "candidate_id": app.candidate_id,
            "candidate_name": app.candidate.name if app.candidate else "Unknown",
            "stage": app.stage,
            "score": app.score,
            "score_detail": json.loads(app.score_detail) if app.score_detail else {},
        })
    return results