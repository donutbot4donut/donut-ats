"""
LLM-powered resume parsing and candidate scoring.
Uses OpenRouter API (OpenAI-compatible endpoint).
Fallback: regex parser / heuristic scoring if API key not set.
"""
import os
import json
import urllib.request
from typing import Optional

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Models: fast/cheap for parsing, smarter for scoring
PARSE_MODEL = "google/gemini-2.5-flash-lite"
SCORE_MODEL = "google/gemini-2.5-flash"


def _call_llm(model: str, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> Optional[str]:
    """Call OpenRouter LLM API. Returns response text or None on failure."""
    if not OPENROUTER_API_KEY:
        return None

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": 4096,
    }).encode("utf-8")

    req = urllib.request.Request(OPENROUTER_URL, data=body, headers={
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://donutlabs.dev",
        "X-Title": "DonutATS",
    })

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[LLM] API error: {e}")
        return None


# ─── Resume Parsing ───

PARSE_SYSTEM_PROMPT = """You are a resume parsing engine. Extract structured information from the resume text.
Output ONLY valid JSON, no other text. The JSON must have these fields:

{
  "name": "Full name (Chinese or English)",
  "email": "email@example.com or null",
  "phone": "phone number string or null",
  "age": integer or null,
  "gender": "男/女/Other or null",
  "current_location": "city or null",
  "expected_salary_min": integer or null,
  "expected_salary_max": integer or null,
  "education_level": "博士/硕士/本科/大专/高中 or null",
  "school": "most recent school name or null",
  "major": "major or null",
  "graduated_year": integer or null,
  "is_985211": true/false,
  "years_of_experience": integer or null,
  "skills": ["skill1", "skill2", ...],
  "work_experiences": [
    {"company": "name", "role": "title", "start_date": "YYYY", "end_date": "YYYY or 至今", "description": "summary"}
  ],
  "project_experiences": [
    {"project_name": "name", "description": "summary", "tech_stack": "technologies used"}
  ],
  "languages": ["language1", ...],
  "certificates": ["cert1", ...],
  "summary": "one-sentence professional summary"
}

Rules:
- Infer age from birth year or explicit mention
- Detect 985/211 universities: 北京大学, 清华大学, 复旦大学, 上海交通大学, 浙江大学, 南京大学, 中国科学技术大学, 哈尔滨工业大学, 西安交通大学, 中国人民大学, 南开大学, 天津大学, 华中科技大学, 武汉大学, 中山大学, 四川大学, 电子科技大学 etc. Also 上海财经大学, 中央财经大学, 北京邮电大学, 西安电子科技大学 etc are 211.
- Salary: if mentioned as "15K-20K", convert to 15000-20000; if "年薪30万", convert to monthly ~25000
- Years of experience: calculate from work history dates
- Skills: extract ALL technical skills mentioned, be thorough
- For missing fields, use null or empty arrays
- Return ONLY the JSON object, no markdown wrapping"""


def llm_parse_resume(text: str) -> Optional[dict]:
    """
    Use LLM to parse resume text into structured data.
    Falls back to None if LLM unavailable (caller should use regex parser).
    """
    if not OPENROUTER_API_KEY or not text or len(text) < 50:
        return None

    # Truncate very long texts to save tokens
    truncated = text[:8000] if len(text) > 8000 else text

    result = _call_llm(PARSE_MODEL, PARSE_SYSTEM_PROMPT, truncated, temperature=0.0)
    if not result:
        return None

    # Clean up response (remove markdown code blocks if present)
    result = result.strip()
    if result.startswith("```"):
        result = result.split("\n", 1)[-1]
        if result.endswith("```"):
            result = result[:-3]
        result = result.strip()
    if result.startswith("json"):
        result = result[4:].strip()

    try:
        return json.loads(result)
    except json.JSONDecodeError:
        print(f"[LLM] Failed to parse JSON response: {result[:200]}")
        return None


# ─── Scoring ───

SCORE_SYSTEM_PROMPT = """You are an expert recruitment evaluator for Donut Labs, an AI-native crypto fintech startup building autonomous trading agents (D0).

Evaluate how well a candidate matches a specific job. Score each criterion from 0-100 and provide a brief reason.

Output ONLY valid JSON:
{
  "overall_score": 0-100,
  "overall_reason": "one paragraph summary",
  "strengths": ["strength1", ...],
  "weaknesses": ["weakness1", ...],
  "criteria_scores": {
    "criteria_name": {"score": 0-100, "reason": "one sentence"}
  }
}

Donut Labs values: Owner Mindset, First Principles Thinking, Learning Agility, Crypto Native, AI Native.
Be honest and critical. Don't inflate scores. A score of 70+ means strong match."""


def llm_score_candidate(
    candidate_name: str,
    candidate_summary: str,
    job_title: str,
    job_description: str,
    criteria_list: list[dict],
) -> Optional[dict]:
    """
    Use LLM to score a candidate against a job.
    Returns dict with overall_score, criteria_scores, strengths, weaknesses.
    """
    if not OPENROUTER_API_KEY:
        return None

    criteria_text = "\n".join(
        f"- [{c['category']}] {c['name']}: {c.get('description', '')} (weight: {c.get('weight', 1.0)})"
        for c in criteria_list
    )

    user_prompt = f"""## Job
Title: {job_title}
Description: {job_description[:1500]}

## Candidate
Name: {candidate_name}
Profile: {candidate_summary[:2000]}

## Scoring Criteria
{criteria_text}

Evaluate the candidate against each criterion. Return JSON."""

    result = _call_llm(SCORE_MODEL, SCORE_SYSTEM_PROMPT, user_prompt, temperature=0.2)
    if not result:
        return None

    result = result.strip()
    if result.startswith("```"):
        result = result.split("\n", 1)[-1]
        if result.endswith("```"):
            result = result[:-3]
        result = result.strip()
    if result.startswith("json"):
        result = result[4:].strip()

    try:
        return json.loads(result)
    except json.JSONDecodeError:
        print(f"[LLM] Failed to parse score JSON: {result[:200]}")
        return None


# ─── Hybrid helpers ───

def smart_parse_resume(file_path: str) -> dict:
    """
    Parse resume using LLM first, fall back to regex parser.
    """
    from resume_parser import extract_text, parse_resume

    text = extract_text(file_path)
    if not text:
        return {"error": "Could not extract text", "raw_text": ""}

    # Try LLM first
    llm_result = llm_parse_resume(text)
    if llm_result:
        return {
            "raw_text": text,
            "name": llm_result.get("name"),
            "email": llm_result.get("email"),
            "phone": llm_result.get("phone"),
            "age": llm_result.get("age"),
            "gender": llm_result.get("gender"),
            "current_location": llm_result.get("current_location"),
            "expected_salary_min": llm_result.get("expected_salary_min"),
            "expected_salary_max": llm_result.get("expected_salary_max"),
            "years_of_experience": llm_result.get("years_of_experience"),
            "skills": llm_result.get("skills", []),
            "educations": [{
                "school": llm_result.get("school"),
                "degree": llm_result.get("education_level"),
                "major": llm_result.get("major"),
                "graduated_year": llm_result.get("graduated_year"),
                "is_985211": llm_result.get("is_985211", False),
            }] if llm_result.get("school") or llm_result.get("education_level") else [],
            "work_experiences": llm_result.get("work_experiences", []),
            "project_experiences": llm_result.get("project_experiences", []),
            "summary": llm_result.get("summary", ""),
            "_parser": "llm",
        }

    # Fall back to regex parser
    result = parse_resume(file_path)
    result["_parser"] = "regex"
    return result


def smart_score_candidate(db, candidate, job) -> dict:
    """
    Score using LLM first, fall back to heuristic scoring.
    """
    from database import RecruitmentCriteria
    from scoring import score_candidate_for_job as heuristic_score
    import json

    criteria = db.query(RecruitmentCriteria).filter(RecruitmentCriteria.is_active == True).all()

    # Build candidate summary
    parts = []
    if candidate.name:
        parts.append(f"Name: {candidate.name}")
    if candidate.email:
        parts.append(f"Email: {candidate.email}")
    if candidate.years_of_experience:
        parts.append(f"Experience: {candidate.years_of_experience} years")
    if candidate.skills_json:
        skills = json.loads(candidate.skills_json)
        if skills:
            parts.append(f"Skills: {', '.join(skills)}")
    if candidate.educations:
        for e in candidate.educations:
            parts.append(f"Education: {e.degree} in {e.major} from {e.school} ({e.graduated_year})")
    if candidate.work_experiences:
        for w in candidate.work_experiences:
            parts.append(f"Work: {w.role} at {w.company} ({w.start_date}-{w.end_date})")
    if candidate.raw_text:
        parts.append(f"\nResume text:\n{candidate.raw_text[:2000]}")

    summary = "\n".join(parts)

    criteria_list = [{"category": c.category, "name": c.name, "description": c.description or "", "weight": c.weight} for c in criteria]

    llm_result = llm_score_candidate(
        candidate.name or "Unknown",
        summary,
        job.title or "",
        job.jd_content or "",
        criteria_list,
    )

    if llm_result:
        return {
            "parser": "llm",
            "total_score": llm_result.get("overall_score", 50),
            "overall_reason": llm_result.get("overall_reason", ""),
            "strengths": llm_result.get("strengths", []),
            "weaknesses": llm_result.get("weaknesses", []),
            "detail": llm_result.get("criteria_scores", {}),
        }

    # Fall back to heuristic scoring
    result = heuristic_score(db, candidate, job)
    result["parser"] = "heuristic"
    return result