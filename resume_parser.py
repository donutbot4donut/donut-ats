"""
Resume parser: extracts structured information from PDF and DOCX resumes.
No LLM dependency — regex + keyword heuristics.
"""
import re
import os
import json
from typing import Optional

# ─── 985/211 university list ───
_985_UNIS = {
    "北京大学", "清华大学", "复旦大学", "上海交通大学", "浙江大学", "南京大学",
    "中国科学技术大学", "哈尔滨工业大学", "西安交通大学", "中国人民大学",
    "北京师范大学", "南开大学", "天津大学", "大连理工大学", "吉林大学",
    "同济大学", "华东师范大学", "东南大学", "厦门大学", "山东大学",
    "中国海洋大学", "武汉大学", "华中科技大学", "湖南大学", "中南大学",
    "中山大学", "华南理工大学", "四川大学", "电子科技大学", "重庆大学",
    "西北工业大学", "兰州大学", "国防科技大学", "东北大学", "西北农林科技大学",
    "中央民族大学", "北京航空航天大学", "北京理工大学", "中国农业大学",
}
_211_UNIS = _985_UNIS | {
    "上海财经大学", "中央财经大学", "对外经济贸易大学", "北京邮电大学",
    "中国政法大学", "北京外国语大学", "上海外国语大学", "西安电子科技大学",
    "北京交通大学", "北京科技大学", "北京化工大学", "北京工业大学",
    "华北电力大学", "中国石油大学", "中国地质大学", "中国矿业大学",
    "华中师范大学", "华中农业大学", "南京航空航天大学", "南京理工大学",
    "河海大学", "南京农业大学", "苏州大学", "西南交通大学", "西南大学",
    "西南财经大学", "暨南大学", "华南师范大学", "哈尔滨工程大学", "东北师范大学",
    "合肥工业大学", "郑州大学", "云南大学", "西北大学", "南昌大学",
    "东华大学", "上海大学", "天津医科大学", "太原理工大学", "河北工业大学",
    "武汉理工大学", "中南财经政法大学", "福州大学", "广西大学", "贵州大学",
    "新疆大学", "石河子大学", "宁夏大学", "青海大学", "西藏大学",
    "内蒙古大学", "延边大学", "海南大学", "北京林业大学", "北京中医药大学",
    "北京体育大学", "中国传媒大学", "中央音乐学院", "中国药科大学",
    "大连海事大学", "东北林业大学", "东北农业大学", "长安大学", "陕西师范大学",
    "第二军医大学", "第四军医大学",
}

# Skill keyword sets
_SKILL_KEYWORDS = {
    "Python", "Go", "Golang", "Java", "JavaScript", "TypeScript", "Rust",
    "Solidity", "C++", "C", "C#", "Ruby", "Swift", "Kotlin", "PHP",
    "React", "Vue", "Angular", "Next.js", "Node.js", "Django", "Flask",
    "FastAPI", "Spring", "Spring Boot", "Express", "GraphQL",
    "TensorFlow", "PyTorch", "Keras", "scikit-learn", "XGBoost",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "Kafka",
    "Docker", "Kubernetes", "AWS", "Azure", "GCP", "Terraform",
    "Git", "CI/CD", "Linux", "Shell", "Ansible", "Prometheus", "Grafana",
    "Machine Learning", "Deep Learning", "NLP", "Computer Vision", "LLM",
    "Web3", "Blockchain", "DeFi", "Smart Contract", "Ethereum", "Solana",
    "Move", "Rust", "Zero Knowledge", "ZK", "MEV", "Quantitative",
    "Trading", "Financial Engineering", "Backtesting", "Risk Management",
    "Agile", "Scrum", "Product Management", "Data Analysis", "SQL", "Pandas",
    "NumPy", "dbt", "Airflow", "Spark", "Hadoop", "Flink",
    "微服务", "分布式", "高性能", "高并发", "系统设计", "架构",
}


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from PDF using pdfplumber."""
    import pdfplumber
    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


def extract_text_from_docx(file_path: str) -> str:
    """Extract text from DOCX using python-docx."""
    from docx import Document
    doc = Document(file_path)
    return "\n".join(p.text for p in doc.paragraphs)


def extract_text(file_path: str) -> str:
    """Auto-detect file type and extract text."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in (".docx", ".doc"):
        return extract_text_from_docx(file_path)
    elif ext in (".txt", ".md"):
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    return ""


# ─── Field extractors ───

def extract_name(text: str) -> Optional[str]:
    """Extract name: first non-empty line, or match common Chinese name patterns."""
    lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) < 30]
    # Try explicit "姓名" pattern
    m = re.search(r"姓名[：:\s]*([^\n]{2,10})", text)
    if m:
        return m.group(1).strip().rstrip("|").strip()
    # Try first short line that looks like a name (2-4 Chinese chars or typical English)
    for line in lines[:5]:
        line = line.strip().rstrip("| ").strip()
        # Chinese name: 2-4 chars
        if re.match(r"^[\u4e00-\u9fff]{2,4}$", line):
            return line
        # English name
        if re.match(r"^[A-Z][a-z]+(\s+[A-Z][a-z]+){0,2}$", line):
            return line
    return None


def extract_email(text: str) -> Optional[str]:
    m = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return m.group(0) if m else None


def extract_phone(text: str) -> Optional[str]:
    # Chinese mobile
    m = re.search(r"(?:电话|手机|Phone|Tel|联系方式)[：:\s]*([+\d\s\-()]{7,20})", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"1[3-9]\d{9}", text)
    if m:
        return m.group(0)
    # International
    m = re.search(r"\+[\d\s\-()]{7,20}", text)
    return m.group(0).strip() if m else None


def extract_age(text: str) -> Optional[int]:
    # Explicit age
    m = re.search(r"年龄[：:\s]*(\d{1,3})", text)
    if m:
        return int(m.group(1))
    # Birth year
    m = re.search(r"出生[年月日]*[：:\s]*(\d{4})", text)
    if m:
        return 2026 - int(m.group(1))
    # "XX岁"
    m = re.search(r"(\d{1,2})\s*岁", text)
    if m:
        return int(m.group(1))
    return None


def extract_education(text: str) -> list[dict]:
    """Extract education entries."""
    results = []
    # Look for education section
    edu_section_patterns = [
        r"教育(?:背景|经历|信息)?[：:\s]*(.*?)(?:工作|项目|技能|实习|培训|自我)",
        r"(?:EDUCATION|Education)[\s\S]*?(?:EXPERIENCE|WORK|PROJECT|SKILL)",
    ]
    for pattern in edu_section_patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            edu_text = m.group(1) if m.lastindex else m.group(0)
            break
    else:
        edu_text = text

    # Parse individual schools
    lines = [l.strip() for l in edu_text.split("\n") if l.strip()]

    for i, line in enumerate(lines):
        school = None
        degree = None
        major = None
        year = None
        is_985 = False
        is_211 = False

        # Check all universities
        for uni in sorted(_211_UNIS, key=len, reverse=True):
            if uni in line:
                school = uni
                is_211 = True
                is_985 = uni in _985_UNIS
                break

        # Degree detection
        for d in ["博士", "硕士", "本科", "大专", "PhD", "Master", "Bachelor", "B.S.", "M.S.", "B.E.", "M.E."]:
            if d.lower() in line.lower():
                if d in ("博士", "PhD"):
                    degree = "博士"
                elif d in ("硕士", "Master", "M.S.", "M.E."):
                    degree = "硕士"
                elif d in ("本科", "Bachelor", "B.S.", "B.E."):
                    degree = "本科"
                elif d in ("大专"):
                    degree = "大专"
                break

        # Year detection
        m = re.search(r"(20\d{2}|199\d)", line)
        if m:
            year = int(m.group(1))

        # Major detection
        major_keywords = [
            "计算机", "软件工程", "人工智能", "数据科学", "数学", "统计", "金融",
            "电子", "通信", "自动化", "物理", "经济", "管理", "设计",
            "Computer Science", "Software Engineering", "AI", "Data Science",
            "Mathematics", "Statistics", "Finance", "Electrical Engineering",
        ]
        for kw in major_keywords:
            if kw.lower() in line.lower():
                major = kw
                break

        if school or degree:
            results.append({
                "school": school,
                "degree": degree,
                "major": major,
                "graduated_year": year,
                "is_985211": is_985,
            })

    return results if results else [{"school": None, "degree": None, "major": None, "graduated_year": None, "is_985211": False}]


def extract_work_experience(text: str) -> list[dict]:
    """Heuristic extraction of work experience entries."""
    results = []
    # Find work section
    patterns = [
        r"工作(?:经历|经验)[：:\s]*(.*?)(?:项目|教育|技能|培训|自我)",
        r"(?:WORK|Work Experience|EXPERIENCE)[\s\S]*?(?:PROJECT|EDUCATION|SKILL)",
    ]
    work_text = ""
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE | re.DOTALL)
        if m:
            work_text = m.group(1) if m.lastindex else m.group(0)
            break

    if not work_text:
        work_text = text

    # Split by date patterns or company-like separators
    segments = re.split(r"\n(?=\d{4}[./-]\d{1,2})", work_text)
    if len(segments) <= 1:
        segments = re.split(r"\n(?=[A-Z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff\s]{2,30}(?:公司|科技|集团|有限|Inc|Ltd|Corp))", work_text)

    for seg in segments:
        seg = seg.strip()
        if not seg or len(seg) < 15:
            continue

        company = None
        role = None
        start_date = None
        end_date = None

        # Company detection
        company_patterns = [
            r"([^\n]{2,40}(?:公司|科技|集团|有限|Inc\.?|Ltd\.?|Corp\.?|LLC|Network|Labs|Capital))",
        ]
        for cp in company_patterns:
            m = re.search(cp, seg)
            if m:
                company = m.group(1).strip()
                break

        # Role detection
        role_patterns = [
            r"(?:职位|岗位|Title|Role)[：:\s]*([^\n]{2,50})",
            r"([^\n]{2,40}(?:工程师|经理|总监|实习生|Developer|Engineer|Manager|Director|Intern|Analyst|Designer))",
        ]
        for rp in role_patterns:
            m = re.search(rp, seg)
            if m:
                role = m.group(1).strip()
                break

        # Date detection
        date_patterns = [
            r"(20\d{2}[./-]\d{1,2})\s*[-–—to至到]+\s*(20\d{2}[./-]\d{1,2}|至今|现在|Present|Now)",
            r"(20\d{2})\s*[-–—to至到]+\s*(20\d{2}|至今|现在|Present|Now)",
        ]
        for dp in date_patterns:
            m = re.search(dp, seg, re.IGNORECASE)
            if m:
                start_date = m.group(1)
                end_date = m.group(2)
                break

        results.append({
            "company": company or "",
            "role": role or "",
            "start_date": start_date or "",
            "end_date": end_date or "",
            "description": seg[:500],
        })

    return results


def extract_project_experience(text: str) -> list[dict]:
    """Extract project entries."""
    results = []
    patterns = [
        r"项目(?:经历|经验)[：:\s]*(.*?)(?:技能|教育|培训|自我|证书)",
        r"(?:PROJECT|Project Experience)[\s\S]*?(?:SKILL|EDUCATION|CERTIFICATE)",
    ]
    proj_text = ""
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE | re.DOTALL)
        if m:
            proj_text = m.group(1) if m.lastindex else m.group(0)
            break

    if not proj_text:
        return results

    segments = re.split(r"\n(?=[A-Z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff\s]{3,50}[:：])", proj_text)
    for seg in segments:
        seg = seg.strip()
        if not seg or len(seg) < 20:
            continue
        name = seg.split("\n")[0][:80].strip()
        # Tech stack detection
        techs = [kw for kw in _SKILL_KEYWORDS if kw.lower() in seg.lower()]
        results.append({
            "project_name": name,
            "role": "",
            "description": seg[:500],
            "tech_stack": ", ".join(techs[:15]),
        })

    return results[:10]


def extract_salary(text: str) -> tuple[Optional[int], Optional[int]]:
    """Extract expected salary range."""
    patterns = [
        r"(?:期望薪资|期望工资|期望月薪|期望年薪|薪资要求|期望薪酬)[：:\s]*([^\n]{3,30})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            sal_text = m.group(1).strip()
            # "15K-20K" or "15000-20000" or "15k-20k" or "面议"
            if "面议" in sal_text or "Negotiable" in sal_text:
                return None, None
            # Extract numbers
            nums = re.findall(r"(\d+)\s*[kK]?", sal_text)
            if len(nums) >= 2:
                lo = int(nums[0]) * (1000 if "k" in sal_text.lower() or "K" in sal_text else 1)
                hi = int(nums[1]) * (1000 if "k" in sal_text.lower() or "K" in sal_text else 1)
                return lo, hi
            elif len(nums) == 1:
                val = int(nums[0]) * (1000 if "k" in sal_text.lower() or "K" in sal_text else 1)
                return val, val
    return None, None


def extract_skills(text: str) -> list[str]:
    """Extract technical skill keywords."""
    found = set()
    for kw in _SKILL_KEYWORDS:
        if kw.lower() in text.lower():
            found.add(kw)
    return sorted(found, key=lambda x: len(x), reverse=True)


def calc_experience_years(works: list[dict]) -> Optional[int]:
    """Calculate total years of experience from work history."""
    years = 0
    for w in works:
        sd = w.get("start_date", "")
        ed = w.get("end_date", "")
        if sd and ed:
            try:
                sy = int(re.search(r"(\d{4})", sd).group(1)) if re.search(r"(\d{4})", sd) else None
                if "至今" in ed or "Present" in ed or "Now" in ed:
                    ey = 2026
                else:
                    ey = int(re.search(r"(\d{4})", ed).group(1)) if re.search(r"(\d{4})", ed) else None
                if sy and ey:
                    years += max(0, ey - sy)
            except (ValueError, AttributeError):
                pass
    return years if years > 0 else None


def parse_resume(file_path: str) -> dict:
    """
    Parse a resume file and return structured data.
    Returns a dict with all extracted fields.
    """
    text = extract_text(file_path)
    if not text:
        return {"error": "Could not extract text from file", "raw_text": ""}

    skills = extract_skills(text)
    salary_min, salary_max = extract_salary(text)
    works = extract_work_experience(text)

    return {
        "raw_text": text,
        "name": extract_name(text),
        "email": extract_email(text),
        "phone": extract_phone(text),
        "age": extract_age(text),
        "educations": extract_education(text),
        "work_experiences": works,
        "project_experiences": extract_project_experience(text),
        "expected_salary_min": salary_min,
        "expected_salary_max": salary_max,
        "years_of_experience": calc_experience_years(works),
        "skills": skills,
    }


def save_uploaded_file(uploaded_file, upload_dir: str = "uploads") -> str:
    """Save an uploaded file and return its path."""
    import shutil
    os.makedirs(upload_dir, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^\w.\-]", "_", getattr(uploaded_file, "filename", "resume"))
    dest = os.path.join(upload_dir, f"{ts}_{safe_name}")
    with open(dest, "wb") as f:
        if hasattr(uploaded_file, "file"):
            shutil.copyfileobj(uploaded_file.file, f)
        else:
            f.write(uploaded_file.read() if hasattr(uploaded_file, "read") else uploaded_file)
    return dest