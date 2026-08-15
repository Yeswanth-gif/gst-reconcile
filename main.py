import os
import time
import glob
import traceback
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# -------------------------------------------------------------
# 0. Custom Logger
# -------------------------------------------------------------
def log(level, message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = {
        "INFO": f"[{timestamp}] ℹ️  [INFO]",
        "SUCCESS": f"[{timestamp}] ✅ [SUCCESS]",
        "WARN": f"[{timestamp}] ⚠️  [WARN]",
        "ERROR": f"[{timestamp}] ❌ [ERROR]",
        "DEBUG": f"[{timestamp}] 🔍 [DEBUG]"
    }.get(level, f"[{timestamp}] [{level}]")
    print(f"{prefix} {message}")

# -------------------------------------------------------------
# 1. Inputs & Setup
# -------------------------------------------------------------
fy_input = input("Enter Financial Years separated by comma (e.g., 2023-24, 2024-25): ").strip()
target_fys = [fy.strip() for fy in fy_input.split(",") if fy.strip()]

# Hardcoded return types to process automatically
return_types = ["GSTR-1", "GSTR-3B"]

DOWNLOAD_DIR = os.path.abspath("./gst_returns_output")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
log("INFO", f"Download directory: {DOWNLOAD_DIR}")
log("INFO", f"Target Financial Years: {target_fys}")
log("INFO", f"Target Return Types: {return_types}")

chrome_options = webdriver.ChromeOptions()
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)

prefs = {
    "download.default_directory": DOWNLOAD_DIR,
    "download.prompt_for_download": False,
    "plugins.always_open_pdf_externally": True
}
chrome_options.add_experimental_option("prefs", prefs)

log("INFO", "Initializing Chrome WebDriver...")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
wait = WebDriverWait(driver, 15)

driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
})

# -------------------------------------------------------------
# 2. Locators & Helper Functions
# -------------------------------------------------------------
FY_LOCATORS = [(By.ID, "fin"), (By.NAME, "fin"), (By.XPATH, "//select[contains(@name,'fin') or contains(@id,'fin')]")]
QUARTER_LOCATORS = [(By.ID, "quarter"), (By.NAME, "quarter"), (By.XPATH, "//select[contains(@name,'quarter') or contains(@id,'quarter')]")]
MONTH_LOCATORS = [(By.ID, "mon"), (By.NAME, "mon"), (By.XPATH, "//select[contains(@name,'mon') or contains(@id,'mon')]")]

def wait_for_dimmer():
    """Waits for GST portal loading spinners / dimmer overlays to disappear."""
    try:
        WebDriverWait(driver, 10).until(
            EC.invisibility_of_element_located((By.CLASS_NAME, "dimmer-holder"))
        )
    except Exception:
        pass
    time.sleep(1)

def rename_latest_download(expected_name):
    """Waits for download completion and renames the file."""
    log("INFO", "Waiting for file download to complete...")
    time.sleep(2)
    while glob.glob(os.path.join(DOWNLOAD_DIR, "*.crdownload")):
        time.sleep(1)

    files = glob.glob(os.path.join(DOWNLOAD_DIR, "*.pdf"))
    if files:
        latest_file = max(files, key=os.path.getctime)
        new_filepath = os.path.join(DOWNLOAD_DIR, expected_name)
        if os.path.exists(new_filepath):
            os.remove(new_filepath)
        os.rename(latest_file, new_filepath)
        log("SUCCESS", f"Saved: {expected_name}")
    else:
        log("ERROR", "No PDF file found after download attempt.")

def safe_click(element):
    """Scrolls element into center view and clicks, falling back to JavaScript click if intercepted."""
    wait_for_dimmer()
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(0.5)
    try:
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)

def click_button_by_visible_text(target_text_substring, timeout=6):
    """Scans all visible <button>, <a>, and <input> elements in Python directly."""
    wait_for_dimmer()
    start_time = time.time()
    while time.time() - start_time < timeout:
        elements = driver.find_elements(By.TAG_NAME, "button") + driver.find_elements(By.TAG_NAME, "a") + driver.find_elements(By.XPATH, "//input[@type='button' or @type='submit']")
        for elem in elements:
            try:
                if elem.is_displayed():
                    label = elem.text.strip() if elem.tag_name in ["button", "a"] else elem.get_attribute("value").strip()
                    if target_text_substring.upper() in label.upper():
                        log("INFO", f"Found matching element: '{label}', clicking...")
                        safe_click(elem)
                        return True
            except Exception:
                continue
        time.sleep(0.5)
    return False

def select_dropdown_native_click(possible_locators, target_text, name_for_log):
    """Clicks dropdown and option elements safely to trigger Angular change events."""
    wait_for_dimmer()
    log("INFO", f"Locating '{name_for_log}' dropdown...")
    select_elem = None
    for loc_type, loc_val in possible_locators:
        try:
            elem = driver.find_element(loc_type, loc_val)
            if elem.is_displayed():
                select_elem = elem
                break
        except Exception:
            continue

    if not select_elem:
        log("ERROR", f"Could not find DOM element for '{name_for_log}' dropdown.")
        return False

    safe_click(select_elem)
    time.sleep(0.5)

    options = select_elem.find_elements(By.TAG_NAME, "option")
    available_texts = [opt.text.strip() for opt in options if opt.text.strip()]
    log("DEBUG", f"'{name_for_log}' options: {available_texts}")

    for option in options:
        opt_text = option.text.strip()
        if target_text.lower() in opt_text.lower():
            safe_click(option)
            driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", select_elem)
            driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", select_elem)
            log("SUCCESS", f"Selected '{opt_text}' in '{name_for_log}'")
            return True

    log("ERROR", f"Target value '{target_text}' not found in '{name_for_log}'.")
    return False

def navigate_back_twice():
    """Clicks the portal BACK / DASHBOARD buttons twice to return to main search page."""
    wait_for_dimmer()
    log("INFO", "Navigating back (Step 1/2)...")
    if not click_button_by_visible_text("BACK", timeout=4):
        log("WARN", "Step 1 BACK button not found, checking for DASHBOARD link...")
        click_button_by_visible_text("RETURN DASHBOARD", timeout=3)
    time.sleep(2)

    wait_for_dimmer()
    log("INFO", "Navigating back (Step 2/2)...")
    if not click_button_by_visible_text("BACK", timeout=4):
        log("WARN", "Step 2 BACK button not found, checking for RETURN DASHBOARD button...")
        click_button_by_visible_text("RETURN DASHBOARD", timeout=3)
    time.sleep(2)

def ensure_on_dashboard():
    """Verifies search controls are present without using hard driver.get URL calls."""
    wait_for_dimmer()
    for loc_type, loc_val in FY_LOCATORS:
        try:
            elem = driver.find_element(loc_type, loc_val)
            if elem.is_displayed():
                return
        except Exception:
            continue

    log("WARN", "Search dropdowns not visible on current screen. Attempting UI click recovery...")
    if click_button_by_visible_text("RETURN DASHBOARD", timeout=4):
        time.sleep(3)
        return

    print("\n" + "!"*70)
    print("👉 ACTION REQUIRED: Please click 'RETURN DASHBOARD' manually in Chrome.")
    input("👉 Press ENTER here once the Financial Year dropdown is visible again...")
    print("!"*70 + "\n")

# -------------------------------------------------------------
# 3. Execution Flow
# -------------------------------------------------------------
try:
    log("INFO", "Opening GST Login page...")
    driver.get("https://services.gst.gov.in/services/login")
    
    print("\n👉 Step 1: Log in manually in Chrome.")
    print("👉 Step 2: Click 'RETURN DASHBOARD' inside Chrome.")
    input("\n👉 Step 3: Press ENTER in this terminal ONLY after search controls are visible...")

    for target_fy in target_fys:
        start_year_short = target_fy.split("-")[0][-2:]
        end_year_short = target_fy.split("-")[1]

        months_schedule = [
            {"quarter": "Quarter 1", "month": "April", "year_yy": start_year_short},
            {"quarter": "Quarter 1", "month": "May", "year_yy": start_year_short},
            {"quarter": "Quarter 1", "month": "June", "year_yy": start_year_short},
            {"quarter": "Quarter 2", "month": "July", "year_yy": start_year_short},
            {"quarter": "Quarter 2", "month": "August", "year_yy": start_year_short},
            {"quarter": "Quarter 2", "month": "September", "year_yy": start_year_short},
            {"quarter": "Quarter 3", "month": "October", "year_yy": start_year_short},
            {"quarter": "Quarter 3", "month": "November", "year_yy": start_year_short},
            {"quarter": "Quarter 3", "month": "December", "year_yy": start_year_short},
            {"quarter": "Quarter 4", "month": "January", "year_yy": end_year_short},
            {"quarter": "Quarter 4", "month": "February", "year_yy": end_year_short},
            {"quarter": "Quarter 4", "month": "March", "year_yy": end_year_short},
        ]

        for return_type in return_types:
            clean_return_prefix = return_type.lower().replace("-", "").replace(" ", "")

            for item in months_schedule:
                month_name = item["month"]
                quarter = item["quarter"]
                year_yy = item["year_yy"]
                
                print("\n" + "="*70)
                log("INFO", f"STARTING: {target_fy} | {return_type} | {month_name}")
                
                ensure_on_dashboard()

                try:
                    # Step A: Select Financial Year
                    if not select_dropdown_native_click(FY_LOCATORS, target_fy, "Financial Year"):
                        continue
                    time.sleep(2)
                    
                    # Step B: Select Quarter
                    if not select_dropdown_native_click(QUARTER_LOCATORS, quarter, "Quarter"):
                        continue
                    time.sleep(2)
                    
                    # Step C: Select Month
                    if not select_dropdown_native_click(MONTH_LOCATORS, month_name, "Month/Period"):
                        continue
                    time.sleep(1)

                    # Step D: Click SEARCH
                    log("INFO", "Clicking 'SEARCH' button...")
                    if not click_button_by_visible_text("SEARCH"):
                        log("ERROR", "Failed to click SEARCH button.")
                        continue
                    time.sleep(3)

                    # Step E: Click VIEW on return card
                    log("INFO", f"Clicking 'VIEW' on {return_type.upper()} card...")
                    view_xpath = f"//div[contains(translate(., 'gstr', 'GSTR'), '{return_type.upper()}')]//button[contains(translate(text(),'view','VIEW'),'VIEW')]"
                    view_btn = wait.until(EC.presence_of_element_located((By.XPATH, view_xpath)))
                    safe_click(view_btn)
                    time.sleep(3)

                    # Step F: Click VIEW SUMMARY (if present)
                    log("INFO", "Locating and clicking 'VIEW SUMMARY' button...")
                    if click_button_by_visible_text("VIEW SUMMARY"):
                        log("SUCCESS", "Clicked 'VIEW SUMMARY' button.")
                        time.sleep(3)
                    else:
                        log("WARN", "'VIEW SUMMARY' button not found. Checking directly for 'DOWNLOAD PDF'...")

                    # Step G: Click DOWNLOAD PDF / FILED RETURN
                    log("INFO", "Locating and clicking 'DOWNLOAD PDF' button...")
                    if click_button_by_visible_text("DOWNLOAD PDF") or click_button_by_visible_text("DOWNLOAD"):
                        log("SUCCESS", "Clicked 'DOWNLOAD PDF' button.")
                        formatted_filename = f"{clean_return_prefix}_{month_name.lower()}_{year_yy}.pdf"
                        rename_latest_download(formatted_filename)
                    else:
                        log("ERROR", f"Could not find Download button for {return_type} ({month_name}).")

                    # Step H: Click BACK twice to safely return to search dashboard
                    navigate_back_twice()

                except Exception as e:
                    log("ERROR", f"Error during {return_type} ({month_name}): {type(e).__name__} - {e}")
                    log("DEBUG", traceback.format_exc())
                    navigate_back_twice()

finally:
    log("INFO", "Process completed. Check 'gst_returns_output' folder.")