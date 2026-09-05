import os
import json
import sys
import re
import time
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv

from api_keys import get_keys

# Windows-консоль (cp1251) падает на эмодзи в print — делаем вывод безопасным
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="backslashreplace")
    except Exception:
        pass

load_dotenv()

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


def _is_retryable(err) -> bool:
    """True если ошибку можно обойти другим API-ключом (лимит/доступ)."""
    if not err:
        return False
    status = getattr(err, "status_code", None)
    if status in (401, 403, 429):
        return True
    code = getattr(err, "code", None)
    msg = str(getattr(err, "message", "")).lower() + " " + str(err).lower()
    if code in ("invalid_api_key", "rate_limit_exceeded", "insufficient_quota", "authentication_error", "permission_denied"):
        return True
    if any(k in msg for k in ("rate limit", "quota", "too many requests", "invalid api key", "authentication", "unauthorized")):
        return True
    return False


def _is_rate_limit(err) -> bool:
    if not err:
        return False
    status = getattr(err, "status_code", None)
    code = str(getattr(err, "code", "") or "").lower()
    message = str(err).lower()
    return (
        status == 429
        or code in ("rate_limit_exceeded", "insufficient_quota")
        or any(token in message for token in ("rate limit", "quota", "too many requests", "tokens per"))
    )


def _retry_after_seconds(err, default: int = 900) -> int:
    message = str(err or "")
    match = re.search(r"try again in\s+(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?", message, re.I)
    if not match:
        return default
    hours, minutes, seconds = (float(value or 0) for value in match.groups())
    parsed = int(hours * 3600 + minutes * 60 + seconds) + 5
    return max(30, min(parsed, 24 * 3600))

def describe_ai_error(err) -> str:
    """Convert provider exceptions into a concise message suitable for job logs."""
    if not err:
        return "AI не ответил: причина не указана"
    status = getattr(err, "status_code", None)
    code = str(getattr(err, "code", "") or "").lower()
    raw = str(err).strip()
    message = raw.lower()
    if _is_rate_limit(err):
        wait_seconds = _retry_after_seconds(err)
        wait_minutes = max(1, round(wait_seconds / 60))
        return f"исчерпан лимит запросов или токенов; AI отключён примерно на {wait_minutes} мин."
    elif status in (401, 403) or code in ("invalid_api_key", "authentication_error", "permission_denied"):
        reason = "API-ключ недействителен или у него нет доступа"
    elif status and int(status) >= 500:
        reason = f"ошибка сервера AI ({status})"
    elif any(token in message for token in ("timeout", "timed out")):
        reason = "сервер AI не ответил вовремя"
    elif any(token in message for token in ("connection", "network", "dns", "temporarily unavailable")):
        reason = "ошибка сети при обращении к AI"
    elif isinstance(err, json.JSONDecodeError) or "json" in message:
        reason = "AI вернул ответ в неверном JSON-формате"
    else:
        reason = raw or err.__class__.__name__
    detail = raw.replace("\n", " ")[:240]
    if detail and detail.lower() not in reason.lower():
        return f"{reason}: {detail}"
    return reason


class AIService:
    def __init__(self):
        self._client = None
        self._api_key = None
        self._provider_cooldown_until = {}

    def _chat(self, provider: str, model: str, messages: list,
              temperature: float = 0.8, max_tokens: int = 500) -> str:
        """Return response text, trying each saved key for the provider."""
        keys = get_keys(provider)
        if not keys:
            raise RuntimeError(f"No API keys configured for {provider}")

        last_err = None
        for key in keys:
            try:
                if provider == "openai":
                    client = OpenAI(api_key=key)
                    if hasattr(client, "responses"):
                        response = client.responses.create(
                            model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
                            input=messages,
                            max_output_tokens=max_tokens,
                        )
                        return response.output_text
                    response = client.chat.completions.create(
                        model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    return response.choices[0].message.content

                client = Groq(api_key=key)
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content
            except Exception as e:
                last_err = e
                retryable = _is_retryable(e)
                print(f"[AI] Key failed ({provider}), trying next: {retryable} -> {describe_ai_error(e)}")
                if not retryable:
                    break

        print(f"[AI] All {len(keys)} keys failed for {provider}: {describe_ai_error(last_err)}")
        raise last_err

    @property
    def client(self):
        """Backward-compat: returns a client for the first available Groq key."""
        load_dotenv(override=True)
        keys = get_keys("groq")
        if not keys:
            api_key = os.getenv("GROQ_API_KEY", "")
            keys = [api_key] if api_key else []
        api_key = keys[0] if keys else ""
        if api_key and api_key != self._api_key:
            self._client = Groq(api_key=api_key)
            self._api_key = api_key
        elif not api_key:
            self._client = None
            self._api_key = None
        return self._client
    
    async def generate_metadata(self, transcript: str, short_num: int, video_info: dict = None) -> dict:
        configured_providers = [
            provider for provider in ("groq", "openai") if get_keys(provider)
        ]
        now = time.time()
        providers = [
            provider for provider in configured_providers
            if self._provider_cooldown_until.get(provider, 0) <= now
        ]
        if not configured_providers:
            return self._default_metadata(short_num, "AI-метаданные не созданы: API-ключ Groq/OpenAI не настроен")
        if not providers:
            remaining = max(
                1,
                round((min(self._provider_cooldown_until[p] for p in configured_providers) - now) / 60)
            )
            return self._default_metadata(
                short_num,
                f"AI временно пропущен после лимита; повтор примерно через {remaining} мин."
            )
        
        video_title = video_info.get("title", "") if video_info else ""
        
        try:
            prompt = f"""Ты — топовый SEO-специалист и эксперт по вирусным алгоритмам YouTube Shorts. 
Твоя задача — проанализировать исходные данные видео и создать метаданные, которые обеспечат максимальный CTR (кликабельность), вовлечение аудитории и органический охват.

Входные данные:
- Тема или базовое название: {video_title}
- Контекст / Транскрибация видео: {transcript}

Правила генерации:
1. ЗАГОЛОВОК (title): Должен создавать сильную интригу (curiosity gap) или бить в эмоции (шок, юмор, польза). Длина — до 60 символов, чтобы текст не обрезался на экранах смартфонов. Добавь 2-3 релевантных и популярных #хештега.
2. ОПИСАНИЕ (description): Напиши 2-3 коротких предложения. Первое предложение должно служить "хуком" (крючком) для зрителя. Органично впиши ключевые слова по теме видео для SEO-оптимизации. Описание должно строго заканчиваться фразой: "Подпишись!"
3. ТЕГИ (tags): Сгенерируй 10-15 тегов. Это должны быть низкочастотные и среднечастотные поисковые запросы (long-tail keywords) СТРОГО НА АНГЛИЙСКОМ ЯЗЫКЕ, чтобы алгоритм рекомендовал ролик на глобальную аудиторию.
4. ФОРМАТ ВЫВОДА: Верни ТОЛЬКО валидный JSON. Не пиши никаких вступительных слов, не используй форматирование Markdown (без ```json). Твой ответ должен сразу начинаться с символа {{ и заканчиваться символом }}.

Пример ожидаемого вывода:
{{
  "title": "Секрет, который от нас скрывали! 🤫 #shorts #лайфхак",
  "description": "Узнай, как этот простой трюк меняет всё. Ты делал это неправильно всю жизнь! 🔥 Подпишись!",
  "tags": ["mindblowing secret trick", "daily life hack hidden", "viral satisfying moment", "how to do it right", "lifehack compilation"]
}}

Выполни задачу для текущих входных данных и верни JSON:"""

            content = None
            last_error = None
            provider_errors = []
            for provider in providers:
                try:
                    content = self._chat(
                        provider, GROQ_MODEL,
                        [{"role": "user", "content": prompt}],
                        temperature=0.9,
                        max_tokens=1500,
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    if _is_rate_limit(exc):
                        self._provider_cooldown_until[provider] = time.time() + _retry_after_seconds(exc)
                    readable_provider_error = describe_ai_error(exc)
                    provider_errors.append(f"{provider}: {readable_provider_error}")
                    print(f"[AI] Provider {provider} failed: {readable_provider_error}")
            if content is None:
                raise last_error or RuntimeError("No AI provider returned metadata")

            print(f"[AI] Raw response: {content[:500]}")
            content = content.strip().replace("```json", "").replace("```", "").replace("`", "")
            metadata = json.loads(content)
            
            result = {
                "title": metadata.get("title", f"#shorts #{short_num}"),
                "description": metadata.get("description", "Подпишись!"),
                "tags": ["#" + t.strip("# ") for t in metadata.get("tags", ["shorts", "viral"])]
            }
            if provider_errors:
                result["_ai_warnings"] = provider_errors
            return result
            
        except Exception as e:
            readable_error = describe_ai_error(e)
            print(f"[AI] Error: {readable_error}")
            return self._default_metadata(short_num, readable_error)
    
    def _default_metadata(self, short_num: int, ai_error: str = None) -> dict:
        result = {
            "title": f"#shorts #тренд #{short_num} 🔥",
            "description": "Смотри до конца! Подпишись! 👍",
            "tags": ["#shorts", "#viral", "#trending", "#fun", "#wow", "#amazing"]
        }
        if ai_error:
            result["_ai_error"] = ai_error
        return result
    
    async def select_best_segments(self, full_transcript: str, short_length: int = 45) -> list:
        """Выбирает 3 лучших фрагмента из транскрипта по критериям вирусности"""
        if not get_keys("groq"):
            return []
        
        try:
            prompt = f"""Действуй как эксперт по виртуальным YouTube Shorts.
Я дам тебе текст длинного видео. Выбери из него 3 лучших фрагмента для нарезки Shorts.

Критерии идеального куска:
1. Сильный хук: Фрагмент начинается сразу с главного (интрига, парадокс, разрушение мифа или сильная эмоция).
2. Автономность: Смысл полностью понятен без просмотра основного видео. Никаких "как я уже говорил", "в предыдущей части".
3. Хронометраж: Текст фрагмента должен быть в пределах 100–150 слов (чтобы уложиться в 30–60 секунд при скорости ~2 слов/сек).

Текст видео:
{full_transcript}

Формат ответа для каждого из 3 фрагментов (строгий JSON массив):
[
  {{
    "title": "Заголовок - цепляющая фраза для надписи на видео (5-7 слов)",
    "quote": "Точный текст спикера от первого до последнего слова фрагмента (100-150 слов)",
    "feature": "Одно предложение - почему этот кусок удержит внимание зрителя"
  }},
  ...ещё 2 фрагмента
]

Верни только JSON массив без markdown кодовых блоков."""

            content = self._chat(
                "groq", GROQ_MODEL,
                [{"role": "user", "content": prompt}],
                temperature=0.8,
                max_tokens=2000
            )
            
            content = content.strip().replace("```json", "").replace("```", "").strip("`")
            segments = json.loads(content)
            
            print(f"[AI] Selected {len(segments)} best segments")
            return segments
            
        except Exception as e:
            print(f"[AI] Error selecting segments: {e}")
            return []