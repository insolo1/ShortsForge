from playwright.sync_api import sync_playwright
import time

print("Starting Playwright test...")

try:
    pw = sync_playwright().start()
    print("Playwright started")
    
    browser = pw.chromium.launch(headless=False, slow_mo=500)
    print("Browser launched!")
    
    page = browser.new_page()
    page.goto("https://google.com")
    print("Opened Google!")
    
    time.sleep(5)
    
    browser.close()
    pw.stop()
    print("Done!")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()