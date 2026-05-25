import os
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict
from dotenv import load_dotenv

class VideoProcessor:
    _whisper_model = None
    _whisper_model_size = None
    
    def __init__(self, upload_dir: str, output_dir: str):
        self.upload_dir = Path(upload_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.ffmpeg = os.getenv("FFMPEG_PATH", "ffmpeg")
        self.gpu_encoder = self._detect_gpu_encoder()
    
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
        except Exception as e:
            print(f"[FFMPEG] GPU detection error: {e}")
        
        print("[FFMPEG] No GPU encoder, using CPU (libx264)")
        return None
    
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
    def _get_whisper_model(cls, model_size="small"):
        """Singleton Whisper model - загружается один раз"""
        if cls._whisper_model is None or cls._whisper_model_size != model_size:
            print(f"[WHISPER] Loading model '{model_size}' (singleton)...")
            from faster_whisper import WhisperModel
            cls._whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
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
        
        load_dotenv(override=True)
        openai_api_key = os.getenv("OPENAI_API_KEY", "")
        
        # Один вызов: 2 ffmpeg (аудио + видео целиком) + 1 LLM запрос
        candidates = extract_features_for_windows(
            video_path, windows, phrases, openai_api_key
        )
        
        if not candidates:
            return self._default_segments(duration, short_length, shorts_count)
        
        # Обучаем скорер
        scorer = SegmentScorer(input_dim=11, n_epochs=20, learning_rate=1e-2, top_ratio=0.2)
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
            j = phrase_idx
            while j < len(phrases) and phrases[j]["start"] < end:
                p = phrases[j]
                if p["start"] >= start and p["end"] <= end:
                    total_words += p["words"]
                    speech_duration += p["duration"]
                    count += 1
                j += 1
            
            if count == 0:
                continue
            
            density = total_words / short_length
            speech_ratio = speech_duration / short_length
            avg_phrase_len = total_words / count
            
            score = (total_words * 1.0) + (density * 10) + (speech_ratio * 20) + (avg_phrase_len * 2)
            
            candidates.append({
                "start": float(start),
                "end": float(end),
                "score": score,
                "words": total_words,
                "density": density,
                "speech_ratio": speech_ratio,
                "phrases": count
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
    
    async def create_short(self, video_path: str, segment: Dict, index: int, job_id: str, subtitle_segments: List[Dict] = None, blurred_bg: bool = False, filename_keywords: str = "") -> str:
        kw_part = f"_{filename_keywords}" if filename_keywords else ""
        output_path = self.output_dir / f"short_{job_id}_{index}{kw_part}.mp4"

        subtitle_font = "Verdana"
        
        env_path = Path(__file__).parent.parent / ".env"
        subtitle_font = "Verdana"
        subtitle_style = "normal"
        subtitle_fontsize = 75
        subtitle_fontcolor = "white"
        subtitle_position = 600
        subtitle_capitalize = True
        subtitle_borderw = 0
        subtitle_bordercolor = "black"
        subtitle_boxborder = 0
        subtitle_boxcolor = "black@0.8"
        subtitle_shadowx = 0
        subtitle_shadowy = 0
        subtitle_shadowcolor = "black"
        subtitle_words_count = 5
        subtitle_word_fade = True

        if env_path.exists():
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('SUBTITLE_FONT='):
                        subtitle_font = line.split('=')[1].strip().strip('"')
                    elif line.startswith('SUBTITLE_STYLE='):
                        subtitle_style = line.split('=')[1].strip().strip('"')
                    elif line.startswith('SUBTITLE_FONTSIZE='):
                        subtitle_fontsize = int(line.split('=')[1].strip())
                    elif line.startswith('SUBTITLE_FONTCOLOR='):
                        subtitle_fontcolor = line.split('=')[1].strip().strip('"')
                    elif line.startswith('SUBTITLE_POSITION_Y='):
                        subtitle_position = int(line.split('=')[1].strip())
                    elif line.startswith('SUBTITLE_CAPITALIZE='):
                        subtitle_capitalize = line.split('=')[1].strip() == '1'
                    elif line.startswith('SUBTITLE_BORDERW='):
                        subtitle_borderw = int(line.split('=')[1].strip())
                    elif line.startswith('SUBTITLE_BORDERCOLOR='):
                        subtitle_bordercolor = line.split('=')[1].strip().strip('"')
                    elif line.startswith('SUBTITLE_BOX_BORDER='):
                        subtitle_boxborder = int(line.split('=')[1].strip())
                    elif line.startswith('SUBTITLE_BOX_COLOR='):
                        subtitle_boxcolor = line.split('=')[1].strip().strip('"')
                    elif line.startswith('SUBTITLE_SHADOW_X='):
                        subtitle_shadowx = int(line.split('=')[1].strip())
                    elif line.startswith('SUBTITLE_SHADOW_Y='):
                        subtitle_shadowy = int(line.split('=')[1].strip())
                    elif line.startswith('SUBTITLE_SHADOW_COLOR='):
                        subtitle_shadowcolor = line.split('=')[1].strip().strip('"')
                    elif line.startswith('SUBTITLE_WORDS_COUNT='):
                        subtitle_words_count = int(line.split('=')[1].strip())
                    elif line.startswith('SUBTITLE_WORD_FADE='):
                        subtitle_word_fade = line.split('=')[1].strip() == '1'
        
        segment_start = segment["start"]
        ass_path = None

        if subtitle_segments:
            ass_path = self.output_dir / f"subs_{job_id}_{index}.ass"
            
            hex_rgb = self.color_to_hex(subtitle_fontcolor).replace('0x', '')
            r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
            primary_color = f"&H00{b}{g}{r}&"
            
            bold_val = 1 if subtitle_style in ("bold", "bold_italic") else 0
            italic_val = 1 if subtitle_style in ("italic", "bold_italic") else 0
            outline_val = subtitle_borderw if subtitle_borderw > 0 else 0
            shadow_val = 1 if (subtitle_shadowx > 0 or subtitle_shadowy > 0) else 0
            margin_v = 1920 - subtitle_position

            with open(ass_path, 'w', encoding='utf-8-sig') as f:
                f.write('[Script Info]\n')
                f.write('PlayResX: 1080\n')
                f.write('PlayResY: 1920\n\n')
                f.write('[V4+ Styles]\n')
                f.write('Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n')
                f.write(f'Style: Default,{subtitle_font},{subtitle_fontsize},{primary_color},&H000000FF,&H00000000,&H00000000,{bold_val},{italic_val},0,0,100,100,0,0,1,{outline_val},{shadow_val},2,20,20,{margin_v},1\n\n')
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

        temp_video = self.output_dir / f"temp_{job_id}_{index}.mp4"

        if blurred_bg:
            filter_chain = "[0:v]split=2[bg_in][fg_in];[bg_in]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25[bg];[fg_in]scale=1080:-1[fg];[bg][fg]overlay=0:(H-h)/2"
        else:
            filter_chain = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
        
        # GPU или CPU
        if self.gpu_encoder:
            video_codec = self.gpu_encoder
            video_preset = "fast"
            video_quality = ["-cq", "28"]
        else:
            video_codec = "libx264"
            video_preset = "ultrafast"
            video_quality = ["-crf", "28"]
        
        cmd1 = [
            self.ffmpeg, "-y",
            "-ss", str(segment["start"]),
            "-i", video_path,
            "-t", str(segment["end"] - segment["start"]),
            "-filter_complex", filter_chain,
            "-c:v", video_codec,
            "-preset", video_preset,
        ] + video_quality + [
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-threads", "2",
            str(temp_video)
        ]
        
        print(f"[FFMPEG] [{index}] Pass 1 (video): {' '.join(cmd1[:10])}...")
        
        loop = asyncio.get_event_loop()
        result1 = await loop.run_in_executor(None, lambda: subprocess.run(cmd1, capture_output=True, timeout=300))
        
        if result1.returncode != 0:
            print(f"[FFMPEG] [{index}] Pass 1 Error: {result1.returncode}")
            error_msg = result1.stderr.decode('utf-8', errors='ignore') if result1.stderr else 'None'
            print(f"[FFMPEG] [{index}] stderr: {error_msg[:200]}")
            # Fallback: если GPU кодировщик не сработал — пробуем CPU
            if self.gpu_encoder and video_codec != "libx264":
                print(f"[FFMPEG] Retrying Pass 1 with libx264 (GPU encoder failed)...")
                cmd1[cmd1.index(video_codec)] = "libx264"
                cmd1[cmd1.index("-preset") + 1] = "ultrafast"
                qpos = -4
                for i, a in enumerate(cmd1):
                    if a == "-cq":
                        cmd1[i] = "-crf"
                        qpos = i
                        break
                if qpos >= 0 and qpos + 1 < len(cmd1):
                    cmd1[qpos + 1] = "28"
                result1 = await loop.run_in_executor(None, lambda: subprocess.run(cmd1, capture_output=True, timeout=300))
                if result1.returncode == 0:
                    video_codec = "libx264"
                    video_preset = "ultrafast"
                    video_quality = ["-crf", "28"]
            if result1.returncode != 0:
                if ass_path and ass_path.exists():
                    ass_path.unlink(missing_ok=True)
                return None

        if ass_path and ass_path.exists():
            ass_str = str(ass_path).replace('\\', '/')
            if len(ass_str) > 1 and ass_str[1] == ':':
                ass_str = ass_str[0] + '\\\\:' + ass_str[2:]
            cmd2 = [
                self.ffmpeg, "-y",
                "-i", str(temp_video),
                "-vf", f"subtitles={ass_str}",
                "-c:v", video_codec,
                "-preset", video_preset,
            ] + video_quality + [
                "-c:a", "copy",
                str(output_path)
            ]
            
            print(f"[FFMPEG] [{index}] Pass 2 (subtitles): {' '.join(cmd2[:10])}...")
            
            result2 = await loop.run_in_executor(None, lambda: subprocess.run(cmd2, capture_output=True, timeout=300))
            
            if result2.returncode != 0:
                print(f"[FFMPEG] [{index}] Pass 2 Error: {result2.returncode}")
                error_msg = result2.stderr.decode('utf-8', errors='ignore') if result2.stderr else 'None'
                print(f"[FFMPEG] [{index}] stderr: {error_msg[:200]}")
                temp_video.unlink(missing_ok=True)
                if ass_path and ass_path.exists():
                    ass_path.unlink(missing_ok=True)
                return None
            
            temp_video.unlink(missing_ok=True)
        else:
            temp_video.rename(output_path)
        
        # Чистим временные ASS файлы
        if ass_path and ass_path.exists():
            ass_path.unlink(missing_ok=True)

        if output_path.exists():
            print(f"[FFMPEG] Video created: {output_path}")
            return str(output_path)
        else:
            print(f"[FFMPEG] File not created: {output_path}")
            return None

    def color_to_hex(self, color_name: str) -> str:
        """Convert color name to FFmpeg drawtext format (0xRRGGBB)"""
        colors = {
            "white": "0xFFFFFF",
            "yellow": "0xFFFF00",
            "red": "0xFF0000",
            "green": "0x00FF00",
            "blue": "0x0000FF",
            "black": "0x000000"
        }
        return colors.get(color_name, "0xFFFFFF")
    
    async def get_subtitles(self, video_path: str, start: float, end: float, model_size: str = "small", word_timestamps: bool = True):
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
                "-i", video_path,
                "-ss", str(start),
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
