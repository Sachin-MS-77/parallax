"""Run in Ubuntu CI: capture the real locally served synthetic demonstration."""
import json
import platform
from pathlib import Path
from playwright.sync_api import sync_playwright

if platform.system() != "Linux":
    raise SystemExit("This evidence script requires an actual Linux runtime")

out = Path("artifacts/linux-demo")
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8877", wait_until="networkidle")
    page.locator("#alerts tr").first.wait_for()
    page.locator("#graph circle").first.wait_for()
    page.screenshot(path=str(out / "01-dashboard.png"))
    page.locator(".investigation").screenshot(path=str(out / "02-investigation.png"))
    page.locator('nav button[data-page="validation"]').click()
    page.locator("#validation table").wait_for()
    page.screenshot(path=str(out / "03-validation.png"))
    page.locator('nav button[data-page="sources"]').click()
    page.locator("#verify").click()
    page.get_by_role("status").filter(has_text="Integrity verified").wait_for()
    page.screenshot(path=str(out / "04-evidence.png"))
    metadata = {
        "system": platform.system(), "platform": platform.platform(),
        "python": platform.python_version(), "browser": browser.version,
        "scope": "Ubuntu CI, headless Chromium, synthetic demo; not a Linux desktop screenshot",
        "page_errors": errors,
    }
    (out / "environment.json").write_text(json.dumps(metadata, indent=2))
    browser.close()
    if errors:
        raise SystemExit("Browser errors found; inspect environment.json")
