import re
from fastapi import APIRouter, HTTPException, Request
from googleapiclient.discovery import build

from app.core.config import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])

YOUTUBE_API_KEY = settings.YOUTUBE_API_KEY or ""


def get_yt_client():
    if YOUTUBE_API_KEY:
        return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    return None


@router.post("/analyze")
async def analyze(data: dict):
    channel_url = data.get("url", "").strip()
    if not channel_url:
        raise HTTPException(status_code=400, detail="URL required")

    client = get_yt_client()
    if not client:
        raise HTTPException(status_code=400, detail="No YouTube API key")

    parsed = _parse_channel_url(channel_url)
    if not parsed:
        raise HTTPException(status_code=400, detail="Invalid channel URL")

    channel_id = None
    if parsed.startswith("@"):
        resp = client.search().list(part="snippet", q=parsed[1:], type="channel", maxResults=1).execute()
        if resp.get("items"):
            channel_id = resp["items"][0]["snippet"]["channelId"]
    else:
        channel_id = parsed

    if not channel_id:
        raise HTTPException(status_code=404, detail="Channel not found")

    chan = client.channels().list(part="snippet,statistics", id=channel_id).execute()
    if not chan.get("items"):
        raise HTTPException(status_code=404, detail="Channel not found")

    channel = chan["items"][0]
    sn = channel.get("snippet", {})
    stats = channel.get("statistics", {})

    videos = []
    search = client.search().list(part="id", channelId=channel_id, type="video",
                                   maxResults=20, order="date").execute()
    video_ids = [item["id"]["videoId"] for item in search.get("items", [])]
    if video_ids:
        vresp = client.videos().list(part="snippet,statistics", id=",".join(video_ids)).execute()
        for item in vresp.get("items", []):
            vs = item.get("statistics", {})
            views = int(vs.get("viewCount", 0))
            likes = int(vs.get("likeCount", 0))
            videos.append({
                "id": item["id"], "title": item.get("snippet", {}).get("title", ""),
                "views": views, "likes": likes,
                "ctr": round((likes / views * 100) if views > 0 else 0, 2),
                "url": f"https://youtube.com/watch?v={item['id']}"
            })

    return {
        "channel": {
            "id": channel_id,
            "title": sn.get("title", ""),
            "subscribers": int(stats.get("subscriberCount", 0)),
            "views": int(stats.get("viewCount", 0)),
            "videos_count": int(stats.get("videoCount", 0)),
        },
        "videos": videos
    }


@router.get("/analytics")
async def get_analytics():
    from app.youtube_api import YouTubeAPI
    yt = YouTubeAPI(tokens_dir=str(settings.TOKENS_DIR),
                    client_secret_file=str(settings.BASE_DIR / "client_secret.json"))

    total_views = 0
    total_subs = 0
    total_videos = 0
    accounts = []

    for token_file in settings.TOKENS_DIR.glob("token_*.pickle"):
        email = token_file.stem.replace("token_", "").replace("_", "@", 1).replace("_at_", "@")
        try:
            if yt.authenticate(email):
                info = yt.get_channel_info()
                if info:
                    s = info.get("statistics", {})
                    subs = int(s.get("subscriberCount", 0))
                    views = int(s.get("viewCount", 0))
                    vids = int(s.get("videoCount", 0))
                    total_views += views
                    total_subs += subs
                    total_videos += vids
                    accounts.append({
                        "email": email,
                        "channel_title": info.get("snippet", {}).get("title", ""),
                        "videos_count": vids, "views": views, "subscribers": subs,
                        "status": "active"
                    })
        except:
            accounts.append({"email": email, "status": "inactive"})

    return {
        "total_videos": total_videos,
        "total_views": total_views,
        "total_subscribers": total_subs,
        "accounts": accounts,
        "videos": []
    }


def _parse_channel_url(url: str):
    m = re.search(r"(?:youtube\.com|youtu\.be)/channel/([a-zA-Z0-9_-]{10,})", url)
    if m:
        return m.group(1)
    m = re.search(r"(?:youtube\.com|youtu\.be)/@([a-zA-Z0-9_-]+)", url)
    if m:
        return "@" + m.group(1)
    return None
