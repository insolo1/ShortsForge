from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import JSONResponse

from app.core.database import get_session
from app.services.auth_service import AuthService
from app.core.security import decode_access_token

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/login")
async def login(username: str, password: str, session: AsyncSession = Depends(get_session)):
    auth = AuthService(session)
    token = await auth.authenticate(username, password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    payload = decode_access_token(token)
    response = JSONResponse({"token": token, "username": username, "role": payload.get("role", "viewer")})
    response.set_cookie("token", token, httponly=False, max_age=86400 * 30, path="/", samesite="lax")
    return response


@router.post("/logout")
async def logout(request: Request):
    response = JSONResponse({"status": "success"})
    response.delete_cookie("token")
    return response


@router.get("/users")
async def get_users(session: AsyncSession = Depends(get_session)):
    auth = AuthService(session)
    users = await auth.get_all_users()
    return {"status": "success", "users": users}


@router.post("/users")
async def create_user(username: str, password: str, role: str = "viewer",
                      session: AsyncSession = Depends(get_session)):
    auth = AuthService(session)
    await auth.create_user(username, password, role)
    return {"status": "success"}


@router.delete("/users/{username}")
async def delete_user(username: str, session: AsyncSession = Depends(get_session)):
    auth = AuthService(session)
    await auth.delete_user(username)
    return {"status": "success"}
