#!/usr/bin/env bash
set -e

echo "=== JobHunt Bot Setup ==="

# Python deps
pip install -r requirements.txt

# Playwright browsers (Chromium only — ~150 MB)
playwright install chromium
playwright install-deps chromium

# Create .env from template if it doesn't exist
if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo "Created .env — open it and fill in your credentials + API key."
fi

echo ""
echo "Setup complete. Next steps:"
echo "  1. Edit .env       — add ANTHROPIC_API_KEY and job portal credentials"
echo "  2. Edit config.py  — fill in your resume profile"
echo "  3. Run: python main.py"
