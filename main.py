#!/usr/bin/env python3
"""
JobHunt Bot — Singapore job scraper + Claude AI matcher.

Usage:
    python main.py              # run all enabled platforms
    python main.py --platform mcf            # only MyCareersFuture
    python main.py --no-score                # skip Claude scoring
    python main.py --min-score 70            # only report jobs scoring 70+
    python main.py --csv                     # also export CSV
    python main.py --pages 10               # scrape 10 pages per keyword/platform
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich import print as rprint

load_dotenv()

import config
import database
import matcher
import reporter
from scrapers import (
    MyCareersFutureScraper,
    JobStreetScraper,
    LinkedInScraper,
    IndeedScraper,
)

console = Console()

SCRAPER_MAP = {
    "mycareers_future": MyCareersFutureScraper,
    "mcf":              MyCareersFutureScraper,
    "jobstreet":        JobStreetScraper,
    "js":               JobStreetScraper,
    "linkedin":         LinkedInScraper,
    "li":               LinkedInScraper,
    "indeed":           IndeedScraper,
    "ind":              IndeedScraper,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Singapore Job Hunt Bot")
    p.add_argument("--platform", "-p",
                   help="Run only this platform (mcf|jobstreet|linkedin|indeed)")
    p.add_argument("--pages", "-n", type=int,
                   default=int(os.getenv("SCRAPE_PAGES", 5)),
                   help="Pages to scrape per keyword per platform (default 5)")
    p.add_argument("--no-score", action="store_true",
                   help="Skip Claude AI scoring (faster, no API cost)")
    p.add_argument("--min-score", type=int,
                   default=int(os.getenv("MIN_SCORE", 60)),
                   help="Minimum score to include in report (default 60)")
    p.add_argument("--csv", action="store_true",
                   help="Also export a CSV report")
    p.add_argument("--report-only", action="store_true",
                   help="Skip scraping; generate report from existing DB")
    return p


def select_platforms(platform_arg: str | None) -> list[str]:
    if platform_arg:
        key = platform_arg.lower()
        if key not in SCRAPER_MAP:
            console.print(f"[red]Unknown platform '{platform_arg}'. "
                          f"Choose from: {', '.join(SCRAPER_MAP)}")
            sys.exit(1)
        canonical = SCRAPER_MAP[key]().__class__.__name__
        # map back to config key
        name_map = {
            "MyCareersFutureScraper": "mycareers_future",
            "JobStreetScraper":       "jobstreet",
            "LinkedInScraper":        "linkedin",
            "IndeedScraper":          "indeed",
        }
        return [name_map[canonical]]
    return [k for k, enabled in config.PLATFORMS.items() if enabled]


def run_scraper(name: str, pages: int) -> list[dict]:
    cls = SCRAPER_MAP.get(name)
    if cls is None:
        console.print(f"[yellow]No scraper registered for '{name}', skipping.")
        return []
    scraper = cls()
    console.print(f"  [cyan]Scraping[/cyan] [bold]{name}[/bold] "
                  f"({len(config.SEARCH_KEYWORDS)} keywords × {pages} pages)…")
    try:
        jobs = scraper.scrape(config.SEARCH_KEYWORDS, config.LOCATION, pages)
        console.print(f"  [green]✓[/green] {len(jobs)} jobs from {name}")
        return jobs
    except Exception as exc:
        console.print(f"  [red]✗[/red] {name} failed: {exc}")
        return []


def main() -> None:
    args = build_parser().parse_args()

    # Verify API key when scoring
    if not args.no_score and not os.getenv("ANTHROPIC_API_KEY"):
        console.print(
            "[red]ANTHROPIC_API_KEY not set.[/red] "
            "Add it to .env or run with --no-score to skip scoring."
        )
        sys.exit(1)

    database.init_db()

    # ── SCRAPING ──────────────────────────────────────────────────────────────
    all_raw: list[dict] = []
    if not args.report_only:
        platforms = select_platforms(args.platform)
        console.rule("[bold]Scraping Jobs")
        for name in platforms:
            jobs = run_scraper(name, args.pages)
            all_raw.extend(jobs)

        console.print(f"\n[bold]Total scraped:[/bold] {len(all_raw)} jobs")

        # Persist all raw jobs first (score=None)
        new_count = 0
        for job in all_raw:
            if database.upsert_job(job):
                new_count += 1
        console.print(f"[bold]New jobs:[/bold] {new_count} (duplicates skipped)")

    # ── SCORING ───────────────────────────────────────────────────────────────
    if not args.no_score:
        unscored = [j for j in database.get_jobs() if j.get("score") is None]
        if unscored:
            console.rule("[bold]Scoring with Claude AI")
            console.print(f"  Scoring {len(unscored)} jobs against your resume…")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Scoring", total=len(unscored))

                def on_progress(current, total):
                    progress.update(task, completed=current)

                scored = matcher.score_jobs_batch(
                    unscored, config.RESUME, on_progress=on_progress
                )

            for job in scored:
                database.upsert_job(job)

            console.print(f"  [green]✓[/green] Scored {len(unscored)} jobs")
        else:
            console.print("[dim]All jobs already scored.[/dim]")

    # ── REPORT ────────────────────────────────────────────────────────────────
    console.rule("[bold]Generating Report")
    jobs_for_report = database.get_jobs(min_score=args.min_score if not args.no_score else 0)

    html_path = reporter.generate_html(jobs_for_report, config.RESUME, args.min_score)
    console.print(f"  [green]HTML report:[/green] {html_path}")

    if args.csv:
        csv_path = reporter.generate_csv(jobs_for_report)
        console.print(f"  [green]CSV  report:[/green] {csv_path}")

    # ── SUMMARY TABLE ─────────────────────────────────────────────────────────
    st = database.stats()
    console.rule("[bold]Summary")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Platform")
    table.add_column("Jobs", justify="right")
    for plat, n in st["by_platform"].items():
        table.add_row(plat, str(n))
    table.add_row("[bold]TOTAL", f"[bold]{st['total']}")
    console.print(table)

    top_jobs = [j for j in jobs_for_report if j.get("score") and j["score"] >= 75][:5]
    if top_jobs:
        console.print("\n[bold yellow]Top 5 matches:[/bold yellow]")
        for j in top_jobs:
            sd = j.get("score_data_obj") or {}
            verdict = sd.get("verdict", "") if isinstance(sd, dict) else ""
            console.print(
                f"  [green]{j['score']:>3}[/green]  "
                f"[bold]{j['title']}[/bold] @ {j['company']}  "
                f"[dim]{j['platform']}[/dim]  "
                f"[cyan]{verdict}[/cyan]"
            )

    console.print(f"\n[bold green]Done.[/bold green] Open {html_path} in your browser.")


if __name__ == "__main__":
    main()
