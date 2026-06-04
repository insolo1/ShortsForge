import os
import tempfile
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Optional

from app.core.config import settings


_whisper_model = None
_whisper_model_size = None


def _detect_whisper_device() -> tuple:
    device = settings.WHISPER_DEVICE
    compute_type = settings.WHISPER_COMPUTE_TYPE

    if device == "auto":
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
                compute_type = compute_type if compute_type != "auto" else "float16"
            else:
                device = "cpu"
                compute_type = compute_type if compute_type != "auto" else "int8"
        except ImportError:
            device = "cpu"
            compute_type = compute_type if compute_type != "auto" else "int8"
    elif device == "cuda":
        compute_type = compute_type if compute_type != "auto" else "float16"
    else:
        compute_type = compute_type if compute_type != "auto" else "int8"

    return device, compute_type


def _get_model(model_size: str = None):
    global _whisper_model, _whisper_model_size
    size = model_size or settings.WHISPER_MODEL
    if _whisper_model is None or _whisper_model_size != size:
        from faster_whisper import WhisperModel
        device, compute_type = _detect_whisper_device()
        print(f"[WHISPER] Loading '{size}' ({device}, {compute_type})...")
        _whisper_model = WhisperModel(size, device=device, compute_type=compute_type)
        _whisper_model_size = size
    return _whisper_model


def _filter_nondialogue(segments: List[Dict]) -> List[Dict]:
    noise_keywords = [
        "музыка", "аплодисменты", "смех", "крик", "шум", "тишина",
        "песня", "звуки", "кашель", "вздох", "шепот", "бормотание",
        "звук", "музыкальное", "интригующая", "динамичная", "тревожная",
        "спокойная", "фоновая", "громкая", "мелодия", "ритм", "бит"
    ]
    filtered = []
    for seg in segments:
        text = seg.get("text", "").strip().lower()
        words = text.split()
        if len(words) <= 4 and any(kw in text for kw in noise_keywords):
            continue
        if len(words) <= 2 and text.isupper():
            continue
        filtered.append(seg)
    return filtered


async def transcribe(video_path: str, start: float, end: float, word_timestamps: bool = True) -> dict:
    ffmpeg = settings.FFMPEG_PATH
    model = _get_model()

    temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_audio.close()

    try:
        loop = asyncio.get_event_loop()

        cmd = [ffmpeg, "-y",
               "-ss", str(start),
               "-i", video_path,
               "-t", str(end - start),
               "-ar", "16000", "-ac", "1",
               "-acodec", "pcm_s16le",
               temp_audio.name]

        result = await loop.run_in_executor(
            None, lambda: subprocess.run(cmd, capture_output=True, timeout=300)
        )

        if result.returncode != 0:
            err = result.stderr.decode('utf-8', errors='ignore') if result.stderr else ''
            print(f"[WHISPER] Audio extraction failed: {err[:200]}")
            return {"text": "Речь в моменте", "segments": []}

        print(f"[WHISPER] Transcribing {start}s-{end}s...")
        segments_gen, info = await loop.run_in_executor(
            None, lambda: model.transcribe(temp_audio.name, language="ru", word_timestamps=word_timestamps)
        )

        segments_list = []
        word_segments = []
        text_parts = []

        for seg in segments_gen:
            text_parts.append(seg.text)
            segments_list.append({"start": seg.start, "end": seg.end, "text": seg.text})
            if hasattr(seg, 'words') and seg.words:
                for word in seg.words:
                    word_segments.append({
                        "start": word.start, "end": word.end,
                        "text": getattr(word, 'word', str(word))
                    })

        full_text = " ".join(text_parts).strip()
        subtitle_data = word_segments if word_timestamps and word_segments else segments_list
        filtered = _filter_nondialogue(subtitle_data)

        return {
            "text": full_text or "Речь в моменте",
            "segments": filtered
        }

    except Exception as e:
        print(f"[WHISPER] Error: {e}")
        return {"text": "Речь в моменте", "segments": []}
    finally:
        if os.path.exists(temp_audio.name):
            os.unlink(temp_audio.name)
