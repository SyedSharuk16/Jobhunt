"""
JobStreet Singapore — Playwright-based scraper with optional login.
Login unlocks full job descriptions and saves job history.
"""

import hashlib
import os
import re
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from .base import BaseScraper

BASE_URL = "https://www.jobstreet.com.sg"


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
                self._login(page)

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

    def _login(self, page) -> None:
        try:
            page.goto(f"{BASE_URL}/login", wait_until="networkidle", timeout=30000)
            page.fill('input[name="email"]', self._email)
            page.fill('input[name="password"]', self._password)
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=15000)
            print("[JobStreet] logged in")
        except PWTimeout:
            print("[JobStreet] login timed out — continuing as guest")

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
