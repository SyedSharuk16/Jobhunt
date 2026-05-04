“””
Yusraa Shifaa — Job Automation Bot Config
Last updated: May 2026
“””

# ── YOUR RESUME PROFILE ────────────────────────────────────────────────────────

RESUME = {
“name”: “Yusraa Shifaa”,

```
# The exact job titles you are targeting (drives search queries)
"target_titles": [
    "HR Business Partner",
    "Senior HR Executive",
    "HR Generalist",
    "People & Culture Executive",
    "HR Manager",
    "L&D Executive",
],

# Your core skills
"skills": [
    "HR Business Partnering",
    "Talent Acquisition",
    "Performance Management",
    "Employee Relations",
    "Learning & Development",
    "Workforce Planning",
    "Organisational Development",
    "Job Redesign",
    "Government Grants (SkillsFuture, WSG, SNEF)",
    "MOM Compliance",
    "Employment Act",
    "Onboarding & Offboarding",
    "Payroll Processing",
    "Change Management",
    "Employee Engagement",
    "Microsoft Office",
    "Google Suite",
    "Canva",
    "Bilingual English and Tamil",
],

# Total years of professional experience
"years_experience": 3,

# Highest education level
"education": "Diploma in Human Resource Management with Psychology, Republic Polytechnic (2023)",

# Industries you prefer (leave empty [] to consider all)
"preferred_industries": [
    "Human Resources",
    "Professional Services",
    "Logistics & Supply Chain",
    "F&B / Hospitality",
    "Aviation",
    "Non-Profit / Social Services",
    "Government / Statutory Boards",
],

# Employment type preferences
"employment_type": ["Full-Time"],

# Desired monthly salary range in SGD
"salary_min_sgd": 4000,   # ⚠️ Confirm with Yusraa
"salary_max_sgd": 6500,   # ⚠️ Confirm with Yusraa

# Brief summary used as context for Claude scoring
"summary": (
    "HR professional with 3+ years of full-spectrum HR experience covering "
    "talent acquisition, performance management, employee relations, L&D, "
    "and government grant administration. Currently operating as HR Business "
    "Partner across SME and corporate environments. Holds a Diploma in HR "
    "Management with Psychology. MOM/Employment Act compliant. Bilingual in "
    "English and Tamil. Based in Singapore, no sponsorship required."
),
```

}

# ── SEARCH SETTINGS ────────────────────────────────────────────────────────────

SEARCH_KEYWORDS = [
“HR Business Partner”,
“Senior HR Executive”,
“HR Generalist”,
“People and Culture”,
“Human Resources Manager”,
“HR Officer”,
“L&D Executive”,
“Talent Acquisition”,
“HR Operations”,
]

LOCATION = “Singapore”

# ── PLATFORM TOGGLES ───────────────────────────────────────────────────────────

PLATFORMS = {
“mycareers_future”: True,   # best for SG HR roles — government portal, free API
“jobstreet”:        True,   # strong HR listings in SG — requires JOBSTREET_EMAIL / PASSWORD in .env
“linkedin”:         True,   # requires LINKEDIN_EMAIL / PASSWORD in .env
“indeed”:           True,   # works without login
}
