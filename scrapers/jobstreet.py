"""
JobStreet Singapore — Playwright-based scraper with optional login.
Handles email OTP by requesting the code from the user via Telegram.
"""

import hashlib
import os
import re
import sys
import importlib
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from .base import BaseScraper

BASE_URL = "https://www.jobstreet.com.sg"

# Selectors that indicate JobStreet is showing an OTP / verification page
_OTP_SIGNALS = [
    "input[name='otp']",
    "input[placeholder*='OTP']",
    "input[placeholder*='verification']",
    "input[placeholder*='code']",
    "input[aria-label*='OTP']",
    "input[aria-label*='verification']",
    "[data-testid='otp-input']",
    "input[type='tel'][maxlength='6']",
    "input[type='number'][maxlength='6']",
]

# The field we actually type the OTP into (first match wins)
_OTP_INPUT = ", ".join(_OTP_SIGNALS)

# Submit button after entering OTP
_OTP_SUBMIT = (
    "button[type='submit'], "
    "button:has-text('Verify'), "
    "button:has-text('Submit'), "
    "button:has-text('Confirm')"
)


def _notifier():
    """Lazy import to avoid circular dependency."""
    return importlib.import_module("notifier")


class JobStreetScraper(BaseScraper):
    name = "jobstreet"

    def __init__(self):
        self._email    = os.getenv("JOBSTREET_EMAIL", "")
        self._password = os.getenv("JOBSTREET_PASSWORD", "")
        self._headless = os.getenv("HEADLESS", "true").lower() == "true"

    def scrape(self, keywords: list[str], location: str, pages: int) -> list[dict]:
        jobs: list[dict] = []
        seen_ids: set[str] = set()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self._headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = ctx.new_page()

            if self._email and self._password:
                logged_in = self._login(page)
                if not logged_in:
                    print("[JobStreet] login failed — scraping as guest")
            else:
                print("[JobStreet] no credentials — scraping as guest")

            for keyword in keywords:
                for pg in range(1, pages + 1):
                    batch = self._scrape_page(page, keyword, location, pg)
                    if not batch:
                        break
                    for job in batch:
                        if job["id"] not in seen_ids:
                            seen_ids.add(job["id"])
                            jobs.append(job)
                    self._sleep(2.0, 4.0)

            browser.close()

        return jobs

    def _login(self, page) -> bool:
        """
        Attempt login. If JobStreet shows an OTP screen, request the code
        from the user via Telegram and enter it automatically.
        Returns True if fully logged in, False otherwise.
        """
        try:
            page.goto(f"{BASE_URL}/login", wait_until="networkidle", timeout=30000)
            page.fill('input[name="email"]', self._email)
            page.fill('input[name="password"]', self._password)
            page.click('button[type="submit"]')

            # Wait up to 15 s — either we land on the home feed OR an OTP page
            try:
                page.wait_for_selector(
                    f"{_OTP_INPUT}, [data-testid='home-feed'], nav[aria-label='main']",
                    timeout=15000,
                )
            except PWTimeout:
                # No OTP page AND no home feed detected — treat as logged in
                print("[JobStreet] logged in (no OTP required)")
                return True

            # Check which state we're in
            if self._is_otp_page(page):
                return self._handle_otp(page)

            print("[JobStreet] logged in (no OTP required)")
            return True

        except PWTimeout:
            print("[JobStreet] login timed out")
            return False
        except Exception as exc:
            print(f"[JobStreet] login error: {exc}")
            return False

    def _is_otp_page(self, page) -> bool:
        for sel in _OTP_SIGNALS:
            if page.query_selector(sel):
                return True
        url = page.url.lower()
        return any(kw in url for kw in ("otp", "verify", "mfa", "2fa", "auth"))

    def _handle_otp(self, page) -> bool:
        """Ask the user for the OTP via Telegram, enter it, submit."""
        print("[JobStreet] OTP page detected — requesting code via Telegram")

        otp = _notifier().wait_for_otp(platform="JobStreet", timeout=180)
        if not otp:
            print("[JobStreet] No OTP received — skipping login")
            return False

        try:
            # Fill the OTP field
            otp_field = page.wait_for_selector(_OTP_INPUT, timeout=5000)
            otp_field.click()
            otp_field.fill(otp)

            # Click the submit / verify button
            submit = page.query_selector(_OTP_SUBMIT)
            if submit:
                submit.click()
            else:
                otp_field.press("Enter")

            # Wait for the OTP page to go away
            page.wait_for_selector(
                f"nav[aria-label='main'], [data-testid='home-feed']",
                timeout=15000,
            )
            print("[JobStreet] OTP accepted — logged in")
            return True

        except PWTimeout:
            print("[JobStreet] OTP submission timed out")
            _notifier()._send(
                "❌ <b>JobStreet OTP failed</b> — the code may have expired or was incorrect.\n"
                "JobStreet will be scraped as a guest today."
            )
            return False
        except Exception as exc:
            print(f"[JobStreet] OTP entry error: {exc}")
            return False

    def _scrape_page(self, page, keyword: str, location: str, pg: int) -> list[dict]:
        slug = keyword.replace(" ", "-").lower()
        url  = f"{BASE_URL}/{slug}-jobs/in-{location.lower()}?pg={pg}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("article[data-job-id], [data-testid='job-card']",
                                   timeout=15000)
        except PWTimeout:
            print(f"[JobStreet] timeout on page {pg} for '{keyword}'")
            return []

        cards = page.query_selector_all(
            "article[data-job-id], [data-testid='job-card']"
        )
        jobs = []
        for card in cards:
            job = self._parse_card(card)
            if job:
                jobs.append(job)
        return jobs

    def _parse_card(self, card) -> dict | None:
        try:
            jid = (
                card.get_attribute("data-job-id")
                or card.get_attribute("data-testid")
                or ""
            )
            title   = self._text(card, "h1,h2,h3,[data-testid='job-title']")
            company = self._text(card, "[data-testid='company-name'], .company-name")
            loc     = self._text(card, "[data-testid='job-location'], .location")
            salary  = self._text(card, "[data-testid='salary'], .salary-range")
            desc    = self._text(card, "[data-testid='job-description'], .job-description")
            href    = card.query_selector("a")
            url     = href.get_attribute("href") if href else ""
            if url and not url.startswith("http"):
                url = BASE_URL + url

            if not title:
                return None

            raw_id = jid or f"{title}{company}"
            return {
                "id":          f"js_{hashlib.md5(raw_id.encode()).hexdigest()[:16]}",
                "platform":    self.name,
                "title":       title,
                "company":     company,
                "location":    loc or "Singapore",
                "salary":      salary,
                "description": desc[:4000],
                "url":         url,
                "posted_at":   "",
            }
        except Exception:
            return None

    @staticmethod
    def _text(el, selector: str) -> str:
        node = el.query_selector(selector)
        return node.inner_text().strip() if node else ""
