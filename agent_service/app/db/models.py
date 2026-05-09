from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class PlanRecord(Base):
    __tablename__ = "plan_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, index=True, nullable=True)
    user_input = Column(Text, nullable=False)
    plan_json = Column(JSON, nullable=False)
    status = Column(String, default="ok")
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class ExecutionRecord(Base):
    __tablename__ = "execution_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, index=True, nullable=True)
    step_id = Column(String, nullable=False)
    tool = Column(String, nullable=False)
    args_json = Column(JSON, nullable=False)
    result = Column(String, default="pending")  # pending, success, failed
    error_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
