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
| 🐳 **Docker** | Воспроизводимый запуск на Windows и Linux-серверах |

## 🆕 Последние изменения

- Большие результаты автоматически делятся на отдельные ZIP-части размером до 1,5 ГБ.
- При загрузке папки нарезки сохраняют группировку по исходным видео.
- Если нарезки одного видео превышают 1,5 ГБ, внутри архивов создаются папки `Название видео 1`, `Название видео 2` и далее.
- ZIP скачивается напрямую, без загрузки всего архива в память страницы, что устраняет частую ошибку `Failed to fetch`.
- Ускорена CPU-обработка: Whisper использует быстрый поиск, VAD и настраиваемое число потоков; FFmpeg использует профиль `veryfast`.
- Если Docker не может записать файл в `uploads/banners`, баннер автоматически сохраняется в доступную папку `uploads`.
- Docker сохраняет между пересборками настройки, историю заданий, результаты и кэш модели Whisper.

---

## 🚀 Быстрый старт

Самый простой и воспроизводимый вариант — Docker. Для локальной разработки без Docker понадобится Python 3.11 и установленный FFmpeg.

### Вариант 1 — Windows (локально, без Docker)

Установи:

- [Visual Studio Code](https://code.visualstudio.com/)
- [Git for Windows x64](https://git-scm.com/download/win) для обычных процессоров Intel/AMD
- [Python 3.11](https://www.python.org/downloads/release/python-3119/)
- полную сборку FFmpeg 5.1 или новее (инструкция ниже)

При установке Python обязательно отметь `Add Python to PATH`. FFmpeg на Windows проще всего установить через Winget:

```powershell
winget install --id Gyan.FFmpeg -e
```

Полностью закрой VS Code и PowerShell после установки, затем открой их заново: уже запущенные процессы не получают обновлённый `PATH`. В новом терминале проверь программы:

```powershell
git --version
py -3.11 --version
ffmpeg -version
```

Клонируй актуальную ветку проекта:

```powershell
git clone --branch develop https://github.com/insolo1/ShortsForge.git
cd ShortsForge
code .
```

Если `code .` не работает, выбери в VS Code **File → Open Folder → ShortsForge**. Проверить текущую папку можно командой `Get-Location`.

Создай конфигурацию:

```powershell
Copy-Item .env.example .env
code .env
```

### Надёжная настройка FFmpeg на Windows

Сначала узнай путь, который зарегистрировал Winget, и проверь запуск файла напрямую:

```powershell
$ffmpeg = (Get-Command ffmpeg.exe -ErrorAction Stop).Source
$ffmpeg
& $ffmpeg -version
```

Ожидаемый результат заканчивается строкой `Exiting with exit code 0`. Запиши **полный путь к файлу `ffmpeg.exe`** в `.env` в корне проекта, используя прямые слеши:

```env
FFMPEG_PATH=C:/Users/User/AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe
```

Не указывай в `FFMPEG_PATH` папку проекта, каталог `bin` без имени файла или путь с повреждённой кириллицей вида `Р±Рё...`. Файл `.env` должен быть сохранён в UTF-8.


После настройки FFmpeg продолжи в терминале VS Code:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Проверь, что Uvicorn и FFmpeg доступны именно этому окружению:

```powershell
.\.venv\Scripts\python.exe -m uvicorn --version
.\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(override=True); import os, subprocess; p=os.getenv('FFMPEG_PATH', 'ffmpeg'); print(repr(p)); subprocess.run([p, '-version'], check=True)"
```

Если обе проверки проходят без `Traceback`, окружение настроено правильно. Активируй его:

```powershell
.\.venv\Scripts\Activate.ps1
```

В начале строки терминала должно появиться `(.venv)`. Если PowerShell запрещает активацию, один раз выполни:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Закрой терминал, открой новый и снова выполни `.\.venv\Scripts\Activate.ps1`.

API-ключ для создания названий и описаний необязателен. При необходимости добавь в `.env` ключ Groq:

```env
GROQ_API_KEY=сюда_ключ
```

Или OpenAI:

```env
OPENAI_API_KEY=сюда_ключ
OPENAI_MODEL=gpt-4o-mini
OPENAI_CHAT_MODEL=gpt-4o-mini
```

Создай администратора и запусти сайт:

```powershell
python create_user.py
python run.py
```

Открой `http://127.0.0.1:8000`. Остановка — `Ctrl+C`.

Последующие запуски:

```powershell
.\.venv\Scripts\Activate.ps1
python run.py
```

Обновление проекта:

```powershell
git pull origin develop
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

Для доступа с телефона или другого компьютера в одной сети запусти:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
ipconfig
```

На другом устройстве открой `http://IP_КОМПЬЮТЕРА:8000`. Если Windows блокирует подключение, выполни PowerShell от администратора:

```powershell
New-NetFirewallRule `
  -DisplayName "VideoBot 8000" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 8000 `
  -Action Allow
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
| `ffmpeg not found` или `[WinError 2]` | Выполни `winget install --id Gyan.FFmpeg -e`, перезапусти VS Code и укажи абсолютный путь к `ffmpeg.exe` в `.env` |
| `[WinError 5] Отказано в доступе` при запуске FFmpeg | `FFMPEG_PATH` часто указывает на папку. Укажи полный путь, заканчивающийся на `ffmpeg.exe`, и проверь его командой `& $env:FFMPEG_PATH -version` |
| `python-dotenv could not parse statement` | Исправь указанную строку `.env`, сохрани файл в UTF-8; не используй повреждённую кириллицу вида `Р±Рё...` |
| `No module named uvicorn` или команда `uvicorn` не найдена | Запускай `.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload`; если модуля нет, повтори установку `requirements.txt` этим же Python |
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

Репозиторий использует `develop` для разработки. Все команды выполняются в терминале VS Code из папки `ShortsForge`.

Получить проект впервые:

```powershell
git clone --branch develop https://github.com/insolo1/ShortsForge.git
cd ShortsForge
```

Перед коммитом проверь, что секреты и видео не попали в индекс:

```powershell
git status --short
git diff --check
git diff
```

Опубликовать только изменения README:

```powershell
git add README.md
git diff --cached
git commit -m "Update installation guide and feature documentation"
git push origin develop
```

Опубликовать исходники вместе с документацией:

```powershell
git add app/main.py app/processor.py app/integrations/whisper.py .env.example .gitignore README.md Dockerfile docker-compose.yml run.py
git diff --cached
git commit -m "Add split ZIP downloads and optimize video processing"
git push origin develop
```

Получить последние обновления на другом компьютере:

```powershell
git switch develop
git pull --ff-only origin develop
python -m pip install -r requirements.txt
```

Не используй `git add .`, пока не убедишься, что `.env`, OAuth-токены, API-ключи и видео игнорируются. Для стабильного релиза создай Pull Request из `develop` в `main` на GitHub. Если работаешь один и хочешь выполнить слияние локально:

```powershell
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
