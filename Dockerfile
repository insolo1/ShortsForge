FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# CPU-версия torch для Docker (без CUDA, экономит ~2-3 ГБ образа).
# Для GPU: убери эту строку и поставь nvidia-container-toolkit.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/uploads /app/output /app/tokens /app/google_credentials /app/saved /app/.cache/whisper && \
    chown -R appuser:appuser /app

ENV FFMPEG_PATH=/usr/bin/ffmpeg
ENV PYTHONPATH=/app
ENV WHISPER_CACHE_DIR=/app/.cache/whisper
ENV OMP_NUM_THREADS=4
ENV MKL_NUM_THREADS=4
ENV OPENBLAS_NUM_THREADS=4

EXPOSE 8000

USER appuser

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
