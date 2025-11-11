from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.database import get_db, engine
from app.db import models
from app.schemas.auth_schema import RegisterRequest, RegisterResponse, LoginRequest, LoginResponse, UserInfo
from app.services.auth_service import register_user, authenticate_user, issue_access_token
from app.utils.token_utils import decode_token

# 앱 시작 시 테이블 생성 (초기 테이블 자동생성)
models.Base.metadata.create_all(bind=engine)

router = APIRouter()
auth_scheme = HTTPBearer(auto_error=False)

def get_current_user(db: Session = Depends(get_db), creds: HTTPAuthorizationCredentials = Depends(auth_scheme)) -> models.User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing credentials")
    try:
        payload = decode_token(creds.credentials)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user_id = int(payload.get("sub", "0"))
    user = db.query(models.User).get(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user

@router.post("/register", response_model=RegisterResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    user = register_user(db, email=req.email, name=req.name, password=req.password)
    return RegisterResponse(user_id=user.id, email=user.email, name=user.name, created_at=user.created_at.isoformat())

@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, email=req.email, name=req.name, password=req.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = issue_access_token(user)
    return LoginResponse(access_token=token)

@router.get("/me", response_model=UserInfo)
def me(current=Depends(get_current_user)):
    return UserInfo(
        user_id=current.id,
        email=current.email,
        name=current.name,
        created_at=current.created_at.isoformat()
    )

