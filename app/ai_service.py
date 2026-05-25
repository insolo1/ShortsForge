import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()


class AIService:
    def __init__(self):
        self._client = None
        self._api_key = None
    
    @property
    def client(self):
        load_dotenv(override=True)
        api_key = os.getenv("GROQ_API_KEY", "")
        if api_key and api_key != self._api_key:
            self._client = Groq(api_key=api_key)
            self._api_key = api_key
        elif not api_key:
            self._client = None
            self._api_key = None
        return self._client
    
    async def generate_metadata(self, transcript: str, short_num: int, video_info: dict = None) -> dict:
        if not self.client:
            return self._default_metadata(short_num)
        
        video_title = video_info.get("title", "") if video_info else ""
        
        try:
            prompt = f"""Ты - эксперт по созданию контента для YouTube Shorts. 
Создай цепляющий заголовок и описание для короткого видео.

Видео: {video_title}
Время: {transcript}

Правила:
1. Заголовок должен быть с #хештегами для вирусности
2. Описание должно заканчиваться на "Подпишись!"
3. Теги - низкочастотные слова на английском

Пример формата:
{{"title": "#shorts #видео #тренд Крутой момент!", "description": "Смотри до конца! 🔥 Подпишись!", "tags": ["shorts", "viral", "trending", "fun", "wow"]}}

Создай JSON с title, description, tags."""

            response = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.9,
                max_tokens=500
            )
            
            content = response.choices[0].message.content
            print(f"[AI] Raw response: {content}")
            content = content.strip().replace("```json", "").replace("```", "").replace("`", "")
            metadata = json.loads(content)
            
            return {
                "title": metadata.get("title", f"#shorts #{short_num}"),
                "description": metadata.get("description", "Подпишись!"),
                "tags": metadata.get("tags", ["shorts", "viral"])
            }
            
        except Exception as e:
            print(f"[AI] Error: {str(e)}")
            return self._default_metadata(short_num)
    
    def _default_metadata(self, short_num: int) -> dict:
        return {
            "title": f"#shorts #тренд #{short_num} 🔥",
            "description": "Смотри до конца! Подпишись! 👍",
            "tags": ["shorts", "viral", "trending", "fun", "wow", "amazing"]
        }
    
    async def select_best_segments(self, full_transcript: str, short_length: int = 45) -> list:
        """Выбирает 3 лучших фрагмента из транскрипта по критериям вирусности"""
        if not self.client:
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

            response = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
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