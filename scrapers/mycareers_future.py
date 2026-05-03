"""
MyCareersFuture.gov.sg — official public REST API, no login required.
Docs: https://api.mycareersfuture.gov.sg
"""

import hashlib
import requests
from .base import BaseScraper

API_BASE = "https://api.mycareersfuture.gov.sg/v2"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobHuntBot/1.0)",
    "Accept": "application/json",
}


class MyCareersFutureScraper(BaseScraper):
    name = "mycareers_future"

    def scrape(self, keywords: list[str], location: str, pages: int) -> list[dict]:
        jobs: list[dict] = []
        seen_ids: set[str] = set()

        for keyword in keywords:
            for page in range(pages):
                batch = self._fetch_page(keyword, page)
                if not batch:
                    break
                for job in batch:
                    jid = job.get("uuid") or self._make_id(job)
                    if jid not in seen_ids:
                        seen_ids.add(jid)
                        jobs.append(self._normalise(job))
                self._sleep(1.0, 2.0)

        return jobs

    def _fetch_page(self, keyword: str, page: int) -> list[dict]:
        params = {
            "search":   keyword,
            "limit":    100,
            "page":     page,
            "sortBy":   "new_posting_date",
        }
        try:
            r = requests.get(f"{API_BASE}/search", params=params, headers=HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
            return data.get("results", [])
        except Exception as exc:
            print(f"[MCF] error on page {page} for '{keyword}': {exc}")
            return []

    def _normalise(self, raw: dict) -> dict:
        metadata = raw.get("metadata", {})
        salary   = raw.get("salary", {})

        sal_str = ""
        if salary.get("minimum") and salary.get("maximum"):
            sal_str = f"SGD {salary['minimum']:,} – {salary['maximum']:,} / month"
        elif salary.get("minimum"):
            sal_str = f"SGD {salary['minimum']:,}+ / month"

        description = raw.get("description", "") or ""
        # MCF returns HTML; strip tags for storage
        import re
        description = re.sub(r"<[^>]+>", " ", description).strip()

        return {
            "id":          f"mcf_{raw.get('uuid', self._make_id(raw))}",
            "platform":    self.name,
            "title":       raw.get("title", ""),
            "company":     raw.get("postedCompany", {}).get("name", ""),
            "location":    raw.get("address", {}).get("building", "") or "Singapore",
            "salary":      sal_str,
            "description": description[:4000],
            "url":         f"https://www.mycareersfuture.gov.sg/job/{raw.get('uuid','')}",
            "posted_at":   raw.get("newPostingDate", ""),
        }

    @staticmethod
    def _make_id(job: dict) -> str:
        key = f"{job.get('title','')}{job.get('postedCompany',{}).get('name','')}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
