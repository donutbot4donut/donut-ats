"""
Email Ingestion: Gmail API integration for automatic resume intake.
Scans ALL emails (not just unread), with dedup and multi-format support.

Setup:
1. Enable Gmail IMAP in Google Account settings
2. Generate App Password (Google Account → Security → 2-Step Verification → App Passwords)
3. Set env vars: GMAIL_USER, GMAIL_APP_PASSWORD
"""
import os
import re
import hashlib
import imaplib
import email
import ssl
from email.header import decode_header
from typing import Optional
from database import SessionLocal, Candidate
from resume_parser import parse_resume

UPLOAD_DIR = "uploads"
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}

# Track processed files by hash to avoid duplicates
_processed_hashes = set()


def _file_hash(filepath: str) -> str:
    """Compute SHA256 of file for dedup."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _candidate_exists(db, email_addr: str, file_hash_val: str) -> bool:
    """Check if we've already ingested this candidate/file."""
    # Check by email
    if email_addr:
        existing = db.query(Candidate).filter(Candidate.email == email_addr).first()
        if existing:
            return True
    # Check by file hash (stored in raw_text or could add a hash field)
    return file_hash_val in _processed_hashes


def _parse_image_text(filepath: str) -> str:
    """Extract text from images using OCR-like heuristics."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}:
        return ""
    try:
        from PIL import Image
        img = Image.open(filepath)
        # Basic metadata extraction
        info = [f"Image: {img.format}", f"Size: {img.size}"]
        # Try to get EXIF/tags
        if hasattr(img, '_getexif') and img._getexif():
            for tag, value in img._getexif().items():
                if value and isinstance(value, str):
                    info.append(str(value))
        return "\n".join(info)
    except ImportError:
        return "[Image file - OCR not available]"
    except Exception:
        return "[Image file]"


def scan_gmail_for_resumes(
    db_session: Optional[SessionLocal] = None,
    mark_read: bool = False,
    max_emails: int = 100,
) -> list[dict]:
    """
    Scan Gmail inbox for emails with resume attachments.
    Scans ALL emails, deduplicates by content hash.

    Returns list of newly ingested candidate dicts.
    """
    user = os.environ.get("GMAIL_USER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")

    if not user or not password:
        return [{"status": "not_configured", "message": "Gmail credentials not set. Set GMAIL_USER and GMAIL_APP_PASSWORD env vars."}]

    results = []
    total_scanned = 0
    new_ingested = 0
    duplicates = 0
    parse_errors = 0

    ctx = ssl.create_default_context()
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=ctx)
        mail.login(user, password)
        mail.select("inbox")

        # Search ALL emails (not just unread)
        status, messages = mail.search(None, "ALL")
        if status != "OK":
            mail.logout()
            return [{"status": "error", "message": "Could not search inbox"}]

        msg_ids = messages[0].split()
        # Process newest first
        msg_ids = list(reversed(msg_ids))[:max_emails]

        for msg_id in msg_ids:
            total_scanned += 1
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            # Decode subject & from
            subject, enc = decode_header(msg["Subject"] or "")[0]
            if isinstance(subject, bytes):
                subject = subject.decode(enc or "utf-8", errors="replace")

            from_addr = msg.get("From", "")

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

                ext = os.path.splitext(filename)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue

                # Save file
                os.makedirs(UPLOAD_DIR, exist_ok=True)
                from datetime import datetime
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                safe_name = re.sub(r"[^\w.\-()]", "_", filename)
                filepath = os.path.join(UPLOAD_DIR, f"gmail_{ts}_{safe_name}")

                payload = part.get_payload(decode=True)
                with open(filepath, "wb") as f:
                    f.write(payload)

                # Dedup check
                fhash = _file_hash(filepath)
                if fhash in _processed_hashes:
                    os.remove(filepath)
                    duplicates += 1
                    continue

                _processed_hashes.add(fhash)

                # Parse based on type
                if ext in {".pdf", ".docx", ".doc"}:
                    parsed = parse_resume(filepath)
                elif ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}:
                    img_text = _parse_image_text(filepath)
                    parsed = {
                        "raw_text": img_text,
                        "name": None,
                        "email": _extract_email_from_header(from_addr),
                        "phone": None,
                        "age": None,
                        "educations": [],
                        "work_experiences": [],
                        "project_experiences": [],
                        "expected_salary_min": None,
                        "expected_salary_max": None,
                        "years_of_experience": None,
                        "skills": [],
                    }
                else:
                    continue

                db = db_session or SessionLocal()
                try:
                    candidate = Candidate(
                        name=parsed.get("name") or _extract_name_from_subject(subject),
                        email=parsed.get("email") or _extract_email_from_header(from_addr),
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
                    new_ingested += 1
                    results.append({
                        "status": "ingested",
                        "candidate_id": candidate.id,
                        "name": candidate.name,
                        "email": candidate.email,
                        "file": filename,
                        "format": ext,
                    })
                except Exception as e:
                    parse_errors += 1
                    results.append({
                        "status": "error",
                        "file": filename,
                        "message": str(e)[:100],
                    })
                finally:
                    if not db_session:
                        db.close()

            if mark_read:
                mail.store(msg_id, "+FLAGS", "\\Seen")

        mail.logout()
    except Exception as e:
        return [{"status": "error", "message": str(e)}]

    # Add summary
    results.insert(0, {
        "status": "summary",
        "total_scanned": total_scanned,
        "new_ingested": new_ingested,
        "duplicates": duplicates,
        "errors": parse_errors,
    })
    return results if len(results) > 1 else [{
        "status": "summary",
        "total_scanned": total_scanned,
        "new_ingested": 0,
        "duplicates": 0,
        "errors": 0,
    }]


def _extract_email_from_header(header: str) -> Optional[str]:
    """Extract email from From: header."""
    m = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", header)
    return m.group(0) if m else None


def _extract_name_from_subject(subject: str) -> Optional[str]:
    """Try to extract candidate name from email subject."""
    # Common patterns in subject lines
    patterns = [
        r"(?:简历|resume|cv)[\-_]?\s*[：:]\s*([^\s\-]{2,10})",
        r"\[([^\]]{2,10})\]",  # [Name] in subject
    ]
    for p in patterns:
        m = re.search(p, subject, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


if __name__ == "__main__":
    results = scan_gmail_for_resumes()
    for r in results:
        print(r)