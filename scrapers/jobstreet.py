"""
JobStreet Singapore — Playwright scraper.
Real domain is sg.jobstreet.com (SEEK platform).
Login is email-OTP only; OTP is requested via Telegram.
"""

import hashlib
import importlib
import json
import os
import re
from urllib.parse import quote
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from .base import BaseScraper

# sg.jobstreet.com is the real domain (www.jobstreet.com.sg redirects here)
BASE_URL   = "https://sg.jobstreet.com"
LOGIN_URL  = "https://sg.jobstreet.com/login"

_OTP_SIGNALS = [
    "input[name='otp']",
    "input[placeholder*='OTP' i]",
    "input[placeholder*='verification' i]",
    "input[placeholder*='code' i]",
    "input[aria-label*='OTP' i]",
    "[data-testid='otp-input']",
    "input[type='tel'][maxlength='6']",
    "input[type='number'][maxlength='6']",
]
_OTP_INPUT  = ", ".join(_OTP_SIGNALS)
_OTP_SUBMIT = (
    "button[type='submit'], "
    "button:has-text('Verify'), "
    "button:has-text('Confirm'), "
    "button:has-text('Submit')"
)

# Email input selectors for login page
_EMAIL_INPUT = (
    "input[type='email'], "
    "input[name='email'], "
    "input[name='emailAddress'], "
    "input[data-automation='email'], "
    "input[placeholder*='email' i]"
)

# Continue / send OTP button on login page
_CONTINUE_BTN = (
    "button[data-automation='sign-in-btn'], "
    "button[type='submit'], "
    "button:has-text('Continue'), "
    "button:has-text('Send OTP'), "
    "button:has-text('Log in'), "
    "button:has-text('Sign in'), "
    "button:has-text('Next')"
)


def _notifier():
    return importlib.import_module("notifier")


class JobStreetScraper(BaseScraper):
    name = "jobstreet"

    def __init__(self):
        self._email    = os.getenv("JOBSTREET_EMAIL", "")
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

            if self._email:
                ok = self._login(page)
                if not ok:
                    print("[JobStreet] login failed — continuing as guest")
            else:
                print("[JobStreet] JOBSTREET_EMAIL not set — scraping as guest")

            for keyword in keywords:
                for pg in range(1, pages + 1):
                    batch = self._scrape_page(page, keyword, pg)
                    if not batch:
                        break
                    for job in batch:
                        if job["id"] not in seen_ids:
                            seen_ids.add(job["id"])
                            jobs.append(job)
                    self._sleep(2.0, 4.0)

            browser.close()

        print(f"[JobStreet] total unique jobs: {len(jobs)}")
        return jobs

    # ── Login ─────────────────────────────────────────────────────────────────

    def _login(self, page) -> bool:
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            self._sleep(2, 3)
            print(f"[JobStreet] login page: {page.url}")

            # Fill email
            try:
                page.wait_for_selector(_EMAIL_INPUT, timeout=15000)
                page.fill(_EMAIL_INPUT, self._email)
            except PWTimeout:
                print("[JobStreet] email field not found — login page may have changed")
                return False

            # Click continue
            page.click(_CONTINUE_BTN)
            print("[JobStreet] email submitted — waiting for OTP screen")

            # Wait for OTP input
            try:
                page.wait_for_selector(_OTP_INPUT, timeout=25000)
            except PWTimeout:
                print("[JobStreet] no OTP screen — checking if already logged in")
                return self._is_logged_in(page)

            return self._handle_otp(page)

        except Exception as exc:
            print(f"[JobStreet] login error: {exc}")
            return False

    def _is_logged_in(self, page) -> bool:
        for sel in [
            "[data-automation='account-menu']",
            "header[data-automation='header']",
            "a[href*='/profile']",
            "button[aria-label*='account' i]",
        ]:
            if page.query_selector(sel):
                print("[JobStreet] already logged in")
                return True
        return False

    def _handle_otp(self, page) -> bool:
        print("[JobStreet] OTP screen — requesting code via Telegram")
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
            # Wait for authenticated header to confirm login
            page.wait_for_selector(
                "[data-automation='account-menu'], header[data-automation='header'], a[href*='/profile']",
                timeout=25000,
            )
            print("[JobStreet] OTP accepted — logged in")
            return True
        except Exception as exc:
            print(f"[JobStreet] OTP entry error: {exc}")
            _notifier()._send("❌ <b>JobStreet OTP failed</b> — continuing as guest.")
            return False

    # ── Scraping ──────────────────────────────────────────────────────────────

    def _scrape_page(self, page, keyword: str, pg: int) -> list[dict]:
        # sg.jobstreet.com uses SEEK's URL format: where= and page=
        url = (
            f"{BASE_URL}/jobs"
            f"?q={quote(keyword)}"
            f"&where=Singapore"
            f"&page={pg}"
            f"&sortMode=ListedDate"
        )
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            # Scroll to trigger lazy-loaded cards
            page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            page.wait_for_timeout(1500)
        except PWTimeout:
            print(f"[JobStreet] timeout '{keyword}' pg {pg}")
            return []

        print(f"[JobStreet] '{keyword}' pg {pg} — url: {page.url[:90]}")

        # Use JavaScript to extract all job data — most reliable approach
        jobs = self._extract_via_js(page)
        if jobs:
            print(f"[JobStreet] '{keyword}' pg {pg}: {len(jobs)} jobs via JS")
            return jobs

        # Fallback: try __NEXT_DATA__
        jobs = self._from_next_data(page)
        if jobs:
            print(f"[JobStreet] '{keyword}' pg {pg}: {len(jobs)} jobs via __NEXT_DATA__")
            return jobs

        print(f"[JobStreet] '{keyword}' pg {pg}: 0 jobs found")
        return []

    def _extract_via_js(self, page) -> list[dict]:
        """
        Run JavaScript in the browser to extract job cards.
        Tries many selector variants so it survives SEEK redesigns.
        """
        raw = page.evaluate("""
        () => {
            // Find all job card containers
            const cardSels = [
                '[data-automation="job-card"]',
                'article[data-job-id]',
                '[data-card-type="JobCard"]',
                'article[data-testid="job-card"]',
            ];
            let cards = [];
            for (const sel of cardSels) {
                cards = Array.from(document.querySelectorAll(sel));
                if (cards.length > 0) break;
            }
            if (!cards.length) return [];

            return cards.map(card => {
                // Title — try every known SEEK/JobStreet variant
                const titleEl = (
                    card.querySelector('[data-automation="job-title"]') ||
                    card.querySelector('a[data-automation="jobcard-link"]') ||
                    card.querySelector('[data-testid="job-title"]') ||
                    card.querySelector('h1 a, h2 a, h3 a, h4 a') ||
                    card.querySelector('h1, h2, h3') ||
                    card.querySelector('a[href*="/job/"]')
                );
                const title = titleEl ? titleEl.textContent.trim() : '';
                if (!title) return null;

                // Company
                const compEl = (
                    card.querySelector('[data-automation="job-company-name"]') ||
                    card.querySelector('[data-automation="advertiser-name"]') ||
                    card.querySelector('[data-testid="company-name"]') ||
                    card.querySelector('a[data-automation*="company"]') ||
                    card.querySelector('[class*="company" i]')
                );

                // Location
                const locEl = (
                    card.querySelector('[data-automation="job-card-location"]') ||
                    card.querySelector('[data-automation="job-location"]') ||
                    card.querySelector('[data-testid="job-location"]')
                );

                // Salary
                const salEl = (
                    card.querySelector('[data-automation="job-card-salary"]') ||
                    card.querySelector('[data-automation="job-salary"]') ||
                    card.querySelector('[data-testid="salary"]')
                );

                // URL
                const linkEl = (
                    card.querySelector('a[data-automation="jobcard-link"]') ||
                    card.querySelector('a[href*="/job/"]') ||
                    card.querySelector('a[href*="jobstreet"]')
                );
                const href = linkEl ? linkEl.href : '';
                const jobId = card.getAttribute('data-job-id') || '';

                return {
                    jobId,
                    title,
                    company:  compEl ? compEl.textContent.trim() : '',
                    location: locEl  ? locEl.textContent.trim()  : 'Singapore',
                    salary:   salEl  ? salEl.textContent.trim()  : '',
                    url:      href || (jobId ? '/job/' + jobId : ''),
                };
            }).filter(j => j !== null && j.title.length > 2);
        }
        """)

        if not raw:
            return []

        results = []
        for item in raw:
            url = item.get("url", "")
            if url and not url.startswith("http"):
                url = BASE_URL + url
            job_id = item.get("jobId") or f"{item['title']}{item.get('company','')}"
            results.append({
                "id":          f"js_{hashlib.md5(job_id.encode()).hexdigest()[:16]}",
                "platform":    self.name,
                "title":       item["title"],
                "company":     item.get("company", ""),
                "location":    item.get("location", "Singapore"),
                "salary":      item.get("salary", ""),
                "description": "",
                "url":         url,
                "posted_at":   "",
            })
        return results

    def _from_next_data(self, page) -> list[dict]:
        try:
            raw = page.evaluate(
                "() => { const el = document.getElementById('__NEXT_DATA__'); "
                "return el ? el.textContent : null; }"
            )
            if not raw:
                return []
            data  = json.loads(raw)
            props = data.get("props", {}).get("pageProps", {})
            for path in [["results"], ["jobs"], ["jobResults", "results"],
                         ["data", "jobs"], ["initialData", "results"]]:
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

    def _normalise_next(self, raw: dict) -> dict:
        salary = raw.get("salary", {}) or {}
        sal_str = ""
        if isinstance(salary, dict):
            lo = salary.get("minimum") or salary.get("min")
            hi = salary.get("maximum") or salary.get("max")
            if lo and hi:
                sal_str = f"SGD {lo:,} - {hi:,} / month"
            elif lo:
                sal_str = f"SGD {lo:,}+ / month"
        elif isinstance(salary, str):
            sal_str = salary

        job_id  = str(raw.get("id") or raw.get("jobId") or "")
        title   = raw.get("title") or raw.get("jobTitle") or ""
        company = (raw.get("advertiser", {}).get("description")
                   or raw.get("companyName") or raw.get("company") or "")
        url     = raw.get("jobUrl") or (f"{BASE_URL}/job/{job_id}" if job_id else "")
        desc    = re.sub(r"<[^>]+>", " ",
                         raw.get("teaser") or raw.get("description") or "").strip()
        raw_id  = job_id or f"{title}{company}"
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
