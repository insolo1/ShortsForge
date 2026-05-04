import subprocess
import sys
import os
import json
from pathlib import Path

def run_automation_process(accounts_data, credentials_dir):
    """Запуск автоматизации в отдельном процессе"""
    from playwright.sync_api import sync_playwright
    import time
    from datetime import datetime
    
    credentials_dir = Path(credentials_dir)
    accounts_db = credentials_dir / "accounts_db.json"
    
    # Загружаем БД
    if accounts_db.exists():
        with open(accounts_db, 'r', encoding='utf-8') as f:
            db = json.load(f)
    else:
        db = {}
    
    def save_db():
        with open(accounts_db, 'w', encoding='utf-8') as f:
            json.dump(db, f, indent=2)
    
    playwright = sync_playwright().start()
    # Используем headless с специальными настройками для обхода защиты
    browser = playwright.chromium.launch(
        headless=False,  # Показываем браузер
        slow_mo=300,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--disable-infobars',
            '--disable-dev-tools',
            '--no-first-run',
            '--no-default-browser-check',
            '--window-size=1920,1080'
        ]
    )
    page = browser.new_page(
        viewport={'width': 1920, 'height': 1080},
        locale='ru-RU'
    )
    
    # Добавляем отпечатки нормального браузера
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru']});
    """)
    
    results = []
    
    for acc in accounts_data:
        email = acc['email']
        password = acc['password']
        recovery = acc.get('recovery', '')
        
        print(f"=== Processing {email} ===")
        
        if email in db:
            print(f"[SKIP] Already configured")
            results.append({'email': email, 'status': 'skipped'})
            continue
        
        try:
            # Используем более надежный метод - JavaScript
            login_url = 'https://accounts.google.com/signin/v2/identifier?flowName=GlifWebSignIn&rc=1'
            
            print(f"[LOGIN] Opening login page...")
            page.goto(login_url, timeout=120000)
            page.wait_for_selector('body', timeout=60000)
            time.sleep(5)
            
            print(f"[LOGIN] Entering email via JS...")
            # Через JavaScript
            page.evaluate(f'''
                document.querySelector('input[type="email"]').value = "{email}";
                document.querySelector('input[type="email"]').dispatchEvent(new Event('input', {{bubbles: true}}));
            ''')
            time.sleep(2)
            
            # Клик на кнопку
            page.keyboard.press('Enter')
            time.sleep(8)
            
            print(f"[LOGIN] Entering password...")
            # Password через JavaScript  
            page.evaluate(f'''
                document.querySelector('input[type="password"]').value = "{password}";
                document.querySelector('input[type="password"]').dispatchEvent(new Event('input', {{bubbles: true}}));
            ''')
            time.sleep(2)
            
            page.keyboard.press('Enter')
            time.sleep(10)
            
            print(f"[LOGIN] Done")
            
        except Exception as e:
            print(f"[LOGIN] Error: {e}")
            print(f"[LOGIN] Trying manual mode...")
            # Если автоматика не работает - просто открываем браузер и ждём
            page.goto('https://accounts.google.com')
            print(f"[LOGIN] Please login manually in the opened browser")
            print(f"[LOGIN] Waiting 60 seconds...")
            time.sleep(60)
            
            # Создание проекта
            page.goto('https://console.cloud.google.com/projectcreate')
            page.wait_for_load_state('networkidle')
            time.sleep(5)
            
            project_name = f"videobot-{email.split('@')[0]}-{int(time.time())}"
            name_input = page.wait_for_selector('input[name="name"]', timeout=10000)
            name_input.fill(project_name)
            
            # Create button
            buttons = page.query_all('button')
            for btn in buttons:
                if 'create' in btn.text_content().lower():
                    btn.click()
                    break
            
            page.wait_for_load_state('networkidle')
            time.sleep(10)
            print(f"[PROJECT] Created: {project_name}")
            
            # Включаем API
            page.goto('https://console.cloud.google.com/apis/library/youtube.googleapis.com')
            page.wait_for_load_state('networkidle')
            time.sleep(5)
            
            buttons = page.query_all('button')
            for btn in buttons:
                if 'enable' in btn.text_content().lower():
                    btn.click()
                    break
            
            page.wait_for_load_state('networkidle')
            time.sleep(5)
            print(f"[API] YouTube API enabled")
            
            # Создаем OAuth
            page.goto('https://console.cloud.google.com/apis/credentials')
            page.wait_for_load_state('networkidle')
            time.sleep(5)
            
            # Create Credentials
            create_btn = page.wait_for_selector('button:has-text("CREATE CREDENTIALS")', timeout=10000)
            create_btn.click()
            time.sleep(2)
            
            # OAuth client ID
            oauth_link = page.query_selector('text=OAuth client ID')
            if oauth_link:
                oauth_link.click()
                time.sleep(3)
            
            # Desktop app
            selects = page.query_selector_all('select, mat-select')
            for sel in selects:
                if sel.is_visible():
                    sel.select_option('desktop')
                    break
            
            time.sleep(1)
            
            # Name
            inputs = page.query_selector_all('input')
            for inp in inputs:
                if inp.is_visible() and inp.get_attribute('type') == 'text':
                    inp.fill(f"VideoBot-{email.split('@')[0]}")
                    break
            
            # Create
            time.sleep(1)
            buttons = page.query_selector_all('button')
            for btn in buttons:
                if 'create' in btn.text_content().lower():
                    btn.click()
                    break
            
            time.sleep(5)
            
            # Download
            buttons = page.query_selector_all('button')
            for btn in buttons:
                if 'download' in btn.text_content().lower():
                    btn.click()
                    break
            
            time.sleep(3)
            print(f"[OAUTH] Credentials created")
            
            # Сохраняем
            db[email] = {
                'project_id': project_name,
                'client_secret_file': f"client_secret_{email.replace('@', '_').replace('.', '_')}.json",
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            save_db()
            
            results.append({'email': email, 'status': 'success'})
            print(f"[SUCCESS] {email}")
            
        except Exception as e:
            print(f"[ERROR] {email}: {e}")
            results.append({'email': email, 'status': 'error', 'message': str(e)})
        
        time.sleep(3)
    
    browser.close()
    playwright.stop()
    
    print(f"\n=== COMPLETE ===")
    for r in results:
        print(f"{r['email']}: {r['status']}")


if __name__ == "__main__":
    # Читаем accounts из файла
    with open('automation_accounts.json', 'r') as f:
        accounts = json.load(f)
    
    creds_dir = 'google_credentials'
    
    run_automation_process(accounts, creds_dir)