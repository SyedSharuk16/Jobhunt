import csv
import json
import os
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


TEMPLATES_DIR = Path(__file__).parent / "templates"
REPORTS_DIR   = Path(__file__).parent / "reports"


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def generate_html(jobs: list[dict], resume: dict, min_score: int = 0) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path  = REPORTS_DIR / f"report_{timestamp}.html"

    # Attach parsed score_data for the template
    for job in jobs:
        raw = job.get("score_data")
        if isinstance(raw, str):
            try:
                job["score_data_obj"] = json.loads(raw)
            except json.JSONDecodeError:
                job["score_data_obj"] = {}
        elif isinstance(raw, dict):
            job["score_data_obj"] = raw
        else:
            job["score_data_obj"] = {}

    by_platform = {}
    for j in jobs:
        by_platform[j["platform"]] = by_platform.get(j["platform"], 0) + 1

    strong_count = sum(1 for j in jobs
                       if isinstance(j.get("score_data_obj"), dict)
                       and "Strong" in j["score_data_obj"].get("verdict", ""))
    good_count   = sum(1 for j in jobs
                       if isinstance(j.get("score_data_obj"), dict)
                       and j["score_data_obj"].get("verdict") == "Good Match")

    tmpl = _env().get_template("report.html")
    html = tmpl.render(
        jobs            = jobs,
        generated_at    = datetime.now().strftime("%d %b %Y %H:%M"),
        candidate_name  = resume.get("name", "Candidate"),
        total_jobs      = len(jobs),
        strong_count    = strong_count,
        good_count      = good_count,
        by_platform     = by_platform,
        min_score       = min_score,
    )
    out_path.write_text(html, encoding="utf-8")
    return out_path


def generate_csv(jobs: list[dict]) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path  = REPORTS_DIR / f"report_{timestamp}.csv"

    fields = ["score", "verdict", "title", "company", "location", "salary",
              "platform", "url", "posted_at", "highlights", "concerns"]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for job in jobs:
            sd = job.get("score_data_obj") or {}
            row = {
                "score":      job.get("score", ""),
                "verdict":    sd.get("verdict", ""),
                "title":      job.get("title", ""),
                "company":    job.get("company", ""),
                "location":   job.get("location", ""),
                "salary":     job.get("salary", ""),
                "platform":   job.get("platform", ""),
                "url":        job.get("url", ""),
                "posted_at":  job.get("posted_at", ""),
                "highlights": " | ".join(sd.get("highlights", [])),
                "concerns":   " | ".join(sd.get("concerns", [])),
            }
            writer.writerow(row)

    return out_path
