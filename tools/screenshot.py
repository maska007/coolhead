"""Screenshot every tab of the running CoolHead app, to check how it looks.

Start the app first (streamlit run app.py), then:
    python tools/screenshot.py                                  # local app, light mode
    python tools/screenshot.py --scheme dark
    python tools/screenshot.py --url https://coolhead.streamlit.app/

Images go to screenshots/ (ignored by git). One-time setup: python -m playwright install chromium
"""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

TABS = ["Through the day", "Heat into the room", "Roof cross-section", "Data"]

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://localhost:8501")
parser.add_argument("--scheme", choices=["light", "dark"], default="light")
parser.add_argument("--out", default="screenshots")
args = parser.parse_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, color_scheme=args.scheme)
    page.goto(args.url, wait_until="domcontentloaded", timeout=90000)
    # on Streamlit Cloud the app runs inside a frame; locally it is the page itself
    page.wait_for_timeout(3000)
    app = next((f for f in page.frames if "/~/+/" in f.url), page.main_frame)
    app.get_by_text("Peak roof, bare").wait_for(timeout=120000)
    app.wait_for_timeout(2500)
    for i, tab in enumerate(TABS, start=1):
        app.get_by_role("tab", name=tab).click()
        app.wait_for_timeout(2000)
        page.screenshot(path=out / f"{args.scheme}_{i}_{tab.split()[0].lower()}.png", full_page=True)
    app.get_by_text("Model settings").click()
    app.wait_for_timeout(1000)
    app.locator('[data-testid="stSidebar"]').screenshot(path=out / f"{args.scheme}_sidebar_settings.png")
    page.set_viewport_size({"width": 400, "height": 900})
    app.get_by_role("tab", name=TABS[0]).click()
    app.wait_for_timeout(2000)
    page.screenshot(path=out / f"{args.scheme}_phone.png", full_page=True)
    errors = app.locator('[data-testid="stException"]').count()
    browser.close()

print(f"saved to {out}/ - errors shown on the page: {errors}")
