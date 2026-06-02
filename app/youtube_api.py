import os
import re
import time
import pickle
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

class YouTubeAPI:
    def __init__(self, client_secret_file: str = "client_secret.json", tokens_dir: str = "tokens"):
        self.client_secret_file = client_secret_file
        self.tokens_dir = Path(tokens_dir)
        self.tokens_dir.mkdir(exist_ok=True)
        self.youtube = None
        self.current_email = None
    
    def get_token_file(self, email: str) -> Path:
        """Получить путь к файлу токена для email"""
        safe_email = email.replace('@', '_').replace('.', '_')
        return self.tokens_dir / f"token_{safe_email}.pickle"
    
    def authenticate(self, email: str) -> bool:
        """Авторизация для конкретного email"""
        try:
            print(f"[YOUTUBE API] Authenticating {email}")
            token_file = self.get_token_file(email)
            creds = None
            
            # Загружаем существующий токен
            if token_file.exists():
                with open(token_file, 'rb') as token:
                    creds = pickle.load(token)
            
            # Если токена нет или он протух
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    print(f"[YOUTUBE API] Refreshing token for {email}")
                    creds.refresh(Request())
                else:
                    print(f"[YOUTUBE API] Starting OAuth flow for {email}")
                    print(f"[YOUTUBE API] Browser will open - login with {email}")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.client_secret_file, SCOPES)
                    creds = flow.run_local_server(port=0)
                
                # Сохраняем токен
                with open(token_file, 'wb') as token:
                    pickle.dump(creds, token)
                print(f"[YOUTUBE API] Token saved for {email}")
            
            self.youtube = build('youtube', 'v3', credentials=creds)
            self.current_email = email
            print(f"[YOUTUBE API] Authenticated successfully: {email}")
            return True
            
        except Exception as e:
            print(f"[YOUTUBE API] Authentication error for {email}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def upload_video(self, video_path: str, title: str, description: str, 
                     tags: List[str], category_id: str = "22",
                     privacy_status: str = "public",
                     publish_at: Optional[datetime] = None) -> Optional[str]:
        """Загрузка видео на YouTube"""
        try:
            if not self.youtube:
                print("[YOUTUBE API] Not authenticated")
                return None
            
            print(f"[YOUTUBE API] Uploading: {title}")
            
            # Подготовка метаданных
            body = {
                'snippet': {
                    'title': title,
                    'description': description,
                    'tags': tags,
                    'categoryId': category_id
                },
                'status': {
                    'privacyStatus': privacy_status,
                    'selfDeclaredMadeForKids': False
                }
            }
            
            # Если указано время публикации
            if publish_at and privacy_status == "private":
                body['status']['publishAt'] = publish_at.isoformat() + 'Z'
                body['status']['privacyStatus'] = 'private'
            
            # Загрузка файла
            media = MediaFileUpload(
                video_path,
                mimetype='video/*',
                resumable=True,
                chunksize=1024*1024  # 1MB chunks
            )
            
            request = self.youtube.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )
            
            response = None
            timeout = 600  # 10 минут таймаут
            start_time = time.time()
            
            while response is None:
                if time.time() - start_time > timeout:
                    print(f"[YOUTUBE API] Upload timeout after {timeout}s")
                    return None
                
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    print(f"[YOUTUBE API] Upload progress: {progress}%")
            
            video_id = response['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            print(f"[YOUTUBE API] Upload successful: {video_url}")
            return video_id
            
        except HttpError as e:
            print(f"[YOUTUBE API] HTTP error: {e.resp.status} - {e.content}")
            return None
        except Exception as e:
            print(f"[YOUTUBE API] Upload error: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_channel_info(self) -> Optional[dict]:
        """Получить информацию о канале"""
        try:
            if not self.youtube:
                return None
            
            request = self.youtube.channels().list(
                part='snippet,statistics',
                mine=True
            )
            response = request.execute()
            
            if response['items']:
                return response['items'][0]
            return None
            
        except Exception as e:
            print(f"[YOUTUBE API] Error getting channel info: {str(e)}")
            return None
    
    def list_videos(self, max_results: int = 10) -> List[dict]:
        """Получить список последних видео"""
        try:
            if not self.youtube:
                return []
            
            request = self.youtube.search().list(
                part='snippet',
                forMine=True,
                type='video',
                maxResults=max_results,
                order='date'
            )
            response = request.execute()
            
            return response.get('items', [])
            
        except Exception as e:
            print(f"[YOUTUBE API] Error listing videos: {str(e)}")
            return []

    def get_channel_by_url(self, url: str) -> Optional[dict]:
        """Получить информацию о канале по URL (публичные данные)"""
        try:
            if not self.youtube:
                return None

            channel_id = self._extract_channel_id(url)
            if not channel_id:
                # Попробуем найти через search
                return self._search_channel(url)

            request = self.youtube.channels().list(
                part='snippet,statistics',
                id=channel_id
            )
            response = request.execute()
            return response['items'][0] if response.get('items') else None

        except Exception as e:
            print(f"[YOUTUBE API] Error getting channel by URL: {str(e)}")
            return None

    def _extract_channel_id(self, url: str) -> Optional[str]:
        """Извлечь ID канала из URL"""
        # youtube.com/channel/UC...
        m = re.search(r'(?:youtube\.com|youtu\.be)/channel/([a-zA-Z0-9_-]{10,})', url)
        if m:
            return m.group(1)
        # youtube.com/@handle
        m = re.search(r'(?:youtube\.com|youtu\.be)/@([a-zA-Z0-9_-]+)', url)
        if m:
            try:
                resp = self.youtube.channels().list(
                    part='id',
                    forHandle=m.group(1)
                ).execute()
                if resp.get('items'):
                    return resp['items'][0]['id']
            except:
                pass
            return m.group(1)
        # youtube.com/c/... или youtube.com/user/...
        return None

    def _search_channel(self, url: str) -> Optional[dict]:
        """Поиск канала через search API"""
        try:
            # Извлекаем имя из URL
            name = re.sub(r'https?://(www\.)?youtube\.com/(c|user)/', '', url).rstrip('/')
            if not name:
                return None

            resp = self.youtube.search().list(
                part='snippet',
                q=name,
                type='channel',
                maxResults=1
            ).execute()

            if not resp.get('items'):
                return None

            channel_id = resp['items'][0]['snippet']['channelId']
            channel_resp = self.youtube.channels().list(
                part='snippet,statistics',
                id=channel_id
            ).execute()

            return channel_resp['items'][0] if channel_resp.get('items') else None

        except Exception as e:
            print(f"[YOUTUBE API] Search channel error: {str(e)}")
            return None

    def get_channel_videos(self, channel_id: str, max_results: int = 20) -> List[dict]:
        """Получить список последних видео канала со статистикой"""
        try:
            if not self.youtube:
                return []

            # Получаем ID видео
            search_resp = self.youtube.search().list(
                part='id',
                channelId=channel_id,
                type='video',
                maxResults=min(max_results, 50),
                order='date'
            ).execute()

            video_ids = [item['id']['videoId'] for item in search_resp.get('items', [])]
            if not video_ids:
                return []

            # Получаем статистику по всем видео
            return self.get_video_details(video_ids)

        except Exception as e:
            print(f"[YOUTUBE API] Error getting channel videos: {str(e)}")
            return []

    def get_video_details(self, video_ids: List[str]) -> List[dict]:
        """Получить детальную информацию о видео (статистика + сниппет)"""
        try:
            if not self.youtube or not video_ids:
                return []

            videos = []
            # YouTube API позволяет до 50 ID за запрос
            for i in range(0, len(video_ids), 50):
                batch = video_ids[i:i+50]
                resp = self.youtube.videos().list(
                    part='snippet,statistics',
                    id=','.join(batch)
                ).execute()

                for item in resp.get('items', []):
                    snippet = item.get('snippet', {})
                    stats = item.get('statistics', {})
                    videos.append({
                        'id': item['id'],
                        'title': snippet.get('title', ''),
                        'description': snippet.get('description', ''),
                        'published_at': snippet.get('publishedAt', ''),
                        'thumbnail': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                        'views': int(stats.get('viewCount', 0)),
                        'likes': int(stats.get('likeCount', 0)),
                        'comments': int(stats.get('commentCount', 0)),
                    })

            return videos

        except Exception as e:
            print(f"[YOUTUBE API] Error getting video details: {str(e)}")
            return []

    def get_accounts_with_stats(self) -> List[dict]:
        """Получить список всех авторизованных аккаунтов со статистикой"""
        accounts = []
        for token_file in self.tokens_dir.glob("token_*.pickle"):
            email = token_file.stem.replace('token_', '').replace('_', '@', 1)
            email = email.replace('_at_', '@')
            try:
                if self.authenticate(email):
                    info = self.get_channel_info()
                    if info:
                        stats = info.get('statistics', {})
                        accounts.append({
                            'email': email,
                            'has_token': True,
                            'channel_id': info.get('id', ''),
                            'channel_title': info.get('snippet', {}).get('title', ''),
                            'channel_avatar': info.get('snippet', {}).get('thumbnails', {}).get('default', {}).get('url', ''),
                            'videos_count': int(stats.get('videoCount', 0)),
                            'views': int(stats.get('viewCount', 0)),
                            'subscribers': int(stats.get('subscriberCount', 0)),
                            'status': 'active'
                        })
                    else:
                        accounts.append({
                            'email': email,
                            'has_token': True,
                            'status': 'inactive'
                        })
            except:
                accounts.append({
                    'email': email,
                    'has_token': True,
                    'status': 'inactive'
                })
        return accounts
