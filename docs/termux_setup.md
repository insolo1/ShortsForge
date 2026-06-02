# Запуск videobot в Termux (Android)

## Вариант 1: Запуск Python напрямую (рекомендуется)

Docker в Termux не поддерживается нативно. Проще запустить приложение напрямую через Python.

### Установка

```bash
pkg update && pkg upgrade -y
pkg install -y python ffmpeg git rust binutils
pip install --upgrade pip
pip install setuptools-rust
```

### Клонирование и установка зависимостей

```bash
git clone https://github.com/твой-username/videobot.git
cd videobot
pip install -r requirements.txt
```

### Настройка

Создай `.env`:

```bash
cp .env.example .env  # или создай вручную
nano .env
```

Минимальное содержимое `.env`:

```
# Без AI и YouTube API ключи — будет работать в офлайн-режиме
# (скрапинг каналов и дефолтные метаданные)
```

### Запуск

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Доступ

Открой в браузере на телефоне: `http://127.0.0.1:8000`

Если хочешь достучаться с другого устройства в той же сети — укажи `--host 0.0.0.0` и используй локальный IP телефона.

---

## Вариант 2: Docker через proot-distro (требуется Android 12+)

Установи Termux, затем:

```bash
pkg install proot-distro
proot-distro install ubuntu
proot-distro login ubuntu
```

Внутри Ubuntu:

```bash
apt update && apt install -y docker.io docker-compose
cd /opt
git clone https://github.com/твой-username/videobot.git
cd videobot
docker-compose up -d
```

Этот вариант **медленный** — Docker внутри proot работает с большими накладными расходами. Рекомендуется Вариант 1.

---

## Полезные команды Termux

| Действие | Команда |
|----------|---------|
| Запуск сервера в фоне | `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &` |
| Остановка сервера | `pkill uvicorn` |
| Просмотр логов | `tail -f nohup.out` |
| Включить режим сна | `termux-wake-lock` |

## Известные ограничения

- Whisper на CPU в Termux работает медленно (~5-10x медленнее ПК)
- NVENC недоступен (нет GPU)
- Для больших видео используй `shorts_count: 1-3`
- Рекомендуемый размер видео: не больше 300 МБ
