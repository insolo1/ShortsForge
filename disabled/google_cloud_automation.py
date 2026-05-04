import os
import time
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import undetected_chromedriver as uc


class GoogleCloudAutomation:
    def __init__(self, credentials_dir="google_credentials"):
        self.credentials_dir = Path(credentials_dir)
        self.credentials_dir.mkdir(exist_ok=True)
        self.driver = None
        self.accounts_db = self.credentials_dir / "accounts_db.json"
        self.load_accounts_db()
    
    def load_accounts_db(self):
        """Загрузка базы данных аккаунтов"""
        if self.accounts_db.exists():
            with open(self.accounts_db, 'r', encoding='utf-8') as f:
                self.db = json.load(f)
        else:
            self.db = {}
    
    def save_accounts_db(self):
        """Сохранение базы данных аккаунтов"""
        with open(self.accounts_db, 'w', encoding='utf-8') as f:
            json.dump(self.db, f, indent=2)
    
    def check_account_exists(self, email):
        """Проверка есть ли уже настроенный проект для аккаунта"""
        if email in self.db:
            client_secret_file = self.credentials_dir / self.db[email]['client_secret_file']
            if client_secret_file.exists():
                print(f"[✓] Account {email} already configured")
                return True
        return False
    
    def setup_driver(self):
        """Настройка браузера"""
        options = uc.ChromeOptions()
        options.add_argument('--start-maximized')
        options.add_argument('--disable-blink-features=AutomationControlled')
        
        self.driver = uc.Chrome(options=options, use_subprocess=True, version_main=147)
        print("[DRIVER] Browser started")
    
    def login_google(self, email, password, recovery_email=""):
        """Вход в Google аккаунт"""
        try:
            print(f"[LOGIN] Logging in as {email}")
            self.driver.get('https://accounts.google.com/signin')
            time.sleep(3)
            
            # Ввод email
            email_input = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email']"))
            )
            email_input.send_keys(email)
            time.sleep(1)
            
            # Нажимаем "Далее"
            next_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
            for btn in next_buttons:
                if btn.is_displayed():
                    btn.click()
                    break
            
            time.sleep(3)
            
            # Ввод пароля
            password_input = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
            )
            password_input.send_keys(password)
            time.sleep(1)
            
            # Нажимаем "Далее"
            next_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
            for btn in next_buttons:
                if btn.is_displayed():
                    btn.click()
                    break
            
            time.sleep(5)
            
            # Проверяем запрос резервного email
            if recovery_email:
                try:
                    time.sleep(2)
                    recovery_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='email']")
                    if recovery_inputs:
                        print(f"[LOGIN] Recovery email requested, entering: {recovery_email}")
                        recovery_inputs[0].send_keys(recovery_email)
                        time.sleep(1)
                        
                        # Нажимаем "Далее"
                        next_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
                        for btn in next_buttons:
                            if btn.is_displayed():
                                btn.click()
                                break
                        
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
            
            # Переход в Google Cloud Console
            self.driver.get('https://console.cloud.google.com/projectcreate')
            time.sleep(5)
            
            # Название проекта
            project_name = f"videobot-{email.split('@')[0]}"
            project_id = f"{project_name}-{int(time.time())}"
            
            # Ввод названия
            name_input = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='name']"))
            )
            name_input.clear()
            name_input.send_keys(project_name)
            time.sleep(1)
            
            # Нажимаем "Create"
            create_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
            for btn in create_buttons:
                try:
                    if 'create' in btn.text.lower():
                        btn.click()
                        break
                except:
                    continue
            
            time.sleep(10)
            print(f"[PROJECT] Project created: {project_id}")
            return project_id
            
        except Exception as e:
            print(f"[PROJECT] Error: {str(e)}")
            return None
    
    def enable_youtube_api(self):
        """Включение YouTube Data API v3"""
        try:
            print(f"[API] Enabling YouTube Data API v3")
            
            self.driver.get('https://console.cloud.google.com/apis/library/youtube.googleapis.com')
            time.sleep(5)
            
            # Нажимаем "Enable"
            enable_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
            for btn in enable_buttons:
                try:
                    if 'enable' in btn.text.lower():
                        btn.click()
                        break
                except:
                    continue
            
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
            
            # Настройка OAuth consent screen
            self.driver.get('https://console.cloud.google.com/apis/credentials/consent')
            time.sleep(5)
            
            # Выбираем External
            external_radio = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            if external_radio:
                external_radio[0].click()
                time.sleep(1)
            
            # Нажимаем Create
            create_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
            for btn in create_buttons:
                try:
                    if 'create' in btn.text.lower():
                        btn.click()
                        break
                except:
                    continue
            
            time.sleep(3)
            
            # Заполняем форму
            app_name_input = self.driver.find_elements(By.CSS_SELECTOR, "input")
            if app_name_input:
                app_name_input[0].send_keys(f"VideoBot-{email.split('@')[0]}")
            
            # Email
            email_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='email']")
            for inp in email_inputs:
                try:
                    if inp.is_displayed():
                        inp.send_keys(email)
                except:
                    continue
            
            # Save and Continue
            time.sleep(2)
            save_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
            for btn in save_buttons:
                try:
                    if 'save' in btn.text.lower() or 'continue' in btn.text.lower():
                        btn.click()
                        time.sleep(2)
                        break
                except:
                    continue
            
            # Пропускаем Scopes
            for _ in range(2):
                save_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
                for btn in save_buttons:
                    try:
                        if 'save' in btn.text.lower() or 'continue' in btn.text.lower():
                            btn.click()
                            time.sleep(2)
                            break
                    except:
                        continue
            
            # Добавляем test user
            add_user_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
            for btn in add_user_buttons:
                try:
                    if 'add' in btn.text.lower():
                        btn.click()
                        time.sleep(1)
                        break
                except:
                    continue
            
            # Вводим email
            email_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input")
            for inp in email_inputs:
                try:
                    if inp.is_displayed():
                        inp.send_keys(email)
                        time.sleep(1)
                        break
                except:
                    continue
            
            # Save
            save_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
            for btn in save_buttons:
                try:
                    if 'save' in btn.text.lower():
                        btn.click()
                        time.sleep(2)
                        break
                except:
                    continue
            
            # Создаём OAuth client ID
            self.driver.get('https://console.cloud.google.com/apis/credentials')
            time.sleep(5)
            
            # Create Credentials
            create_cred_button = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'CREATE CREDENTIALS')]"))
            )
            create_cred_button.click()
            time.sleep(2)
            
            # OAuth client ID
            oauth_option = self.driver.find_elements(By.XPATH, "//span[contains(., 'OAuth client ID')]")
            if oauth_option:
                oauth_option[0].click()
                time.sleep(3)
            
            # Application type: Desktop app
            app_type_select = self.driver.find_elements(By.CSS_SELECTOR, "select")
            if app_type_select:
                app_type_select[0].send_keys("Desktop app")
                time.sleep(1)
            
            # Name
            name_input = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
            if name_input:
                name_input[0].send_keys(f"VideoBot-{email.split('@')[0]}")
            
            # Create
            create_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
            for btn in create_buttons:
                try:
                    if 'create' in btn.text.lower():
                        btn.click()
                        break
                except:
                    continue
            
            time.sleep(5)
            
            # Download JSON
            download_buttons = self.driver.find_elements(By.XPATH, "//button[contains(., 'DOWNLOAD')]")
            if download_buttons:
                download_buttons[0].click()
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
            # Проверяем есть ли уже
            if self.check_account_exists(email):
                return True
            
            print(f"\n{'='*60}")
            print(f"Processing account: {email}")
            print(f"{'='*60}\n")
            
            # Логин
            if not self.login_google(email, password, recovery_email):
                return False
            
            # Создание проекта
            project_id = self.create_project(email)
            if not project_id:
                return False
            
            # Включение API
            if not self.enable_youtube_api():
                return False
            
            # Создание OAuth
            if not self.create_oauth_credentials(email):
                return False
            
            # Сохраняем в БД
            self.db[email] = {
                'project_id': project_id,
                'client_secret_file': f"client_secret_{email.replace('@', '_').replace('.', '_')}.json",
                'created_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            self.save_accounts_db()
            
            print(f"[✓] Account {email} configured successfully!")
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to process {email}: {str(e)}")
            return False
    
    def process_accounts(self, accounts):
        """Обработка списка аккаунтов"""
        self.setup_driver()
        
        success_count = 0
        for email, password in accounts:
            if self.process_account(email, password):
                success_count += 1
            time.sleep(5)  # Пауза между аккаунтами
        
        self.driver.quit()
        
        print(f"\n{'='*60}")
        print(f"Completed: {success_count}/{len(accounts)} accounts configured")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    # Пример использования
    accounts = [
        ("email1@gmail.com", "password1"),
        ("email2@gmail.com", "password2"),
        # ... добавь все 100 аккаунтов
    ]
    
    automation = GoogleCloudAutomation()
    automation.process_accounts(accounts)
