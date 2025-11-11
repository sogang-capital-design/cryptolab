# ai/app/schemas/auth_schema.py
from pydantic import BaseModel, Field

class RegisterRequest(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)

class RegisterResponse(BaseModel):
    user_id: int
    email: str
    name: str
    created_at: str

class LoginRequest(BaseModel):
    email: str
    name: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 7200

class UserInfo(BaseModel):
    user_id: int
    email: str
    name: str
    created_at: str
