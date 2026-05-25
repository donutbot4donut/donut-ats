"""SQLite database models and session for DonutATS."""
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime, timezone

DB_PATH = "sqlite:///donut_ats.db"
engine = create_engine(DB_PATH, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Candidate(Base):
    __tablename__ = "candidates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=True)
    email = Column(String(300), nullable=True)
    phone = Column(String(50), nullable=True)
    age = Column(Integer, nullable=True)
    gender = Column(String(20), nullable=True)
    current_location = Column(String(200), nullable=True)
    expected_salary_min = Column(Integer, nullable=True)
    expected_salary_max = Column(Integer, nullable=True)
    years_of_experience = Column(Integer, nullable=True)
    resume_path = Column(String(500), nullable=True)
    source_channel = Column(String(100), nullable=True)
    raw_text = Column(Text, nullable=True)
    skills_json = Column(Text, nullable=True)  # JSON array of detected skills
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    educations = relationship("Education", back_populates="candidate", cascade="all, delete-orphan")
    work_experiences = relationship("WorkExperience", back_populates="candidate", cascade="all, delete-orphan")
    project_experiences = relationship("ProjectExperience", back_populates="candidate", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="candidate", cascade="all, delete-orphan")


class Education(Base):
    __tablename__ = "education"
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    school = Column(String(200), nullable=True)
    degree = Column(String(50), nullable=True)
    major = Column(String(200), nullable=True)
    graduated_year = Column(Integer, nullable=True)
    is_985211 = Column(Boolean, default=False)

    candidate = relationship("Candidate", back_populates="educations")


class WorkExperience(Base):
    __tablename__ = "work_experience"
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    company = Column(String(300), nullable=True)
    role = Column(String(300), nullable=True)
    start_date = Column(String(50), nullable=True)
    end_date = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)

    candidate = relationship("Candidate", back_populates="work_experiences")


class ProjectExperience(Base):
    __tablename__ = "project_experience"
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    project_name = Column(String(300), nullable=True)
    role = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    tech_stack = Column(Text, nullable=True)

    candidate = relationship("Candidate", back_populates="project_experiences")


class RecruitmentCriteria(Base):
    __tablename__ = "recruitment_criteria"
    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(100), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    weight = Column(Float, default=1.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    department = Column(String(100), nullable=True)
    jd_content = Column(Text, nullable=True)
    status = Column(String(50), default="draft")
    criteria_json = Column(Text, nullable=True)  # JSON: {"criteria_id": weight, ...}
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    applications = relationship("Application", back_populates="job", cascade="all, delete-orphan")


class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    stage = Column(String(50), default="screening")
    score = Column(Float, nullable=True)
    score_detail = Column(Text, nullable=True)  # JSON
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    candidate = relationship("Candidate", back_populates="applications")
    job = relationship("Job", back_populates="applications")


class ResponseTemplate(Base):
    __tablename__ = "response_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(50), nullable=False)
    channel = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    subject = Column(String(300), nullable=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CommunicationLog(Base):
    __tablename__ = "communication_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    type = Column(String(50), nullable=False)
    channel = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    sent_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    status = Column(String(50), default="sent")


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()