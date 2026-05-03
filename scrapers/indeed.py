"""
Indeed Singapore — requests + BeautifulSoup scraper (no login required).
"""

import hashlib
import re
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper

BASE_URL = "https://sg.indeed.com"
HEADERS  = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-SG,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}


class IndeedScraper(BaseScraper):
    name = "indeed"

    def scrape(self, keywords: list[str], location: str, pages: int) -> list[dict]:
        jobs: list[dict] = []
        seen_ids: set[str] = set()
        session = requests.Session()
        session.headers.update(HEADERS)

        for keyword in keywords:
            for pg in range(pages):
                batch = self._fetch_page(session, keyword, location, pg * 10)
                if not batch:
                    break
                for job in batch:
                    if job["id"] not in seen_ids:
                        seen_ids.add(job["id"])
                        jobs.append(job)
                self._sleep(2.0, 4.0)

        return jobs

    def _fetch_page(self, session: requests.Session,
                    keyword: str, location: str, start: int) -> list[dict]:
        params = {"q": keyword, "l": location, "start": start, "sort": "date"}
        try:
            r = session.get(f"{BASE_URL}/jobs", params=params, timeout=20)
            r.raise_for_status()
        except Exception as exc:
            print(f"[Indeed] error for '{keyword}' start={start}: {exc}")
            return []

        soup = BeautifulSoup(r.text, "lxml")
        cards = soup.select("div.job_seen_beacon, li.css-5lfssm, .jobsearch-SerpJobCard")
        jobs  = []
        for card in cards:
            job = self._parse_card(card)
            if job:
                jobs.append(job)
        return jobs

    def _parse_card(self, card) -> dict | None:
        try:
            # job ID
            jid = card.get("data-jk") or card.get("id", "")

            title_el = card.select_one(
                "h2.jobTitle a, h2.jobTitle span, [data-testid='jobTitle'] span"
            )
            comp_el  = card.select_one(
                "span[data-testid='company-name'], .companyName"
            )
            loc_el   = card.select_one(
                "div[data-testid='text-location'], .companyLocation"
            )
            sal_el   = card.select_one(
                "div[data-testid='attribute_snippet_testid'], .metadata.salary-snippet-container"
            )
            desc_el  = card.select_one(".job-snippet, ul.css-9446gz")

            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                return None

            raw_id = jid or hashlib.md5(title.encode()).hexdigest()[:16]
            href_el = card.select_one("h2.jobTitle a")
            href    = href_el.get("href", "") if href_el else ""
            if href and not href.startswith("http"):
                href = BASE_URL + href

            return {
                "id":          f"ind_{raw_id}",
                "platform":    self.name,
                "title":       title,
                "company":     comp_el.get_text(strip=True) if comp_el else "",
                "location":    loc_el.get_text(strip=True) if loc_el else "Singapore",
                "salary":      sal_el.get_text(strip=True) if sal_el else "",
                "description": desc_el.get_text(" ", strip=True)[:4000] if desc_el else "",
                "url":         href,
                "posted_at":   "",
            }
        except Exception:
            return None
