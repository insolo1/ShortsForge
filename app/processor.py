import os
import asyncio
import subprocess
import re
from pathlib import Path
from typing import List, Dict

BASE_DIR = Path(__file__).parent.parent

def _read_env(key: str, default: str = "") -> str:
    """Читает значение из .env напрямую (обходит os.environ / load_dotenv)"""
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
        """Singleton Whisper model - загружается один раз, авто CUDA"""
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
    
    async def extract_segments(self, video_path: str, short_length: int, shorts_count: int, subtitle_segments: List[Dict] = None, smart_selection: bool = False) -> List[Dict]:
        duration = await self.get_duration(video_path)
        
        if duration < short_length:
            print(f"[PROCESS] Video too short: {duration}s < {short_length}s")
            return []
        
        # Если smart_selection и есть субтитры — используем нейросетевой скоринг
        if smart_selection and subtitle_segments:
            return self._find_best_segments_nn(duration, short_length, shorts_count, subtitle_segments, video_path)
        
        # Если есть субтитры без smart_selection — выбираем лучшие моменты по плотности речи
        if subtitle_segments:
            return self._find_best_segments(duration, short_length, shorts_count, subtitle_segments)
        
        # Иначе просто режем по порядку
        segments = []
        for i in range(min(shorts_count, int(duration // short_length))):
            start = i * short_length
            end = min(start + short_length, duration)
            segments.append({"start": start, "end": end})
        
        print(f"[PROCESS] Found {len(segments)} segments")
        return segments
    
    def _find_best_segments_nn(self, duration: float, short_length: int, shorts_count: int, subtitle_segments: List[Dict], video_path: str = "") -> List[Dict]:
        """Находит лучшие отрезки с помощью нейросетевого скоринга (SegmentScorer)."""
        
        from segment_scorer import SegmentScorer, extract_features_for_windows
        
        phrases = self._build_phrases(subtitle_segments)
        if not phrases:
            return self._default_segments(duration, short_length, shorts_count)
        
        step = short_length // 2
        windows = []
        for start in range(0, int(duration - short_length), step):
            end = start + short_length
            windows.append((float(start), float(end)))
        
        openai_api_key = _read_env("OPENAI_API_KEY", "")
        
        # Один вызов: 2 ffmpeg (аудио + видео целиком) + 1 LLM запрос
        candidates = extract_features_for_windows(
            video_path, windows, phrases, openai_api_key
        )
        
        if not candidates:
            return self._default_segments(duration, short_length, shorts_count)
        
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
            if len(best_segments) >= shorts_count:
                break
        
        if len(best_segments) < shorts_count:
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
                if len(best_segments) >= shorts_count:
                    break
        
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
                if word["start"] - current_phrase["end"] < 1.0:
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
    
    def _find_best_segments(self, duration: float, short_length: int, shorts_count: int, subtitle_segments: List[Dict], video_path: str = "") -> List[Dict]:
        """Находит лучшие отрезки по плотности речи и длине непрерывной речи"""
        
        phrases = self._build_phrases(subtitle_segments)
        
        if not phrases:
            return self._default_segments(duration, short_length, shorts_count)
        
        # 2. Вычисляем score для каждого окна
        step = short_length // 2
        candidates = []
        phrase_idx = 0
        
        for start in range(0, int(duration - short_length), step):
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
            return self._default_segments(duration, short_length, shorts_count)
        
        # Сортируем по score
        candidates.sort(key=lambda x: x["score"], reverse=True)
        
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
            
            if len(best_segments) >= shorts_count:
                break
        
        # Если набрали меньше чем нужно - добираем из следующих по score
        if len(best_segments) < shorts_count:
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
                if len(best_segments) >= shorts_count:
                    break
        
        # Сортируем по времени
        best_segments.sort(key=lambda x: x["start"])
        
        print(f"[PROCESS] Found {len(best_segments)} best segments. Top score: {best_segments[0]['score']:.1f}, words: {best_segments[0]['words']}, density: {best_segments[0]['density']:.1f}")
        return best_segments
    
    def _default_segments(self, duration: float, short_length: int, shorts_count: int) -> List[Dict]:
        """Fallback если нет субтитров"""
        segments = []
        for i in range(min(shorts_count, int(duration // short_length))):
            start = i * short_length
            end = min(start + short_length, duration)
            segments.append({"start": start, "end": end})
        return segments
    
    async def create_short(self, video_path: str, segment: Dict, index: int, job_id: str, subtitle_segments: List[Dict] = None, blurred_bg: bool = False, filename_keywords: str = "", crop_fill: bool = False, banner_enabled: bool = False, banner_path: str = None, banner_x: int = 0, banner_y: int = 0, banner_w: int = 1080, banner_h: int = 200, banner_opacity: int = 100) -> str:
        kw_part = f"_{filename_keywords}" if filename_keywords else ""
        output_path = self.output_dir / f"short_{job_id}_{index}{kw_part}.mp4"

        subtitle_font = _read_env("SUBTITLE_FONT", "Montserrat")
        subtitle_style = _read_env("SUBTITLE_STYLE", "normal")
        subtitle_fontsize = int(_read_env("SUBTITLE_FONTSIZE", "100"))
        subtitle_fontcolor = _read_env("SUBTITLE_FONTCOLOR", "white")
        subtitle_position = int(_read_env("SUBTITLE_POSITION_Y", "1670"))
        subtitle_capitalize = _read_env("SUBTITLE_CAPITALIZE", "1") == "1"
        subtitle_borderw = int(_read_env("SUBTITLE_BORDERW", "3"))
        subtitle_bordercolor = _read_env("SUBTITLE_BORDERCOLOR", "black")
        subtitle_boxborder = int(_read_env("SUBTITLE_BOX_BORDER", "0"))
        subtitle_boxcolor = _read_env("SUBTITLE_BOX_COLOR", "black@0.8")
        subtitle_shadowx = int(_read_env("SUBTITLE_SHADOW_X", "2"))
        subtitle_shadowy = int(_read_env("SUBTITLE_SHADOW_Y", "2"))
        subtitle_shadowcolor = _read_env("SUBTITLE_SHADOW_COLOR", "black")
        print(f"[SETTINGS] font={subtitle_font} size={subtitle_fontsize} pos={subtitle_position} borderw={subtitle_borderw} bordercolor={subtitle_bordercolor} shadow=({subtitle_shadowx},{subtitle_shadowy}) boxborder={subtitle_boxborder}")
        
        ass_path = None

        if subtitle_segments:
            # ASS + subtitles filter (стабильнее drawtext для 100+ слов)
            ass_path = self.output_dir / f"subs_{job_id}_{index}.ass"

            hex_rgb = self.color_to_hex(subtitle_fontcolor).replace('0x', '')
            r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
            primary_color = f"&H00{b}{g}{r}&"

            outline_rgb = self.color_to_hex(subtitle_bordercolor).replace('0x', '')
            or_, og, ob = outline_rgb[0:2], outline_rgb[2:4], outline_rgb[4:6]
            outline_color = f"&H00{ob}{og}{or_}&"

            shadow_rgb = self.color_to_hex(subtitle_shadowcolor).replace('0x', '')
            sr, sg, sb = shadow_rgb[0:2], shadow_rgb[2:4], shadow_rgb[4:6]
            shadow_ass_color = f"&H00{sb}{sg}{sr}&"

            bold_val = 1 if subtitle_style in ("bold", "bold_italic") else 0
            italic_val = 1 if subtitle_style in ("italic", "bold_italic") else 0
            outline_val = subtitle_borderw if subtitle_borderw > 0 and subtitle_bordercolor != "none" else 0
            shadow_dist = max(subtitle_shadowx, subtitle_shadowy) if subtitle_shadowcolor != "none" else 0
            margin_v = 1920 - subtitle_position

            # Box background (BorderStyle=3)
            if subtitle_boxborder > 0 and subtitle_boxcolor != "none":
                border_style = 3
                box_rgb = self.color_to_hex(subtitle_boxcolor.split('@')[0]).replace('0x', '')
                br, bg_, bb = box_rgb[0:2], box_rgb[2:4], box_rgb[4:6]
                if '@' in subtitle_boxcolor:
                    alpha_val = min(255, int(float(subtitle_boxcolor.split('@')[1]) * 255))
                    alpha_ass = f"{alpha_val:02X}"
                else:
                    alpha_ass = "80"
                back_color = f"&H{alpha_ass}{bb}{bg_}{br}&"
            else:
                border_style = 1
                back_color = shadow_ass_color

            with open(ass_path, 'w', encoding='utf-8-sig') as f:
                f.write('[Script Info]\n')
                f.write('PlayResX: 1080\n')
                f.write('PlayResY: 1920\n\n')
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

                for idx, seg in enumerate(subtitle_segments, 1):
                    start_t = seg['start']
                    end_t = seg['end']
                    if start_t < 0:
                        start_t = 0
                    text = seg['text'].strip().replace('\\', r'\N')
                    if subtitle_capitalize:
                        text = text.capitalize()
                    f.write(f'Dialogue: 0,{fmt_ass(start_t)},{fmt_ass(end_t)},Default,,0,0,0,,{text}\n')

        if crop_fill:
            if blurred_bg:
                print(f"[FFMPEG] [{index}] crop_fill + blurred_bg both enabled, using crop_fill (square fg + blurred bg)")
            filter_parts = [
                "[0:v]split=2[bg_in][fg_in]",
                "[bg_in]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=8[bg]",
                "[fg_in]scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080[fg]",
                "[bg][fg]overlay=0:(H-h)/2[vid_out]"
            ]
        elif blurred_bg:
            filter_parts = [
                "[0:v]split=2[bg_in][fg_in]",
                "[bg_in]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=8[bg]",
                "[fg_in]scale=1080:-1[fg]",
                "[bg][fg]overlay=0:(H-h)/2[vid_out]"
            ]
        else:
            filter_parts = [
                "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2[vid_out]"
            ]

        # Добавляем баннер поверх видео
        use_banner = banner_enabled and banner_path and Path(banner_path).exists()
        if use_banner:
            banner_scale_filter = f"scale={banner_w}:{banner_h}"
            opacity = max(0.0, min(1.0, banner_opacity / 100.0))
            filter_parts.append(f"[1:v]loop=-1:1:0,setpts=N/FRAME_RATE/TB,{banner_scale_filter}[banner]")
            if opacity < 1.0:
                filter_parts.append(f"[vid_out][banner]overlay={banner_x}:{banner_y}:format=auto,format=rgba,colorchannelmixer=aa={opacity}[vid_out]")
            else:
                filter_parts.append(f"[vid_out][banner]overlay={banner_x}:{banner_y}[vid_out]")

        filter_chain = ";".join(filter_parts)

        print(f"[FFMPEG] [{index}] crop_fill={crop_fill}, blurred_bg={blurred_bg}, banner={use_banner}, filter={filter_chain[:60]}...")

        # GPU или CPU
        if self.gpu_encoder == "h264_nvenc":
            video_codec = "h264_nvenc"
            video_preset = "p4"
            video_quality = ["-cq", "18", "-b:v", "20M", "-rc", "vbr"]
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
            video_preset = "ultrafast"
            video_quality = ["-crf", "18", "-threads", "0"]
        
        # ASS субтитры — один subtitles фильтр вместо цепочки drawtext
        if ass_path and ass_path.exists():
            ass_rel = os.path.relpath(ass_path, BASE_DIR).replace('\\', '/')
            filter_chain += f";[vid_out]subtitles=filename={ass_rel}:fontsdir=fonts[vid_out]"
        
        loop = asyncio.get_event_loop()

        cmd = [
            self.ffmpeg, "-y",
            "-ss", str(segment["start"]),
            "-i", video_path,
        ]
        if use_banner:
            cmd += ["-i", banner_path]
        cmd += [
            "-t", str(segment["end"] - segment["start"]),
            "-filter_complex", filter_chain,
            "-map", "[vid_out]",
            "-map", "0:a?",
            "-c:v", video_codec,
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
        
        result = await loop.run_in_executor(None, lambda: subprocess.run(cmd, capture_output=True, timeout=300, cwd=str(BASE_DIR)))
        
        if result.returncode != 0:
            print(f"[FFMPEG] [{index}] Error: {result.returncode}")
            error_msg = result.stderr.decode('utf-8', errors='ignore') if result.stderr else 'None'
            print(f"[FFMPEG] [{index}] stderr: {error_msg[:2000]}")
            # Fallback на CPU если GPU кодировщик не сработал
            if self.gpu_encoder and video_codec != "libx264":
                print(f"[FFMPEG] Retrying with libx264 (GPU encoder failed)...")
                cmd = [self.ffmpeg, "-y",
                    "-ss", str(segment["start"]),
                    "-i", video_path]
                if use_banner:
                    cmd += ["-i", banner_path]
                cmd += [
                    "-t", str(segment["end"] - segment["start"]),
                    "-filter_complex", filter_chain,
                    "-map", "[vid_out]",
                    "-map", "0:a?",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-crf", "18",
                    "-threads", "0",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-movflags", "+faststart",
                    str(output_path)]
                result = await loop.run_in_executor(None, lambda: subprocess.run(cmd, capture_output=True, timeout=300, cwd=str(BASE_DIR)))
                if result.returncode == 0:
                    video_codec = "libx264"
                    video_preset = "ultrafast"
                    video_quality = ["-crf", "18"]
            if result.returncode != 0:
                if ass_path and ass_path.exists():
                    ass_path.unlink(missing_ok=True)
                return None
        
        # Чистим временные ASS файлы
        if ass_path and ass_path.exists():
            ass_path.unlink(missing_ok=True)

        if output_path.exists():
            print(f"[FFMPEG] Video created: {output_path}")
            return str(output_path)
        else:
            print(f"[FFMPEG] File not created: {output_path}")
            return None

    def _find_font(self, name: str):
        """Ищет TTF файл шрифта: по имени, без пробелов, или первый попавшийся"""
        candidates = [
            self.fonts_dir / f"{name}.ttf",
            self.fonts_dir / f"{name.replace(' ', '')}.ttf",
        ]
        for c in candidates:
            if c.exists():
                return c
        # Fallback: первый TTF в папке
        ttf_list = sorted(self.fonts_dir.glob("*.ttf"))
        if ttf_list:
            print(f"[FONT] '{name}.ttf' not found, using {ttf_list[0].name}")
            return ttf_list[0]
        return None

    def color_to_hex(self, color_name: str) -> str:
        """Convert color name to ASS hex string (without &H prefix)"""
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
        return colors.get(color_name, "0xFFFFFF")
    
    async def get_subtitles(self, video_path: str, start: float, end: float, model_size: str = "base", word_timestamps: bool = True):
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
                    escaped_text = chunk['text'].replace('{', '\\{').replace('}', '\\}')
                    f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{escaped_text}\n")
    
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
