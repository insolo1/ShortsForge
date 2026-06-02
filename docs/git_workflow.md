# Git workflow для videobot

## Первый запуск

```bash
git clone https://github.com/твой-username/videobot.git
cd videobot
```

## Ежедневная работа

### Перед началом — получить последние изменения

```bash
git pull
```

### Посмотреть что изменилось

```bash
git status            # изменённые файлы
git diff              # содержимое изменений
git log --oneline -5  # последние 5 коммитов
```

### Закоммитить изменения

```bash
git add -A                    # добавить всё
git commit -m "Краткое описание"
```

### Отправить на сервер

```bash
git push
```

## Полезные команды

| Действие | Команда |
|----------|---------|
| Отменить изменения в файле | `git checkout -- файл.py` |
| Убрать файл из staged | `git reset HEAD файл.py` |
| Посмотреть историю | `git log --oneline --graph` |
| Создать ветку | `git checkout -b feature-name` |
| Вернуться на main | `git checkout main` |
| Слить ветку | `git merge feature-name` |
| Откатить последний коммит (локально) | `git reset --soft HEAD~1` |

## Структура проекта

```
videobot/
├── app/
│   ├── main.py           # FastAPI сервер и все роуты
│   ├── processor.py      # Обработка видео (ffmpeg, Whisper)
│   ├── youtube_api.py    # YouTube API / OAuth
│   ├── ai_service.py     # Groq AI (метаданные)
│   └── ...
├── static/
│   ├── index.html        # Главная страница
│   ├── admin.html        # Админ-панель
│   ├── script.js         # Фронтенд-логика
│   └── ...
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env
```

## Что НЕ нужно коммитить

Файлы в `.dockerignore` и `.gitignore` уже исключены. Проверяй перед коммитом:

```bash
git status
```

Если увидел `.env`, `jobs.json`, `tokens/` — добавь их в `.gitignore`:

```bash
echo ".env" >> .gitignore
git add .gitignore
git commit -m "Add .env to gitignore"
```

## CI/CD (опционально)

При пуше в `main` можно настроить автодеплой через GitHub Actions:

1. На сервере установлен Docker + docker-compose
2. В репозитории настроен secret `SSH_KEY`
3. GitHub Actions делает `git pull && docker-compose build && docker-compose up -d`

Пример `.github/workflows/deploy.yml`:

```yaml
name: Deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v0.1.5
        with:
          host: ${{ secrets.HOST }}
          username: ${{ secrets.USER }}
          key: ${{ secrets.SSH_KEY }}
          script: |
            cd videobot
            git pull
            docker-compose build
            docker-compose up -d
```
