"""
Нейросетевой скоринг "интересности" сегментов видео.

Оптимизированная версия:
  - Аудио извлекается ОДИН раз для всего видео → нарезка в памяти через librosa
  - Видеокадры извлекаются ОДИН раз (5 fps) → анализ окон по индексам
  - LLM-оценка батчевая (один запрос для топ-кандидатов)
  - Все экстракторы возвращают кеш, из которого быстро режутся окна

Три модальности признаков:
  Текст:   total_words, density, speech_ratio, avg_phrase_len
  Аудио:   energy_mean, energy_peak, energy_variance, silence_ratio
  Визуал:  scene_changes, face_count_avg, motion_intensity
"""

import os
import torch
import torch.nn as nn
import numpy as np
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor


_FFMPEG = os.getenv("FFMPEG_PATH", "ffmpeg")

FEATURE_KEYS = [
    "total_words", "density", "speech_ratio", "avg_phrase_len",
    "unique_ratio", "emotion_boost", "pacing_var",
    "energy_mean", "energy_peak", "energy_variance", "silence_ratio",
    "scene_changes", "face_count_avg", "motion_intensity",
]


class InterestNet(nn.Module):
    """
    Полносвязная сеть для оценки интересности сегмента.
    Вход: 11 признаков → 32 → 16 → 1 (Sigmoid)
    """

    def __init__(self, input_dim: int = 14, hidden_dims: Optional[List[int]] = None) -> None:
        super().__init__()
        if hidden_dims is None:
            hidden_dims = [32, 16]

        layers: List[nn.Module] = []
        prev = input_dim
        for h in hidden_dims:
            layers.append(nn.Linear(prev, h))
            layers.append(nn.ReLU())
            prev = h
        layers.append(nn.Linear(prev, 1))
        layers.append(nn.Sigmoid())

        self.net = nn.Sequential(*layers)
        self._init_weights()

    def _init_weights(self) -> None:
        for m in self.net:
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.zeros_(m.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class SegmentScorer:
    """Скоринг сегментов видео с помощью нейросети."""

    def __init__(
        self,
        input_dim: int = 14,
        hidden_dims: Optional[List[int]] = None,
        n_epochs: int = 100,
        learning_rate: float = 1e-2,
        top_ratio: float = 0.2,
    ) -> None:
        self.input_dim = input_dim
        self.hidden_dims = hidden_dims
        self.n_epochs = n_epochs
        self.learning_rate = learning_rate
        self.top_ratio = top_ratio
        self.model: Optional[InterestNet] = None
        self._mean: Optional[np.ndarray] = None
        self._std: Optional[np.ndarray] = None

    def _features_to_tensor(self, features_list: List[Dict]) -> torch.Tensor:
        rows = []
        for f in features_list:
            rows.append([float(f.get(k, 0)) for k in FEATURE_KEYS])
        X = np.array(rows, dtype=np.float32)
        mean = X.mean(axis=0, keepdims=True)
        std = X.std(axis=0, keepdims=True) + 1e-8
        X = (X - mean) / std
        self._mean = mean
        self._std = std
        return torch.tensor(X)

    def _heuristic_score(self, features_list: List[Dict]) -> np.ndarray:
        scores = []
        for f in features_list:
            text_score = (
                f.get("total_words", 0) * 1.0
                + f.get("density", 0) * 10
                + f.get("speech_ratio", 0) * 20
                + f.get("avg_phrase_len", 0) * 2
            )
            audio_score = (
                f.get("energy_mean", 0) * 5
                + f.get("energy_peak", 0) * 3
                + f.get("energy_variance", 0) * 8
                - f.get("silence_ratio", 0) * 15
            )
            visual_score = (
                f.get("scene_changes", 0) * 3
                + f.get("face_count_avg", 0) * 5
                + f.get("motion_intensity", 0) * 4
            )
            scores.append(text_score + audio_score + visual_score)
        return np.array(scores)

    def fit(self, features_list: List[Dict]) -> "SegmentScorer":
        if len(features_list) < 5:
            print("[SCORER] Too few samples for NN training, falling back to heuristic")
            self.model = None
            return self

        X = self._features_to_tensor(features_list)
        N = X.shape[0]

        heuristic = self._heuristic_score(features_list)
        threshold = np.percentile(heuristic, int((1 - self.top_ratio) * 100))
        y = (heuristic >= threshold).astype(np.float32).reshape(-1, 1)

        if y.sum() < 2 or (1 - y).sum() < 2:
            print("[SCORER] All samples same class, skipping NN training")
            self.model = None
            return self

        y_tensor = torch.tensor(y)
        self.model = InterestNet(input_dim=self.input_dim, hidden_dims=self.hidden_dims)
        criterion = nn.BCELoss()
        optimizer = torch.optim.Adam(self.model.parameters(), lr=self.learning_rate)

        self.model.train()
        for epoch in range(self.n_epochs):
            predictions = self.model(X)
            loss = criterion(predictions, y_tensor)
            loss.backward()
            optimizer.step()
            optimizer.zero_grad()

        print(f"[SCORER] Trained on {N} samples, top_ratio={self.top_ratio}")
        return self

    def predict(self, features: Dict) -> float:
        if self.model is None:
            s = self._heuristic_score([features])[0]
            return min(max(s / 150, 0), 1.0)

        row = np.array([[float(features.get(k, 0)) for k in FEATURE_KEYS]], dtype=np.float32)
        row = (row - self._mean) / self._std
        x = torch.tensor(row)

        self.model.eval()
        with torch.no_grad():
            prob = self.model(x).item()
        return prob

    def rank_segments(self, candidates: List[Dict]) -> List[Dict]:
        for c in candidates:
            c["nn_score"] = self.predict(c)
        candidates.sort(key=lambda x: x["nn_score"], reverse=True)
        return candidates


# =============================================================================
# Кешированные экстракторы — извлекают данные ОДИН раз, режут в памяти
# =============================================================================

class AudioCache:
    """
    Извлекает аудио всего видео ОДИН раз, потом нарезает окна в памяти.

    Вместо запуска ffmpeg для каждого окна — один вызов, всё в RAM.
    """

    def __init__(self, video_path: str) -> None:
        self.video_path = video_path
        self._rms: Optional[np.ndarray] = None
        self._sr: int = 22050
        self._hop_length: int = 512
        self._frames_per_sec: float = 0

    def load(self) -> None:
        """Извлекает аудио целиком, считает RMS один раз."""
        import tempfile
        import subprocess
        import os

        try:
            temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_audio.close()

            cmd = [
                _FFMPEG, "-y",
                "-i", self.video_path,
                "-ar", "22050",
                "-ac", "1",
                "-acodec", "pcm_s16le",
                temp_audio.name,
            ]
            subprocess.run(cmd, capture_output=True, timeout=120)

            import librosa
            y, sr = librosa.load(temp_audio.name, sr=22050)
            os.unlink(temp_audio.name)

            if len(y) == 0:
                self._rms = np.array([0])
                return

            self._rms = librosa.feature.rms(y=y, hop_length=self._hop_length)[0]
            self._sr = sr
            self._frames_per_sec = sr / self._hop_length
            y_len = len(y)
            y_dur = len(y) / sr
            del y

            print(f"[AUDIO CACHE] Loaded {y_len} samples, {len(self._rms)} RMS frames, duration={y_dur:.1f}s")

        except Exception as e:
            print(f"[AUDIO CACHE] Error: {e}")
            self._rms = np.array([0])

    def get_features(self, start: float, end: float) -> Dict:
        """Нарезает окно из кешированного RMS — мгновенно, без ffmpeg."""
        if self._rms is None:
            self.load()

        if len(self._rms) <= 1:
            return {"energy_mean": 0, "energy_peak": 0, "energy_variance": 0, "silence_ratio": 1}

        frame_start = int(start * self._frames_per_sec)
        frame_end = int(end * self._frames_per_sec)
        frame_start = max(0, min(frame_start, len(self._rms)))
        frame_end = max(0, min(frame_end, len(self._rms)))

        if frame_end <= frame_start:
            return {"energy_mean": 0, "energy_peak": 0, "energy_variance": 0, "silence_ratio": 1}

        window_rms = self._rms[frame_start:frame_end]

        energy_mean = float(np.mean(window_rms))
        energy_peak = float(np.max(window_rms))
        energy_variance = float(np.var(window_rms))

        silence_threshold = energy_mean * 0.3
        silence_frames = np.sum(window_rms < silence_threshold)
        silence_ratio = float(silence_frames / len(window_rms))

        return {
            "energy_mean": energy_mean,
            "energy_peak": energy_peak,
            "energy_variance": energy_variance,
            "silence_ratio": silence_ratio,
        }


class VisualCache:
    """
    Извлекает кадры всего видео ОДИН раз (5 fps), потом анализирует окна по индексам.

    Вместо ffmpeg для каждого окна — один вызов, все кадры в памяти.
    """

    def __init__(self, video_path: str, fps: int = 5) -> None:
        self.video_path = video_path
        self.fps = fps
        self._frames: List[np.ndarray] = []
        self._timestamps: List[float] = []

    def load(self) -> None:
        """Извлекает все кадры (5 fps), масштабируя до 320x180 для экономии памяти."""
        import tempfile
        import subprocess
        import os
        import cv2

        try:
            temp_video = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            temp_video.close()

            cmd = [
                _FFMPEG, "-y",
                "-i", self.video_path,
                "-vf", f"fps={self.fps},scale=320:180",
                "-an",
                temp_video.name,
            ]
            subprocess.run(cmd, capture_output=True, timeout=120)

            cap = cv2.VideoCapture(temp_video.name)
            os.unlink(temp_video.name)

            if not cap.isOpened():
                return

            frame_idx = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                self._frames.append(gray)
                self._timestamps.append(frame_idx / self.fps)
                frame_idx += 1

            cap.release()
            print(f"[VISUAL CACHE] Loaded {len(self._frames)} frames at {self.fps}fps (320x180), duration={len(self._frames)/self.fps:.1f}s")

        except Exception as e:
            print(f"[VISUAL CACHE] Error: {e}")

    def get_features(self, start: float, end: float) -> Dict:
        """Анализирует окно из кешированных кадров — мгновенно, без ffmpeg."""
        import cv2

        if not self._frames:
            self.load()

        if not self._frames:
            return {"scene_changes": 0, "face_count_avg": 0, "motion_intensity": 0}

        # Находим кадры в окне [start, end]
        indices = [i for i, t in enumerate(self._timestamps) if start <= t <= end]

        if not indices:
            return {"scene_changes": 0, "face_count_avg": 0, "motion_intensity": 0}

        scene_changes = 0
        face_counts = []
        motion_values = []

        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        prev_frame = None
        for idx in indices:
            frame = self._frames[idx]

            faces = face_cascade.detectMultiScale(frame, scaleFactor=1.1, minNeighbors=3, minSize=(30, 30))
            face_counts.append(len(faces))

            if prev_frame is not None:
                diff = cv2.absdiff(prev_frame, frame)
                motion = float(np.mean(diff))
                motion_values.append(motion)
                if motion > 30:
                    scene_changes += 1

            prev_frame = frame

        return {
            "scene_changes": scene_changes,
            "face_count_avg": float(np.mean(face_counts)) if face_counts else 0,
            "motion_intensity": float(np.mean(motion_values)) if motion_values else 0,
        }


def extract_llm_scores_batch(
    transcripts: List[Tuple[float, float, str]],
    openai_api_key: str,
) -> Dict[Tuple[float, float], float]:
    """
    Батчевая LLM-оценка: отправляет все транскрипты в одном запросе.

    Параметры:
        transcripts: список (start, end, text)
        openai_api_key: ключ OpenAI

    Возвращает:
        Словарь {(start, end): score}
    """
    if not openai_api_key or not transcripts:
        return {}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=openai_api_key)

        combined = "\n---\n".join(
            f"Сегмент {i+1} ({s:.0f}s-{e:.0f}s): {t[:200]}"
            for i, (s, e, t) in enumerate(transcripts)
            if len(t.strip()) >= 10
        )

        if not combined:
            return {}

        n_segments = len(transcripts)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты эксперт по виральному контенту для YouTube Shorts. "
                        f"Оцени {n_segments} сегментов по шкале 0-10 (0=скучный, 10=вирусный). "
                        "Ответь ТОЛЬКО числами через запятую, без объяснений. "
                        f"Пример для {n_segments} сегментов: 3,7,1,8"
                    ),
                },
                {"role": "user", "content": combined},
            ],
            max_tokens=50,
            temperature=0.3,
        )

        text = response.choices[0].message.content.strip()
        scores = [float(x.strip()) for x in text.split(",")]

        result = {}
        for i, (s, e, t) in enumerate(transcripts):
            if i < len(scores):
                result[(s, e)] = min(max(scores[i] / 10.0, 0), 1)
            else:
                result[(s, e)] = 0.5

        print(f"[LLM] Scored {len(result)} segments in 1 API call")
        return result

    except Exception as e:
        print(f"[LLM BATCH] Error: {e}")
        return {}


def extract_features_for_windows(
    video_path: str,
    windows: List[Tuple[float, float]],
    phrases: List[Dict],
    openai_api_key: str = "",
) -> List[Dict]:
    """
    Извлекает все признаки для списка окон за 3 вызова ffmpeg (аудио + видео + LLM)
    вместо N*2 вызовов для N окон.

    Параметры:
        video_path: путь к видео
        windows: список (start, end) — границы окон
        phrases: фразы с таймингами
        openai_api_key: ключ OpenAI (опционально)

    Возвращает:
        Список словарей с признаками для каждого окна
    """

    # 1. Загружаем кеши (2 вызова ffmpeg вместо N*2)
    audio_cache = AudioCache(video_path)
    audio_cache.load()

    visual_cache = VisualCache(video_path)
    visual_cache.load()

    # 2. Собираем текстовые + аудио + визуальные признаки для каждого окна
    results = []
    llm_transcripts = []
    phrase_idx = 0

    for start, end in windows:
        # Сдвигаем указатель до первой фразы в окне
        while phrase_idx < len(phrases) and phrases[phrase_idx]["end"] <= start:
            phrase_idx += 1

        total_words = 0
        speech_duration = 0.0
        count = 0
        phrase_lengths = []
        window_text_parts = []
        j = phrase_idx
        while j < len(phrases) and phrases[j]["start"] < end:
            p = phrases[j]
            if p["start"] >= start and p["end"] <= end:
                total_words += p.get("words", 0)
                speech_duration += p.get("duration", 0)
                count += 1
                phrase_lengths.append(p.get("words", 0))
                window_text_parts.append(p.get("full_text", ""))
            j += 1

        if count == 0:
            continue

        duration_w = max(end - start, 0.1)
        density = total_words / duration_w
        speech_ratio = speech_duration / duration_w
        avg_phrase_len = total_words / count
        window_text = " ".join(window_text_parts)

        # Вариативность темпа
        pacing_var = 0.0
        if count >= 3:
            mean_pl = sum(phrase_lengths) / count
            if mean_pl > 0:
                variance = sum((pl - mean_pl) ** 2 for pl in phrase_lengths) / count
                pacing_var = (variance ** 0.5) / mean_pl

        audio_feats = audio_cache.get_features(start, end)
        visual_feats = visual_cache.get_features(start, end)

        # Лексическое разнообразие
        words_lower = window_text.lower().split()
        unique_ratio = len(set(words_lower)) / max(len(words_lower), 1)

        # Эмоциональные триггеры
        exclamations = window_text.count('!')
        questions = window_text.count('?')
        emotion_boost = (exclamations * 3) + (questions * 2)

        features = {
            "start": start,
            "end": end,
            "total_words": total_words,
            "density": density,
            "speech_ratio": speech_ratio,
            "avg_phrase_len": avg_phrase_len,
            "words": total_words,
            "phrases": count,
            "unique_ratio": unique_ratio,
            "emotion_boost": emotion_boost,
            "pacing_var": pacing_var,
            "transcript": window_text,
        }
        features.update(audio_feats)
        features.update(visual_feats)

        heuristic = (
            min(density / 5.0, 1.0) * 25 +
            min(speech_ratio, 1.0) * 25 +
            min(avg_phrase_len / 20.0, 1.0) * 15 +
            unique_ratio * 15 +
            min(emotion_boost / 10.0, 1.0) * 10
        )
        features["score"] = heuristic

        if openai_api_key and len(window_text.strip()) >= 10:
            llm_transcripts.append((start, end, window_text))

        results.append(features)

    # 3. Батчевый LLM-скоринг (1 API вызов вместо N)
    if llm_transcripts and openai_api_key:
        llm_scores = extract_llm_scores_batch(llm_transcripts, openai_api_key)
        for f in results:
            key = (f["start"], f["end"])
            if key in llm_scores:
                f["llm_score"] = llm_scores[key]

    print(f"[FEATURES] Extracted for {len(results)} windows (2 ffmpeg calls + 1 LLM call)")
    return results
