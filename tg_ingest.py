"""
Telegram Ingestion: TG Bot integration for automatic resume intake.
Currently a scaffold — configure a TG Bot to enable.

Setup:
1. Create a bot via @BotFather on Telegram
2. Set env var: TG_BOT_TOKEN
3. Users forward resumes to the bot, bot downloads and parses
"""
import os
import re
from typing import Optional
from database import SessionLocal, Candidate
from resume_parser import parse_resume

UPLOAD_DIR = "uploads"
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")


def scan_telegram_resumes(
    db_session: Optional[SessionLocal] = None,
) -> list[dict]:
    """
    Poll Telegram bot for new resume documents.
    Uses long polling via python-telegram-bot or manual HTTP API.

    Returns list of ingested candidates.
    """
    if not TG_BOT_TOKEN:
        return [{"status": "not_configured", "message": "TG_BOT_TOKEN not set. Create a bot via @BotFather and set the env var."}]

    import urllib.request
    import json

    results = []
    try:
        # Get updates
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates?timeout=5&limit=20"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        if not data.get("ok"):
            return [{"status": "error", "message": f"TG API error: {data}"}]

        for update in data.get("result", []):
            msg = update.get("message", {})
            doc = msg.get("document")
            if not doc:
                continue

            file_name = doc.get("file_name", "resume")
            if not any(file_name.lower().endswith(ext) for ext in [".pdf", ".docx", ".doc"]):
                continue

            # Get file
            file_id = doc["file_id"]
            file_url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getFile?file_id={file_id}"
            with urllib.request.urlopen(file_url, timeout=10) as fresp:
                file_data = json.loads(fresp.read())

            file_path = file_data["result"]["file_path"]
            download_url = f"https://api.telegram.org/file/bot{TG_BOT_TOKEN}/{file_path}"

            # Download and save
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = re.sub(r"[^\w.\-]", "_", file_name)
            local_path = os.path.join(UPLOAD_DIR, f"tg_{ts}_{safe_name}")

            urllib.request.urlretrieve(download_url, local_path)

            parsed = parse_resume(local_path)
            sender = msg.get("from", {})
            tg_username = sender.get("username", "")
            tg_name = f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip()

            db = db_session or SessionLocal()
            try:
                candidate = Candidate(
                    name=parsed.get("name") or tg_name or tg_username,
                    email=parsed.get("email"),
                    phone=parsed.get("phone"),
                    expected_salary_min=parsed.get("expected_salary_min"),
                    expected_salary_max=parsed.get("expected_salary_max"),
                    years_of_experience=parsed.get("years_of_experience"),
                    resume_path=local_path,
                    source_channel=f"telegram (@{tg_username})" if tg_username else "telegram",
                    raw_text=parsed.get("raw_text", ""),
                    skills_json=json.dumps(parsed.get("skills", []), ensure_ascii=False),
                )
                db.add(candidate)
                db.commit()
                db.refresh(candidate)
                results.append({"status": "ingested", "candidate_id": candidate.id, "name": candidate.name, "file": file_name})
            finally:
                if not db_session:
                    db.close()

    except Exception as e:
        results.append({"status": "error", "message": str(e)})

    return results if results else [{"status": "no_new", "message": "No new resume documents found"}]


if __name__ == "__main__":
    results = scan_telegram_resumes()
    for r in results:
        print(r)