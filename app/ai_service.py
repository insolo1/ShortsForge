import os
import json
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv

from api_keys import get_keys

load_dotenv()


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


class AIService:
    def __init__(self):
        self._client = None
        self._api_key = None

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
                print(f"[AI] Key failed ({provider}), trying next: {retryable} -> {e}")
                if not retryable:
                    break

        print(f"[AI] All {len(keys)} keys failed for {provider}: {last_err}")
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
        providers = [
            provider for provider in ("groq", "openai") if get_keys(provider)
        ]
        if not providers:
            return self._default_metadata(short_num)
        
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
            for provider in providers:
                try:
                    content = self._chat(
                        provider, "llama-3.3-70b-versatile",
                        [{"role": "user", "content": prompt}],
                        temperature=0.9,
                        max_tokens=500,
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    print(f"[AI] Provider {provider} failed: {exc}")
            if content is None:
                raise last_error or RuntimeError("No AI provider returned metadata")

            print(f"[AI] Raw response: {content}")
            content = content.strip().replace("```json", "").replace("```", "").replace("`", "")
            metadata = json.loads(content)
            
            return {
                "title": metadata.get("title", f"#shorts #{short_num}"),
                "description": metadata.get("description", "Подпишись!"),
                "tags": ["#" + t.strip("# ") for t in metadata.get("tags", ["shorts", "viral"])]
            }
            
        except Exception as e:
            print(f"[AI] Error: {str(e)}")
            return self._default_metadata(short_num)
    
    def _default_metadata(self, short_num: int) -> dict:
        return {
            "title": f"#shorts #тренд #{short_num} 🔥",
            "description": "Смотри до конца! Подпишись! 👍",
            "tags": ["#shorts", "#viral", "#trending", "#fun", "#wow", "#amazing"]
        }
    
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

            response = self._chat(
                "groq", "llama-3.3-70b-versatile",
                [{"role": "user", "content": prompt}],
                temperature=0.8,
                max_tokens=2000
            )
            
            content = response.choices[0].message.content
            content = content.strip().replace("```json", "").replace("```", "").strip("`")
            segments = json.loads(content)
            
            print(f"[AI] Selected {len(segments)} best segments")
            return segments
            
        except Exception as e:
            print(f"[AI] Error selecting segments: {e}")
            return []