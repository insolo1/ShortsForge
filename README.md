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

Самый простой и воспроизводимый вариант — Docker. Для локальной разработки без Docker понадобится Python 3.11 и установленный FFmpeg.

### Вариант 1 — Windows (локально, без Docker)

```powershell
# 1. Установи Python 3.11, Git и FFmpeg. Добавь FFmpeg в PATH:
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

Если PowerShell запрещает активацию окружения, выполни один раз от своего пользователя:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Вариант 2 — Linux / сервер (Docker, рекомендуется)

Нужны Git, Docker Engine и плагин Docker Compose. Проверка:

```bash
git --version
docker --version
docker compose version
```

```bash
git clone https://github.com/insolo1/ShortsForge.git
cd ShortsForge

# 1. Конфигурация. Не добавляй созданный .env в Git.
cp .env.example .env
nano .env

# 2. Постоянные каталоги и JSON-файлы для bind mounts
mkdir -p uploads output saved tokens google_credentials cache/whisper
for file in users.json sessions.json presets.json jobs.json job_logs.json settings.json api_keys.json; do
  [ -f "$file" ] || printf '{}\n' > "$file"
done

# 3. Создай пользователя для входа
python3 create_user.py

# Контейнер работает от UID 1000
sudo chown -R 1000:1000 uploads output saved tokens google_credentials cache \
  users.json sessions.json presets.json jobs.json job_logs.json settings.json api_keys.json

# 4. Проверка конфигурации и запуск
docker compose config
docker compose up -d --build videobot
docker compose logs -f videobot
```

Открой `http://IP_СЕРВЕРА:8200`. Если включён UFW:

```bash
sudo ufw allow 8200/tcp
```

Обновление установленного приложения:

```bash
git pull
docker compose up -d --build videobot
docker image prune -f
```

> Активная ветка разработки — `develop`. Для стабильной установки можно заменить команду клонирования на `git clone --branch main https://github.com/insolo1/ShortsForge.git`.

---

## ⚙️ Конфигурация (.env)

Для запуска без AI-метаданных достаточно скопировать `.env.example`. API-ключи Groq/OpenAI необязательны. Никогда не публикуй `.env`, `client_secret.json`, содержимое `tokens/` и рабочие JSON-файлы.

| Переменная | Обязательно | Описание |
|---|---|---|
| `FFMPEG_PATH` | Нет | Путь к ffmpeg (`/usr/bin/ffmpeg` на Linux). По умолчанию `ffmpeg` из PATH |
| `GROQ_API_KEY` | Нет | AI-метаданные (бесплатно на console.groq.com). Fallback на OpenAI |
| `OPENAI_API_KEY` | Нет | Альтернативный AI-провайдер |
| `OPENAI_MODEL` | Нет | По умолчанию `gpt-4o-mini` |
| `OPENAI_CHAT_MODEL` | Нет | По умолчанию `gpt-4o-mini` |
| `WHISPER_MODEL` | Нет | `base` / `small` / `medium` / `large-v3` / `large-v3-turbo` |
| `WHISPER_DEVICE` | Нет | `auto` / `cpu` / `cuda` |
| `WHISPER_CPU_THREADS` | Нет | Потоков CPU для Whisper (по умолчанию до `4`) |
| `WHISPER_BEAM_SIZE` | Нет | `1` — быстро, `5` — точнее, но медленнее |
| `SEGMENT_WORKERS` | Нет | Параллельных задач сегментов (по умолчанию `2`) |
| `VIDEO_PRESET` | Нет | `low` / `medium` / `high` (NVENC) или CPU-пресет |
| `VIDEO_CPU_PRESET` | Нет | CPU-кодирование: по умолчанию `veryfast`; `medium` медленнее |
| `VIDEO_CPU_CRF` | Нет | Качество CPU-кодирования: по умолчанию `20`; меньше — качественнее и медленнее |
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

### Быстрые настройки для CPU-сервера

```env
WHISPER_MODEL=base
WHISPER_CPU_THREADS=4
WHISPER_BEAM_SIZE=1
WHISPER_VAD_FILTER=1
SEGMENT_WORKERS=2
VIDEO_CPU_PRESET=veryfast
VIDEO_CPU_CRF=20
```

`large-v3-turbo` и `large-v3` на сервере без CUDA могут обрабатываться во много раз дольше. Начни с `base`, проверь результат и только затем повышай модель.

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

Для самостоятельного запуска используй только `docker-compose.yml`. Файл `docker-compose.server.yml` относится к авторскому монорепозиторию с дополнительными проектами и из одного этого репозитория не запускается.

Для публикации в интернет рекомендуется поставить перед приложением Nginx или Caddy, включить HTTPS и не открывать порт 8200 напрямую наружу.

### Полезные команды Docker

```bash
docker compose ps                     # состояние
docker compose logs -f videobot       # логи
docker compose restart videobot       # перезапуск
docker compose down                   # остановка без удаления bind-данных
docker compose up -d --build videobot # пересборка после обновления
```

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
| `Permission denied: /app/uploads/banners` | Выполни `sudo chown -R 1000:1000 uploads output saved`; в новой версии также есть автоматический fallback |
| Первый запуск Docker создал папку вместо JSON-файла | Останови Compose, удали именно ошибочно созданную папку и повтори шаг инициализации JSON из инструкции |
| Видео создаётся очень долго | Выбери Whisper `base`, `VIDEO_CPU_PRESET=veryfast`; для `large-v3*` используй CUDA |
| `invalid_grant` от YouTube | Удали просроченный аккаунт/токен в интерфейсе и авторизуй заново |

---

## 📤 Как опубликовать изменения в GitHub

Репозиторий использует `develop` для разработки. Перед коммитом проверь, что секреты и видео не попали в индекс:

```bash
git status --short
git diff --check
git diff
```

Добавь только исходники и публичную документацию:

```bash
git add app/main.py app/processor.py app/integrations/whisper.py \
  .env.example .gitignore README.md Dockerfile docker-compose.yml run.py
git diff --cached
git commit -m "Fix uploads and speed up video processing"
git push origin develop
```

Не используй `git add .`, пока не убедишься, что `.env`, OAuth-токены, API-ключи и видео игнорируются. Для стабильного релиза создай Pull Request из `develop` в `main` на GitHub. Если работаешь один и хочешь выполнить слияние локально:

```bash
git switch main
git pull --ff-only origin main
git merge --no-ff develop
git push origin main
git switch develop
```

---

## 📜 Лицензия

MIT License — см. [LICENSE](LICENSE).

**Сторонние компоненты:**
- Шрифт TikTok Sans: SIL OFL 1.1
- FFmpeg: LGPL/GPL
- faster-whisper и Python-зависимости: их собственные лицензии
