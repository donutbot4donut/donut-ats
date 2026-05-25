"""
JD Manager: template-based JD generation combining recruitment criteria,
job specifics, and company context.
"""
from sqlalchemy.orm import Session
from database import Job, RecruitmentCriteria
import json


COMPANY_INTRO = """## About Donut Labs

Donut Labs is an AI-native crypto fintech company building the future of autonomous trading. Our core product, D0, is an AI agent that monitors, analyzes, recommends, and executes trades across financial markets — 24/7.

We believe the future of trading is agentic. Our mission: Build the market infrastructure for zero-human funds.

**Tech highlights:**
- Multi-agent AI system orchestrating research, analysis, and execution
- Self-built perpetual futures engine (Spring Boot + Java 21)
- Multi-chain support (Solana, EVM, BTC roadmapped)
- 155+ integrated tools via d0-cli: research, trading, DeFi, perps, prediction markets, backtesting

**Team:** ~35 people, remote-first with HQ in Hong Kong. Lean, high-density, A-players only."""

COMPANY_VALUES = """## Our Values

- **Owner Mindset** — Own your outcomes. Flag your mistakes. No one else will.
- **First Principles Thinking** — Depth over breadth. Understand why before you build.
- **Learning Agility** — Adapt fast, learn continuously. The crypto + AI landscape shifts weekly.
- **Overcommunicated** — Surface problems immediately. Share context proactively.
- **Directed Progress** — Ship working code over perfect code. Focus on the next concrete step."""


def generate_jd(
    db: Session,
    title: str,
    department: str = "Engineering",
    responsibilities: list[str] = None,
    requirements: list[str] = None,
    nice_to_have: list[str] = None,
) -> str:
    """
    Generate a complete JD in Markdown format.
    """
    sections = [
        f"# {title}",
        f"**Department:** {department}  |  **Location:** Remote / Hong Kong  |  **Type:** Full-time",
        "",
        COMPANY_INTRO,
        "",
        COMPANY_VALUES,
        "",
        "## The Role",
        "",
    ]

    if responsibilities:
        sections.append("### What You'll Do")
        for r in responsibilities:
            sections.append(f"- {r}")
        sections.append("")

    if requirements:
        sections.append("### What We're Looking For")
        for r in requirements:
            sections.append(f"- {r}")
        sections.append("")

    if nice_to_have:
        sections.append("### Nice to Have")
        for n in nice_to_have:
            sections.append(f"- {n}")
        sections.append("")

    sections.extend([
        "## Why Join Donut?",
        "",
        "- **Build the future of finance.** AI agents replacing manual trading is inevitable — we're building it first.",
        "- **Extreme autonomy.** No micromanagement. You own your domain end-to-end.",
        "- **AI × Crypto at the frontier.** Work at the intersection of two of the most exciting technology waves.",
        "- **High-density team.** Work with A-players who ship fast and think deep.",
        "- **Remote-first.** Work from anywhere. We care about output, not hours at a desk.",
        "",
        "## Hiring Process",
        "",
        "1. **Application Review** (48h) — We read every application carefully.",
        "2. **Screening Call** (30min) — Get to know each other, discuss your experience and motivations.",
        "3. **Technical Deep-Dive** (60min) — Solve real problems with the team.",
        "4. **Final Interview** (45min) — Meet a co-founder, discuss vision and culture fit.",
        "5. **Offer** — We move fast. 48h from final interview to offer.",
        "",
        "## How to Apply",
        "",
        "Send your resume/GitHub/portfolio to careers@donutbrowser.ai or DM us on Telegram @DonutD0Bot.",
        "No cover letter needed — just tell us what you've built and why you want to build at Donut.",
    ])

    return "\n".join(sections)


def create_job_with_jd(
    db: Session,
    title: str,
    department: str = "Engineering",
    responsibilities: list[str] = None,
    requirements: list[str] = None,
    nice_to_have: list[str] = None,
    criteria_weights: dict = None,
) -> Job:
    """Create a job with auto-generated JD."""
    jd_content = generate_jd(db, title, department, responsibilities, requirements, nice_to_have)

    job = Job(
        title=title,
        department=department,
        jd_content=jd_content,
        status="draft",
        criteria_json=json.dumps(criteria_weights) if criteria_weights else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job