import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()


class AIService:
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY", "")
        if api_key:
            self.client = Groq(api_key=api_key)
        else:
            self.client = None
    
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