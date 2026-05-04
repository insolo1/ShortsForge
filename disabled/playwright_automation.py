import os
import time
import json
from pathlib import Path
from datetime import datetime


class GoogleCloudAutomation:
    def __init__(self, credentials_dir="google_credentials"):
        self.credentials_dir = Path(credentials_dir)
        self.credentials_dir.mkdir(exist_ok=True)
        self.browser = None
        self.page = None
        self.playwright = None
        self.accounts_db = self.credentials_dir / "accounts_db.json"
        self.load_accounts_db()
    
    def load_accounts_db(self):
        if self.accounts_db.exists():
            with open(self.accounts_db, 'r', encoding='utf-8') as f:
                self.db = json.load(f)
        else:
            self.db = {}
    
    def save_accounts_db(self):
        with open(self.accounts_db, 'w', encoding='utf-8') as f:
            json.dump(self.db, f, indent=2)
    
    def check_account_exists(self, email):
        if email in self.db:
            client_secret_file = self.credentials_dir / self.db[email].get('client_secret_file', '')
            if client_secret_file and client_secret_file.exists():
                print(f"[✓] Account {email} already configured")
                return True
        return False
    
    def setup_browser(self):
        """Запуск браузера через Playwright"""
        try:
            print("[PLAYWRIGHT] Starting...")
            from playwright.sync_api import sync_playwright
            playwright = sync_playwright().start()
            print("[PLAYWRIGHT] Launching browser...")
            self.browser = playwright.chromium.launch(headless=False, slow_mo=500)
            self.page = self.browser.new_page()
            self.playwright = playwright  # Сохраняем ссылку
            print("[DRIVER] Browser started")
        except Exception as e:
            print(f"[PLAYWRIGHT ERROR] {str(e)}")
            raise
    
    def close_browser(self):
        if self.browser:
            try:
                self.browser.close()
            except:
                pass
        if hasattr(self, 'playwright') and self.playwright:
            try:
                self.playwright.stop()
            except:
                pass
        print("[DRIVER] Browser closed")
    
    def login_google(self, email, password, recovery_email=""):
        """Вход в Google аккаунт через Playwright"""
        try:
            print(f"[LOGIN] Logging in as {email}")
            self.page.goto('https://accounts.google.com/signin')
            self.page.wait_for_load_state('networkidle')
            time.sleep(2)
            
            # Ввод email
            email_input = self.page.wait_for_selector('input[type="email"]', timeout=10000)
            email_input.fill(email)
            time.sleep(1)
            
            # Нажимаем "Далее"
            self.page.keyboard.press('Enter')
            time.sleep(3)
            
            # Ввод пароля
            password_input = self.page.wait_for_selector('input[type="password"]', timeout=10000)
            password_input.fill(password)
            time.sleep(1)
            
            self.page.keyboard.press('Enter')
            time.sleep(5)
            
            # Проверяем запрос резервного email
            if recovery_email:
                try:
                    time.sleep(2)
                    recovery_input = self.page.query_selector('input[type="email"]')
                    if recovery_input and recovery_input.is_visible():
                        print(f"[LOGIN] Recovery email requested, entering: {recovery_email}")
                        recovery_input.fill(recovery_email)
                        time.sleep(1)
                        self.page.keyboard.press('Enter')
                        time.sleep(3)
                except Exception as e:
                    print(f"[LOGIN] Recovery email not needed or error: {e}")
            
            print(f"[LOGIN] Logged in successfully")
            return True
            
        except Exception as e:
            print(f"[LOGIN] Error: {str(e)}")
            return False
    
    def create_project(self, email):
        """Создание Google Cloud проекта"""
        try:
            print(f"[PROJECT] Creating project for {email}")
            self.page.goto('https://console.cloud.google.com/projectcreate')
            self.page.wait_for_load_state('networkidle')
            time.sleep(5)
            
            project_name = f"videobot-{email.split('@')[0]}-{int(time.time())}"
            
            name_input = self.page.wait_for_selector('input[name="name"]', timeout=10000)
            name_input.fill(project_name)
            time.sleep(1)
            
            # Нажимаем "Create"
            create_buttons = self.page.query_all('button')
            for btn in create_buttons:
                if 'create' in btn.text_content().lower():
                    btn.click()
                    break
            
            self.page.wait_for_load_state('networkidle')
            time.sleep(10)
            print(f"[PROJECT] Project created: {project_name}")
            return project_name
            
        except Exception as e:
            print(f"[PROJECT] Error: {str(e)}")
            return None
    
    def enable_youtube_api(self):
        """Включение YouTube Data API"""
        try:
            print(f"[API] Enabling YouTube Data API")
            self.page.goto('https://console.cloud.google.com/apis/library/youtube.googleapis.com')
            self.page.wait_for_load_state('networkidle')
            time.sleep(5)
            
            # Кнопка Enable
            enable_buttons = self.page.query_all('button')
            for btn in enable_buttons:
                btn_text = btn.text_content().lower()
                if 'enable' in btn_text:
                    btn.click()
                    break
            
            self.page.wait_for_load_state('networkidle')
            time.sleep(5)
            print(f"[API] YouTube API enabled")
            return True
            
        except Exception as e:
            print(f"[API] Error: {str(e)}")
            return False
    
    def create_oauth_credentials(self, email):
        """Создание OAuth credentials"""
        try:
            print(f"[OAUTH] Creating OAuth credentials")
            self.page.goto('https://console.cloud.google.com/apis/credentials/consent')
            self.page.wait_for_load_state('networkidle')
            time.sleep(5)
            
            # External
            external_radio = self.page.query_selector('input[type="radio"]')
            if external_radio:
                external_radio.check()
                time.sleep(1)
            
            create_buttons = self.page.query_all('button')
            for btn in create_buttons:
                if 'create' in btn.text_content().lower():
                    btn.click()
                    break
            
            time.sleep(3)
            
            # Заполняем форму
            inputs = self.page.query_selector_all('input')
            for inp in inputs[:3]:
                try:
                    if inp.is_visible():
                        inp.fill(f"VideoBot-{email.split('@')[0]}")
                except:
                    continue
            
            # Save and Continue
            for _ in range(3):
                time.sleep(2)
                buttons = self.page.query_all('button')
                for btn in buttons:
                    btn_text = btn.text_content().lower()
                    if 'save' in btn_text or 'continue' in btn_text:
                        btn.click()
                        break
            
            # Добавляем test user
            time.sleep(2)
            buttons = self.page.query_all('button')
            for btn in buttons:
                if 'add' in btn.text_content().lower():
                    btn.click()
                    time.sleep(1)
                    break
            
            # Вводим email
            inputs = self.page.query_selector_all('input')
            for inp in inputs:
                if inp.is_visible():
                    inp.fill(email)
                    break
            
            # Save
            time.sleep(1)
            buttons = self.page.query_all('button')
            for btn in buttons:
                if 'save' in btn.text_content().lower():
                    btn.click()
                    break
            
            time.sleep(3)
            
            # Создаём OAuth client ID
            self.page.goto('https://console.cloud.google.com/apis/credentials')
            self.page.wait_for_load_state('networkidle')
            time.sleep(5)
            
            # Create Credentials
            create_btn = self.page.wait_for_selector('button:has-text("CREATE CREDENTIALS")', timeout=10000)
            create_btn.click()
            time.sleep(2)
            
            # OAuth client ID
            oauth_link = self.page.query_selector('text=OAuth client ID')
            if oauth_link:
                oauth_link.click()
                time.sleep(3)
            
            # Desktop app
            selects = self.page.query_selector_all('select, mat-select')
            for sel in selects:
                if sel.is_visible():
                    sel.select_option('desktop')
                    break
            
            # Name
            time.sleep(1)
            inputs = self.page.query_selector_all('input')
            for inp in inputs:
                if inp.is_visible() and inp.get_attribute('type') == 'text':
                    inp.fill(f"VideoBot-{email.split('@')[0]}")
                    break
            
            # Create
            time.sleep(1)
            buttons = self.page.query_all('button')
            for btn in buttons:
                if 'create' in btn.text_content().lower():
                    btn.click()
                    break
            
            time.sleep(5)
            
            # Download JSON
            download_buttons = self.page.query_all('button')
            for btn in download_buttons:
                btn_text = btn.text_content().lower()
                if 'download' in btn_text:
                    btn.click()
                    break
            
            time.sleep(3)
            print(f"[OAUTH] OAuth credentials created")
            return True
            
        except Exception as e:
            print(f"[OAUTH] Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def process_account(self, email, password, recovery_email=""):
        """Полная обработка одного аккаунта"""
        try:
            print(f"\n=== Processing: {email} ===")
            
            if self.check_account_exists(email):
                print(f"[SKIP] {email} already configured")
                return True
            
            # Запускаем браузер
            print(f"[START] Launching browser for {email}")
            self.setup_browser()
            
            # Логин
            print(f"[LOGIN] Starting login process")
            login_result = self.login_google(email, password, recovery_email)
            
            if not login_result:
                print(f"[ERROR] Login failed for {email}")
                self.close_browser()
                return False
            
            # Создание проекта
            print(f"[PROJECT] Creating project")
            project_id = self.create_project(email)
            if not project_id:
                self.close_browser()
                return False
            
            # Включение API
            print(f"[API] Enabling YouTube API")
            if not self.enable_youtube_api():
                self.close_browser()
                return False
            
            # Создание OAuth
            print(f"[OAUTH] Creating credentials")
            if not self.create_oauth_credentials(email):
                self.close_browser()
                return False
            
            # Сохраняем в БД
            self.db[email] = {
                'project_id': project_id,
                'client_secret_file': f"client_secret_{email.replace('@', '_').replace('.', '_')}.json",
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            self.save_accounts_db()
            
            self.close_browser()
            print(f"[SUCCESS] Account {email} configured!")
            return True
            
        except Exception as e:
            print(f"[EXCEPTION] {str(e)}")
            import traceback
            traceback.print_exc()
            try:
                self.close_browser()
            except:
                pass
            return False
    
    def process_accounts(self, accounts):
        """Обработка списка аккаунтов"""
        success_count = 0
        for email, password, recovery in accounts:
            if self.process_account(email, password, recovery):
                success_count += 1
            time.sleep(5)
        
        print(f"\n{'='*60}")
        print(f"Completed: {success_count}/{len(accounts)} accounts configured")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    accounts = [
        ("email1@gmail.com", "password1", "recovery1@gmail.com"),
    ]
    
    automation = GoogleCloudAutomation()
    automation.process_accounts(accounts)