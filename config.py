"""
Edit this file to match YOUR resume before running the bot.
The more detail you add, the better Claude can score job matches.
"""

# ── YOUR RESUME PROFILE ────────────────────────────────────────────────────────
# Fill every field. Claude uses this to score every scraped job 0-100.

RESUME = {
    "name": "Your Name",

    # The exact job titles you are targeting (drives search queries)
    "target_titles": [
        "Software Engineer",
        "Backend Engineer",
        "Full Stack Developer",
    ],

    # Your core technical skills
    "skills": [
        "Python",
        "FastAPI",
        "Django",
        "PostgreSQL",
        "Redis",
        "AWS",
        "Docker",
        "Git",
    ],

    # Total years of professional experience
    "years_experience": 3,

    # Highest education level
    "education": "Bachelor of Computer Science",

    # Industries you prefer (leave empty [] to consider all)
    "preferred_industries": [
        "Technology",
        "FinTech",
        "E-Commerce",
    ],

    # Employment type preferences
    "employment_type": ["Full-Time", "Contract"],

    # Desired monthly salary range in SGD (set to None to ignore)
    "salary_min_sgd": 4000,
    "salary_max_sgd": 8000,

    # Brief summary used as context for Claude scoring
    "summary": (
        "3-year backend Python developer with experience building REST APIs "
        "and microservices. Strong in FastAPI, PostgreSQL, AWS. Looking for "
        "backend or full-stack roles in Singapore tech companies."
    ),
}

# ── SEARCH SETTINGS ────────────────────────────────────────────────────────────

# Keywords sent to each platform's search box.
# Add synonyms and related titles to cast a wider net.
SEARCH_KEYWORDS = [
    "Python developer",
    "Backend engineer",
    "Software engineer",
    "Full stack developer",
]

# Always filter results to Singapore
LOCATION = "Singapore"

# ── PLATFORM TOGGLES ───────────────────────────────────────────────────────────
PLATFORMS = {
    "mycareers_future": True,   # government portal, free API — recommended
    "jobstreet":        True,   # requires JOBSTREET_EMAIL / PASSWORD in .env
    "linkedin":         True,   # requires LINKEDIN_EMAIL / PASSWORD in .env
    "indeed":           True,   # works without login
}
