from typing import Optional
from sqlalchemy.orm import Session
from passlib.hash import bcrypt
from app.db import models
from app.utils.token_utils import create_access_token

def register_user(db: Session, email: str, name: str, password: str) -> models.User:
    # 비밀번호 해시
    pwd_hash = bcrypt.hash(password)
    user = models.User(email=email, name=name, password_hash=pwd_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def authenticate_user(db: Session, email: str, name: str, password: str) -> Optional[models.User]:
    user = db.query(models.User).filter(models.User.email == email, models.User.name == name).first()
    if not user:
        return None
    if not bcrypt.verify(password, user.password_hash):
        return None
    return user

def issue_access_token(user: models.User) -> str:
    return create_access_token({"sub": str(user.id), "email": user.email, "name": user.name})

