"""
MyCareersFuture.gov.sg — Playwright scraper using Next.js page data.

MCF's REST API blocks direct server calls. Instead we load the search
page in a real browser and extract the embedded __NEXT_DATA__ JSON that
Next.js injects into every page — no response-interception timing issues.
"""

import hashlib
import json
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
                args=["--disable-blink-features=AutomationControlled",
                      "--no-sandbox", "--disable-dev-shm-usage"],
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

        print(f"[MCF] total unique jobs found: {len(jobs)}")
        return jobs

    def _scrape_page(self, page, keyword: str, pg: int) -> list[dict]:
        url = (
            f"{SEARCH_URL}"
            f"?search={quote(keyword)}"
            f"&sortBy=new_posting_date"
            f"&page={pg}"
        )
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Give React/Next.js a moment to hydrate
            page.wait_for_timeout(3000)
        except PWTimeout:
            print(f"[MCF] page load timeout for '{keyword}' pg {pg}")
            return []

        # Try 1: extract from __NEXT_DATA__ (most reliable)
        results = self._from_next_data(page, keyword, pg)
        if results:
            print(f"[MCF] '{keyword}' pg {pg}: {len(results)} jobs via __NEXT_DATA__")
            return [self._normalise(r) for r in results]

        # Try 2: DOM scraping
        dom_jobs = self._parse_dom(page)
        if dom_jobs:
            print(f"[MCF] '{keyword}' pg {pg}: {len(dom_jobs)} jobs via DOM")
            return dom_jobs

        print(f"[MCF] '{keyword}' pg {pg}: 0 jobs found")
        return []

    def _from_next_data(self, page, keyword: str, pg: int) -> list:
        """Read the __NEXT_DATA__ JSON that Next.js embeds in every page."""
        try:
            raw = page.evaluate(
                "() => {"
                "  const el = document.getElementById('__NEXT_DATA__');"
                "  return el ? el.textContent : null;"
                "}"
            )
            if not raw:
                return []

            data = json.loads(raw)
            props = data.get("props", {}).get("pageProps", {})

            # MCF stores results under various keys depending on version
            candidates = [
                props.get("results"),
                props.get("jobs"),
                props.get("searchResults"),
                props.get("initialData", {}).get("results") if isinstance(props.get("initialData"), dict) else None,
                props.get("data", {}).get("results") if isinstance(props.get("data"), dict) else None,
            ]
            for c in candidates:
                if isinstance(c, list) and c:
                    return c

            # Deep search: find any list of dicts that has a 'title' key
            return self._deep_find_results(props)

        except Exception as exc:
            print(f"[MCF] __NEXT_DATA__ parse error: {exc}")
            return []

    def _deep_find_results(self, obj, depth: int = 0) -> list:
        """Recursively find the first list of job-like dicts."""
        if depth > 5:
            return []
        if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "title" in obj[0]:
            return obj
        if isinstance(obj, dict):
            for v in obj.values():
                found = self._deep_find_results(v, depth + 1)
                if found:
                    return found
        return []

    def _parse_dom(self, page) -> list[dict]:
        """Fallback: extract job cards directly from the rendered DOM."""
        jobs = []
        try:
            # MCF uses various card patterns across versions
            selectors = [
                "article[data-testid]",
                "[data-testid='job-card']",
                "article",
                "[class*='JobCard']",
                "[class*='job-card']",
            ]
            cards = []
            for sel in selectors:
                cards = page.query_selector_all(sel)
                if cards:
                    break

            for card in cards:
                try:
                    title_el  = card.query_selector("h2, h3, [data-testid='job-title'], [class*='title']")
                    comp_el   = card.query_selector("[data-testid='company-name'], [class*='company'], [class*='Company']")
                    link_el   = card.query_selector("a[href*='/job/']")
                    salary_el = card.query_selector("[data-testid='salary'], [class*='salary'], [class*='Salary']")

                    title = title_el.inner_text().strip() if title_el else ""
                    if not title:
                        continue

                    href  = link_el.get_attribute("href") if link_el else ""
                    if href and not href.startswith("http"):
                        href = "https://www.mycareersfuture.gov.sg" + href

                    match = re.search(r"/job/([a-zA-Z0-9\-]+)", href or "")
                    jid   = match.group(1) if match else hashlib.md5(title.encode()).hexdigest()[:16]

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
                except Exception:
                    continue
        except Exception as exc:
            print(f"[MCF] DOM parse error: {exc}")
        return jobs

    def _normalise(self, raw: dict) -> dict:
        salary = raw.get("salary", {}) or {}
        sal_str = ""
        if isinstance(salary, dict):
            lo, hi = salary.get("minimum"), salary.get("maximum")
            if lo and hi:
                sal_str = f"SGD {lo:,} - {hi:,} / month"
            elif lo:
                sal_str = f"SGD {lo:,}+ / month"
        elif isinstance(salary, str):
            sal_str = salary

        desc = raw.get("description", "") or ""
        desc = re.sub(r"<[^>]+>", " ", desc).strip()

        uuid = raw.get("uuid", "")
        company = (
            raw.get("postedCompany", {}).get("name", "")
            or raw.get("company", "")
            or raw.get("companyName", "")
        )
        return {
            "id":          f"mcf_{uuid or self._make_id(raw)}",
            "platform":    self.name,
            "title":       raw.get("title", ""),
            "company":     company,
            "location":    "Singapore",
            "salary":      sal_str,
            "description": desc[:4000],
            "url":         f"https://www.mycareersfuture.gov.sg/job/{uuid}" if uuid else "",
            "posted_at":   raw.get("newPostingDate", raw.get("postedDate", "")),
        }

    @staticmethod
    def _make_id(job: dict) -> str:
        key = f"{job.get('title', '')}{job.get('company', '')}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
