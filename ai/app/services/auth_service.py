# ai/app/services/auth_service.py
from typing import Optional
from sqlalchemy.orm import Session
from passlib.hash import pbkdf2_sha256  # ← bcrypt 대신 이거 사용
from app.db import models
from app.utils.token_utils import create_access_token


def _hash(password: str) -> str:
    """패스워드 해시 (salt 포함, 자동 반복횟수 관리)"""
    return pbkdf2_sha256.hash(password)


def _verify(password: str, hashed: str) -> bool:
    """패스워드 검증"""
    return pbkdf2_sha256.verify(password, hashed)


def register_user(db: Session, email: str, name: str, password: str) -> models.User:
    pwd_hash = _hash(password)
    user = models.User(email=email, name=name, password_hash=pwd_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, name: str, password: str) -> Optional[models.User]:
    user = (
        db.query(models.User)
        .filter(models.User.email == email, models.User.name == name)
        .first()
    )
    if not user:
        return None
    if not _verify(password, user.password_hash):
        return None
    return user


def issue_access_token(user: models.User) -> str:
    return create_access_token({"sub": str(user.id), "email": user.email, "name": user.name})
