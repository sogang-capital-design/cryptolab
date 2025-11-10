from pydantic import BaseModel, EmailStr, Field

class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)

class RegisterResponse(BaseModel):
    user_id: int
    email: EmailStr
    name: str
    created_at: str

class LoginRequest(BaseModel):
    email: EmailStr
    name: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 7200

class UserInfo(BaseModel):
    user_id: int
    email: EmailStr
    name: str
    created_at: str

