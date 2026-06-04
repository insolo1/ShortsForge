from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.user_repo import UserRepository
from app.core.security import hash_password, verify_password, create_access_token, decode_access_token


class AuthService:
    def __init__(self, session: AsyncSession):
        self.user_repo = UserRepository(session)

    async def authenticate(self, username: str, password: str) -> Optional[str]:
        user = await self.user_repo.get_by_username(username)
        if not user or not verify_password(password, user.password):
            return None
        return create_access_token(user.username, user.role)

    async def create_user(self, username: str, password: str, role: str = "viewer"):
        existing = await self.user_repo.get_by_username(username)
        if existing:
            existing.password = hash_password(password)
            existing.role = role
            return
        await self.user_repo.create(username=username, password=hash_password(password), role=role)

    async def get_all_users(self):
        users = await self.user_repo.list()
        return [{"username": u.username, "role": u.role} for u in users]

    async def delete_user(self, username: str):
        user = await self.user_repo.get_by_username(username)
        if user:
            await self.user_repo.delete(user.id)
