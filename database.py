import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "jobs.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id          TEXT PRIMARY KEY,
                platform    TEXT NOT NULL,
                title       TEXT NOT NULL,
                company     TEXT,
                location    TEXT,
                salary      TEXT,
                description TEXT,
                url         TEXT,
                posted_at   TEXT,
                score       INTEGER,
                score_data  TEXT,
                scraped_at  TEXT NOT NULL,
                seen        INTEGER DEFAULT 0
            )
        """)
        conn.commit()


def job_exists(job_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return row is not None


def upsert_job(job: dict) -> bool:
    """Insert or update a job. Returns True if this is a new job."""
    now = datetime.utcnow().isoformat()
    is_new = not job_exists(job["id"])

    with _connect() as conn:
        conn.execute("""
            INSERT INTO jobs
                (id, platform, title, company, location, salary, description,
                 url, posted_at, score, score_data, scraped_at)
            VALUES
                (:id, :platform, :title, :company, :location, :salary, :description,
                 :url, :posted_at, :score, :score_data, :scraped_at)
            ON CONFLICT(id) DO UPDATE SET
                score      = excluded.score,
                score_data = excluded.score_data,
                scraped_at = excluded.scraped_at
        """, {
            "id":          job["id"],
            "platform":    job["platform"],
            "title":       job["title"],
            "company":     job.get("company", ""),
            "location":    job.get("location", ""),
            "salary":      job.get("salary", ""),
            "description": job.get("description", ""),
            "url":         job.get("url", ""),
            "posted_at":   job.get("posted_at", ""),
            "score":       job.get("score"),
            "score_data":  json.dumps(job.get("score_data")) if job.get("score_data") else None,
            "scraped_at":  now,
        })
        conn.commit()

    return is_new


def get_jobs(min_score: int = 0, limit: int = 500) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM jobs
            WHERE (score IS NULL OR score >= ?)
            ORDER BY score DESC, scraped_at DESC
            LIMIT ?
        """, (min_score, limit)).fetchall()
        return [dict(r) for r in rows]


def stats() -> dict:
    with _connect() as conn:
        total   = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        scored  = conn.execute("SELECT COUNT(*) FROM jobs WHERE score IS NOT NULL").fetchone()[0]
        by_plat = conn.execute(
            "SELECT platform, COUNT(*) as n FROM jobs GROUP BY platform"
        ).fetchall()
        return {
            "total":    total,
            "scored":   scored,
            "by_platform": {r["platform"]: r["n"] for r in by_plat},
        }
