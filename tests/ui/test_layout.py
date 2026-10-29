"""Read-only browser smoke tests for the equipment tracker UI.

Start the app separately, then run:
  python -m unittest discover -s tests/ui -v
Screenshots and layout diagnostics are written to test-results/ui/.
"""
import os
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = os.getenv("UI_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
USERNAME = os.getenv("UI_USERNAME", "")
PASSWORD = os.getenv("UI_PASSWORD", "")
OUT_DIR = Path(os.getenv("UI_ARTIFACTS_DIR", "test-results/ui"))

PAGES = [
    ("home", "/"),
    ("equipment", "/equipment/"),
    ("projects", "/projects"),
    ("employees", "/employees"),
    ("help", "/help"),
]
VIEWPORTS = [
    ("desktop", {"width": 1440, "height": 900}),
    ("tablet", {"width": 768, "height": 1024}),
    ("mobile", {"width": 390, "height": 844}),
]


class LayoutSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not USERNAME or not PASSWORD:
            raise unittest.SkipTest(
                "Set UI_USERNAME and UI_PASSWORD to an existing test account."
            )
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()
        cls.context = cls.browser.new_context()
        cls.page = cls.context.new_page()
        cls.page.set_default_timeout(10000)

        response = cls.page.goto(f"{BASE_URL}/", wait_until="networkidle")
        if response and response.status >= 500:
            raise RuntimeError(f"App returned HTTP {response.status} at {BASE_URL}/")
        if "/auth/login" in cls.page.url:
            cls.page.locator('input[name="username"]').fill(USERNAME)
            cls.page.locator('input[name="password"]').fill(PASSWORD)
            cls.page.locator('button[type="submit"], input[type="submit"]').first.click()
            cls.page.wait_for_load_state("networkidle")
        if "/auth/login" in cls.page.url:
            raise RuntimeError("Login failed. Check UI_USERNAME/UI_PASSWORD.")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "browser"):
            cls.browser.close()
        if hasattr(cls, "playwright"):
            cls.playwright.stop()

    def test_pages_render_at_desktop_tablet_and_mobile_sizes(self):
        problems = []
        for page_name, path in PAGES:
            for viewport_name, viewport in VIEWPORTS:
                with self.subTest(page=page_name, viewport=viewport_name):
                    self.page.set_viewport_size(viewport)
                    response = self.page.goto(f"{BASE_URL}{path}", wait_until="networkidle")
                    self.assertIsNotNone(response, f"No HTTP response for {path}")
                    self.assertLess(response.status, 500, f"HTTP {response.status} on {path}")
                    self.assertNotIn("/auth/login", self.page.url, f"Login expired at {path}")

                    safe_name = f"{page_name}_{viewport_name}"
                    self.page.screenshot(
                        path=str(OUT_DIR / f"{safe_name}.png"),
                        full_page=True,
                        animations="disabled",
                    )
                    layout = self.page.evaluate("""() => {
                      const doc = document.documentElement;
                      const vw = doc.clientWidth;
                      const overflow = doc.scrollWidth > vw + 2
                        ? {viewport: vw, document: doc.scrollWidth, extra: doc.scrollWidth - vw}
                        : null;
                      const visible = [...document.querySelectorAll(
                        'a, button, input, select, textarea, [role="button"]'
                      )].filter(el => {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 &&
                          s.visibility !== 'hidden' && s.display !== 'none';
                      });
                      const overlaps = [];
                      for (let i = 0; i < visible.length; i++) {
                        const a = visible[i], ra = a.getBoundingClientRect();
                        for (let j = i + 1; j < visible.length; j++) {
                          const b = visible[j], rb = b.getBoundingClientRect();
                          if (a.contains(b) || b.contains(a)) continue;
                          const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
                          const h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
                          if (w > 3 && h > 3) {
                            overlaps.push({
                              a: (a.innerText || a.getAttribute('aria-label') || a.name || a.tagName).trim().slice(0, 70),
                              b: (b.innerText || b.getAttribute('aria-label') || b.name || b.tagName).trim().slice(0, 70),
                              area: Math.round(w * h)
                            });
                          }
                        }
                      }
                      return {overflow, overlaps: overlaps.slice(0, 20)};
                    }""")
                    if layout["overflow"]:
                        problems.append(
                            f"{safe_name}: horizontal overflow {layout['overflow']}"
                        )
                    if layout["overlaps"]:
                        problems.append(
                            f"{safe_name}: possible clickable-element overlaps "
                            f"{layout['overlaps']}"
                        )

        report = OUT_DIR / "layout-report.txt"
        report.write_text(
            "UI layout smoke-test report\n"
            f"Base URL: {BASE_URL}\n"
            "Screenshots: one per page and viewport in this folder.\n\n"
            + ("\n".join(problems) if problems else
               "No horizontal overflow or likely interactive overlaps detected."),
            encoding="utf-8",
        )
        self.assertFalse(
            any("horizontal overflow" in p for p in problems),
            "Horizontal overflow detected; inspect test-results/ui/layout-report.txt",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
