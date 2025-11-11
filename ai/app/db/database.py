from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# SQLite 상대경로: ai/app/data/user.db
SQLALCHEMY_DATABASE_URL = "sqlite:///./data/user.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# FastAPI 의존성
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

