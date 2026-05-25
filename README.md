# Video to Shorts Bot

Автоматический бот для создания коротких видео (Shorts/Reels) из длинных видео с AI-выбором лучших моментов.

## Возможности

- **Smart Selection** — нейросетевой выбор лучших моментов (InterestNet + GPT-4)
- ** Whisper** — распознавание речи с таймингами слов
- **Субтитры** — автоматические субтитры с настройкой стиля
- **Размытый фон** — 9:16 формат с blur-эффектом
- **YouTube Upload** — автозагрузка через YouTube Data API
- **Мультиаккаунт** — распределение по аккаунтам
- **Отложенная публикация** — планирование на потом
- **Мобильный UI** — адаптивный интерфейс

## Требования

- Python 3.11+
- FFmpeg
- OpenAI API key (для GPT)

## Установка

### Локально (Windows)

```bash
pip install -r requirements.txt
```

### Docker (VPS)

```bash
cd сервер
docker-compose up -d --build videobot
```

## Настройка

### 1. Создай `.env` файл:

```env
GROQ_API_KEY=your_api_key

# Настройки субтитров
SUBTITLE_FONT="Arial"
SUBTITLE_STYLE="normal"
SUBTITLE_FONTSIZE=75
SUBTITLE_FONTCOLOR="white"
SUBTITLE_POSITION_Y=760
SUBTITLE_CAPITALIZE=1
SUBTITLE_BORDERW=0
SUBTITLE_BORDERCOLOR="black"
SUBTITLE_BOX_BORDER=0
SUBTITLE_BOX_COLOR="black@0.8"
SUBTITLE_SHADOW_X=0
SUBTITLE_SHADOW_Y=0
SUBTITLE_SHADOW_COLOR="black"
```

### 2. YouTube API

1. Создай проект в [Google Cloud Console](https://console.cloud.google.com/)
2. Включи **YouTube Data API v3**
3. Создай **Desktop app** (не Web!) credentials
4. Скачай `client_secret.json` в корень проекта

### 3. FFmpeg

```bash
# Windows: добавь в PATH или установи FFMPEG_PATH в .env
FFMPEG_PATH=ffmpeg

# Linux/VPS
sudo apt install ffmpeg
```

## Запуск

```bash
# Локально
cd app
python main.py

# Docker
cd сервер
docker-compose up -d videobot
```

Открой http://localhost:8000 (или http://VPS_IP:8200 для Docker)

## Алгоритм Smart Selection

1. **Whisper** — транскрибирует видео (1-3 мин для 10 мин видео)
2. **AudioCache** — извлекает аудио features (энергия, тишина)
3. **VisualCache** — извлекает видео features (сцены, лица, движение)
4. **InterestNet** — нейросеть предсказывает score каждого окна
5. **GPT-4o-mini** — подтверждает выбор через LLM scoring
6. **Финальный score** = 0.6 × NN + 0.4 × LLM

## Структура проекта

```
videobot/
├── app/
│   ├── main.py           # FastAPI сервер
│   ├── processor.py      # Обработка видео, FFmpeg
│   ├── segment_scorer.py # NN scoring (InterestNet)
│   ├── ai_service.py     # GPT/Groq интеграция
│   └── youtube_api.py    # YouTube Data API
├── static/
│   ├── index.html        # Главная страница
│   ├── admin.html        # Админка
│   └── notes.html        # Заметки
├── сервер/
│   ├── Dockerfile        # Docker образ
│   └── docker-compose.yml
├── .env                  # Настройки (не коммитить!)
├── client_secret.json    # Google OAuth (не коммитить!)
├── requirements.txt
└── README.md
```

## Развёртывание на VPS (Raspberry Pi)

```bash
# Копирование файлов
scp -r app/ pi@VPS_IP:/home/pi/flask-docker/videobot/
scp -r static/ pi@VPS_IP:/home/pi/flask-docker/videobot/
scp .env pi@VPS_IP:/home/pi/flask-docker/videobot/

# Сборка и запуск
ssh pi@VPS_IP
cd /home/pi/flask-docker
sudo docker-compose up -d --build videobot

# Просмотр логов
sudo docker logs -f videobot

# Рестарт (после изменений кода, без rebuild)
sudo docker-compose restart videobot
```

## Ключевые параметры видео

| Параметр | Значение |
|----------|----------|
| Формат | 9:16 (1080×1920) |
| Codec | libx264 |
| CRF | 18 (качество) |
| Preset | medium |
| Audio | AAC 192k |
| Threads | 4 |

## Параметры субтитров по умолчанию

| Параметр | Дефолт |
|----------|--------|
| Обводка | 0 px |
| Фон рамки | 0 px |
| Тень | 0 px |

## Troubleshooting

### Ошибка "token expired"
- Удали `tokens/` папку
- Переавторизуй аккаунт

### Медленная обработка
- Whisper — главный bottleneck (1-3 мин)
- Для быстрого результата отключи smart_selection

### YouTube upload failed
- Проверь credentials (Desktop app, не Web!)
- Добавь тестовых пользователей в OAuth
- Опубликуй приложение (или токен истечёт через 7 дней)

## Лицензия

MIT