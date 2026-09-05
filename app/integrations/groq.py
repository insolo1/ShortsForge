import json
import time
from groq import Groq, RateLimitError, APIStatusError

from app.core.config import settings
from app.core.redis import cache_get_json, cache_set_json, redis_client


_GROQ_TPD_LIMIT = 100000
_GROQ_RATE_KEY = "groq:tpd:used"
_GROQ_BLOCKED_KEY = "groq:blocked_until"
_groq_disabled_until: float = 0.0


async def get_groq_client() -> Groq:
    if not settings.GROQ_API_KEY:
        return None
    return Groq(api_key=settings.GROQ_API_KEY)


async def check_groq_rate_limit() -> bool:
    if not redis_client:
        return True
    used = await redis_client.get(_GROQ_RATE_KEY)
    if used and int(used) >= _GROQ_TPD_LIMIT:
        return False
    return True


async def increment_groq_usage(tokens: int = 1300):
    if not redis_client:
        return
    await redis_client.incrby(_GROQ_RATE_KEY, tokens)
    await redis_client.expire(_GROQ_RATE_KEY, 86400)


async def is_groq_blocked() -> bool:
    global _groq_disabled_until
    if time.time() < _groq_disabled_until:
        return True
    if redis_client:
        blocked = await redis_client.get(_GROQ_BLOCKED_KEY)
        if blocked:
            until = float(blocked)
            if time.time() < until:
                _groq_disabled_until = until
                return True
    return False


async def _set_groq_blocked(retry_after: int = 60):
    global _groq_disabled_until
    until = time.time() + retry_after
    _groq_disabled_until = until
    if redis_client:
        await redis_client.setex(_GROQ_BLOCKED_KEY, retry_after, str(until))
    print(f"[GROQ] Blocked for {retry_after}s (until {time.ctime(until)})")


async def generate_metadata(transcript: str, short_num: int, video_info: dict = None) -> dict:
    client = await get_groq_client()
    if not client:
        return _default_metadata(short_num, "AI-метаданные не созданы: ключ Groq не настроен")

    if await is_groq_blocked():
        print("[GROQ] Skipped (blocked after previous error)")
        return _default_metadata(short_num, "Groq временно отключён после предыдущей ошибки или лимита")

    cache_key = f"meta:{hash(transcript)}"
    cached = await cache_get_json(cache_key)
    if cached:
        return cached

    if not await check_groq_rate_limit():
        print("[GROQ] Rate limit reached, using fallback")
        return _default_metadata(short_num, "исчерпан дневной лимит Groq")

    video_title = video_info.get("title", "") if video_info else ""

    prompt = f"""Ты — топовый SEO-специалист и эксперт по вирусным алгоритмам YouTube Shorts. 
Твоя задача — проанализировать исходные данные видео и создать метаданные, которые обеспечат максимальный CTR.

Входные данные:
- Тема или базовое название: {video_title}
- Контекст / Транскрибация видео: {transcript}

Правила генерации:
1. ЗАГОЛОВОК (title): Должен создавать сильную интригу (curiosity gap) или бить в эмоции. Длина — до 60 символов. Добавь 2-3 релевантных #хештега.
2. ОПИСАНИЕ (description): 2-3 коротких предложения. Первое — хук. Органично впиши ключевые слова. Строго заканчивается фразой: "Подпишись!"
3. ТЕГИ (tags): 10-15 тегов на АНГЛИЙСКОМ языке (long-tail keywords).
4. ФОРМАТ ВЫВОДА: Только валидный JSON, без markdown.

Пример:
{{
  "title": "Секрет, который от нас скрывали! #shorts #лайфхак",
  "description": "Узнай, как этот простой трюк меняет всё. Подпишись!",
  "tags": ["mindblowing secret trick", "daily life hack hidden", "viral satisfying moment"]
}}

Выполни задачу для текущих входных данных и верни JSON:"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=500
        )
        content = response.choices[0].message.content
        print(f"[GROQ] Raw: {content[:100]}...")
        content = content.strip().replace("```json", "").replace("```", "").replace("`", "")
        metadata = json.loads(content)

        result = {
            "title": metadata.get("title", f"#shorts #{short_num}"),
            "description": metadata.get("description", "Подпишись!"),
            "tags": ["#" + t.strip("# ") for t in metadata.get("tags", ["shorts", "viral"])]
        }
        await cache_set_json(cache_key, result, ttl=86400)
        return result
    except RateLimitError as e:
        retry_after = 60
        if hasattr(e, 'response') and e.response is not None:
            retry_after = int(e.response.headers.get("Retry-After", "60"))
        elif hasattr(e, 'headers') and e.headers:
            retry_after = int(e.headers.get("Retry-After", "60"))
        print(f"[GROQ] RateLimitError, retry-after={retry_after}s")
        await _set_groq_blocked(retry_after)
        return _default_metadata(short_num, f"исчерпан лимит Groq; повтор через {retry_after} сек.")
    except APIStatusError as e:
        retry_after = 120
        if hasattr(e, 'response') and e.response is not None:
            retry_after = int(e.response.headers.get("Retry-After", "120"))
        print(f"[GROQ] APIStatusError {e.status_code}, block {retry_after}s")
        await _set_groq_blocked(retry_after)
        status = getattr(e, "status_code", 0)
        if status in (401, 403):
            reason = "API-ключ Groq недействителен или у него нет доступа"
        elif status >= 500:
            reason = f"ошибка сервера Groq ({status})"
        else:
            reason = f"Groq отклонил запрос ({status})"
        return _default_metadata(short_num, reason)
    except Exception as e:
        print(f"[GROQ] Error: {e}")
        raw = str(e).replace("\n", " ")[:240]
        reason = "Groq вернул неверный JSON" if isinstance(e, json.JSONDecodeError) else raw
        return _default_metadata(short_num, reason)


def _default_metadata(short_num: int, ai_error: str = None) -> dict:
    result = {
        "title": f"#shorts #тренд #{short_num}",
        "description": "Смотри до конца! Подпишись!",
        "tags": ["#shorts", "#viral", "#trending", "#fun", "#wow", "#amazing"]
    }
    if ai_error:
        result["_ai_error"] = ai_error
    return result
