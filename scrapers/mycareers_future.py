"""
MyCareersFuture.gov.sg — Playwright scraper with response interception.

MCF's REST API blocks direct server requests (allowlist check).
Instead, we load the search page in a real browser and intercept
the JSON response that the browser itself fetches from the API.
"""

import hashlib
import re
from urllib.parse import quote
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from .base import BaseScraper

SEARCH_URL = "https://www.mycareersfuture.gov.sg/search"


class MyCareersFutureScraper(BaseScraper):
    name = "mycareers_future"

    def scrape(self, keywords: list[str], location: str, pages: int) -> list[dict]:
        jobs: list[dict] = []
        seen_ids: set[str] = set()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
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

            for keyword in keywords:
                for pg in range(1, pages + 1):
                    batch = self._scrape_page(page, keyword, pg)
                    if not batch:
                        break
                    for job in batch:
                        if job["id"] not in seen_ids:
                            seen_ids.add(job["id"])
                            jobs.append(job)
                    self._sleep(1.5, 3.0)

            browser.close()

        return jobs

    def _scrape_page(self, page, keyword: str, pg: int) -> list[dict]:
        """
        Load the MCF search page and intercept the API JSON response
        that the browser fetches automatically.
        """
        captured: list[dict] = []

        def on_response(response):
            if "api.mycareersfuture.gov.sg/v2/search" in response.url:
                try:
                    data = response.json()
                    captured.extend(data.get("results", []))
                except Exception:
                    pass

        page.on("response", on_response)

        url = (
            f"{SEARCH_URL}"
            f"?search={quote(keyword)}"
            f"&sortBy=new_posting_date"
            f"&page={pg}"
        )
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except PWTimeout:
            print(f"[MCF] timeout for '{keyword}' page {pg}")

        page.remove_listener("response", on_response)

        if not captured:
            # Fallback: parse job cards directly from the DOM
            captured_jobs = self._parse_dom(page)
            if captured_jobs:
                return captured_jobs
            print(f"[MCF] no results for '{keyword}' page {pg}")
            return []

        return [self._normalise(r) for r in captured]

    def _parse_dom(self, page) -> list[dict]:
        """DOM fallback: parse visible job cards if API interception missed."""
        jobs = []
        try:
            cards = page.query_selector_all("article, [data-testid='job-card']")
            for card in cards:
                title_el  = card.query_selector("h2, h3, [data-testid='job-title']")
                comp_el   = card.query_selector("[data-testid='company-name'], .company")
                link_el   = card.query_selector("a")
                salary_el = card.query_selector("[data-testid='salary'], .salary")

                title  = title_el.inner_text().strip()  if title_el  else ""
                if not title:
                    continue
                href   = link_el.get_attribute("href")  if link_el   else ""
                if href and not href.startswith("http"):
                    href = "https://www.mycareersfuture.gov.sg" + href
                match  = re.search(r"/job/([a-f0-9\-]+)", href or "")
                jid    = match.group(1) if match else hashlib.md5(title.encode()).hexdigest()[:16]

                jobs.append({
                    "id":          f"mcf_{jid}",
                    "platform":    self.name,
                    "title":       title,
                    "company":     comp_el.inner_text().strip() if comp_el else "",
                    "location":    "Singapore",
                    "salary":      salary_el.inner_text().strip() if salary_el else "",
                    "description": "",
                    "url":         href,
                    "posted_at":   "",
                })
        except Exception as exc:
            print(f"[MCF] DOM parse error: {exc}")
        return jobs

    def _normalise(self, raw: dict) -> dict:
        salary = raw.get("salary", {}) or {}
        sal_str = ""
        if salary.get("minimum") and salary.get("maximum"):
            sal_str = f"SGD {salary['minimum']:,} - {salary['maximum']:,} / month"
        elif salary.get("minimum"):
            sal_str = f"SGD {salary['minimum']:,}+ / month"

        description = raw.get("description", "") or ""
        description = re.sub(r"<[^>]+>", " ", description).strip()

        uuid = raw.get("uuid", "")
        return {
            "id":          f"mcf_{uuid or self._make_id(raw)}",
            "platform":    self.name,
            "title":       raw.get("title", ""),
            "company":     raw.get("postedCompany", {}).get("name", ""),
            "location":    "Singapore",
            "salary":      sal_str,
            "description": description[:4000],
            "url":         f"https://www.mycareersfuture.gov.sg/job/{uuid}" if uuid else "",
            "posted_at":   raw.get("newPostingDate", ""),
        }

    @staticmethod
    def _make_id(job: dict) -> str:
        key = f"{job.get('title', '')}{job.get('postedCompany', {}).get('name', '')}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
