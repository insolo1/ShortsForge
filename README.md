# Video to Shorts Bot

FastAPI-приложение для нарезки длинных видео на вертикальные Shorts/Reels: транскрипция faster-whisper, умный отбор фрагментов, субтитры ASS, баннеры, AI-метаданные и публикация на YouTube.

## Текущее состояние

Основной рабочий контур находится в **app/main.py** и **app/processor.py**. Каталоги **app/api**, **app/tasks**, **app/repositories**, **app/services** и **app/models** содержат модульную архитектуру, но веб-интерфейс и актуальные маршруты пока обслуживаются монолитным FastAPI-приложением из **app/main.py**.

Недавние изменения:

- smart-selection гарантированно добирает запрошенное число непересекающихся фрагментов, если исходник достаточно длинный;
- длинная непрерывная речь Whisper разбивается на ограниченные фразы и корректно участвует в скоринге;
- AI-метаданные реально генерируются после рендера через Groq или OpenAI;
- исправлена UTF-8 строка описания;
- pause-баннер сохраняет заданную итоговую длительность ролика;
- во время pause-баннера звучит только аудио баннера, без наложения основного голоса;
- добавлены TikTok Sans и Montserrat Bold.

## Возможности

- загрузка одного файла или папки с видео;
- создание нескольких роликов параллельно;
- фиксированная или автоматическая длительность;
- smart-selection по транскрипции всего видео;
- отдельный InterestNet-путь для видео длиннее двух часов;
- вертикальный рендер 1080×1920;
- crop-fill, обычный pad или размытый фон;
- субтитры ASS с таймингами слов;
- TikTok Sans, Montserrat, Montserrat Bold/ExtraBold/Black, Bebas Neue и Russo One;
- баннер-картинка или MP4;
- режим обычного overlay;
- режим pause: заморозка кадра, баннер и его аудио, затем продолжение видео;
- AI-заголовок, описание и теги;
- локальные пользователи, роли, проекты и логи;
- YouTube OAuth, несколько аккаунтов и загрузка роликов;
- Docker-развёртывание на порту 8200.

## Как устроен пайплайн

1. Загруженный файл сохраняется в **uploads/**.
2. FFmpeg определяет длительность и доступные потоки.
3. Если smart-selection включён, faster-whisper моделью base транскрибирует всё видео.
4. **VideoProcessor.extract_segments()** выбирает окна.
5. Для каждого окна выполняется точная транскрипция выбранной моделью Whisper.
6. FFmpeg строит вертикальное видео, субтитры и баннер.
7. AIService формирует заголовок, описание и теги.
8. Результаты сохраняются в **output/** и доступны в интерфейсе/ZIP.

Подробности:

- [Smart Selection — руководство](docs/smart_selection.md)
- [Smart Selection — алгоритм](docs/smart_selection_algo.md)
- [Полный пайплайн](docs/full_pipeline.md)
- [Рекомендуемые настройки](docs/optimal_settings.md)

## Smart Selection и Auto-duration

В UI доступны значения **off**, **global**, **parts** и **hybrid**.

В текущей реализации:

- **off** — последовательная нарезка без полного сканирования Whisper;
- **global / parts / hybrid** — запускают один и тот же актуальный smart-движок глобального отбора;
- названия Топ, Сетка и Гибрид сохранены в интерфейсе, но отдельные стратегии parts/hybrid пока не реализованы.

Для видео до 7200 секунд используется текстовый score по шести признакам. Для более длинных видео включается InterestNet с текстовыми, аудио- и визуальными признаками.

**Auto-duration** меняет длину каждого результата:

1. базовый smart-отбор работает с окном max_length;
2. внутри выбранного окна проверяются варианты от min_length до max_length;
3. старт и длина перебираются с шагом 5 секунд;
4. выбирается вариант с максимальным interest score.

Если smart-отбор вернул меньше роликов, чем запросил пользователь, алгоритм добирает непересекающиеся окна по временной сетке. Максимальное число без перекрытий ограничено:

~~~text
floor(video_duration / short_length)
~~~

## Баннеры и длительность

### Overlay

Баннер отображается поверх основного видео. Выходное аудио берётся из первой аудиодорожки исходника:

~~~text
-map 0:a:0?
~~~

Звук MP4-баннера в overlay не подмешивается, иначе речь накладывается на основной голос.

### Pause

В выбранной позиции:

1. основной кадр замораживается;
2. показывается баннер;
3. воспроизводится только аудио баннера либо тишина, если аудиодорожки нет;
4. основное видео продолжается.

Пауза заменяет равный по длительности участок исходника. Поэтому ролик с заданной длиной 59 секунд и баннером 6 секунд остаётся длиной около 59 секунд, а не 65.

## Требования

- Python 3.11+
- FFmpeg с libx264, AAC, libass/subtitles и drawtext
- 8+ ГБ RAM для комфортной транскрипции
- NVIDIA CUDA — опционально для локального faster-whisper/NVENC
- Groq или OpenAI API key — опционально, для AI-метаданных
- Google OAuth credentials — только для YouTube

## Локальная установка

### Windows PowerShell

~~~powershell
cd K:\DIY\videobot

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
~~~

Альтернативная точка запуска:

~~~powershell
python run.py
~~~

Открыть: http://127.0.0.1:8000

FFmpeg должен быть доступен в PATH либо указан в **.env**:

~~~env
FFMPEG_PATH=ffmpeg
~~~

### Linux

~~~bash
sudo apt-get update
sudo apt-get install -y ffmpeg

python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
~~~

## Docker

Основной Compose-файл находится в корне проекта.

~~~bash
cd /path/to/videobot
docker compose up -d --build videobot
docker compose ps
docker compose logs -f --tail=200 videobot
~~~

Сайт: http://SERVER_IP:8200

Проброс портов:

~~~text
host 8200 -> container 8000
~~~

Исходники копируются внутрь образа через Dockerfile, поэтому после изменения Python/HTML/шрифтов нужен rebuild:

~~~bash
docker compose up -d --build --force-recreate videobot
~~~

Обычный restart нового кода в образ не добавляет.

Контейнер работает от UID 1000. При проблемах с записью:

~~~bash
sudo chown -R 1000:1000 uploads output tokens google_credentials
~~~

Текущий Dockerfile устанавливает CPU-версию PyTorch. Для CUDA внутри контейнера нужны NVIDIA Container Toolkit, CUDA-совместимый образ/torch и включённый GPU-блок Compose. Наличие NVIDIA на хосте само по себе не делает текущий Docker-образ GPU-образом.

## Настройки .env

Минимальный пример:

~~~env
FFMPEG_PATH=ffmpeg

WHISPER_MODEL=base
SEGMENT_WORKERS=2
VIDEO_PRESET=medium

GROQ_API_KEY=
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6-luna
OPENAI_CHAT_MODEL=gpt-4o-mini

SUBTITLE_FONT=TikTok Sans
SUBTITLE_STYLE=normal
SUBTITLE_FONTSIZE=100
SUBTITLE_FONTCOLOR=white
SUBTITLE_POSITION_Y=1670
SUBTITLE_CAPITALIZE=1
SUBTITLE_BORDERW=3
SUBTITLE_BORDERCOLOR=black
SUBTITLE_BOX_BORDER=0
SUBTITLE_BOX_COLOR=black@0.8
SUBTITLE_SHADOW_X=2
SUBTITLE_SHADOW_Y=2
SUBTITLE_SHADOW_COLOR=black
SUBTITLE_WORDS_COUNT=3
SUBTITLE_WORD_FADE=1
~~~

API-ключи также можно добавить в настройках интерфейса. В Docker надёжнее хранить постоянные ключи в **.env**: текущий Compose не монтирует **api_keys.json**, поэтому UI-ключи внутри контейнера могут исчезнуть после пересоздания.

Не коммитьте реальные ключи, **client_secret.json**, OAuth-токены, пользовательские данные и содержимое uploads/output.

## AI-метаданные

После успешного рендера каждый ролик получает:

- title;
- description в корректном UTF-8;
- tags.

Порядок провайдеров: Groq, затем OpenAI. Если провайдер недоступен или вернул невалидный JSON, используется безопасный локальный fallback.

Для OpenAI используется Responses API, если установленный SDK его поддерживает. Модель задаётся через **OPENAI_MODEL**.

## Субтитры и шрифты

Шрифты лежат в **fonts/** и передаются libass через fontsdir.

Доступны, среди прочих:

- TikTok Sans;
- Montserrat;
- Montserrat Bold;
- Montserrat ExtraBold;
- Montserrat Black;
- Bebas Neue;
- Russo One.

TikTok Sans распространяется по SIL Open Font License 1.1; копия лицензии находится в **fonts/TikTok Sans OFL.txt**.

## YouTube

1. Создайте проект в Google Cloud Console.
2. Включите YouTube Data API v3.
3. Создайте OAuth credentials типа Desktop app.
4. Положите **client_secret.json** в корень или загрузите credentials через интерфейс.
5. Авторизуйте нужные аккаунты.

Токены сохраняются в **tokens/** и **google_credentials/**.

## Данные проекта

| Путь | Назначение |
|---|---|
| uploads/ | загруженные исходники и баннеры |
| output/ | готовые ролики |
| saved/ | сохранённые проекты/копии |
| tokens/ | YouTube OAuth-токены |
| google_credentials/ | credentials аккаунтов |
| fonts/ | локальные шрифты |
| jobs.json, job_logs.json | состояние и логи задач |
| users.json, sessions.json | локальная авторизация |
| videobot.db | SQLite/модульный слой БД |

При ошибке подключения к внешней БД приложение продолжает работу на JSON-хранилищах.

## Структура

~~~text
videobot/
├── app/
│   ├── main.py               # активное FastAPI-приложение
│   ├── processor.py          # FFmpeg, Whisper, сегменты, субтитры
│   ├── ai_service.py         # Groq/OpenAI метаданные
│   ├── api_keys.py           # хранилище и маскирование ключей
│   ├── segment_scorer.py     # InterestNet и признаки
│   ├── youtube_api.py        # YouTube OAuth/upload
│   ├── api/                  # модульные роуты (переходная архитектура)
│   ├── tasks/                # Celery-задачи (переходная архитектура)
│   └── repositories/         # SQLAlchemy repositories
├── static/                   # текущий HTML/JS интерфейс
├── frontend/                 # отдельный React/Vite frontend
├── fonts/
├── docs/
├── tests/
├── uploads/
├── output/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── run.py
~~~

## Диагностика

### Сайт не открывается

~~~bash
docker compose ps
docker compose logs --tail=200 videobot
curl -v http://127.0.0.1:8200/
~~~

Статус должен быть **Up**, а в логах — запуск Uvicorn на 0.0.0.0:8000.

Ошибка **No module named uvicorn** означает, что образ собран без актуального requirements.txt. Пересоберите без кеша:

~~~bash
docker compose build --no-cache videobot
docker compose up -d --force-recreate videobot
~~~

### Создаётся меньше роликов

Проверьте строки:

~~~text
Scan done: ... words
Found N segments
~~~

Без перекрытия невозможно создать больше floor(duration / short_length). Если smart-кандидатов мало, актуальная версия автоматически включает time-grid fallback.

### Ролик длиннее заданного

В актуальном pause-режиме баннер входит в заданную длительность. Старые ролики нужно перерендерить. Проверьте, что контейнер действительно пересобран с новым **app/processor.py**.

### AI-описание не создаётся

Проверьте:

- ключ присутствует в **.env** или интерфейсе;
- в логе есть **Generating AI metadata...**;
- затем появляется **[AI] Raw response** либо сообщение об ошибке провайдера.

### Два голоса

- overlay использует только первую аудиодорожку источника;
- pause последовательно соединяет source-before, banner/silence и source-after;
- звук не должен собираться через amix;
- сравнивайте именно файл, который получил пользователь, а не старую CDN/браузерную копию.

## Проверка изменений

~~~bash
python -m py_compile app/main.py app/processor.py app/ai_service.py
pytest
git diff --check
~~~

## Лицензирование

Отдельный LICENSE для исходного кода проекта сейчас отсутствует. Не объявляйте проект MIT/Apache без добавления соответствующего файла. Встроенный TikTok Sans лицензирован отдельно по SIL OFL 1.1.
