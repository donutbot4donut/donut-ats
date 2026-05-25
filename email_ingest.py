"""
Email Ingestion: Gmail API integration for automatic resume intake.
Currently a scaffold — configure Gmail API credentials to enable.

Setup:
1. Enable Gmail API in Google Cloud Console
2. Create OAuth 2.0 credentials (or app password for simpler setup)
3. Set env vars: GMAIL_USER, GMAIL_APP_PASSWORD
"""
import os
import base64
import re
from typing import Optional
from database import SessionLocal, Candidate
from resume_parser import parse_resume, save_uploaded_file

UPLOAD_DIR = "uploads"


def _get_gmail_service():
    """Placeholder: returns None until Gmail API is configured."""
    # Production: use google-auth + googleapiclient
    # For lightweight: use IMAP with app password
    return None


def scan_gmail_for_resumes(
    db_session: Optional[SessionLocal] = None,
    mark_read: bool = True,
) -> list[dict]:
    """
    Scan Gmail inbox for unread emails with PDF/DOCX attachments.
    Currently uses IMAP fallback via app password.

    Returns list of newly ingested candidate dicts.
    """
    user = os.environ.get("GMAIL_USER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")

    if not user or not password:
        return [{"status": "not_configured", "message": "Gmail credentials not set. Set GMAIL_USER and GMAIL_APP_PASSWORD env vars."}]

    import imaplib
    import email
    from email.header import decode_header

    results = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(user, password)
        mail.select("inbox")

        # Search for unread emails with attachments
        status, messages = mail.search(None, 'UNSEEN')
        if status != "OK":
            mail.logout()
            return [{"status": "error", "message": "Could not search inbox"}]

        msg_ids = messages[0].split()
        for msg_id in msg_ids[:20]:  # limit to 20 per scan
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            # Decode subject
            subject, enc = decode_header(msg["Subject"] or "")[0]
            if isinstance(subject, bytes):
                subject = subject.decode(enc or "utf-8", errors="replace")

            # Check for attachments
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                if part.get("Content-Disposition") is None:
                    continue

                filename = part.get_filename()
                if not filename:
                    continue

                # Decode filename
                fn_decoded, fn_enc = decode_header(filename)[0]
                if isinstance(fn_decoded, bytes):
                    filename = fn_decoded.decode(fn_enc or "utf-8", errors="replace")

                if not any(filename.lower().endswith(ext) for ext in [".pdf", ".docx", ".doc"]):
                    continue

                # Save and parse
                os.makedirs(UPLOAD_DIR, exist_ok=True)
                from datetime import datetime
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_name = re.sub(r"[^\w.\-]", "_", filename)
                filepath = os.path.join(UPLOAD_DIR, f"gmail_{ts}_{safe_name}")

                with open(filepath, "wb") as f:
                    payload = part.get_payload(decode=True)
                    f.write(payload)

                parsed = parse_resume(filepath)

                db = db_session or SessionLocal()
                try:
                    candidate = Candidate(
                        name=parsed.get("name"),
                        email=parsed.get("email") or msg.get("From", ""),
                        phone=parsed.get("phone"),
                        age=parsed.get("age"),
                        expected_salary_min=parsed.get("expected_salary_min"),
                        expected_salary_max=parsed.get("expected_salary_max"),
                        years_of_experience=parsed.get("years_of_experience"),
                        resume_path=filepath,
                        source_channel="gmail",
                        raw_text=parsed.get("raw_text", ""),
                        skills_json=__import__("json").dumps(parsed.get("skills", []), ensure_ascii=False),
                    )
                    db.add(candidate)
                    db.commit()
                    db.refresh(candidate)
                    results.append({"status": "ingested", "candidate_id": candidate.id, "name": candidate.name, "file": filename})
                finally:
                    if not db_session:
                        db.close()

            if mark_read:
                mail.store(msg_id, "+FLAGS", "\\Seen")

        mail.logout()
    except Exception as e:
        results.append({"status": "error", "message": str(e)})

    return results if results else [{"status": "no_new", "message": "No new resumes found"}]


if __name__ == "__main__":
    results = scan_gmail_for_resumes()
    for r in results:
        print(r)