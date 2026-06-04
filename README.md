# Video to Shorts Bot

Автоматический бот для создания коротких видео (Shorts/Reels) из длинных видео с AI-выбором лучших моментов.

## Возможности

- **Smart Selection** — 4 режима: off / global (топ) / parts (сетка) / hybrid (гибрид)
- **Whisper** — распознавание речи с таймингами слов
- **InterestNet** — нейросеть на PyTorch (14 признаков: текст + аудио + визуал)
- **LLM scoring** — GPT-дооценка топ-кандидатов (опционально)
- **Субтитры** — автоматические субтитры с настройкой стиля
- **Баннер** — изображение или видео поверх шортса
- **Размытый фон** — 9:16 формат с blur-эффектом
- **YouTube Upload** — автозагрузка через YouTube Data API
- **Мультиаккаунт** — распределение по аккаунтам
- **Отложенная публикация** — планирование на потом
- **Статистика** — отслеживание созданных шортсов и обработанных видео
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

### Режимы

| Режим | Описание |
|-------|----------|
| **off** | Простое деление на равные части, без анализа |
| **global** | Топ-N лучших окон по всему видео (качество, не равномерно) |
| **parts** | 1 лучший из каждой части видео (равномерно, качество ниже) |
| **hybrid** | Топ-3 из каждой части → глобальный реранк (рекомендуемый) |

### Движки скоринга

**Простая формула (≤ 7200с):** 6 текстовых метрик — плотность, речь/тишина, длина фраз, разнообразие, эмоции, темп. Score 0–100.

**InterestNet (> 7200с):** 14 признаков — текст (7) + аудио (4: громкость, пик, вариация, тишина) + визуал (3: сцены, лица, движение). Нейросеть 14→32→16→1, Sigmoid, обучение 20 эпох прямо на видео.

### Пайплайн

1. **Whisper** — транскрипция (модель base)
2. **Сборка фраз** — склейка сегментов по паузам (< 1с)
3. **ffmpeg** — извлечение аудио + кадров (1 раз, кеш)
4. **Скользящее окно** — short_length, шаг short_length//2
5. **Скоринг** — простая формула или InterestNet
6. **Отбор непересекающихся**
7. **(ОПЦИОНАЛЬНО) LLM scoring** — GPT дооценка топ-10
8. **Генерация метаданных** — Groq/OpenAI (название, описание, теги)

### Финальный score (с LLM)

```python
final_score = 0.6 × nn_score + 0.4 × llm_score
```

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