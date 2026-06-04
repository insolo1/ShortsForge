import json
from typing import Optional, Any
from redis.asyncio import Redis

from app.core.config import settings

redis_client: Optional[Redis] = None


async def init_redis():
    global redis_client
    try:
        redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis_client.ping()
        print("[REDIS] Connected")
    except Exception as e:
        print(f"[REDIS] Connection failed (non-fatal): {e}")
        redis_client = None


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()


async def cache_get(key: str) -> Optional[str]:
    if not redis_client:
        return None
    return await redis_client.get(key)


async def cache_set(key: str, value: str, ttl: int = 3600):
    if not redis_client:
        return
    await redis_client.setex(key, ttl, value)


async def cache_delete(key: str):
    if not redis_client:
        return
    await redis_client.delete(key)


async def cache_get_json(key: str) -> Optional[Any]:
    val = await cache_get(key)
    return json.loads(val) if val else None


async def cache_set_json(key: str, value: Any, ttl: int = 3600):
    await cache_set(key, json.dumps(value, ensure_ascii=False), ttl)
