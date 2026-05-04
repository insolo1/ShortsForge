import os
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
