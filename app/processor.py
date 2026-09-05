import os
import math
import asyncio
import json
import subprocess
import re
import threading
from pathlib import Path
from typing import List, Dict

BASE_DIR = Path(__file__).parent.parent
SETTINGS_FILE = BASE_DIR / "settings.json"


def _read_env(key: str, default: str = "") -> str:
    """Читает значение из settings.json (UI) или .env напрямую."""
    # Сначала settings.json — сюда пишет UI, когда .env смонтирован read-only
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if key in data:
                return str(data[key])
    except Exception:
        pass
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        try:
            text = env_path.read_text(encoding="utf-8")
            m = re.search(rf"^{re.escape(key)}\s*=\s*'?\"?([^'\n]*?)'?\"?\s*$", text, re.MULTILINE)
            if m:
                return m.group(1).strip().strip("'\"")
        except Exception:
            pass
    return default

class VideoProcessor:
    _whisper_model = None
    _whisper_model_size = None
    _whisper_lock = threading.Lock()
    
    def __init__(self, upload_dir: str, output_dir: str):
        self.upload_dir = Path(upload_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.ffmpeg = os.getenv("FFMPEG_PATH", "ffmpeg")
        self.gpu_encoder = self._detect_gpu_encoder()
        self.fonts_dir = Path(__file__).parent.parent / "fonts"
    
    def _detect_gpu_encoder(self):
        """Автоопределение GPU кодека для ffmpeg"""
        try:
            result = subprocess.run([self.ffmpeg, "-encoders"], capture_output=True, text=True, timeout=10)
            encoders = result.stdout + result.stderr
            
            if "h264_nvenc" in encoders:
                print("[FFMPEG] NVIDIA NVENC detected")
                return "h264_nvenc"
            elif "h264_amf" in encoders:
                print("[FFMPEG] AMD AMF detected")
                return "h264_amf"
            elif "h264_qsv" in encoders:
                print("[FFMPEG] Intel QSV detected")
                return "h264_qsv"
            elif "h264_v4l2m2m" in encoders:
                print("[FFMPEG] Raspberry Pi V4L2 M2M detected")
                return "h264_v4l2m2m"
        except Exception as e:
            print(f"[FFMPEG] GPU detection error: {e}")
        
        print("[FFMPEG] No GPU encoder, using CPU (libx264)")
        return None
    
    async def download_video(self, url: str, job_id: str = "") -> str:
        import uuid
        output_path = self.upload_dir / f"{job_id or uuid.uuid4().hex}_downloaded.mp4"

        cmd = ["yt-dlp", "-f", "best", "-o", str(output_path), url]
        print(f"[DOWNLOAD] {url} -> {output_path}")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: subprocess.run(cmd, capture_output=True, timeout=600))

        if result.returncode != 0:
            error = result.stderr.decode('utf-8', errors='ignore') if result.stderr else ''
            raise Exception(f"Download failed: {error[:300]}")

        if not output_path.exists():
            raise Exception(f"Downloaded file not found: {output_path}")

        print(f"[DOWNLOAD] OK: {output_path}")
        return str(output_path)

    @staticmethod
    def _filter_nondialogue(segments):
        """Удаляет сегменты с описаниями звуков/музыки (не речь персонажей)"""
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

    @classmethod
    def _get_whisper_model(cls, model_size="base"):
        """Singleton Whisper model - загружается один раз, авто CUDA. Потокобезопасно."""
        with cls._whisper_lock:
            if cls._whisper_model is None or cls._whisper_model_size != model_size:
                device = "cpu"
                compute_type = "int8"
                try:
                    import torch
                    if torch.cuda.is_available():
                        device = "cuda"
                        compute_type = "float16"
                        print(f"[WHISPER] CUDA detected: {torch.cuda.get_device_name(0)}")
                except ImportError:
                    pass
                print(f"[WHISPER] Loading model '{model_size}' ({device}, {compute_type})...")
                from faster_whisper import WhisperModel
                cls._whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
                cls._whisper_model_size = model_size
            return cls._whisper_model
    
    async def get_duration(self, video_path: str) -> float:
        print(f"[FFPROBE] Getting duration for: {video_path}")
        
        cmd = [self.ffmpeg, "-i", video_path]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stderr
            
            import re
            match = re.search(r'Duration:\s*(\d+):(\d+):(\d+)\.(\d+)', output)
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = int(match.group(3))
                ms = int(match.group(4))
                duration = hours * 3600 + minutes * 60 + seconds + ms / 100
                print(f"[FFPROBE] Duration: {duration} seconds")
                return duration
        except Exception as e:
            print(f"[FFPROBE] Error: {e}")
        
        print(f"[FFPROBE] Failed to get duration, returning default")
        return 300
    
    async def extract_segments(self, video_path: str, short_length: int, shorts_count: int, subtitle_segments: List[Dict] = None, smart_selection: str = "off", auto_duration: bool = False, min_length: int = 30, max_length: int = 60, scene_start: bool = False) -> List[Dict]:
        duration = await self.get_duration(video_path)
        mode = smart_selection or "off"
        if mode not in ("global", "parts", "hybrid", "true", "1"):
            if duration < short_length:
                print(f"[PROCESS] Video too short: {duration}s < {short_length}s")
                return []
            print("[PROCESS] Smart selection is off: cutting consecutively from 00:00")
            return self._default_segments(duration, short_length, shorts_count)

        scene_starts = None
        if scene_start and mode in ("global", "parts", "hybrid", "true", "1"):
            scene_starts = await self._detect_scene_starts(video_path, duration, short_length)
            print(f"[PROCESS] Scene-aligned selection: {len(scene_starts)} usable scene starts")

        # ── Авто-длительность: обычный выбор сегментов + уточнение самого интересного окна ──
        if auto_duration:
            min_length = max(15, int(min_length or 30))
            max_length = max(min_length, int(max_length or 60))
            if duration < min_length:
                print(f"[PROCESS] Video too short for auto-duration: {duration}s < {min_length}s")
                return []
            # ищем лучшие места базовым режимом (окно = max_length), затем уточняем длину
            base = self._base_segments(duration, min(max_length, int(duration)), shorts_count, subtitle_segments, video_path, mode, scene_starts)
            if not base:
                return []
            if subtitle_segments:
                phrases = self._build_phrases(subtitle_segments)
                if phrases:
                    import bisect
                    p_starts = [p["start"] for p in phrases]
                    refined = [self._refine_segment_duration(
                        phrases, p_starts, seg, min_length, max_length,
                        locked_start=bool(scene_starts)
                    ) for seg in base]
                    refined = [r for r in refined if r]
                    print(f"[PROCESS] Auto-duration refined {len(refined)} segments ({min_length}-{max_length}s)")
                    return refined
            return base

        if duration < short_length:
            print(f"[PROCESS] Video too short: {duration}s < {short_length}s")
            return []
        return self._base_segments(duration, short_length, shorts_count, subtitle_segments, video_path, mode, scene_starts)

    def _base_segments(self, duration: float, short_length: int, shorts_count: int, subtitle_segments: List[Dict], video_path: str, mode: str, candidate_starts: List[float] = None) -> List[Dict]:
        """Выбирает сегменты базовым способом (off / density / нейросетевой)."""
        if mode not in ("global", "parts", "hybrid", "true", "1"):
            # off — простое деление подряд
            return self._default_segments(duration, short_length, shorts_count, candidate_starts)
        if subtitle_segments:
            selection_mode = "global" if mode in ("true", "1") else mode
            if duration > 7200 and selection_mode in ("global", "hybrid"):
                # очень длинные видео — нейросетевой скоринг (InterestNet)
                return self._find_best_segments_nn(
                    duration, short_length, shorts_count, subtitle_segments,
                    video_path, candidate_starts, selection_mode
                )
            # стандартный отбор по плотности речи
            return self._find_best_segments(
                duration, short_length, shorts_count, subtitle_segments,
                video_path, candidate_starts, selection_mode
            )
        return self._default_segments(duration, short_length, shorts_count, candidate_starts)

    async def _detect_scene_starts(self, video_path: str, duration: float, short_length: int) -> List[float]:
        """Return visual cut timestamps that can fit a full output segment."""
        max_start = max(0.0, float(duration) - float(short_length))
        cmd = [
            self.ffmpeg, "-hide_banner", "-i", video_path,
            "-vf", r"select=gt(scene\,0.35),showinfo",
            "-an", "-f", "null", "-"
        ]
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            )
            if result.returncode != 0:
                detail = (result.stderr or "").replace("\n", " ")[-300:]
                print(f"[SCENE] Detection failed: {detail}")
                return []
            found = [0.0]
            for value in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr or ""):
                timestamp = float(value)
                if timestamp <= max_start + 0.01 and timestamp - found[-1] >= 0.5:
                    found.append(timestamp)
            return found
        except Exception as exc:
            print(f"[SCENE] Detection failed, using ordinary smart-selection grid: {exc}")
            return []

    def _score_window_interest(self, phrases: List[Dict], p_starts: List[float], start: float, end: float) -> float:
        """0-100: насколько интересно окно [start,end] по речи (плотность, эмоции, темп)."""
        import bisect
        i0 = bisect.bisect_left(p_starts, start)
        total_words = 0
        speech = 0.0
        count = 0
        phrase_lengths = []
        text_parts = []
        j = i0
        while j < len(phrases) and phrases[j]["start"] < end:
            p = phrases[j]
            if p["end"] <= end:
                total_words += p["words"]
                speech += p["duration"]
                count += 1
                phrase_lengths.append(p["words"])
                text_parts.append(p.get("full_text", ""))
            j += 1
        if count == 0:
            return -1.0

        win_len = max(end - start, 0.1)
        window_text = " ".join(text_parts)
        density = total_words / win_len
        speech_ratio = speech / win_len
        avg_phrase_len = total_words / count
        words_lower = window_text.lower().split()
        unique_ratio = len(set(words_lower)) / max(len(words_lower), 1)
        exclamations = window_text.count('!')
        questions = window_text.count('?')
        emotion_boost = (exclamations * 3) + (questions * 2)
        pacing_var = 0.0
        if count >= 3:
            mean_pl = sum(phrase_lengths) / count
            if mean_pl > 0:
                variance = sum((pl - mean_pl) ** 2 for pl in phrase_lengths) / count
                pacing_var = (variance ** 0.5) / mean_pl
        return (
            min(density / 5.0, 1.0) * 25 +
            min(speech_ratio, 1.0) * 25 +
            min(avg_phrase_len / 20.0, 1.0) * 15 +
            unique_ratio * 15 +
            min(emotion_boost / 10.0, 1.0) * 10 +
            min(pacing_var, 1.0) * 10 +
            min(total_words / 100.0, 1.0) * 2
        )

    def _refine_segment_duration(self, phrases: List[Dict], p_starts: List[float], seg: Dict, min_length: int, max_length: int, locked_start: bool = False) -> Dict:
        """Внутри найденного сегмента ищет самое интересное окно в диапазоне [min_length, max_length]."""
        start = seg["start"]
        end = seg["end"]
        segdur = end - start
        if segdur <= min_length:
            return seg
        step = 5
        best = None
        best_score = -1.0
        w_start = start
        while w_start <= end - min_length:
            max_wlen = min(max_length, end - w_start)
            w_len = min_length
            while w_len <= max_wlen:
                w_end = w_start + w_len
                score = self._score_window_interest(phrases, p_starts, w_start, w_end)
                if score > best_score:
                    best_score = score
                    best = {"start": float(w_start), "end": float(w_end)}
                w_len += step
            if locked_start:
                break
            w_start += step
        return best or seg
    
    def _order_candidates_for_mode(self, candidates: List[Dict], duration: float,
                                   shorts_count: int, selection_mode: str) -> List[Dict]:
        """Order scored windows according to global, parts, or hybrid strategy."""
        def score(item):
            return float(item.get("final_score", item.get("nn_score", item.get("score", 0.0))) or 0.0)

        ranked = sorted(candidates, key=score, reverse=True)
        if selection_mode == "global" or not ranked:
            return ranked

        target = max(1, int(shorts_count))
        prioritized = []
        if selection_mode == "parts":
            # One best window from each equal section keeps coverage predictable.
            part_len = max(float(duration) / target, 0.001)
            for part_index in range(target):
                part_start = part_index * part_len
                part_end = duration if part_index == target - 1 else (part_index + 1) * part_len
                local = [item for item in ranked
                         if part_start <= float(item["start"]) < part_end]
                if local:
                    prioritized.append(local[0])
        elif selection_mode == "hybrid":
            # Keep local top-3 from a fine grid, then rank that pool globally.
            part_count = max(min(target, 200), 20)
            part_len = max(float(duration) / part_count, 0.001)
            pool = []
            for part_index in range(part_count):
                part_start = part_index * part_len
                part_end = duration if part_index == part_count - 1 else (part_index + 1) * part_len
                local = [item for item in ranked
                         if part_start <= float(item["start"]) < part_end]
                pool.extend(local[:3])
            prioritized = sorted(pool, key=score, reverse=True)
        else:
            return ranked

        seen = {id(item) for item in prioritized}
        return prioritized + [item for item in ranked if id(item) not in seen]

    def _find_best_segments_nn(self, duration: float, short_length: int, shorts_count: int, subtitle_segments: List[Dict], video_path: str = "", candidate_starts: List[float] = None, selection_mode: str = "global") -> List[Dict]:
        """Находит лучшие отрезки с помощью нейросетевого скоринга (SegmentScorer)."""
        
        from segment_scorer import SegmentScorer, extract_features_for_windows
        
        # Scene cuts define the candidate pool; shorts_count still defines the target.
        effective_count = min(shorts_count, len(candidate_starts)) if candidate_starts else shorts_count
        
        phrases = self._build_phrases(subtitle_segments)
        if not phrases:
            return self._default_segments(duration, short_length, shorts_count, candidate_starts)
        
        step = max(1, short_length // 2)
        windows = []
        starts = candidate_starts if candidate_starts else range(0, int(duration - short_length), step)
        for start in starts:
            end = float(start) + short_length
            if end <= duration + 0.01:
                windows.append((float(start), float(end)))

        from api_keys import get_keys
        openai_api_keys = get_keys("openai")

        # Один вызов: 2 ffmpeg (аудио + видео целиком) + 1 LLM запрос
        candidates = extract_features_for_windows(
            video_path, windows, phrases, openai_api_keys
        )
        
        if not candidates:
            return self._default_segments(duration, short_length, shorts_count, candidate_starts)
        
        # Обучаем скорер
        scorer = SegmentScorer(input_dim=14, n_epochs=20, learning_rate=1e-2, top_ratio=0.2)
        scorer.fit(candidates)
        ranked = scorer.rank_segments(candidates)
        
        # Комбинируем с LLM если есть
        has_llm = any("llm_score" in c for c in ranked)
        if has_llm:
            for c in ranked:
                nn = c.get("nn_score", 0)
                llm = c.get("llm_score", 0.5)
                c["final_score"] = 0.6 * nn + 0.4 * llm
            ranked.sort(key=lambda x: x.get("final_score", 0), reverse=True)
        
        ranked = self._order_candidates_for_mode(ranked, duration, effective_count, selection_mode)
        # Выбираем топ N непересекающихся
        best_segments = []
        for cand in ranked:
            overlap = False
            for sel in best_segments:
                if cand["start"] < sel["end"] and cand["end"] > sel["start"]:
                    overlap = True
                    break
            if not overlap:
                cand["score"] = cand.get("final_score", cand.get("nn_score", cand["score"]))
                best_segments.append(cand)
            if len(best_segments) >= effective_count:
                break
        
        if len(best_segments) < effective_count:
            for cand in ranked:
                if cand in best_segments:
                    continue
                overlap = False
                for sel in best_segments:
                    if cand["start"] < sel["end"] and cand["end"] > sel["start"]:
                        overlap = True
                        break
                if not overlap:
                    cand["score"] = cand.get("final_score", cand.get("nn_score", cand["score"]))
                    best_segments.append(cand)
                if len(best_segments) >= effective_count:
                    break
        
        best_segments = self._fill_requested_segments(
            best_segments, duration, short_length, shorts_count, candidate_starts
        )
        best_segments.sort(key=lambda x: x["start"])
        
        top = best_segments[0] if best_segments else None
        if top:
            print(f"[PROCESS] NN selected {len(best_segments)} segments. Top nn_score: {top.get('nn_score', 'N/A')}, llm: {top.get('llm_score', 'N/A')}, words: {top['words']}, density: {top['density']:.1f}")
        
        return best_segments

    def _build_phrases(self, subtitle_segments: List[Dict]) -> List[Dict]:
        """Группирует слова в непрерывные фразы (паузы < 1 сек = одна фраза)."""
        if not subtitle_segments:
            return []
        
        phrases = []
        current_phrase = None
        current_texts = None
        
        for word in subtitle_segments:
            if current_phrase is None:
                current_phrase = {"start": word["start"], "end": word["end"], "words": 1}
                current_texts = [word.get("text", "")]
            else:
                # Bound phrases so long continuous speech remains scoreable.
                phrase_duration = word["end"] - current_phrase["start"]
                if (word["start"] - current_phrase["end"] < 1.0
                        and phrase_duration <= 12.0
                        and current_phrase["words"] < 40):
                    current_phrase["end"] = word["end"]
                    current_phrase["words"] += 1
                    current_texts.append(word.get("text", ""))
                else:
                    current_phrase["duration"] = current_phrase["end"] - current_phrase["start"]
                    current_phrase["density"] = current_phrase["words"] / max(current_phrase["duration"], 0.1)
                    current_phrase["full_text"] = " ".join(current_texts)
                    phrases.append(current_phrase)
                    current_phrase = {"start": word["start"], "end": word["end"], "words": 1}
                    current_texts = [word.get("text", "")]
        
        if current_phrase:
            current_phrase["duration"] = current_phrase["end"] - current_phrase["start"]
            current_phrase["density"] = current_phrase["words"] / max(current_phrase["duration"], 0.1)
            current_phrase["full_text"] = " ".join(current_texts)
            phrases.append(current_phrase)
        
        return phrases

    def _fill_requested_segments(self, selected: List[Dict], duration: float,
                                 short_length: int, shorts_count: int,
                                 candidate_starts: List[float] = None) -> List[Dict]:
        """Fill sparse smart-selection results with deterministic time windows."""
        # Scene alignment restricts starts, but never overrides the requested count.
        if candidate_starts:
            target = min(max(0, int(shorts_count)), len(candidate_starts))
        else:
            target = min(max(0, int(shorts_count)), int(duration // short_length))
        if target <= 0 or len(selected) >= target:
            return selected[:target] if target else []

        filled = list(selected)
        for fallback in self._default_segments(duration, short_length, target, candidate_starts):
            if any(fallback["start"] < item["end"] and fallback["end"] > item["start"]
                   for item in filled):
                continue
            filled.append({**fallback, "score": 0.0, "words": 0, "density": 0.0})
            if len(filled) >= target:
                break

        if len(filled) < target:
            if candidate_starts:
                print(f"[PROCESS] Scene-aligned selection produced {len(filled)}/{target}; no non-scene fallback")
                return filled
            print(f"[PROCESS] Smart selection produced {len(selected)}/{target}; using time-grid fallback")
            filled = [
                {**item, "score": 0.0, "words": 0, "density": 0.0}
                for item in self._default_segments(duration, short_length, target)
            ]
        return filled
    
    def _find_best_segments(self, duration: float, short_length: int, shorts_count: int, subtitle_segments: List[Dict], video_path: str = "", candidate_starts: List[float] = None, selection_mode: str = "global") -> List[Dict]:
        """Находит лучшие отрезки по плотности речи и длине непрерывной речи"""
        
        # Rank all scene starts, then keep only the requested number.
        effective_count = min(shorts_count, len(candidate_starts)) if candidate_starts else shorts_count
        
        phrases = self._build_phrases(subtitle_segments)
        
        if not phrases:
            return self._default_segments(duration, short_length, shorts_count, candidate_starts)
        
        # 2. Вычисляем score для каждого окна
        step = max(1, short_length // 2)
        candidates = []
        phrase_idx = 0

        starts = candidate_starts if candidate_starts else range(0, int(duration - short_length), step)
        for start in starts:
            start = float(start)
            end = start + short_length
            
            # Сдвигаем указатель до первой фразы в окне
            while phrase_idx < len(phrases) and phrases[phrase_idx]["end"] <= start:
                phrase_idx += 1
            
            # Собираем фразы в окне (идут подряд)
            total_words = 0
            speech_duration = 0.0
            count = 0
            phrase_lengths = []
            window_text_parts = []
            j = phrase_idx
            while j < len(phrases) and phrases[j]["start"] < end:
                p = phrases[j]
                if p["start"] >= start and p["end"] <= end:
                    total_words += p["words"]
                    speech_duration += p["duration"]
                    count += 1
                    phrase_lengths.append(p["words"])
                    window_text_parts.append(p.get("full_text", ""))
                j += 1
            
            if count == 0:
                continue
            
            window_text = " ".join(window_text_parts)
            density = total_words / short_length
            speech_ratio = speech_duration / short_length
            avg_phrase_len = total_words / max(count, 1)
            
            # Лексическое разнообразие (уникальные слова / всего слов)
            words_lower = window_text.lower().split()
            unique_ratio = len(set(words_lower)) / max(len(words_lower), 1)
            
            # Эмоциональные триггеры из текста
            exclamations = window_text.count('!')
            questions = window_text.count('?')
            emotion_boost = (exclamations * 3) + (questions * 2)
            
            # Вариативность темпа (std длины фраз / средняя)
            pacing_var = 0.0
            if count >= 3:
                mean_pl = sum(phrase_lengths) / count
                if mean_pl > 0:
                    variance = sum((pl - mean_pl) ** 2 for pl in phrase_lengths) / count
                    pacing_var = (variance ** 0.5) / mean_pl
            
            # Нормализованный скор (0-1 по каждой метрике)
            score = (
                min(density / 5.0, 1.0) * 25 +
                min(speech_ratio, 1.0) * 25 +
                min(avg_phrase_len / 20.0, 1.0) * 15 +
                unique_ratio * 15 +
                min(emotion_boost / 10.0, 1.0) * 10 +
                min(pacing_var, 1.0) * 10
            )
            
            candidates.append({
                "start": float(start),
                "end": float(end),
                "score": score,
                "words": total_words,
                "density": density,
                "speech_ratio": speech_ratio,
                "phrases": count,
                "unique_ratio": unique_ratio,
                "emotion_boost": emotion_boost,
                "pacing_var": pacing_var
            })
        
        if not candidates:
            return self._default_segments(duration, short_length, shorts_count, candidate_starts)
        
        # Сортируем по score
        candidates.sort(key=lambda x: x["score"], reverse=True)
        candidates = self._order_candidates_for_mode(candidates, duration, effective_count, selection_mode)
        
        # Выбираем топ N непересекающихся
        best_segments = []
        for cand in candidates:
            overlap = False
            for sel in best_segments:
                if cand["start"] < sel["end"] and cand["end"] > sel["start"]:
                    overlap = True
                    break
            
            if not overlap:
                best_segments.append(cand)
            
            if len(best_segments) >= effective_count:
                break
        
        # Если набрали меньше чем нужно - добираем из следующих по score
        if len(best_segments) < effective_count:
            for cand in candidates:
                if cand in best_segments:
                    continue
                overlap = False
                for sel in best_segments:
                    if cand["start"] < sel["end"] and cand["end"] > sel["start"]:
                        overlap = True
                        break
                if not overlap:
                    best_segments.append(cand)
                if len(best_segments) >= effective_count:
                    break
        
        # Сортируем по времени
        best_segments = self._fill_requested_segments(
            best_segments, duration, short_length, shorts_count, candidate_starts
        )
        best_segments.sort(key=lambda x: x["start"])
        
        print(f"[PROCESS] Found {len(best_segments)} best segments. Top score: {best_segments[0]['score']:.1f}, words: {best_segments[0]['words']}, density: {best_segments[0]['density']:.1f}")
        return best_segments
    
    def _default_segments(self, duration: float, short_length: int, shorts_count: int, candidate_starts: List[float] = None) -> List[Dict]:
        """Fallback если нет субтитров."""
        if candidate_starts:
            segments = []
            target = min(max(0, int(shorts_count)), len(candidate_starts))
            for start in candidate_starts:
                end = min(float(start) + short_length, duration)
                if end - float(start) < short_length * 0.9:
                    continue
                if any(float(start) < item["end"] and end > item["start"] for item in segments):
                    continue
                segments.append({"start": float(start), "end": end, "scene_aligned": True})
                if len(segments) >= target:
                    break
            if segments:
                return segments

        segments = []
        for i in range(min(shorts_count, int(duration // short_length))):
            start = i * short_length
            end = min(start + short_length, duration)
            segments.append({"start": start, "end": end})
        return segments

    def _bg_filter_chain(self, in_label: str, out_label: str, crop_mode: str = "original", blurred_bg: bool = False, suffix: str = "") -> str:
        """Build a fixed 9:16 frame with selectable crop mode.

        crop_mode:
          "original" — 16:9 fit inside 9:16 (black or blurred bars)
          "square"   — 1:1 center, blurred bars top+bottom (if blurred_bg)
          "vertical" — 9:16 fill, crop sides (no blurred_bg — full frame)
        """
        s = suffix
        width, height = 1080, 1920
        half_w, half_h = width // 2, height // 2

        if crop_mode == "square":
            if blurred_bg:
                return (
                    f"{in_label}split=2[bg_in{s}][fg_in{s}];"
                    f"[bg_in{s}]scale=540:960:force_original_aspect_ratio=increase,"
                    f"crop=540:960,boxblur=12:1,"
                    f"scale={width}:{height},setsar=1[bg{s}];"
                    f"[fg_in{s}]scale={width}:{width}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{width}:(iw-{width})/2:(ih-{width})/2,setsar=1[fg{s}];"
                    f"[bg{s}][fg{s}]overlay=(W-w)/2:(H-h)/2,format=yuv420p[{out_label}]"
                )
            return (
                f"{in_label}scale={width}:{width}:force_original_aspect_ratio=increase,"
                f"crop={width}:{width}:(iw-{width})/2:(ih-{width})/2,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
                f"setsar=1,format=yuv420p[{out_label}]"
            )
        if crop_mode == "vertical":
            return (
                f"{in_label}scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}:(iw-{width})/2:(ih-{height})/2,"
                f"setsar=1,format=yuv420p[{out_label}]"
            )
        # original (16:9 fit)
        if blurred_bg:
            return (
                f"{in_label}split=2[bg_in{s}][fg_in{s}];"
                f"[bg_in{s}]scale=540:960:force_original_aspect_ratio=increase,"
                f"crop=540:960,boxblur=12:1,"
                f"scale={width}:{height},setsar=1[bg{s}];"
                f"[fg_in{s}]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"setsar=1[fg{s}];"
                f"[bg{s}][fg{s}]overlay=(W-w)/2:(H-h)/2,format=yuv420p[{out_label}]"
            )
        return (
            f"{in_label}scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad=max(iw\\,{width}):max(ih\\,{height}):(ow-iw)/2:(oh-ih)/2:black,"
            f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2,"
            f"setsar=1,format=yuv420p[{out_label}]"
        )

    @staticmethod
    def _ass_time(t: float) -> str:
        hours = int(t // 3600)
        minutes = int((t % 3600) // 60)
        seconds = int(t % 60)
        cs = int((t % 1) * 100)
        return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"

    @staticmethod
    def _parse_ass_time(t: str) -> float:
        parts = t.split(":")
        h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
        return h * 3600 + m * 60 + s

    def _shift_ass_times(self, ass_path, shift_after: float, shift_by: float):
        """Сдвигает тайминги ASS-событий, начинающихся после shift_after, на shift_by секунд."""
        if not ass_path or not ass_path.exists() or shift_by <= 0:
            return
        try:
            text = ass_path.read_text(encoding="utf-8-sig")
            lines = text.split("\n")
            out = []
            for line in lines:
                if line.startswith("Dialogue:"):
                    parts = line.split(",", 9)
                    if len(parts) >= 10:
                        try:
                            start = self._parse_ass_time(parts[1].strip())
                            end = self._parse_ass_time(parts[2].strip())
                            if start >= shift_after - 0.01:
                                start += shift_by
                                end += shift_by
                                parts[1] = self._ass_time(start)
                                parts[2] = self._ass_time(end)
                                line = ",".join(parts[:9]) + "," + parts[9]
                        except Exception:
                            pass
                out.append(line)
            ass_path.write_text("\n".join(out), encoding="utf-8-sig")
        except Exception as e:
            print(f"[ASS] Shift error: {e}")

    def _remove_ass_events_in_interval(self, ass_path, interval_start: float, interval_end: float):
        """Remove subtitle events covered by a same-duration banner replacement."""
        if not ass_path or not ass_path.exists() or interval_end <= interval_start:
            return
        try:
            text = ass_path.read_text(encoding="utf-8-sig")
            output = []
            for line in text.split("\n"):
                if line.startswith("Dialogue:"):
                    parts = line.split(",", 9)
                    if len(parts) >= 10:
                        try:
                            start = self._parse_ass_time(parts[1].strip())
                            end = self._parse_ass_time(parts[2].strip())
                            if start < interval_end and end > interval_start:
                                continue
                        except Exception:
                            pass
                output.append(line)
            ass_path.write_text("\n".join(output), encoding="utf-8-sig")
        except Exception as exc:
            print(f"[ASS] Banner interval cleanup error: {exc}")
    async def _get_video_fps(self, video_path: str) -> float:
        try:
            result = subprocess.run([self.ffmpeg, "-i", video_path], capture_output=True, text=True, timeout=30)
            m = re.search(r'(\d+(?:\.\d+)?)\s*fps', result.stderr)
            if m:
                return max(1.0, float(m.group(1)))
        except Exception:
            pass
        return 30.0

    async def _has_audio(self, video_path: str) -> bool:
        try:
            result = subprocess.run([self.ffmpeg, "-i", video_path], capture_output=True, text=True, timeout=30)
            return bool(re.search(r'Stream.*Audio:', result.stderr))
        except Exception:
            return False

    @staticmethod
    def count_audio_streams(video_path: str) -> int:
        try:
            result = subprocess.run([os.getenv("FFMPEG_PATH", "ffmpeg"), "-i", video_path], capture_output=True, text=True, timeout=30)
            return len(re.findall(r'Stream.*Audio:', result.stderr))
        except Exception:
            return 0

    
    async def create_short(self, video_path: str, segment: Dict, index: int, job_id: str, subtitle_segments: List[Dict] = None, crop_mode: str = "original", blurred_bg: bool = False, filename_keywords: str = "", banner_enabled: bool = False, banner_path: str = None, banner_x: int = 0, banner_y: int = 0, banner_w: int = 1080, banner_h: int = 200, banner_opacity: int = 100, banner_style: str = "overlay", banner_position: int = 50, banner_duration: int = 3, banner_full_duration: bool = False, music_path: str = None, music_volume: float = 0.7, music_start: float = 0, music_end: float = 0, replace_audio: bool = False, subtitle_font_name: str = None) -> str:
        frame_width, frame_height = 1080, 1920
        kw_part = f"_{filename_keywords}" if filename_keywords else ""
        output_path = self.output_dir / f"short_{job_id}_{index}{kw_part}.mp4"

        subtitle_font = subtitle_font_name or _read_env("SUBTITLE_FONT", "Montserrat")
        subtitle_font_path = self._find_font(subtitle_font)
        subtitle_fonts_dir = self.fonts_dir
        font_file_implies_bold = False
        font_file_implies_italic = False
        if subtitle_font_path:
            # ASS/libass resolves Fontname by the name embedded in the TTF, not
            # by its filename. Uploaded fonts are commonly renamed, so using
            # Path.stem here silently falls back to a system font.
            subtitle_font = self._font_family_name(subtitle_font_path) or subtitle_font_path.stem
            subtitle_font = subtitle_font.replace(",", " ").strip()
            subtitle_fonts_dir = subtitle_font_path.parent
            font_file_style = subtitle_font_path.stem.lower()
            font_file_implies_bold = any(token in font_file_style for token in ("bold", "black"))
            font_file_implies_italic = "italic" in font_file_style
        subtitle_style = _read_env("SUBTITLE_STYLE", "normal")
        subtitle_fontsize = int(_read_env("SUBTITLE_FONTSIZE", "100"))
        subtitle_fontcolor = _read_env("SUBTITLE_FONTCOLOR", "white")
        subtitle_position = int(_read_env("SUBTITLE_POSITION_Y", "1670"))
        subtitle_capitalize = _read_env("SUBTITLE_CAPITALIZE", "1") == "1"
        subtitle_borderw = int(_read_env("SUBTITLE_BORDERW", "0"))
        subtitle_bordercolor = _read_env("SUBTITLE_BORDERCOLOR", "black")
        subtitle_boxborder = int(_read_env("SUBTITLE_BOX_BORDER", "0"))
        subtitle_boxcolor = _read_env("SUBTITLE_BOX_COLOR", "black@0.8")
        subtitle_shadowx = int(_read_env("SUBTITLE_SHADOW_X", "2"))
        subtitle_shadowy = int(_read_env("SUBTITLE_SHADOW_Y", "2"))
        subtitle_shadowcolor = _read_env("SUBTITLE_SHADOW_COLOR", "black")
        subtitle_words_count = int(_read_env("SUBTITLE_WORDS_COUNT", "1"))
        subtitle_word_fade = _read_env("SUBTITLE_WORD_FADE", "1") == "1"
        print(f"[SETTINGS] font={subtitle_font} size={subtitle_fontsize} pos={subtitle_position} borderw={subtitle_borderw} bordercolor={subtitle_bordercolor} shadow=({subtitle_shadowx},{subtitle_shadowy}) boxborder={subtitle_boxborder} words={subtitle_words_count} fade={subtitle_word_fade}")
        
        ass_path = None

        if subtitle_segments:
            # ASS + subtitles filter (стабильнее drawtext для 100+ слов)
            ass_path = self.output_dir / f"subs_{job_id}_{index}.ass"

            primary_color = self._ass_color(subtitle_fontcolor, "FFFFFF") or "&H00FFFFFF&"
            outline_color = self._ass_color(subtitle_bordercolor, "000000") or "&H00000000&"
            shadow_ass_color = self._ass_color(subtitle_shadowcolor, "000000") or "&H00000000&"

            bold_val = 1 if subtitle_style in ("bold", "bold_italic") or font_file_implies_bold else 0
            italic_val = 1 if subtitle_style in ("italic", "bold_italic") or font_file_implies_italic else 0
            outline_val = subtitle_borderw if subtitle_borderw > 0 and subtitle_bordercolor != "none" else 0
            shadow_dist = max(subtitle_shadowx, subtitle_shadowy) if subtitle_shadowcolor != "none" else 0
            subtitle_anchor_y = max(0, min(frame_height, round(subtitle_position * frame_height / 1920)))
            margin_v = frame_height - subtitle_anchor_y

            # Box background (BorderStyle=3)
            if subtitle_boxborder > 0 and subtitle_boxcolor != "none":
                border_style = 3
                back_color = self._ass_color(subtitle_boxcolor, "000000") or "&H80000000&"
            else:
                border_style = 1
                back_color = shadow_ass_color

            with open(ass_path, 'w', encoding='utf-8-sig') as f:
                f.write('[Script Info]\n')
                f.write(f'PlayResX: {frame_width}\n')
                f.write(f'PlayResY: {frame_height}\n')
                f.write('WrapStyle: 2\n')
                f.write('\n')
                f.write('[V4+ Styles]\n')
                f.write('Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n')
                f.write(f'Style: Default,{subtitle_font},{subtitle_fontsize},{primary_color},&H000000FF,{outline_color},{back_color},{bold_val},{italic_val},0,0,100,100,0,0,{border_style},{outline_val},{shadow_dist},2,20,20,{margin_v},1\n\n')
                f.write('[Events]\n')
                f.write('Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')

                def fmt_ass(t):
                    hours = int(t // 3600)
                    minutes = int((t % 3600) // 60)
                    seconds = int(t % 60)
                    cs = int((t % 1) * 100)
                    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"

                # Group words and keep captions visible through short pauses.
                wc = max(1, subtitle_words_count)
                segs = [
                    item for item in subtitle_segments
                    if str(item.get("text", "")).strip()
                ]
                segment_duration = max(0.1, float(segment["end"] - segment["start"]))
                i = 0
                while i < len(segs):
                    group = segs[i:i + wc]
                    start_t = max(0.0, float(group[0].get("start", 0)))
                    raw_end = float(group[-1].get("end", start_t + 0.3))
                    end_t = max(start_t + 0.25, raw_end)
                    next_index = i + wc
                    if next_index < len(segs):
                        next_start = max(start_t, float(segs[next_index].get("start", end_t)))
                        # Keep the caption through a short pause, but never into
                        # the following caption. The former +0.05 overlap made
                        # virtually every next word alternate to another Y level.
                        end_t = max(end_t, min(next_start, raw_end + 0.35))
                        if next_start > start_t:
                            end_t = min(end_t, next_start)
                    end_t = min(segment_duration, end_t)

                    text_value = " ".join(
                        str(item.get("text", "")).strip() for item in group
                    )
                    text_value = (
                        text_value.replace("\\", "\\\\")
                        .replace("{", r"\{")
                        .replace("}", r"\}")
                        .replace("\r", "")
                        .replace("\n", r"\N")
                    )
                    if subtitle_capitalize:
                        text_value = text_value.upper()
                    text_value = f"{{\\an2\\pos({frame_width // 2},{subtitle_anchor_y})}}{text_value}"
                    if subtitle_word_fade and end_t - start_t >= 0.4:
                        fade_ms = min(80, int((end_t - start_t) * 120))
                        text_value = f"{{\\fad({fade_ms},{fade_ms})}}{text_value}"
                    f.write(
                        f'Dialogue: 0,{fmt_ass(start_t)},{fmt_ass(end_t)},'
                        f'Default,,0,0,0,,{text_value}\n'
                    )
                    i += wc
        use_banner = banner_enabled and banner_path and Path(banner_path).exists()
        pause_mode = use_banner and banner_style == "pause"
        freeze_path = None
        banner_is_video = bool(use_banner) and Path(banner_path).suffix.lower() in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")

        if pause_mode:
            # ── Режим паузы: видео останавливается в середине, показывается баннер ──
            segdur = segment["end"] - segment["start"]
            pos_pct = max(0.0, min(100.0, float(banner_position if banner_position is not None else 50))) / 100.0
            T = segdur * pos_pct
            D = max(0.1, float(banner_duration if banner_duration is not None else 3))
            banner_input_loops = 0
            # Never pause in the middle of a spoken word. First use the real
            # waveform to find a quiet gap; recognized word gaps are fallback.
            pause_aligned = False
            probe_rel_start = max(0.0, T - 3.0)
            probe_duration = min(6.0, segdur - probe_rel_start)
            if probe_duration >= 0.5:
                probe_cmd = [
                    self.ffmpeg, "-hide_banner",
                    "-ss", str(segment["start"] + probe_rel_start),
                    "-t", str(probe_duration), "-i", video_path,
                    "-vn", "-af", "silencedetect=noise=-24dB:d=0.08",
                    "-f", "null", "-"
                ]
                try:
                    loop = asyncio.get_running_loop()
                    detected = await loop.run_in_executor(
                        None,
                        lambda: subprocess.run(
                            probe_cmd, capture_output=True, text=True, timeout=60
                        )
                    )
                    silence_pairs = re.findall(
                        r"silence_start:\s*([0-9.]+).*?"
                        r"silence_end:\s*([0-9.]+)",
                        detected.stderr or "", re.DOTALL
                    )
                    quiet_points = []
                    for silence_start, silence_end in silence_pairs:
                        point = probe_rel_start + (
                            float(silence_start) + float(silence_end)
                        ) / 2.0
                        if 0.5 <= point <= segdur - 0.5:
                            quiet_points.append((abs(point - T), point))
                    nearby_quiet = [point for point in quiet_points if point[0] <= 3.0]
                    if nearby_quiet:
                        aligned_t = min(nearby_quiet)[1]
                        print(
                            f"[AUDIO] Banner pause aligned to silence "
                            f"{T:.3f}s -> {aligned_t:.3f}s"
                        )
                        T = aligned_t
                        pause_aligned = True
                except Exception as exc:
                    print(f"[AUDIO] Silence alignment failed: {exc}")

            if not pause_aligned and subtitle_segments:
                words = sorted(
                    (item for item in subtitle_segments if item.get("end") is not None),
                    key=lambda item: float(item.get("start", 0.0)),
                )
                gaps = []
                previous_end = 0.0
                for word in words:
                    word_start = max(0.0, float(word.get("start", previous_end)))
                    if word_start - previous_end >= 0.08:
                        gap_mid = (previous_end + word_start) / 2.0
                        if 0.5 <= gap_mid <= segdur - 0.5:
                            gaps.append((abs(gap_mid - T), -(word_start - previous_end), gap_mid))
                    previous_end = max(previous_end, float(word.get("end", word_start)))
                nearby_gaps = [gap for gap in gaps if gap[0] <= 3.0]
                if nearby_gaps:
                    aligned_t = min(nearby_gaps)[2]
                    print(
                        f"[AUDIO] Banner pause aligned to word gap "
                        f"{T:.3f}s -> {aligned_t:.3f}s"
                    )
                    T = aligned_t
            # Keep the banner input finite. An infinite stream can leave FFmpeg
            # waiting after every filtered output has already reached EOF.
            if banner_is_video:
                mp4_dur = await self.get_duration(banner_path)
                if mp4_dur and mp4_dur > 0:
                    if banner_full_duration:
                        D = float(mp4_dur)
                    banner_input_loops = max(0, int(math.ceil(D / mp4_dur)) - 1)
            if T < 1.0:
                T = min(1.0, segdur / 2.0)
            if segdur - T < 1.0:
                T = max(0.5, segdur - 1.0)

            # banner_duration is part of the requested final duration. Replace
            # the same interval in the source instead of extending the output.
            D = min(D, max(0.1, segdur - T - 0.1))
            source_resume = min(segdur, T + D)
            banner_media_offset = 0.0

            # кадр-заморозка в точке паузы (абсолютное время внутри исходного видео)
            freeze_path = self.output_dir / f"freeze_{job_id}_{index}.png"
            mid_abs = segment["start"] + T
            subprocess.run(
                [self.ffmpeg, "-y", "-ss", str(mid_abs), "-i", video_path, "-frames:v", "1", str(freeze_path)],
                capture_output=True, timeout=60
            )
            if not freeze_path.exists():
                # fallback: output-seeking
                subprocess.run(
                    [self.ffmpeg, "-y", "-i", video_path, "-ss", str(mid_abs), "-frames:v", "1", str(freeze_path)],
                    capture_output=True, timeout=60
                )
            if not freeze_path.exists():
                print(f"[FFMPEG] [{index}] Freeze frame failed, using overlay banner instead")
                pause_mode = False

        if pause_mode:
            fps = await self._get_video_fps(video_path)
            opacity = max(0.0, min(1.0, banner_opacity / 100.0))
            bx = (frame_width - int(banner_w)) // 2 + int(banner_x)
            by = (frame_height - int(banner_h)) // 2 + int(banner_y)

            chain_parts = [
                "[0:v]split=2[va0][vc0]",
                f"[va0]trim=duration={T},setpts=PTS-STARTPTS[va_t]",
                self._bg_filter_chain("[va_t]", "va", crop_mode, blurred_bg, suffix="_a"),
                self._bg_filter_chain("[1:v]", "vbf", crop_mode, blurred_bg, suffix="_b"),
                f"[2:v]setpts=N/FRAME_RATE/TB,fps={fps},scale={banner_w}:{banner_h},"
                f"trim=start={banner_media_offset}:duration={D},setpts=PTS-STARTPTS[banner]",
            ]
            if opacity < 1.0:
                chain_parts.append(f"[vbf][banner]overlay={bx}:{by}:format=auto,format=rgba,colorchannelmixer=aa={opacity}[vb]")
            else:
                chain_parts.append(f"[vbf][banner]overlay={bx}:{by}[vb]")
            chain_parts += [
                f"[vc0]trim=start={source_resume}:end={segdur},setpts=PTS-STARTPTS[vc_t]",
                self._bg_filter_chain("[vc_t]", "vc", crop_mode, blurred_bg, suffix="_c"),
                "[va][vb][vc]concat=n=3:v=1:a=0[vid]",
            ]
            has_audio = await self._has_audio(video_path)
            banner_has_audio = banner_is_video and await self._has_audio(banner_path)
            if has_audio:
                chain_parts.append(
                    f"[0:a:0]aformat=sample_rates=48000:channel_layouts=stereo,"
                    f"atrim=start=0:end={T},asetpts=PTS-STARTPTS[a_before]"
                )
                if banner_has_audio:
                    echo_delay_samples = 379  # 7.90 ms at 48 kHz
                    inverse_comb_denominator = " ".join(
                        ["1"] + ["0"] * (echo_delay_samples - 1) + ["0.28"]
                    )
                    fade_out_start = max(0.0, D - 0.04)
                    chain_parts.append(
                        f"[2:a:0]aformat=sample_rates=48000:channel_layouts=stereo,"
                        f"atrim=start={banner_media_offset}:duration={D},"
                        f"asetpts=PTS-STARTPTS,"
                        f"aiir=z='1':p='{inverse_comb_denominator}':"
                        f"f=tf:r=d:n=false,"
                        f"volume=0.90,"
                        f"afade=t=in:st=0:d=0.04,"
                        f"afade=t=out:st={fade_out_start}:d=0.04[a_pause]"
                    )
                else:
                    chain_parts.append(
                        f"anullsrc=channel_layout=stereo:sample_rate=48000,"
                        f"atrim=duration={D},asetpts=PTS-STARTPTS[a_pause]"
                    )
                chain_parts += [
                    f"[0:a:0]aformat=sample_rates=48000:channel_layouts=stereo,"
                    f"atrim=start={source_resume}:end={segdur},asetpts=PTS-STARTPTS[a_after]",
                    "[a_before][a_pause][a_after]concat=n=3:v=0:a=1[aud]",
                ]
            filter_chain = ";".join(chain_parts)
            map_video = "[vid]"
            map_audio = "[aud]" if has_audio else None

            cmd_inputs = ["-ss", str(segment["start"]), "-t", str(segdur), "-i", video_path]
            cmd_inputs += ["-loop", "1", "-t", str(D), "-framerate", str(fps), "-i", str(freeze_path)]
            if banner_is_video:
                cmd_inputs += ["-stream_loop", str(banner_input_loops), "-i", banner_path]
            else:
                cmd_inputs += ["-loop", "1", "-i", banner_path]
            # Banner replaces [T, T+D], so later timestamps stay unchanged.
            self._remove_ass_events_in_interval(ass_path, T, source_resume)
        else:
            # ── Overlay режим: баннер поверх всего видео ──
            filter_parts = [self._bg_filter_chain("[0:v]", "vid_out", crop_mode, blurred_bg)]
            overlay_loops = 1
            if use_banner:
                banner_scale_filter = f"scale={banner_w}:{banner_h}"
                opacity = max(0.0, min(1.0, banner_opacity / 100.0))
                if banner_is_video:
                    # видео-баннер: конечное зацикливание (бесконечное -stream_loop -1 виснет)
                    segdur = segment["end"] - segment["start"]
                    banner_dur = await self.get_duration(banner_path)
                    if banner_dur and banner_dur > 0:
                        overlay_loops = max(1, int(math.ceil(segdur / banner_dur)))
                    filter_parts.append(f"[1:v]{banner_scale_filter}[banner]")
                else:
                    filter_parts.append(f"[1:v]loop=-1:1:0,setpts=N/FRAME_RATE/TB,{banner_scale_filter}[banner]")
                if opacity < 1.0:
                    filter_parts.append(f"[vid_out][banner]overlay={banner_x}:{banner_y}:format=auto,format=rgba,colorchannelmixer=aa={opacity}[vid_out]")
                else:
                    filter_parts.append(f"[vid_out][banner]overlay={banner_x}:{banner_y}[vid_out]")
            filter_chain = ";".join(filter_parts)
            map_video = "[vid_out]"
            map_audio = "0:a:0?"

            cmd_inputs = ["-ss", str(segment["start"]), "-t", str(segment["end"] - segment["start"]), "-i", video_path]
            if use_banner:
                if banner_is_video:
                    cmd_inputs += ["-stream_loop", str(overlay_loops), "-i", banner_path]
                else:
                    cmd_inputs += ["-i", banner_path]

        print(f"[FFMPEG] [{index}] crop_mode={crop_mode}, blurred_bg={blurred_bg}, banner={use_banner}, style={banner_style if use_banner else '-'}, filter={filter_chain[:60]}...")

        # GPU или CPU (VIDEO_PRESET: fast / medium / high — скорость кодирования)
        video_preset_env = _read_env("VIDEO_PRESET", "high").lower()
        if self.gpu_encoder == "h264_nvenc":
            video_codec = "h264_nvenc"
            video_preset = {"fast": "p2", "medium": "p4", "high": "p6"}.get(video_preset_env, "p4")
            video_quality = {
                "fast": ["-cq", "20", "-b:v", "15M", "-rc", "vbr"],
                "medium": ["-cq", "18", "-b:v", "20M", "-rc", "vbr"],
                "high": ["-cq", "14", "-b:v", "30M", "-maxrate", "45M", "-bufsize", "60M", "-rc", "vbr", "-multipass", "fullres", "-spatial-aq", "1", "-aq-strength", "8"],
            }.get(video_preset_env, ["-cq", "14", "-b:v", "30M", "-maxrate", "45M", "-bufsize", "60M", "-rc", "vbr", "-multipass", "fullres", "-spatial-aq", "1", "-aq-strength", "8"])
        elif self.gpu_encoder == "h264_v4l2m2m":
            video_codec = "h264_v4l2m2m"
            video_preset = ""
            video_quality = ["-b:v", "5M", "-g", "30"]
        elif self.gpu_encoder:
            video_codec = self.gpu_encoder
            video_preset = "fast"
            video_quality = ["-cq", "18"]
        else:
            video_codec = "libx264"
            video_preset = "medium"
            video_quality = ["-crf", "16", "-threads", "0"]
        
        # ASS субтитры — один subtitles фильтр вместо цепочки drawtext
        if ass_path and ass_path.exists():
            ass_rel = os.path.relpath(ass_path, BASE_DIR).replace('\\', '/')
            fonts_dir_rel = os.path.relpath(subtitle_fonts_dir, BASE_DIR).replace('\\', '/')
            filter_chain += f";{map_video}subtitles=filename={ass_rel}:fontsdir={fonts_dir_rel}[vid_sub]"
            map_video = "[vid_sub]"
        
        loop = asyncio.get_event_loop()

        cmd = [self.ffmpeg, "-y"] + cmd_inputs + [
            "-filter_complex", filter_chain,
            "-map", map_video,
        ]
        if map_audio:
            cmd += ["-map", map_audio]
        cmd += ["-c:v", video_codec,
        ]
        if video_preset:
            cmd += ["-preset", video_preset]
        cmd += video_quality + [
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path)
        ]
        
        print(f"[FFMPEG] [{index}] Render: {' '.join(cmd[:10])}...")
        
        result = await loop.run_in_executor(None, lambda: subprocess.run(cmd, capture_output=True, timeout=600, cwd=str(BASE_DIR)))
        
        if result.returncode != 0:
            error_msg = result.stderr.decode('utf-8', errors='ignore') if result.stderr else 'None'
            print(f"[FFMPEG] [{index}] Error: {result.returncode}")
            print(f"[FFMPEG] [{index}] stderr: {error_msg[:2000]}")
            # Fallback на CPU если GPU кодировщик не сработал
            if self.gpu_encoder and video_codec != "libx264":
                print(f"[FFMPEG] Retrying with libx264 (GPU encoder failed)...")
                cmd = [self.ffmpeg, "-y"] + cmd_inputs + [
                    "-filter_complex", filter_chain,
                    "-map", map_video,
                ]
                if map_audio:
                    cmd += ["-map", map_audio]
                cmd += [
                    "-c:v", "libx264",
                    "-preset", "medium",
                    "-crf", "16",
                    "-threads", "0",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-movflags", "+faststart",
                    str(output_path)]
                result = await loop.run_in_executor(None, lambda: subprocess.run(cmd, capture_output=True, timeout=600, cwd=str(BASE_DIR)))
                if result.returncode == 0:
                    video_codec = "libx264"
                    video_preset = "medium"
                    video_quality = ["-crf", "16"]
            if result.returncode != 0:
                if ass_path and ass_path.exists():
                    ass_path.unlink(missing_ok=True)
                if freeze_path and Path(freeze_path).exists():
                    Path(freeze_path).unlink(missing_ok=True)
                error_msg = result.stderr.decode('utf-8', errors='ignore')[-500:] if result.stderr else 'unknown'
                raise RuntimeError(f"ffmpeg failed (rc={result.returncode}): {error_msg}")
        
        # Чистим временные ASS файлы
        if ass_path and ass_path.exists():
            ass_path.unlink(missing_ok=True)
        if freeze_path and Path(freeze_path).exists():
            Path(freeze_path).unlink(missing_ok=True)

        if output_path.exists():
            # Фоновая музыка: микшируем/заменяем аудио (отдельный быстрый проход, видео копируется)
            if music_path and Path(music_path).exists():
                ok = await self._mix_music(
                    str(output_path), music_path,
                    volume=music_volume, start=music_start, end=music_end,
                    replace_audio=replace_audio
                )
                print(f"[MUSIC] {'OK' if ok else 'SKIPPED/FAILED'} for {output_path.name}")
            print(f"[FFMPEG] Video created: {output_path}")
            return str(output_path)
        else:
            print(f"[FFMPEG] File not created: {output_path}")
            return None

    async def _mix_music(self, video_path: str, music_path: str, volume: float = 0.7,
                         start: float = 0, end: float = 0, replace_audio: bool = False) -> bool:
        """Накладывает музыку на готовый шортс (видео копируется, аудио перекодируется)."""
        try:
            dur = await self.get_duration(video_path) or 30.0
            volume = min(2.0, max(0.0, float(volume)))
            frag = self.output_dir / f"mus_{os.path.basename(video_path)}.wav"

            # 1) Вырезаем нужный фрагмент музыки [start, end] (или с start) один раз
            mcmd = [self.ffmpeg, "-y"]
            if end and end > start:
                mcmd += ["-ss", str(float(start)), "-t", str(float(end) - float(start))]
            elif start and start > 0:
                mcmd += ["-ss", str(float(start))]
            mcmd += ["-i", music_path, "-ac", "2", "-ar", "48000", str(frag)]
            loop = asyncio.get_event_loop()
            r = await loop.run_in_executor(None, lambda: subprocess.run(mcmd, capture_output=True, timeout=120))
            if not frag.exists():
                return False

            out = self.output_dir / f"{Path(video_path).stem}_mus.mp4"
            has_audio = await self._has_audio(video_path)
            if replace_audio or not has_audio:
                fc = (f"[1:a]atrim=0:{dur},asetpts=PTS-STARTPTS,volume={volume}[a]")
                cmd = [self.ffmpeg, "-y", "-i", video_path, "-stream_loop", "-1", "-i", str(frag),
                       "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
                       "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)]
            else:
                fc = (f"[1:a]atrim=0:{dur},asetpts=PTS-STARTPTS,volume={volume}[m];"
                      f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo[a0];"
                      f"[a0][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
                cmd = [self.ffmpeg, "-y", "-i", video_path, "-stream_loop", "-1", "-i", str(frag),
                       "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
                       "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out)]

            r2 = await loop.run_in_executor(None, lambda: subprocess.run(cmd, capture_output=True, timeout=300))
            frag.unlink(missing_ok=True)
            if r2.returncode == 0 and out.exists():
                os.replace(str(out), video_path)
                return True
            if out.exists():
                out.unlink(missing_ok=True)
            return False
        except Exception as e:
            print(f"[MUSIC] Error: {e}")
            return False

    @staticmethod
    def _font_family_name(font_path):
        """Read the internal family name from a TrueType name table."""
        try:
            data = Path(font_path).read_bytes()
            if len(data) < 12:
                return None
            table_count = int.from_bytes(data[4:6], "big")
            name_offset = None
            for index in range(table_count):
                record = 12 + index * 16
                if record + 16 > len(data):
                    break
                if data[record:record + 4] == b"name":
                    name_offset = int.from_bytes(data[record + 8:record + 12], "big")
                    break
            if name_offset is None or name_offset + 6 > len(data):
                return None
            count = int.from_bytes(data[name_offset + 2:name_offset + 4], "big")
            strings_at = name_offset + int.from_bytes(data[name_offset + 4:name_offset + 6], "big")
            choices = []
            for index in range(count):
                record = name_offset + 6 + index * 12
                if record + 12 > len(data):
                    break
                platform = int.from_bytes(data[record:record + 2], "big")
                language = int.from_bytes(data[record + 4:record + 6], "big")
                name_id = int.from_bytes(data[record + 6:record + 8], "big")
                length = int.from_bytes(data[record + 8:record + 10], "big")
                offset = int.from_bytes(data[record + 10:record + 12], "big")
                if name_id not in (1, 16):
                    continue
                raw = data[strings_at + offset:strings_at + offset + length]
                try:
                    value = raw.decode("utf-16-be" if platform in (0, 3) else "mac_roman").strip("\x00 ")
                except (UnicodeDecodeError, LookupError):
                    continue
                if value:
                    priority = (name_id == 16, platform == 3, language in (0, 0x409))
                    choices.append((priority, value))
            return max(choices, default=(None, None))[1]
        except (OSError, ValueError, IndexError):
            return None

    def _find_font(self, name: str):
        """Ищет TTF файл шрифта: по имени, без пробелов, или первый попавшийся"""
        clean_name = str(name or "").replace("\\", "/").strip("/")
        relative = Path(clean_name)
        candidates = []
        if not relative.is_absolute() and ".." not in relative.parts:
            candidates.extend([
                self.fonts_dir / f"{clean_name}.ttf",
                self.fonts_dir / f"{clean_name.replace(' ', '')}.ttf",
            ])
        for c in candidates:
            if c.exists():
                return c
        # A plain family name may refer to an installed system font (Arial,
        # Verdana, Impact, etc.); leave it to libass instead of silently
        # replacing it with Montserrat. Only a missing uploaded-font path gets
        # a deterministic local fallback.
        if len(relative.parts) > 1:
            default_font = self.fonts_dir / "Montserrat.ttf"
            if default_font.exists():
                print(f"[FONT] '{name}.ttf' not found, using {default_font.name}")
                return default_font
        return None

    @staticmethod
    def color_to_hex(color_name: str) -> str:
        """Convert color name or '#RRGGBB'/hex to hex string (0xRRGGBB)."""
        colors = {
            "white": "0xFFFFFF",
            "yellow": "0xFFFF00",
            "red": "0xFF0000",
            "green": "0x00FF00",
            "blue": "0x0000FF",
            "cyan": "0x00FFFF",
            "magenta": "0xFF00FF",
            "orange": "0xFFA500",
            "gray": "0x808080",
            "black": "0x000000",
            "none": "0x000000",
        }
        if color_name:
            c = color_name.strip().lower()
            if c.startswith("#"):
                c = c[1:]
            if len(c) == 6 and all(ch in "0123456789abcdef" for ch in c):
                return "0x" + c.upper()
        return colors.get(color_name, "0xFFFFFF")

    @staticmethod
    def _ass_color(color_value, default_rgb="FFFFFF"):
        """Parse 'name' / 'name@0.8' / '#RRGGBB' / '#RRGGBB@0.8' into ASS &HAABBGGRR&.

        The alpha part after '@' is opacity in 0..1 (1 = fully opaque).
        ASS alpha is inverted (00 = opaque, FF = transparent), so it is flipped here.
        Returns None for empty / 'none' values.
        """
        if not color_value or color_value == "none":
            return None
        color = color_value
        alpha = 1.0
        if "@" in color_value:
            color, a = color_value.split("@", 1)
            try:
                alpha = min(1.0, max(0.0, float(a)))
            except (TypeError, ValueError):
                alpha = 1.0
        rgb = VideoProcessor.color_to_hex(color).replace("0x", "")
        if len(rgb) != 6:
            rgb = default_rgb
        r, g, b = rgb[0:2], rgb[2:4], rgb[4:6]
        alpha_hex = f"{int((1.0 - alpha) * 255):02X}"
        return f"&H{alpha_hex}{b}{g}{r}&"
    
    async def get_subtitles(self, video_path: str, start: float, end: float, model_size: str = None, word_timestamps: bool = True, progress_cb=None):
        if model_size is None:
            model_size = _read_env("WHISPER_MODEL", "base")
        try:
            model = self._get_whisper_model(model_size)
            
            wt_str = "with word timestamps" if word_timestamps else "without word timestamps"
            print(f"[WHISPER] Transcribing {start}s - {end}s ({model_size}, {wt_str})...")
            
            import tempfile
            import os
            
            temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_audio.close()
            
            cmd = [
                self.ffmpeg, "-y",
                "-ss", str(start),
                "-i", video_path,
                "-t", str(end - start),
                "-ar", "16000",
                "-ac", "1",
                "-acodec", "pcm_s16le",
                temp_audio.name
            ]
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: subprocess.run(cmd, capture_output=True, timeout=300))

            if result.returncode != 0:
                err = result.stderr.decode('utf-8', errors='ignore') if result.stderr else ''
                print(f"[WHISPER] Audio extraction failed ({result.returncode}): {err[:300]}")
                os.unlink(temp_audio.name)
                return {"text": "Речь в моменте", "segments": []}

            print(f"[WHISPER] Creating temporary audio: {temp_audio.name}")
            if not os.path.exists(temp_audio.name):
                raise Exception("Audio file not created")

            print(f"[WHISPER] Running transcription on: {temp_audio.name}")
            import time
            start_transcribe = time.time()
            print(f"[WHISPER] Starting model.transcribe()...")
            try:
                result = model.transcribe(temp_audio.name, language="ru", word_timestamps=word_timestamps)
                print(f"[WHISPER] model.transcribe() returned, type: {type(result)}")
                
                segments_list = []
                text_parts = []
                word_segments = []
                
                # faster_whisper returns tuple: (segments_generator, info)
                print(f"[WHISPER] Unpacking result...")
                segments_gen, info = result
                print(f"[WHISPER] Got generator, starting iteration...")
                total_sec = max(float(getattr(info, "duration", 0) or (end - start)), 1.0)
                last_pct = [0]
                
                for seg in segments_gen:
                    text_parts.append(seg.text)
                    segments_list.append({
                        "start": seg.start,
                        "end": seg.end,
                        "text": seg.text
                    })
                    if hasattr(seg, 'words') and seg.words:
                        for word in seg.words:
                            word_segments.append({
                                "start": word.start,
                                "end": word.end,
                                "text": word.word if hasattr(word, 'word') else str(word)
                            })
                    # прогресс транскрипции (для длинных видео — видно, что не зависло)
                    if progress_cb:
                        pct = int(float(seg.end) / total_sec * 100)
                        if pct - last_pct[0] >= 10:
                            last_pct[0] = pct
                            progress_cb(min(pct, 100))
                
                print(f"[WHISPER] Transcription done in {time.time()-start_transcribe:.1f}s, got {len(segments_list)} segments")
                
                full_text = " ".join(text_parts).strip()
                subtitle_data = word_segments if word_segments else segments_list
                filtered = self._filter_nondialogue(subtitle_data)
                removed = len(subtitle_data) - len(filtered)
                if removed:
                    print(f"[WHISPER] Removed {removed} non-dialogue segments")
                print(f"[WHISPER] Got: {len(filtered)} segments/words, text: {full_text[:100]}...")
                
                os.unlink(temp_audio.name)
                if not filtered:
                    return {"text": full_text if full_text else "Речь в моменте", "segments": []}
                return {"text": full_text if full_text else "Речь в моменте", "segments": filtered}
            except Exception as e:
                print(f"[WHISPER] Transcription error: {e}")
                os.unlink(temp_audio.name)
                return {"text": "Речь в моменте", "segments": []}
        except Exception as e:
            print(f"[WHISPER] Error: {str(e)}")
            return {"text": "Речь в моменте", "segments": []}
    
    def create_srt_file(self, segments: List[Dict], output_path: str):
        def format_time(seconds):
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            ms = int((seconds % 1) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"
        
        with open(output_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                f.write(f"{i}\n")
                f.write(f"{format_time(seg['start'])} --> {format_time(seg['end'])}\n")
                f.write(f"{seg['text'].strip()}\n\n")
    
    def create_ass_file(self, segments: List[Dict], font: str, fontsize: int, fontcolor: str,
                        position: int, style: str, borderw: int, bordercolor: str,
                        boxborder: int, boxcolor: str, shadowx: int, shadowy: int,
                        shadowcolor: str, output_path: str, words_count: int = 5, word_fade: bool = True):
        """Create ASS subtitle file with proper styling for 9:16 video"""

        colors = {"white": "FFFFFF", "yellow": "FFFF00", "red": "FF0000",
                 "green": "00FF00", "blue": "0000FF", "black": "000000", "cyan": "00FFFF", "magenta": "FF00FF", "orange": "FFA500"}
        
        # Convert colors to ASS format (&HBBGGRR)
        def to_ass_color(color_name, alpha="00"):
            hex_color = colors.get(color_name, "FFFFFF")
            # ASS format: &HBBGGRR (reverse order)
            r = hex_color[0:2]
            g = hex_color[2:4]
            b = hex_color[4:6]
            return f"&H{alpha}{b}{g}{r}"
        
        primary_color = to_ass_color(fontcolor)
        
        # Border/Outline color
        outline_color = to_ass_color(bordercolor) if bordercolor != "none" and borderw > 0 else "&H000000"
        
        # Shadow color
        shadow_color = to_ass_color(shadowcolor) if shadowcolor != "none" else "&H000000"
        
        # Back color (for box background)
        back_color = "&H000000"
        if boxcolor != "none" and boxborder > 0:
            if "@" in boxcolor:
                # Parse alpha from format like "black@0.8"
                color_part = boxcolor.split("@")[0]
                alpha_val = float(boxcolor.split("@")[1])
                alpha_hex = f"{int((1-alpha_val)*255):02X}"
                back_color = to_ass_color(color_part, alpha_hex)
            else:
                back_color = to_ass_color(boxcolor)
        
        # Bold and Italic
        bold = "1" if style in ["bold", "bold_italic"] else "0"
        italic = "1" if style in ["italic", "bold_italic"] else "0"
        
        # Border style: 1=outline + shadow, 3=opaque box
        border_style = "3" if boxborder > 0 and boxcolor != "none" else "1"
        
        # Outline width (border)
        outline = str(borderw) if borderw > 0 and bordercolor != "none" else "0"
        
        # Shadow offset
        shadow = str(max(shadowx, shadowy)) if shadowcolor != "none" else "0"
        
        # Alignment: 2=bottom center, calculate based on position
        # For 1920x1080 baseline, position is Y from bottom. Convert to ASS alignment
        alignment = 2  # Bottom center

        # MarginV: vertical margin from bottom (for 9:16 we use 1080x1920 resolution)
        # position is from bottom in pixels for 1920 height, convert to 1080 base
        margin_v = int(position * 1080 / 1920)

        ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{fontsize},{primary_color},&H000000,{outline_color},{back_color},{bold},{italic},0,0,100,100,0,0,{border_style},{outline},{shadow},{alignment},10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        def split_words(segment_text: str, segment_start: float, segment_end: float) -> List[Dict]:
            """Split segment into word-level chunks with timing"""
            words = segment_text.strip().split()
            if not words:
                return []
            total_words = len(words)
            total_duration = segment_end - segment_start
            duration_per_word = total_duration / total_words if total_words > 0 else 0.5
            fade_duration = 0.05  # 50ms fade

            result = []
            for i, word in enumerate(words):
                word_start = segment_start + i * duration_per_word
                word_end = word_start + duration_per_word
                result.append({
                    'text': word,
                    'start': word_start,
                    'end': word_end,
                    'fade_in': fade_duration if i == 0 else 0.01,
                    'fade_out': fade_duration if i == total_words - 1 else 0.01
                })
            return result

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ass_header)
            for seg in segments:
                text = seg['text'].strip().replace('\n', ' ').replace('{', '\\{').replace('}', '\\}')

                word_chunks = split_words(text, seg['start'], seg['end'])
                for chunk in word_chunks:
                    start = self.format_ass_time(chunk['start'])
                    end = self.format_ass_time(chunk['end'])
                    f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{chunk['text']}\n")
    
    def format_ass_time(self, seconds: float) -> str:
        """Format time for ASS subtitle format (H:MM:SS.cc)"""
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = seconds % 60
        # Format: H:MM:SS.cc (centiseconds)
        return f"{hours}:{mins:02d}:{secs:05.2f}"
    
    async def get_transcript(self, start: float, end: float) -> str:
        return f"{int(start//60)}:{int(start%60):02d} - {int(end//60)}:{int(end%60):02d}"
    
    async def get_video_info(self, video_path: str) -> Dict:
        duration = await self.get_duration(video_path)
        filename = Path(video_path).stem
        return {
            "title": filename[:50] if len(filename) > 50 else filename,
            "duration": duration
        }
