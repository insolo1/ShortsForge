FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Код монтируется через volume, нужен только requirements для установки зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV FFMPEG_PATH=/usr/bin/ffmpeg
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
