import os
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict
from dotenv import load_dotenv

class VideoProcessor:
    def __init__(self, upload_dir: str, output_dir: str):
        self.upload_dir = Path(upload_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    async def get_duration(self, video_path: str) -> float:
        print(f"[FFPROBE] Getting duration for: {video_path}")
        
        cmd = [r"C:\ffmpeg\ffmpeg1\bin\ffmpeg.exe", "-i", video_path]
        
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
    
    async def extract_segments(self, video_path: str, short_length: int, shorts_count: int, subtitle_segments: List[Dict] = None) -> List[Dict]:
        duration = await self.get_duration(video_path)
        
        if duration < short_length:
            print(f"[PROCESS] Video too short: {duration}s < {short_length}s")
            return []
        
        # Если есть субтитры - выбираем лучшие моменты по плотности речи
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
    
    def _find_best_segments(self, duration: float, short_length: int, shorts_count: int, subtitle_segments: List[Dict]) -> List[Dict]:
        """Находит лучшие отрезки по плотности речи и длине непрерывной речи"""
        
        # 1. Группируем слова в непрерывные фразы (паузы < 1 сек = одна фраза)
        phrases = []
        if not subtitle_segments:
            return self._default_segments(duration, short_length, shorts_count)
        
        current_phrase = None
        for word in subtitle_segments:
            if current_phrase is None:
                current_phrase = {"start": word["start"], "end": word["end"], "words": 1, "texts": [word.get("text", "")]}
            else:
                # Если пауза < 1 сек - продолжаем фразу
                if word["start"] - current_phrase["end"] < 1.0:
                    current_phrase["end"] = word["end"]
                    current_phrase["words"] += 1
                    current_phrase["texts"].append(word.get("text", ""))
                else:
                    # Сохраняем старую фразу и начинаем новую
                    current_phrase["duration"] = current_phrase["end"] - current_phrase["start"]
                    current_phrase["density"] = current_phrase["words"] / max(current_phrase["duration"], 0.1)
                    current_phrase["full_text"] = " ".join(current_phrase["texts"])
                    phrases.append(current_phrase)
                    current_phrase = {"start": word["start"], "end": word["end"], "words": 1, "texts": [word.get("text", "")]}
        
        # Добавляем последнюю фразу
        if current_phrase:
            current_phrase["duration"] = current_phrase["end"] - current_phrase["start"]
            current_phrase["density"] = current_phrase["words"] / max(current_phrase["duration"], 0.1)
            current_phrase["full_text"] = " ".join(current_phrase["texts"])
            phrases.append(current_phrase)
        
        if not phrases:
            return self._default_segments(duration, short_length, shorts_count)
        
        # 2. Вычисляем score для каждого окна
        step = short_length // 2
        candidates = []
        
        for start in range(0, int(duration - short_length), step):
            end = start + short_length
            
            # Находим все фразы в этом окне
            phrases_in_window = [p for p in phrases if p["start"] >= start and p["end"] <= end]
            
            if not phrases_in_window:
                continue
            
            # Метрики:
            # - Общее количество слов
            total_words = sum(p["words"] for p in phrases_in_window)
            # - Плотность слов (слов в секунду)
            density = total_words / short_length
            # - Общая длительность речи (без пауз)
            speech_duration = sum(p["duration"] for p in phrases_in_window)
            # - Процент времени с речью
            speech_ratio = speech_duration / short_length
            # - Средняя длина фразы
            avg_phrase_len = total_words / len(phrases_in_window) if phrases_in_window else 0
            
            # Score = комбинация всех метрик
            # Больше слов, выше плотность, больше речи без пауз = лучше
            score = (total_words * 1.0) + (density * 10) + (speech_ratio * 20) + (avg_phrase_len * 2)
            
            candidates.append({
                "start": float(start),
                "end": float(end),
                "score": score,
                "words": total_words,
                "density": density,
                "speech_ratio": speech_ratio,
                "phrases": len(phrases_in_window)
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
    
    async def create_short(self, video_path: str, segment: Dict, index: int, job_id: str, subtitle_segments: List[Dict] = None, blurred_bg: bool = False) -> str:
        output_path = self.output_dir / f"short_{job_id}_{index}.mp4"
        
        # Читаем настройки субтитров
        load_dotenv(override=True)
        
        env_path = Path(__file__).parent.parent / ".env"
        subtitle_font = "Verdana"
        subtitle_style = "normal"
        subtitle_fontsize = 75
        subtitle_fontcolor = "white"
        subtitle_position = 600
        subtitle_capitalize = True
        subtitle_borderw = 6
        subtitle_bordercolor = "black"
        subtitle_boxborder = 20
        subtitle_boxcolor = "black@0.8"
        subtitle_shadowx = 3
        subtitle_shadowy = 3
        subtitle_shadowcolor = "black"
        
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
        
        # 9:16 формат
        if blurred_bg:
            # Размытый фон: основное видео по центру + размытая подложка
            # Используем ; для нескольких фильтров
            filters = "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2[main];[0:v]scale=270:480,boxblur=20[blur];[blur][main]overlay=0:0"
        else:
            filters = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
        
        # Субтитры через drawtext (по словам) - записываем в файл через filter_script
        if subtitle_segments:
            print(f"[SUBTITLE] Adding {len(subtitle_segments)} words/segments via drawtext")
            
            for seg in subtitle_segments:
                text = seg['text'].strip().replace("'", "'").replace(":", "\\:")
                if not text:
                    continue
                    
                start_time = seg['start']
                end_time = seg['end']
                
                # Стиль текста (bold/italic не поддерживаются drawtext напрямую, используем через font)
                fontcolor_hex = self.color_to_hex(subtitle_fontcolor)
                style_str = ""
                # Для bold/italic нужно использовать соответствующий файл шрифта
                # В данной сборке FFmpeg опции bold/italic не поддерживаются
                
                # Тень
                shadow_str = ""
                if subtitle_shadowcolor != "none":
                    shadow_hex = self.color_to_hex(subtitle_shadowcolor)
                    shadow_str = f":shadowx={subtitle_shadowx}:shadowy={subtitle_shadowy}:shadowcolor={shadow_hex}"
                
                # Обводка
                border_str = ""
                if subtitle_borderw > 0 and subtitle_bordercolor != "none":
                    border_hex = self.color_to_hex(subtitle_bordercolor)
                    border_str = f":borderw={subtitle_borderw}:bordercolor={border_hex}"
                
                # Фон (box) - disabled for now, will fix format later
                box_str = ""
                # TODO: Enable boxcolor with proper format 0xRRGGBBAA
                # if subtitle_boxborder > 0 and subtitle_boxcolor != "none":
                #     box_color_hex = self.color_to_hex(subtitle_boxcolor)
                #     # Convert alpha: 0.8 -> CC (hex)
                #     alpha_hex = "CC"  # Default 80% opacity
                #     if "@" in subtitle_boxcolor:
                #         alpha_val = float(subtitle_boxcolor.split("@")[1])
                #         alpha_hex = f"{int(alpha_val * 255):02X}"
                #     box_str = f":box=1:boxborderw={subtitle_boxborder}:boxcolor={box_color_hex}{alpha_hex}"
                
                # Итоговый drawtext
                enable_expr = f"between(t, {start_time:.3f}, {end_time:.3f})"
                
                dt = "drawtext=text='" + text + "':"
                dt += f"fontsize={subtitle_fontsize}:"
                dt += f"fontcolor={fontcolor_hex}:"
                dt += f"x=(w-text_w)/2:"
                dt += f"y={1920-subtitle_position}:"
                dt += f"enable='{enable_expr}'"
                dt += style_str + shadow_str + border_str + box_str
                
                filters += "," + dt
        
        # Write filter to file to avoid WinError 206 (command line too long)
        filter_file_path = self.output_dir / f"filter_{job_id}_{index}.txt"
        with open(filter_file_path, 'w', encoding='utf-8') as f:
            f.write(filters)
        
        print(f"[VIDEO] Filter length: {len(filters)} chars")
        print(f"[FILTER] Filter written to file: {filter_file_path}")
        
        if blurred_bg:
            cmd = [
                r"C:\ffmpeg\ffmpeg1\bin\ffmpeg.exe", "-y",
                "-ss", str(segment["start"]),
                "-i", video_path,
                "-t", str(segment["end"] - segment["start"]),
                "-filter_complex", filters,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                str(output_path)
            ]
        else:
            cmd = [
                r"C:\ffmpeg\ffmpeg1\bin\ffmpeg.exe", "-y",
                "-ss", str(segment["start"]),
                "-i", video_path,
                "-t", str(segment["end"] - segment["start"]),
                "-filter_script:v", str(filter_file_path),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-map", "0:v",
                "-map", "0:a",
                str(output_path)
            ]
        
        print(f"[FFMPEG] Command: {' '.join(cmd[:10])}...")
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: subprocess.run(cmd, capture_output=True))
        
        # Cleanup filter file
        if filter_file_path and filter_file_path.exists():
            try:
                filter_file_path.unlink()
                print(f"[FILTER] Cleaned up filter file")
            except Exception as e:
                print(f"[FILTER] Warning: could not delete filter file: {e}")
        
        if result.returncode != 0:
            print(f"[FFMPEG] Error: {result.returncode}")
            error_msg = result.stderr.decode('utf-8', errors='ignore') if result.stderr else 'None'
            print(f"[FFMPEG] stderr (full): {error_msg}")
            # Save filter file for debugging if error occurred
            if filter_file_path and filter_file_path.exists():
                print(f"[FFMPEG] Filter file kept for debugging: {filter_file_path}")
            else:
                print(f"[FFMPEG] stderr (truncated): {result.stderr[:500] if result.stderr else 'None'}")
            return None
        else:
            print(f"[FFMPEG] Success")
            if output_path.exists():
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
    
    async def get_subtitles(self, video_path: str, start: float, end: float):
        try:
            from faster_whisper import WhisperModel
            
            print(f"[WHISPER] Loading model...")
            model = WhisperModel("base", device="cpu", compute_type="int8")
            
            print(f"[WHISPER] Transcribing {start}s - {end}s with word timestamps...")
            
            import tempfile
            import os
            
            temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_audio.close()
            
            cmd = [
                r"C:\ffmpeg\ffmpeg1\bin\ffmpeg.exe", "-y",
                "-i", video_path,
                "-ss", str(start),
                "-t", str(end - start),
                "-ar", "16000",
                "-ac", "1",
                "-acodec", "pcm_s16le",
                temp_audio.name
            ]
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: subprocess.run(cmd, capture_output=True, timeout=60))
            
            # Транскрибируем с word_timestamps=True для покадрового отображения
            segments, info = model.transcribe(temp_audio.name, language="ru", word_timestamps=True)
            
            srt_segments = []
            text_parts = []
            word_segments = []  # Список отдельных слов с таймингами
            
            for seg in segments:
                text_parts.append(seg.text)
                
                # Если есть словесные тайминги, добавляем их
                if hasattr(seg, 'words') and seg.words:
                    for word in seg.words:
                        word_segments.append({
                            "start": word.start,
                            "end": word.end,
                            "text": word.word
                        })
                else:
                    # Если нет word timestamps, используем обычные сегменты
                    srt_segments.append({
                        "start": seg.start,
                        "end": seg.end,
                        "text": seg.text
                    })
            
            os.unlink(temp_audio.name)
            
            # Используем word_segments если они есть, иначе srt_segments
            subtitle_data = word_segments if word_segments else srt_segments
            full_text = " ".join(text_parts).strip()
            
            print(f"[WHISPER] Got: {len(subtitle_data)} segments/words, text: {full_text[:100]}...")
            return {"text": full_text if full_text else "Речь в моменте", "segments": subtitle_data}
            
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
                        shadowcolor: str, output_path: str):
        """Create ASS subtitle file with proper styling for 9:16 video"""
        
        colors = {"white": "FFFFFF", "yellow": "FFFF00", "red": "FF0000", 
                 "green": "00FF00", "blue": "0000FF", "black": "000000"}
        
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
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ass_header)
            for seg in segments:
                start = self.format_ass_time(seg['start'])
                end = self.format_ass_time(seg['end'])
                text = seg['text'].strip().replace('\n', ' ').replace('{', '\\{').replace('}', '\\}')
                f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")
    
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
