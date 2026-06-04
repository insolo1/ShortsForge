from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    role: str


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class UserOut(BaseModel):
    username: str
    role: str
