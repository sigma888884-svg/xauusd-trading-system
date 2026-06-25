"""
إعداد الاتصال بقاعدة بيانات Postgres عبر SQLAlchemy
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """ينشئ الجداول إن لم تكن موجودة (للـMVP، بدون migrations كاملة)."""
    from app import models  # noqa: F401  (تسجيل النماذج قبل create_all)
    Base.metadata.create_all(bind=engine)
