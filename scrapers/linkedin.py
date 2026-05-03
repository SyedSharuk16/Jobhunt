"""
LinkedIn Jobs Singapore — Playwright scraper with login.
NOTE: Automated scraping may conflict with LinkedIn's ToS.
Use responsibly and at low frequency.
"""

import hashlib
import os
import re
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from .base import BaseScraper

BASE_URL  = "https://www.linkedin.com"
JOBS_URL  = f"{BASE_URL}/jobs/search"


class LinkedInScraper(BaseScraper):
    name = "linkedin"

    def __init__(self):
        self._email    = os.getenv("LINKEDIN_EMAIL", "")
        self._password = os.getenv("LINKEDIN_PASSWORD", "")
        self._headless = os.getenv("HEADLESS", "true").lower() == "true"

    def scrape(self, keywords: list[str], location: str, pages: int) -> list[dict]:
        if not (self._email and self._password):
            print("[LinkedIn] no credentials set — skipping")
            return []

        jobs: list[dict] = []
        seen_ids: set[str] = set()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self._headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
            )
            page = ctx.new_page()

            if not self._login(page):
                browser.close()
                return []

            for keyword in keywords:
                for pg in range(pages):
                    batch = self._scrape_page(page, keyword, location, pg * 25)
                    if not batch:
                        break
                    for job in batch:
                        if job["id"] not in seen_ids:
                            seen_ids.add(job["id"])
                            jobs.append(job)
                    self._sleep(3.0, 6.0)

            browser.close()

        return jobs

    def _login(self, page) -> bool:
        try:
            page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
            page.fill("#username", self._email)
            page.fill("#password", self._password)
            page.click('[data-litms-control-urn="login-submit"]')
            page.wait_for_url("**/feed/**", timeout=20000)
            print("[LinkedIn] logged in")
            return True
        except PWTimeout:
            print("[LinkedIn] login failed or checkpoint required — skipping")
            return False

    def _scrape_page(self, page, keyword: str, location: str, start: int) -> list[dict]:
        params = (
            f"?keywords={keyword.replace(' ', '%20')}"
            f"&location={location.replace(' ', '%20')}"
            f"&f_TPR=r604800"   # past week
            f"&start={start}"
        )
        try:
            page.goto(JOBS_URL + params, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector(".jobs-search__results-list li, .job-card-container",
                                   timeout=15000)
        except PWTimeout:
            print(f"[LinkedIn] timeout for '{keyword}' start={start}")
            return []

        # Scroll to load all cards
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        self._sleep(1.5, 2.5)

        cards = page.query_selector_all(
            ".jobs-search__results-list li, .job-card-container"
        )
        jobs = []
        for card in cards:
            job = self._parse_card(card)
            if job:
                jobs.append(job)
        return jobs

    def _parse_card(self, card) -> dict | None:
        try:
            link_el  = card.query_selector("a.job-card-container__link, a.base-card__full-link")
            title_el = card.query_selector(
                ".job-card-container__link span, .base-search-card__title"
            )
            comp_el  = card.query_selector(
                ".job-card-container__company-name, .base-search-card__subtitle a"
            )
            loc_el   = card.query_selector(
                ".job-card-container__metadata-item, .job-search-card__location"
            )

            title = title_el.inner_text().strip() if title_el else ""
            if not title:
                return None

            href = link_el.get_attribute("href") if link_el else ""
            # Extract LinkedIn job ID from URL
            match = re.search(r"/jobs/view/(\d+)", href or "")
            jid   = match.group(1) if match else hashlib.md5(title.encode()).hexdigest()[:16]

            return {
                "id":          f"li_{jid}",
                "platform":    self.name,
                "title":       title,
                "company":     comp_el.inner_text().strip() if comp_el else "",
                "location":    loc_el.inner_text().strip() if loc_el else "Singapore",
                "salary":      "",
                "description": "",   # fetched separately if needed
                "url":         href.split("?")[0] if href else "",
                "posted_at":   "",
            }
        except Exception:
            return None
