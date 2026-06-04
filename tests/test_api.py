import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_get_roles(client):
    async with client as c:
        resp = await c.get("/roles")
        assert resp.status_code == 200
        data = resp.json()
        assert "roles" in data
        assert "admin" in data["roles"]


@pytest.mark.asyncio
async def test_get_fonts(client):
    async with client as c:
        resp = await c.get("/fonts")
        assert resp.status_code == 200
        data = resp.json()
        assert "fonts" in data
        assert len(data["fonts"]) > 0


@pytest.mark.asyncio
async def test_login_invalid(client):
    async with client as c:
        resp = await c.post("/api/login", data={"username": "bad", "password": "bad"})
        assert resp.status_code == 401
