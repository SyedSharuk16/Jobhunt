"""
JobStreet Singapore — Playwright scraper.
Works as guest for public job listings; login unlocks full descriptions.
OTP is handled via Telegram if triggered during login.
"""

import hashlib
import importlib
import json
import os
import re
from urllib.parse import quote
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from .base import BaseScraper

BASE_URL = "https://www.jobstreet.com.sg"

# JobStreet (SEEK) uses data-automation attributes — very stable across redesigns
_SEL_CARD    = "article[data-job-id], article[data-testid='job-card'], [data-automation='job-card']"
_SEL_TITLE   = "[data-automation='job-title'], [data-testid='job-title'], h1, h2, h3"
_SEL_COMPANY = "[data-automation='job-company-name'], [data-testid='company-name'], [class*='company']"
_SEL_LOC     = "[data-automation='job-card-location'], [data-testid='job-location'], [class*='location']"
_SEL_SALARY  = "[data-automation='job-card-salary'], [data-testid='salary'], [class*='salary']"

_OTP_SIGNALS = [
    "input[name='otp']",
    "input[placeholder*='OTP']",
    "input[placeholder*='verification' i]",
    "input[placeholder*='code' i]",
    "input[aria-label*='OTP' i]",
    "[data-testid='otp-input']",
    "input[type='tel'][maxlength='6']",
    "input[type='number'][maxlength='6']",
]
_OTP_INPUT  = ", ".join(_OTP_SIGNALS)
_OTP_SUBMIT = "button[type='submit'], button:has-text('Verify'), button:has-text('Confirm')"


def _notifier():
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
                args=["--disable-blink-features=AutomationControlled",
                      "--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()

            # Login if credentials provided
            if self._email and self._password:
                ok = self._login(page)
                if not ok:
                    print("[JobStreet] login failed — continuing as guest")
            else:
                print("[JobStreet] no credentials set — scraping as guest")

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

        print(f"[JobStreet] total unique jobs found: {len(jobs)}")
        return jobs

    # ── Login ─────────────────────────────────────────────────────────────────

    def _login(self, page) -> bool:
        try:
            page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
            self._sleep(1, 2)

            # Fill credentials
            page.fill('input[type="email"], input[name="email"]', self._email)
            page.fill('input[type="password"], input[name="password"]', self._password)
            page.click('button[type="submit"]')

            # Wait for either: home feed, OTP screen, or timeout
            try:
                page.wait_for_selector(
                    f"{_OTP_INPUT}, "
                    "[data-testid='home-feed'], "
                    "header[data-automation='header'], "
                    "nav[aria-label='main'], "
                    "[class*='Dashboard'], "
                    "a[href*='/profile']",
                    timeout=20000,
                )
            except PWTimeout:
                print("[JobStreet] post-login wait timed out — assuming logged in")
                return True

            if self._on_otp_page(page):
                return self._handle_otp(page)

            print("[JobStreet] logged in successfully")
            return True

        except Exception as exc:
            print(f"[JobStreet] login error: {exc}")
            return False

    def _on_otp_page(self, page) -> bool:
        for sel in _OTP_SIGNALS:
            if page.query_selector(sel):
                return True
        return any(kw in page.url.lower() for kw in ("otp", "verify", "mfa", "2fa"))

    def _handle_otp(self, page) -> bool:
        print("[JobStreet] OTP screen detected — requesting via Telegram")
        otp = _notifier().wait_for_otp(platform="JobStreet", timeout=180)
        if not otp:
            return False
        try:
            field = page.wait_for_selector(_OTP_INPUT, timeout=5000)
            field.fill(otp)
            btn = page.query_selector(_OTP_SUBMIT)
            if btn:
                btn.click()
            else:
                field.press("Enter")
            page.wait_for_selector(
                "header[data-automation='header'], nav[aria-label='main'], a[href*='/profile']",
                timeout=20000,
            )
            print("[JobStreet] OTP accepted")
            return True
        except Exception as exc:
            print(f"[JobStreet] OTP entry error: {exc}")
            _notifier()._send("❌ <b>JobStreet OTP failed</b> — continuing as guest.")
            return False

    # ── Scraping ──────────────────────────────────────────────────────────────

    def _scrape_page(self, page, keyword: str, location: str, pg: int) -> list[dict]:
        # Use the standard JobStreet /jobs search endpoint
        url = (
            f"{BASE_URL}/jobs"
            f"?q={quote(keyword)}"
            f"&l={quote(location)}"
            f"&pg={pg}"
            f"&sortmode=ListedDate"
        )
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)  # let React render
        except PWTimeout:
            print(f"[JobStreet] page load timeout '{keyword}' pg {pg}")
            return []

        # Try Next.js data first (fastest, most structured)
        results = self._from_next_data(page)
        if results:
            print(f"[JobStreet] '{keyword}' pg {pg}: {len(results)} via __NEXT_DATA__")
            return results

        # Fall back to DOM card parsing
        dom = self._parse_dom(page, keyword, pg)
        return dom

    def _from_next_data(self, page) -> list[dict]:
        try:
            raw = page.evaluate(
                "() => { const el = document.getElementById('__NEXT_DATA__'); "
                "return el ? el.textContent : null; }"
            )
            if not raw:
                return []
            data = json.loads(raw)
            props = data.get("props", {}).get("pageProps", {})

            # JobStreet / SEEK stores jobs in various locations
            for path in [
                ["results"],
                ["jobs"],
                ["jobResults", "results"],
                ["data", "jobs"],
                ["initialData", "results"],
            ]:
                obj = props
                for key in path:
                    obj = obj.get(key) if isinstance(obj, dict) else None
                    if obj is None:
                        break
                if isinstance(obj, list) and obj:
                    return [self._normalise_next(j) for j in obj if j.get("title")]

            return self._deep_find(props)
        except Exception as exc:
            print(f"[JobStreet] __NEXT_DATA__ error: {exc}")
            return []

    def _deep_find(self, obj, depth: int = 0) -> list[dict]:
        if depth > 5:
            return []
        if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "title" in obj[0]:
            return [self._normalise_next(j) for j in obj if j.get("title")]
        if isinstance(obj, dict):
            for v in obj.values():
                found = self._deep_find(v, depth + 1)
                if found:
                    return found
        return []

    def _parse_dom(self, page, keyword: str, pg: int) -> list[dict]:
        jobs = []
        try:
            cards = page.query_selector_all(_SEL_CARD)
            if not cards:
                print(f"[JobStreet] no cards found for '{keyword}' pg {pg}")
                return []
            print(f"[JobStreet] '{keyword}' pg {pg}: {len(cards)} cards via DOM")
            for card in cards:
                job = self._parse_card(card)
                if job:
                    jobs.append(job)
        except Exception as exc:
            print(f"[JobStreet] DOM parse error: {exc}")
        return jobs

    def _parse_card(self, card) -> dict | None:
        try:
            title   = self._text(card, _SEL_TITLE)
            if not title:
                return None
            company = self._text(card, _SEL_COMPANY)
            loc     = self._text(card, _SEL_LOC)
            salary  = self._text(card, _SEL_SALARY)

            jid_attr = card.get_attribute("data-job-id") or ""
            link_el  = card.query_selector("a[href*='/job/'], a[href*='jobstreet']")
            href     = link_el.get_attribute("href") if link_el else ""
            if href and not href.startswith("http"):
                href = BASE_URL + href

            raw_id = jid_attr or f"{title}{company}"
            return {
                "id":          f"js_{hashlib.md5(raw_id.encode()).hexdigest()[:16]}",
                "platform":    self.name,
                "title":       title,
                "company":     company,
                "location":    loc or "Singapore",
                "salary":      salary,
                "description": "",
                "url":         href,
                "posted_at":   "",
            }
        except Exception:
            return None

    def _normalise_next(self, raw: dict) -> dict:
        salary = raw.get("salary", {}) or {}
        sal_str = ""
        if isinstance(salary, dict):
            lo, hi = salary.get("minimum") or salary.get("min"), salary.get("maximum") or salary.get("max")
            if lo and hi:
                sal_str = f"SGD {lo:,} - {hi:,} / month"
            elif lo:
                sal_str = f"SGD {lo:,}+ / month"
        elif isinstance(salary, str):
            sal_str = salary

        job_id = str(raw.get("id") or raw.get("jobId") or "")
        title  = raw.get("title") or raw.get("jobTitle") or ""
        company = (
            raw.get("advertiser", {}).get("description")
            or raw.get("companyName")
            or raw.get("company")
            or ""
        )
        url = raw.get("jobUrl") or (f"{BASE_URL}/job/{job_id}" if job_id else "")

        desc = raw.get("teaser") or raw.get("description") or ""
        desc = re.sub(r"<[^>]+>", " ", desc).strip()

        raw_id = job_id or f"{title}{company}"
        return {
            "id":          f"js_{hashlib.md5(raw_id.encode()).hexdigest()[:16]}",
            "platform":    self.name,
            "title":       title,
            "company":     company,
            "location":    raw.get("jobLocation", {}).get("label") or "Singapore",
            "salary":      sal_str,
            "description": desc[:4000],
            "url":         url,
            "posted_at":   raw.get("listingDate") or raw.get("postedAt") or "",
        }

    @staticmethod
    def _text(el, selector: str) -> str:
        node = el.query_selector(selector)
        return node.inner_text().strip() if node else ""
