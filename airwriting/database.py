from __future__ import annotations
import os
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Integer, ForeignKey, Text, DateTime, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
PROJECT_ROOT=Path(__file__).resolve().parent.parent
DB_URL=os.getenv("AIRWRITING_DATABASE_URL",f"sqlite:///{(PROJECT_ROOT/'data'/'airwriting.db').as_posix()}")
if DB_URL.startswith("sqlite:///") and DB_URL != "sqlite:///:memory:":
    db_path=DB_URL[len("sqlite:///"):]
    if DB_URL.startswith("sqlite:////"):
        db_path="/"+db_path.lstrip("/")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
connect_args={"check_same_thread":False} if DB_URL.startswith("sqlite") else {}
engine=create_engine(DB_URL,connect_args=connect_args,pool_pre_ping=True)
if DB_URL.startswith("sqlite"):
    from sqlalchemy import event
    @event.listens_for(engine,"connect")
    def _sqlite_pragmas(connection, _record):
        cursor=connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
SessionLocal=sessionmaker(engine,expire_on_commit=False)
class Base(DeclarativeBase): pass
class DrawingSession(Base):
    __tablename__="sessions"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    name:Mapped[str]=mapped_column(String(160),default="Untitled drawing")
    recognized_text:Mapped[str|None]=mapped_column(Text,nullable=True)
    image_path:Mapped[str|None]=mapped_column(String(500),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),index=True)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc))
    strokes:Mapped[list["StrokeRecord"]]=relationship(back_populates="session",cascade="all, delete-orphan",order_by="StrokeRecord.stroke_index")
class StrokeRecord(Base):
    __tablename__="strokes"
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    session_id:Mapped[str]=mapped_column(ForeignKey("sessions.id",ondelete="CASCADE"),nullable=False)
    stroke_index:Mapped[int]=mapped_column(Integer,nullable=False)
    points_json:Mapped[str]=mapped_column(Text,nullable=False)
    color:Mapped[str]=mapped_column(String(16),nullable=False)
    thickness:Mapped[int]=mapped_column(Integer,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
    session:Mapped[DrawingSession]=relationship(back_populates="strokes")
    __table_args__=(Index("ix_strokes_session_order","session_id","stroke_index",unique=True),)
Base.metadata.create_all(engine)
