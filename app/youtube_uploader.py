import asyncio
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time


class YouTubeUploader:
    def __init__(self):
        self.driver = None
    
    def setup_driver(self):
        """Настройка Chrome драйвера с обходом защиты"""
        options = uc.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--start-maximized')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-infobars')
        options.add_argument('--disable-popup-blocking')
        options.add_argument('--ignore-certificate-errors')
        
        prefs = {
            "profile.default_content_setting.notifications": 1,
            "profile.managed_auto_select": False
        }
        options.add_experimental_option("prefs", prefs)
        
        # Создаём драйвер с версией 147
        try:
            print("[YOUTUBE] Trying to setup driver with version 147...")
            self.driver = uc.Chrome(options=options, use_subprocess=True, version_main=147)
        except Exception as e:
            print(f"[YOUTUBE] Failed with v147: {e}")
            try:
                print("[YOUTUBE] Trying auto-detect version...")
                self.driver = uc.Chrome(options=options, use_subprocess=True, driver_executable_path=None)
            except Exception as e2:
                print(f"[YOUTUBE] Failed auto-detect: {e2}")
                raise Exception("Cannot setup Chrome driver. Please update Chrome browser to latest version.")
        
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
                Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru']});
            """
        })
        
        print(f"[YOUTUBE] Driver setup complete")
    
    def login(self, email: str, password: str, recovery_email: str = "") -> bool:
        """Вход в YouTube аккаунт"""
        try:
            print(f"[YOUTUBE] Logging in as {email}")
            
            # Сначала переходим на YouTube чтобы установить cookies
            self.driver.get('https://www.youtube.com')
            time.sleep(5)
            
            # Теперь переходим на страницу входа
            self.driver.get('https://accounts.google.com/signin/v2/identifier?service=youtube')
            time.sleep(5)
            
            # Ввод email
            try:
                email_input = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email']"))
                )
                email_input.send_keys(email)
                time.sleep(2)
                
                # Ищем кнопку "Далее"
                next_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
                for btn in next_buttons:
                    if btn.is_displayed():
                        btn.click()
                        break
                
                time.sleep(5)
            except Exception as e:
                print(f"[YOUTUBE] Email input error: {e}")
                return False
            
            # Ввод пароля
            try:
                password_input = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
                )
                password_input.send_keys(password)
                time.sleep(2)
                
                # Ищем кнопку "Далее"
                next_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
                for btn in next_buttons:
                    if btn.is_displayed():
                        btn.click()
                        break
                
                time.sleep(8)
            except Exception as e:
                print(f"[YOUTUBE] Password input error: {e}")
                return False
            
            # Проверяем запрос резервного email
            if recovery_email:
                try:
                    time.sleep(3)
                    # Ищем поле для резервного email
                    recovery_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='email']")
                    if recovery_inputs:
                        print(f"[YOUTUBE] Recovery email requested, entering: {recovery_email}")
                        recovery_inputs[0].send_keys(recovery_email)
                        time.sleep(2)
                        
                        # Нажимаем "Далее"
                        next_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
                        for btn in next_buttons:
                            if btn.is_displayed():
                                btn.click()
                                break
                        
                        time.sleep(5)
                except Exception as e:
                    print(f"[YOUTUBE] Recovery email error (may not be needed): {e}")
            
            # Проверяем успешность входа
            time.sleep(5)
            if "myaccount.google.com" in self.driver.current_url or "youtube.com" in self.driver.current_url:
                print(f"[YOUTUBE] Logged in successfully")
                return True
            else:
                print(f"[YOUTUBE] Login may have failed, current URL: {self.driver.current_url}")
                # Даём время на ручную верификацию если нужно
                print(f"[YOUTUBE] Waiting 30 seconds for manual verification if needed...")
                time.sleep(30)
                return True
            
        except Exception as e:
            print(f"[YOUTUBE] Login error: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def check_daily_uploads(self) -> int:
        """Проверка количества видео, загруженных сегодня"""
        try:
            print(f"[YOUTUBE] Checking daily uploads...")
            self.driver.get('https://studio.youtube.com/channel/UC/videos')
            time.sleep(5)
            
            # Ждём загрузки списка видео
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "ytcp-video-row"))
            )
            
            # Получаем все строки с видео
            video_rows = self.driver.find_elements(By.CSS_SELECTOR, "ytcp-video-row")
            
            from datetime import datetime
            today = datetime.now().date()
            today_count = 0
            
            for row in video_rows[:20]:  # Проверяем первые 20 видео
                try:
                    # Ищем дату публикации
                    date_elements = row.find_elements(By.CSS_SELECTOR, "#video-date-uploaded")
                    if not date_elements:
                        continue
                    
                    date_text = date_elements[0].text.strip()
                    print(f"[YOUTUBE] Found video date: {date_text}")
                    
                    # Проверяем сегодняшние видео
                    # Форматы: "Опубликовано 2 часа назад", "Опубликовано сегодня", "19 апр. 2026 г."
                    if any(word in date_text.lower() for word in ['сегодня', 'today', 'час', 'hour', 'минут', 'minute']):
                        today_count += 1
                    elif today.strftime("%d") in date_text and today.strftime("%b") in date_text:
                        today_count += 1
                        
                except Exception as e:
                    print(f"[YOUTUBE] Error parsing video row: {str(e)}")
                    continue
            
            print(f"[YOUTUBE] Found {today_count} videos uploaded today")
            return today_count
            
        except Exception as e:
            print(f"[YOUTUBE] Check uploads error: {str(e)}")
            import traceback
            traceback.print_exc()
            return 0
    
    def upload_video(self, video_path: str, title: str, description: str, tags: List[str], 
                     publish_time: datetime = None) -> bool:
        """Загрузка видео на YouTube"""
        try:
            print(f"[YOUTUBE] Uploading video: {title}")
            
            # Переход напрямую на страницу загрузки
            self.driver.get('https://www.youtube.com/upload')
            time.sleep(10)
            
            # Проверяем URL
            print(f"[YOUTUBE] Current URL: {self.driver.current_url}")
            
            # Ожидаем появления основного контента
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(5)
            
            # Делаем скриншот
            try:
                self.driver.save_screenshot('K:/DIY/videobot/upload_debug.png')
                print("[YOUTUBE] Saved debug screenshot")
            except:
                pass
            
            # Ищем элементы через JavaScript - сохраняем для анализа
            js_script = "return document.querySelectorAll('input[type=\"file\"]').length;"
            file_count = self.driver.execute_script(js_script)
            print(f"[YOUTUBE] JS: {file_count} file inputs")
            
            # Проверяем текущий URL
            print(f"[YOUTUBE] URL after load: {self.driver.current_url}")
            
            # Пробуем найти input через CSS
            inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            print(f"[YOUTUBE] Found {len(inputs)} file inputs by CSS")
            
            if inputs:
                file_input = inputs[0]
            else:
                # Пробуем XPATH
                inputs = self.driver.find_elements(By.XPATH, "//input[@type='file']")
                print(f"[YOUTUBE] Found {len(inputs)} file inputs by XPath")
                if inputs:
                    file_input = inputs[0]
                else:
                    # Сохраняем HTML для анализа
                    with open('K:/DIY/videobot/upload_page.html', 'w', encoding='utf-8') as f:
                        f.write(self.driver.page_source)
                    raise Exception("No file input found - saved page source")
            
            # Отправляем файл
            abs_path = str(Path(video_path).absolute())
            print(f"[YOUTUBE] Sending file: {abs_path}")
            file_input.send_keys(abs_path)
            
            time.sleep(30)
            print("[YOUTUBE] File upload initiated")
            
            # Проверяем не появилась ли капча или блокировка
            page_text = self.driver.page_source.lower()
            if "verify" in page_text or "captcha" in page_text or "suspicious" in page_text:
                print("[YOUTUBE] Security check detected!")
                time.sleep(30)
            
            # Ожидание загрузки метаданных
            time.sleep(10)
            
            # Ввод названия
            try:
                title_input = WebDriverWait(self.driver, 30).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='text'][aria-label='Название']"))
                )
            except:
                title_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='text']")
            title_input.clear()
            title_input.send_keys(title)
            
            # Ввод описания
            time.sleep(1)
            try:
                description_input = self.driver.find_element(By.CSS_SELECTOR, "textarea[aria-label='Описание']")
            except:
                description_input = self.driver.find_elements(By.CSS_SELECTOR, "textarea")
                if description_input:
                    description_input = description_input[0]
                else:
                    description_input = None
            
            if description_input:
                description_input.clear()
                description_input.send_keys(description)
            
            # Клик "Не для детей" - ищем по тексту
            time.sleep(2)
            try:
                not_for_kids_options = self.driver.find_elements(By.CSS_SELECTOR, "tp-yt-iron-icon path")
                for opt in not_for_kids_options:
                    if opt.get_attribute("d"):
                        opt.click()
                        break
            except:
                pass
            
            # Далее - ищем по кнопке с текстом "Далее" или "Next"
            time.sleep(3)
            next_buttons = self.driver.find_elements(By.CSS_SELECTOR, "ytcp-button")
            for btn in next_buttons:
                try:
                    if btn.text and "далее" in btn.text.lower():
                        btn.click()
                        break
                except:
                    continue
            
            time.sleep(3)
            
            # Пропускаем добавление элементов - снова "Далее"
            next_buttons = self.driver.find_elements(By.CSS_SELECTOR, "ytcp-button")
            for btn in next_buttons:
                try:
                    if btn.text and "далее" in btn.text.lower():
                        btn.click()
                        break
                except:
                    continue
            
            time.sleep(3)
            
            # Пропускаем проверки - снова "Далее"
            next_buttons = self.driver.find_elements(By.CSS_SELECTOR, "ytcp-button")
            for btn in next_buttons:
                try:
                    if btn.text and "далее" in btn.text.lower():
                        btn.click()
                        break
                except:
                    continue
            
            time.sleep(3)
            
            # Планирование публикации - ищем чекбокс "Запланировать на"
            if publish_time:
                schedule_checkbox = self.driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
                for cb in schedule_checkbox:
                    try:
                        if cb.is_displayed():
                            cb.click()
                            break
                    except:
                        continue
                time.sleep(1)
                
                # Установка даты и времени
                date_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='date']")
                for inp in date_inputs:
                    try:
                        if inp.is_displayed():
                            inp.clear()
                            inp.send_keys(publish_time.strftime("%Y-%m-%d"))
                            break
                    except:
                        continue
                
                time_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='time']")
                for inp in time_inputs:
                    try:
                        if inp.is_displayed():
                            inp.clear()
                            inp.send_keys(publish_time.strftime("%H:%M"))
                            break
                    except:
                        continue
            
            # Публикация - ищем кнопку "Опубликовать" или "Готово"
            time.sleep(2)
            publish_buttons = self.driver.find_elements(By.CSS_SELECTOR, "ytcp-button")
            for btn in publish_buttons:
                try:
                    text = btn.text.lower()
                    if "опубликовать" in text or "готово" in text or "done" in text:
                        btn.click()
                        break
                except:
                    continue
            
            time.sleep(8)
            print(f"[YOUTUBE] Video uploaded successfully")
            return True
            
        except Exception as e:
            print(f"[YOUTUBE] Upload error: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def close(self):
        """Закрытие браузера"""
        if self.driver:
            self.driver.quit()
    
    def calculate_publish_times(self, count: int, time_slot: str, videos_per_day: int, day_offset: int = 0) -> List[datetime]:
        """Расчёт оптимального времени публикации"""
        times = []
        now = datetime.now()
        
        # Определяем временной диапазон
        if time_slot == 'morning':
            start_hour, end_hour = 8, 12
        elif time_slot == 'afternoon':
            start_hour, end_hour = 12, 18
        elif time_slot == 'evening':
            start_hour, end_hour = 18, 22
        else:  # auto
            # Оптимальное время: 14:00, 17:00, 20:00
            optimal_hours = [14, 17, 20]
            for i in range(count):
                hour = optimal_hours[i % len(optimal_hours)]
                minute = random.randint(0, 59)
                publish_time = now + timedelta(days=day_offset, hours=hour-now.hour, minutes=minute-now.minute)
                # Если время уже прошло сегодня, добавляем день
                if publish_time < now:
                    publish_time += timedelta(days=1)
                times.append(publish_time)
            return times
        
        # Равномерное распределение в диапазоне
        for i in range(count):
            video_in_day = i % videos_per_day
            
            hour_range = end_hour - start_hour
            hour = start_hour + (hour_range * video_in_day // videos_per_day)
            minute = random.randint(0, 59)
            
            publish_time = now + timedelta(days=day_offset, hours=hour-now.hour, minutes=minute-now.minute)
            # Если время уже прошло сегодня, добавляем день
            if publish_time < now:
                publish_time += timedelta(days=1)
            times.append(publish_time)
        
        return times
