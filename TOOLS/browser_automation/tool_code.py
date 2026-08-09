import json
from playwright.sync_api import sync_playwright

def scrape_webpage(url: str) -> str:
    """Extracts body text from a webpage using Playwright."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000)
            text = page.inner_text("body")
            browser.close()
            return text[:4000]
    except Exception as e:
        return f"Browser Automation Error: {str(e)}"

def fill_web_form(url: str, form_data: str, submit_selector: str = None) -> str:
    """Fills out form elements on a webpage."""
    try:
        parsed_data = json.loads(form_data)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000)

            for selector, value in parsed_data.items():
                page.fill(selector, str(value))

            if submit_selector:
                page.click(submit_selector)
                page.wait_for_load_state("networkidle")

            body_preview = page.inner_text("body")[:1000]
            browser.close()
            return f"Form submitted successfully. Result preview:\n{body_preview}"
    except Exception as e:
        return f"Form Filling Error: {str(e)}"