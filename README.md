<div align="center">

# 🎬 VideoBot

### AI-generator вертикальных шортсов

Превращает длинные видео в вирусные вертикальные **Shorts / Reels / TikTok`и** автоматически.

<img src="https://img.shields.io/badge/python-3.10+-blue" alt="Python 3.10+">
<img src="https://img.shields.io/badge/ffmpeg-required-red" alt="FFmpeg">
<img src="https://img.shields.io/badge/AI-Whisper%20%7C%20Groq%20%7C%20OpenAI-green" alt="AI">

</div>

---

## ✨ Возможности

| | |
|---|---|
| 🎬 **Умный отбор моментов** | Whisper + InterestNet + LLM: находит самые яркие отрезки |
| 📱 **Вертикальный 1080×1920** | Готовый формат под Shorts/Reels/TikTok |
| 🎯 **Pause-режим** | Стоп-кадр + баннер + аудио баннера |
| 🤖 **AI-метаданные** | Заголовки, описания, теги (Groq → OpenAI fallback) |
| ✍️ **Анимированные субтитры** | Настраиваемые шрифты, стили, границы |
| 🧩 **Тактики монтажа** | `off` / `global` / `parts` / `hybrid` |
| 📺 **Загрузка на YouTube** | OAuth + прямой аплоад в один клик |
| 🐳 **Docker** | Работает на серверах и даже в Termux (Android) |

---

## 🚀 Быстрый старт

### Вариант 1 — Windows (локально)

```powershell
# 1. Установи FFmpeg и добавь его в PATH:
#    https://ffmpeg.org/download.html

# 2. Клонируй и настрой
git clone https://github.com/insolo1/ShortsForge.git
cd ShortsForge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Конфигурация
copy .env.example .env    # впиши свои API-ключи

# 4. Создай админа для входа
python create_user.py

# 5. Запуск
python run.py
# Открой http://127.0.0.1:8000
```

### Вариант 2 — Linux / сервер (Docker)

```bash
git clone https://github.com/insolo1/ShortsForge.git
cd ShortsForge

# 1. Папки для Docker (контейнер работает от UID 1000)
mkdir -p uploads output tokens google_credentials
sudo chown -R 1000:1000 uploads output tokens google_credentials

# 2. Конфигурация
cp .env.example .env      # добавь API-ключи, FFMPEG_PATH=/usr/bin/ffmpeg
python3 create_user.py    # создай аккаунт админа

# 3. Запуск
docker compose up -d --build videobot
# Сайт: http://YOUR_SERVER_IP:8200

# Обновление после изменений в коде:
git pull
docker compose up -d --build videobot
```

### Вариант 3 — Termux (Android)

```bash
pkg update && pkg install -y git ffmpeg python3 docker
git clone https://github.com/insolo1/ShortsForge.git
cd ShortsForge
cp .env.example .env
python3 create_user.py
docker compose up -d --build videobot
```

> 💡 Активная ветка по умолчанию — `develop`. Когда нужен стабильный релиз — смёрджи её в `main`.

---

## ⚙️ Конфигурация (.env)

| Переменная | Обязательно | Описание |
|---|---|---|
| `FFMPEG_PATH` | Нет | Путь к ffmpeg (`/usr/bin/ffmpeg` на Linux). По умолчанию `ffmpeg` из PATH |
| `GROQ_API_KEY` | Нет | AI-метаданные (бесплатно на console.groq.com). Fallback на OpenAI |
| `OPENAI_API_KEY` | Нет | Альтернативный AI-провайдер |
| `OPENAI_MODEL` | Нет | По умолчанию `gpt-4o-mini` |
| `OPENAI_CHAT_MODEL` | Нет | По умолчанию `gpt-4o-mini` |
| `WHISPER_MODEL` | Нет | `base` / `small` / `medium` / `large-v3` / `large-v3-turbo` |
| `WHISPER_DEVICE` | Нет | `auto` / `cpu` / `cuda` |
| `SEGMENT_WORKERS` | Нет | Параллельных задач сегментов (по умолчанию `2`) |
| `VIDEO_PRESET` | Нет | `low` / `medium` / `high` (NVENC) или CPU-пресет |
| `YOUTUBE_API_KEY` | Нет | YouTube Data API v3 ключ |
| `DATABASE_URL` | Нет | Postgres (продакшен), иначе без БД |
| `REDIS_URL` | Нет | Redis (брокер Celery для продакшена) |

---

## 🎮 Использование

1. **Открой веб-интерфейс** → `http://localhost:8000` (или `:8200` в Docker)
2. **Войди** — аккаунт, созданный через `create_user.py`
3. **Загрузи видео** — перетащи файл или выбери папку
4. **Настрой**:
   - Длина шортса: рекомендуется 45–60 сек
   - Количество шортсов из одного видео: 2–4
   - Тактика отбора: `hybrid` (лучший универсал)
   - Баннер: картинка или MP4 + pause-режим
5. **Генерируй** — следи за прогрессом в реальном времени
6. **Скачивай** — отдельные MP4 или ZIP (авто-разбивка, максимум 1.5 ГБ на архив)
7. **Публикуй на YouTube** — подключи OAuth, выбери аккаунт, выложи

---

## 🧠 Тактики отбора моментов

| Тактика | Для чего |
|---|---|
| `off` | Последовательная нарезка (сериалы, лонгриды) |
| `global` | Лучшие моменты (реакции, гейминг) |
| `parts` | Равномерное покрытие (лекции, подкасты) |
| `hybrid` | **Лучший баланс** — качество + покрытие |

**Авто-длительность** (включается в UI): подгоняет каждый шортс 45–75 сек под завершённую мысль.

---

## ⏸️ Pause-режим (баннер)

Видео ставится на паузу → показывается баннер + играет аудио баннера → видео продолжается.

- Аудио баннера: MP4-баннер со звуком или тишина (для картинки)
- Длительность: по фактической длине баннера
- Звук синхронизирован — без наложений на речь видео

---

## 📺 Загрузка на YouTube

1. Google Cloud Console → включи **YouTube Data API v3**
2. Создай OAuth-креды типа **Desktop App**
3. Сохрани как `client_secret.json` в корень проекта
4. В UI: Настройки → YouTube-аккаунты → Добавить аккаунт
5. Авторизуй каждый канал один раз (токены хранятся локально в `tokens/`)

---

## 🏭 Продакшен-стек

Для полного продакшена (Postgres + сопутствующие боты) используй `docker-compose.server.yml`:

```bash
cp .env.example .env   # задай POSTGRES_USER / PASSWORD / DB
docker compose -f docker-compose.server.yml up -d --build
```

Стек поднимает:
- `db` — PostgreSQL 13
- `videobot` — это приложение (порт 8200)
- `mitsubishi-docs`, `anamnesis`, `tiktokbot` — сопутствующие сервисы (отдельные репозитории)

---

## 📁 Структура проекта

```
videobot/
├── app/
│   ├── main.py           # FastAPI-приложение + роуты + веб-интерфейс
│   ├── processor.py      # Пайплайн FFmpeg + Whisper
│   ├── ai_service.py     # AI-метаданные (Groq/OpenAI c fallback)
│   ├── youtube_api.py    # OAuth + загрузка
│   ├── core/             # config, security, database, redis
│   ├── services/         # auth-сервис
│   └── api/              # REST-эндпоинты
├── static/               # Веб-интерфейс (HTML/JS)
├── fonts/                # Шрифты субтитров
├── migrations/           # Alembic-миграции
├── uploads/              # Входные видео (gitignored)
├── output/               # Готовые шортсы (gitignored)
├── tokens/               # OAuth-токены YouTube (gitignored)
├── google_credentials/   # Креды сервисных аккаунтов (gitignored)
├── create_user.py        # Первичное создание админа
├── Dockerfile
├── docker-compose.yml
├── docker-compose.server.yml
├── requirements.txt
└── run.py                # Локальный запуск
```

---

## 🖥️ Требования к железу

| Компонент | Минимум | Рекомендуется |
|---|---|---|
| RAM | 8 ГБ | 16+ ГБ |
| GPU | Не нужна (CPU) | NVIDIA 8+ ГБ VRAM (NVENC + быстрый Whisper) |
| Диск | 20 ГБ свободно | 100+ ГБ SSD |
| CPU | 4 ядра | 8+ ядер |

---

## 🔧 Решение проблем

| Проблема | Решение |
|---|---|
| `ffmpeg not found` | Установи ffmpeg, добавь в PATH или задай `FFMPEG_PATH` в .env |
| `CUDA out of memory` | Меньшая Whisper-модель (`base`), снизь `SEGMENT_WORKERS` |
| `Неверный логин или пароль` | Запусти `python3 create_user.py` и задай пароль заново |
| `AI metadata failed` | Проверь API-ключи в .env и квоты (Groq → fallback на OpenAI) |
| `YouTube upload 403` | Пере-авторизуй аккаунт, проверь scopes OAuth |
| `ZIP download fails` | Архивы >1.5 ГБ режутся; качай части отдельно |

---

## 📜 Лицензия

MIT License — см. [LICENSE](LICENSE).

**Сторонние компоненты:**
- Шрифт TikTok Sans: SIL OFL 1.1
- FFmpeg: LGPL/GPL
- faster-whisper и Python-зависимости: их собственные лицензии