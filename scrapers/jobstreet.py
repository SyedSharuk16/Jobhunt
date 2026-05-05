"""
JobStreet Singapore — Playwright scraper.
Real domain is sg.jobstreet.com (SEEK platform).
Login uses email-OTP: clicks "Sign in with email" on the OAuth page,
submits the email address, then waits for OTP via Telegram.
"""

import hashlib
import importlib
import json
import os
import re
from urllib.parse import quote
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from .base import BaseScraper

BASE_URL  = "https://sg.jobstreet.com"
LOGIN_URL = "https://sg.jobstreet.com/oauth/login?returnUrl=%2F"

# ── OTP input detection ───────────────────────────────────────────────────────
_OTP_SIGNALS = [
    "input[name='otp']",
    "input[placeholder*='OTP' i]",
    "input[placeholder*='verification' i]",
    "input[placeholder*='code' i]",
    "input[aria-label*='OTP' i]",
    "[data-testid='otp-input']",
    "input[type='tel'][maxlength='6']",
    "input[type='number'][maxlength='6']",
    "input[autocomplete='one-time-code']",
]
_OTP_INPUT  = ", ".join(_OTP_SIGNALS)
_OTP_SUBMIT = (
    "button[type='submit'], "
    "button:has-text('Verify'), "
    "button:has-text('Confirm'), "
    "button:has-text('Submit'), "
    "button:has-text('Continue')"
)

# Continue / send OTP button after email is entered
_CONTINUE_BTN = (
    "button[data-automation='sign-in-btn'], "
    "button[type='submit'], "
    "button:has-text('Continue'), "
    "button:has-text('Send'), "
    "button:has-text('Next'), "
    "button:has-text('Log in'), "
    "button:has-text('Sign in')"
)

# Selectors for the "sign in with email" link on the OAuth page.
# Ordered from most specific to least specific.
# NOTE: intentionally excludes a[href*='email'] which is too broad
#       and can match mailto: or unrelated links.
_EMAIL_OPTION_TEXTS = [
    "sign in with email",
    "use email",
    "continue with email",
    "email address",
    "email instead",
    "use your email",
    "email",   # last resort — short text match
]


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
            print(f"[JobStreet] login page loaded: {page.url}")

            # Screenshot for debugging (uploaded as GitHub Actions artifact)
            self._save_screenshot(page, "login_step1_oauth_page")

            # Log all clickable elements so we can diagnose selector mismatches
            self._log_interactive_elements(page)

            # Step 1: find and click the "sign in with email" option
            clicked = self._click_email_option(page)
            if clicked:
                self._sleep(2, 3)
                print(f"[JobStreet] after email option click, URL: {page.url}")
                self._save_screenshot(page, "login_step2_after_email_click")
                self._log_interactive_elements(page)

            # Step 2: fill the email input — use element handle to avoid re-search timeout
            email_el = self._find_email_input(page)
            if email_el is None:
                print("[JobStreet] email input still not visible — aborting login")
                return self._is_logged_in(page)

            email_el.fill(self._email)
            print(f"[JobStreet] email entered ({self._email})")
            self._save_screenshot(page, "login_step3_email_filled")

            # Step 3: click continue / send OTP
            try:
                page.click(_CONTINUE_BTN, timeout=10000)
                print("[JobStreet] submitted email — waiting for OTP screen")
            except PWTimeout:
                print("[JobStreet] could not find/click continue button")
                self._save_screenshot(page, "login_step3_no_continue_btn")
                return False

            self._sleep(2, 3)
            self._save_screenshot(page, "login_step4_post_submit")

            # Step 4: wait for OTP field
            try:
                page.wait_for_selector(_OTP_INPUT, timeout=30000)
            except PWTimeout:
                print("[JobStreet] no OTP screen — checking login state")
                self._log_interactive_elements(page)
                return self._is_logged_in(page)

            return self._handle_otp(page)

        except Exception as exc:
            print(f"[JobStreet] login error: {exc}")
            self._save_screenshot(page, "login_error")
            return False

    def _click_email_option(self, page) -> bool:
        """Find and click the 'sign in with email' link on the OAuth page."""
        for text in _EMAIL_OPTION_TEXTS:
            # Try both <a> and <button> with exact case-insensitive text match
            for tag in ("a", "button", "span", "div"):
                try:
                    # Playwright :has-text matches if element contains the text
                    sel = f"{tag}:has-text('{text}')"
                    el  = page.query_selector(sel)
                    if el and el.is_visible():
                        label = el.inner_text().strip()
                        # Skip if text is too long (avoid matching paragraphs of text)
                        if len(label) > 60:
                            continue
                        print(f"[JobStreet] clicking email option [{tag}] text='{label}'")
                        el.click()
                        return True
                except Exception:
                    continue
        print("[JobStreet] no 'sign in with email' option found on page")
        return False

    def _find_email_input(self, page) -> object | None:
        """Return a visible email input element handle, or None."""
        selectors = [
            "input[type='email']",
            "input[name='email']",
            "input[name='emailAddress']",
            "input[data-automation='email']",
            "input[data-automation='emailAddress']",
            "input[data-testid='email']",
            "input[data-testid='emailAddress']",
            "input[placeholder*='email' i]",
            "input[aria-label*='email' i]",
            # Broad fallback: any visible text/email input that isn't a search box
            "input[type='text']:not([role='combobox']):not([placeholder*='search' i])",
        ]
        # Give the page up to 15 s to show the email field
        for sel in selectors:
            try:
                el = page.wait_for_selector(sel, timeout=15000, state="visible")
                if el:
                    print(f"[JobStreet] found email input with selector: {sel}")
                    return el
            except PWTimeout:
                continue
            except Exception:
                continue
        return None

    def _is_logged_in(self, page) -> bool:
        for sel in [
            "[data-automation='account-menu']",
            "header[data-automation='header']",
            "a[href*='/profile']",
            "button[aria-label*='account' i]",
            "[data-testid='account-menu']",
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
            page.wait_for_selector(
                "[data-automation='account-menu'], "
                "header[data-automation='header'], "
                "a[href*='/profile']",
                timeout=25000,
            )
            print("[JobStreet] OTP accepted — logged in")
            return True
        except Exception as exc:
            print(f"[JobStreet] OTP entry error: {exc}")
            _notifier()._send("❌ <b>JobStreet OTP failed</b> — continuing as guest.")
            return False

    # ── Debug helpers ─────────────────────────────────────────────────────────

    def _save_screenshot(self, page, label: str) -> None:
        try:
            os.makedirs("reports", exist_ok=True)
            path = f"reports/jobstreet_{label}.png"
            page.screenshot(path=path, full_page=False)
            print(f"[JobStreet] screenshot → {path}")
        except Exception as exc:
            print(f"[JobStreet] screenshot failed: {exc}")

    def _log_interactive_elements(self, page) -> None:
        try:
            items = page.evaluate("""
            () => {
                const els = document.querySelectorAll('a, button, input, [role="button"]');
                return Array.from(els)
                    .filter(e => {
                        const r = e.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    })
                    .map(e => ({
                        tag:  e.tagName,
                        type: e.type || '',
                        text: (e.textContent || e.value || e.placeholder || '').trim().slice(0, 60),
                        href: (e.href || '').slice(0, 80),
                    }))
                    .filter(e => e.text || e.href)
                    .slice(0, 30);
            }
            """)
            print(f"[JobStreet] visible interactive elements ({len(items)}):")
            for it in items:
                print(f"  <{it['tag'].lower()}> type={it['type']!r} "
                      f"text={it['text']!r} href={it['href']!r}")
        except Exception as exc:
            print(f"[JobStreet] element log failed: {exc}")

    # ── Scraping ──────────────────────────────────────────────────────────────

    def _scrape_page(self, page, keyword: str, pg: int) -> list[dict]:
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
            page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            page.wait_for_timeout(1500)
        except PWTimeout:
            print(f"[JobStreet] timeout loading '{keyword}' pg {pg}")
            return []

        landed = page.url
        print(f"[JobStreet] '{keyword}' pg {pg} — landed: {landed[:100]}")

        if "/jobs" not in landed and "q=" not in landed:
            print(f"[JobStreet] redirected away from search — skipping")
            return []

        jobs = self._extract_via_js(page)
        if jobs:
            print(f"[JobStreet] '{keyword}' pg {pg}: {len(jobs)} jobs via JS")
            return jobs

        jobs = self._from_next_data(page)
        if jobs:
            print(f"[JobStreet] '{keyword}' pg {pg}: {len(jobs)} jobs via __NEXT_DATA__")
            return jobs

        card_counts = page.evaluate("""
        () => {
            const sels = [
                '[data-automation="job-card"]',
                'article[data-job-id]',
                '[data-card-type="JobCard"]',
                'article[data-testid="job-card"]',
                'article',
                '[data-testid*="job"]',
            ];
            return sels.map(s => s + ':' + document.querySelectorAll(s).length);
        }
        """)
        print(f"[JobStreet] '{keyword}' pg {pg}: 0 jobs — card counts: {card_counts}")
        return []

    def _extract_via_js(self, page) -> list[dict]:
        raw = page.evaluate("""
        () => {
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

                const compEl = (
                    card.querySelector('[data-automation="job-company-name"]') ||
                    card.querySelector('[data-automation="advertiser-name"]') ||
                    card.querySelector('[data-testid="company-name"]') ||
                    card.querySelector('a[data-automation*="company"]') ||
                    card.querySelector('[class*="company" i]')
                );

                const locEl = (
                    card.querySelector('[data-automation="job-card-location"]') ||
                    card.querySelector('[data-automation="job-location"]') ||
                    card.querySelector('[data-testid="job-location"]')
                );

                const salEl = (
                    card.querySelector('[data-automation="job-card-salary"]') ||
                    card.querySelector('[data-automation="job-salary"]') ||
                    card.querySelector('[data-testid="salary"]')
                );

                const linkEl = (
                    card.querySelector('a[data-automation="jobcard-link"]') ||
                    card.querySelector('a[href*="/job/"]') ||
                    card.querySelector('a[href*="jobstreet"]')
                );
                const href  = linkEl ? linkEl.href : '';
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
