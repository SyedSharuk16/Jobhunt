"""
Telegram notifier — sends daily job match summary to your phone.

Setup (one time):
  1. Open Telegram → search @BotFather → send /newbot → follow prompts → copy token
  2. Start a chat with your new bot (just send /start)
  3. Visit https://api.telegram.org/bot<TOKEN>/getUpdates to get your chat_id
  4. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to GitHub Secrets / .env
"""

import json
import os
import time
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _post(method: str, payload: dict) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        print("[Telegram] token or chat_id not set — skipping notification")
        return False
    try:
        r = requests.post(f"{API}/{method}", json=payload, timeout=15)
        r.raise_for_status()
        return True
    except Exception as exc:
        print(f"[Telegram] {method} failed: {exc}")
        return False


def _send(text: str, parse_mode: str = "HTML") -> bool:
    return _post("sendMessage", {
        "chat_id":    CHAT_ID,
        "text":       text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    })


def _get_updates(offset: int | None = None, timeout: int = 5) -> list[dict]:
    """Long-poll Telegram for new messages."""
    params: dict = {"limit": 20, "timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(f"{API}/getUpdates", params=params,
                         timeout=timeout + 5)
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception:
        return []


def wait_for_otp(platform: str = "JobStreet", timeout: int = 180) -> str | None:
    """
    Alert the user via Telegram that an OTP is needed, then block until
    they reply with it (or until timeout seconds elapse).

    Returns the OTP string, or None on timeout.
    """
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[Telegram] Cannot request OTP — bot not configured.")
        return None

    # Drain any old pending updates so we only catch fresh replies
    existing = _get_updates(timeout=0)
    offset = existing[-1]["update_id"] + 1 if existing else None

    _send(
        f"🔐 <b>{platform} needs your OTP</b>\n\n"
        f"Check your email — an OTP was just sent.\n"
        f"<b>Reply to this message with the code.</b>\n\n"
        f"⏳ You have {timeout // 60} minutes."
    )
    print(f"[Telegram] Waiting up to {timeout}s for OTP reply…")

    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = int(deadline - time.time())
        # Use short long-poll windows so we stay responsive
        poll_secs = min(10, remaining)
        if poll_secs <= 0:
            break

        updates = _get_updates(offset=offset, timeout=poll_secs)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            # Only accept messages from the configured chat
            if str(msg.get("chat", {}).get("id", "")) != str(CHAT_ID):
                continue
            text = msg.get("text", "").strip()
            # Accept 4–8 digit numeric codes
            if text.isdigit() and 4 <= len(text) <= 8:
                _send(f"✅ Got it! Entering OTP <code>{text}</code> now…")
                return text

    _send(
        f"⏰ <b>OTP timeout</b> — no code received within {timeout // 60} min.\n"
        f"{platform} login skipped for today's run."
    )
    return None


def _send_document(path: str, caption: str = "") -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        return False
    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"{API}/sendDocument",
                data={"chat_id": CHAT_ID, "caption": caption},
                files={"document": f},
                timeout=60,
            )
        r.raise_for_status()
        return True
    except Exception as exc:
        print(f"[Telegram] sendDocument failed: {exc}")
        return False


# ── Platform display names ────────────────────────────────────────────────────
_PLAT_LABEL = {
    "mycareers_future": "MyCareersFuture",
    "jobstreet":        "JobStreet",
    "linkedin":         "LinkedIn",
    "indeed":           "Indeed SG",
}

_VERDICT_EMOJI = {
    "Strong Match": "🟢",
    "Good Match":   "🔵",
    "Weak Match":   "🟡",
    "Not Relevant": "⚫",
}


def notify(jobs: list[dict], stats: dict, report_path: str | None = None) -> None:
    """
    Send the daily digest to Telegram.
    Always sends a header with scrape stats, then top matches.
    """
    total_scraped = stats.get("total", 0)
    by_plat       = stats.get("by_platform", {})

    plat_lines = "\n".join(
        f"  • {_PLAT_LABEL.get(p, p)}: {n}"
        for p, n in by_plat.items()
    ) or "  • No platforms returned results"

    if not jobs:
        _send(
            f"🔍 <b>Daily Job Hunt — Singapore</b>\n\n"
            f"<b>Jobs scraped:</b> {total_scraped}\n"
            f"{plat_lines}\n\n"
            f"⚠️ None met the score threshold today.\n"
            f"<i>Check GitHub Actions logs for details.</i>"
        )
        return

    strong = [j for j in jobs if isinstance(j.get("score_data_obj"), dict)
              and "Strong" in j["score_data_obj"].get("verdict", "")]
    good   = [j for j in jobs if isinstance(j.get("score_data_obj"), dict)
              and j["score_data_obj"].get("verdict") == "Good Match"]

    header = (
        f"🎯 <b>Daily Job Hunt — Singapore</b>\n\n"
        f"<b>Jobs scraped:</b> {total_scraped}\n"
        f"{plat_lines}\n\n"
        f"🟢 Strong matches: {len(strong)}\n"
        f"🔵 Good matches:   {len(good)}\n"
        f"📋 Showing top {min(len(jobs), 10)}\n\n"
        f"<i>Top matches below ↓</i>"
    )
    _send(header)

    # Send top 10 jobs (strong first, then good, then rest by score)
    top = sorted(jobs, key=lambda j: j.get("score") or 0, reverse=True)[:10]

    for job in top:
        sd      = job.get("score_data_obj") or {}
        verdict = sd.get("verdict", "") if isinstance(sd, dict) else ""
        emoji   = _VERDICT_EMOJI.get(verdict, "⚪")
        score   = job.get("score") or 0
        salary  = f"\n💰 {job['salary']}" if job.get("salary") else ""

        highlights = sd.get("highlights", []) if isinstance(sd, dict) else []
        hl_text    = ""
        if highlights:
            hl_text = "\n✅ " + "\n✅ ".join(highlights[:2])

        concerns = sd.get("concerns", []) if isinstance(sd, dict) else []
        co_text  = ""
        if concerns:
            co_text = "\n⚠️ " + concerns[0]

        apply_btn = f'\n\n👉 <a href="{job["url"]}">Apply now</a>' if job.get("url") else ""

        card = (
            f"{emoji} <b>{job['title']}</b>\n"
            f"🏢 {job.get('company', 'Unknown')}\n"
            f"📍 {job.get('location', 'Singapore')}\n"
            f"⭐ Score: {score}/100  |  {verdict}"
            f"{salary}"
            f"{hl_text}"
            f"{co_text}"
            f"{apply_btn}"
        )
        _send(card)

    # Attach the full HTML report so they can browse all jobs in mobile browser
    if report_path and os.path.exists(report_path):
        _send_document(
            report_path,
            caption=f"📄 Full report — {len(jobs)} jobs. Open in browser to filter."
        )
