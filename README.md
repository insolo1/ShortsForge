# VideoBot — AI Shorts Generator

Turn long videos into viral vertical Shorts/Reels/TikToks automatically.

**Features:**
- 🎬 Smart AI selection of best moments (Whisper + InterestNet + LLM)
- 📱 Vertical 1080×1920 render with animated subtitles
- 🎯 Pause mode: freeze frame + banner overlay + banner audio
- 🤖 AI titles, descriptions, tags (Groq/OpenAI)
- 📺 YouTube OAuth + direct upload
- 🐳 Docker ready for servers

---

## Quick Start

### Option 1: Windows (Local)
```powershell
# 1. Install FFmpeg (add to system PATH)
# Download: https://ffmpeg.org/download.html

# 2. Clone & setup
git clone https://github.com/YOUR_USERNAME/videobot.git
cd videobot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Configure
copy .env.example .env
# Edit .env: add FFMPEG_PATH, GROQ_API_KEY, OPENAI_API_KEY

# 4. Run
python run.py
# Open http://127.0.0.1:8000
```

### Option 2: Linux / Server (Docker)
```bash
git clone https://github.com/YOUR_USERNAME/videobot.git
cd videobot

# 1. Prepare folders (UID 1000 for Docker)
mkdir -p uploads output tokens google_credentials
sudo chown -R 1000:1000 uploads output tokens google_credentials

# 2. Configure
cp .env.example .env
# Edit .env: add your API keys, FFMPEG_PATH=/usr/bin/ffmpeg

# 3. Run
docker compose up -d --build videobot
# Site: http://YOUR_SERVER_IP:8200
```

---

## Configuration (.env)

| Variable | Required | Description |
|----------|----------|-------------|
| `FFMPEG_PATH` | Yes* | Path to ffmpeg binary (`/usr/bin/ffmpeg` on Linux) |
| `GROQ_API_KEY` | No | For AI metadata (free at console.groq.com) |
| `OPENAI_API_KEY` | No | Alternative AI provider |
| `OPENAI_MODEL` | No | Default: `gpt-4o-mini` |
| `WHISPER_MODEL` | No | `base`/`small`/`medium`/`large-v3-turbo` |
| `VIDEO_PRESET` | No | `low`/`medium`/`high` (NVENC) |

*If ffmpeg is in system PATH, `FFMPEG_PATH` is optional.

---

## Usage

1. **Open web UI** → `http://localhost:8000` (or `:8200` in Docker)
2. **Upload video** — drag & drop or select folder
3. **Configure**:
   - Short length: 45–60 sec recommended
   - Count per video: 2–4
   - Smart selection: `hybrid` (best for most content)
   - Banner: upload image/MP4, enable pause mode
4. **Generate** → watch progress in real-time
5. **Download** — individual MP4s or ZIP (auto-split by source, max 1.5 GB per ZIP)
6. **Upload to YouTube** — connect OAuth, select account, publish

---

## Smart Selection Modes

| Mode | Best For |
|------|----------|
| `off` | Sequential cuts (serial content) |
| `global` | Top highlights (reactions, gaming) |
| `parts` | Even coverage (lectures, podcasts) |
| `hybrid` | **Best all-rounder** — quality + coverage |

**Auto-duration** (enable in UI): adjusts each short 45–75 sec to fit complete thoughts.

---

## Pause Mode (Banner)

Video pauses → banner shows + banner audio plays → video continues.
- Banner audio: MP4 banner with sound, or silence (image banner)
- Duration: banner's actual length (up to video segment)
- Audio sync fixed: no overlap between main video and banner

---

## YouTube Upload

1. Google Cloud Console → Enable **YouTube Data API v3**
2. Create **OAuth 2.0 Desktop App** credentials
3. Save as `client_secret.json` in project root
4. In UI: Settings → YouTube Accounts → Add Account
5. Authorize each channel once (tokens saved locally)

---

## Project Structure

```
videobot/
├── app/
│   ├── main.py           # FastAPI app + routes
│   ├── processor.py      # FFmpeg + Whisper pipeline
│   ├── ai_service.py     # Groq/OpenAI metadata
│   ├── youtube_api.py    # OAuth + upload
│   └── processor.py      # Core video processing
├── static/               # Web UI (HTML/JS)
├── fonts/                # Subtitle fonts
├── uploads/              # Input videos (gitignored)
├── output/               # Generated shorts (gitignored)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── run.py                # Local entry point
```

---

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| RAM | 8 GB | 16+ GB |
| GPU | None (CPU) | NVIDIA 8+ GB VRAM (NVENC + faster Whisper) |
| Disk | 20 GB free | 100+ GB SSD |
| CPU | 4 cores | 8+ cores |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ffmpeg not found` | Install ffmpeg, add to PATH, or set `FFMPEG_PATH` in .env |
| `CUDA out of memory` | Use smaller Whisper model (`base`), reduce `SEGMENT_WORKERS` |
| `AI metadata failed` | Check API keys in .env, verify quota |
| `YouTube upload 403` | Re-authorize account, check OAuth scopes |
| `ZIP download fails` | Large archives >1.5 GB auto-split; download parts separately |

---

## License

MIT License — see [LICENSE](LICENSE).

**Third-party:**
- TikTok Sans font: SIL OFL 1.1
- FFmpeg: LGPL/GPL
- faster-whisper, Python deps: their respective licenses