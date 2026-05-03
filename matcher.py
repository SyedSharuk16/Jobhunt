"""
Claude-powered job ↔ resume matcher.
Uses claude-haiku for fast, cheap batch scoring.
"""

import json
import os
import anthropic

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


_SYSTEM = """\
You are a precise job-match evaluator. Given a candidate profile and a job posting,
return a JSON object with these fields:
- "score": integer 0-100 (100 = perfect match)
- "highlights": list of up to 3 strings — why this role suits the candidate
- "concerns": list of up to 3 strings — gaps or mismatches
- "verdict": one of "Strong Match", "Good Match", "Weak Match", "Not Relevant"

Respond ONLY with valid JSON. No markdown, no preamble.\
"""


def score_job(job: dict, resume: dict) -> dict:
    """
    Ask Claude to score one job against the resume.
    Returns the score_data dict (score, highlights, concerns, verdict).
    Falls back to a neutral score on any error.
    """
    prompt = f"""CANDIDATE PROFILE:
Name: {resume.get('name', 'Candidate')}
Target roles: {', '.join(resume.get('target_titles', []))}
Skills: {', '.join(resume.get('skills', []))}
Years of experience: {resume.get('years_experience', 'unknown')}
Education: {resume.get('education', '')}
Summary: {resume.get('summary', '')}
Preferred industries: {', '.join(resume.get('preferred_industries', []) or [])}
Desired salary (SGD/month): {resume.get('salary_min_sgd', '?')} – {resume.get('salary_max_sgd', '?')}

JOB POSTING:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Location: {job.get('location', '')}
Salary: {job.get('salary', 'not stated')}
Description:
{job.get('description', 'No description available.')[:2000]}
"""

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        data = json.loads(text)
        # Validate and clamp score
        data["score"] = max(0, min(100, int(data.get("score", 50))))
        return data
    except json.JSONDecodeError:
        return {"score": 50, "highlights": [], "concerns": ["Parse error"], "verdict": "Unknown"}
    except Exception as exc:
        print(f"[Matcher] error scoring '{job.get('title')}': {exc}")
        return {"score": 50, "highlights": [], "concerns": [str(exc)], "verdict": "Unknown"}


def score_jobs_batch(jobs: list[dict], resume: dict,
                     on_progress=None) -> list[dict]:
    """
    Score a list of jobs. Injects 'score' and 'score_data' into each dict.
    on_progress(current, total) called after each job if provided.
    """
    total = len(jobs)
    for i, job in enumerate(jobs):
        result = score_job(job, resume)
        job["score"]      = result["score"]
        job["score_data"] = result
        if on_progress:
            on_progress(i + 1, total)
    return jobs
