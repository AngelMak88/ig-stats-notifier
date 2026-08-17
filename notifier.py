import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

import requests
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "instagram-looter2.p.rapidapi.com"
API_BASE = f"https://{RAPIDAPI_HOST}"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

IG_USERNAMES = [
    u.strip().lstrip("@")
    for u in (
        os.environ.get("IG_USERNAMES")
        or "mynamesophiaaa,yourfavoritesophiaaa,sophiaamaryme1,itssophia.mr"
    ).split(",")
    if u.strip()
]

# Weekday name (Python %A, e.g. "Monday") on which the follower count is
# also checked/reported, in addition to the daily views check. Kept low
# frequency because the free RapidAPI plan is capped at 150 requests/month:
# daily views alone is already 4 accounts x ~30 days = ~120 calls/month,
# leaving only ~30/month (~1x/week for 4 accounts) of headroom.
WEEKLY_FOLLOWER_CHECK_DAY = os.environ.get("WEEKLY_FOLLOWER_CHECK_DAY") or "Sunday"

STATE_PATH = os.path.join(BASE_DIR, "state.json")
RECENT_REELS_COUNT = 5

LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logger = logging.getLogger("notifier")
logger.setLevel(logging.INFO)
_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "notifier.log"),
    maxBytes=1_000_000,
    backupCount=3,
    encoding="utf-8",
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_handler)
logger.addHandler(logging.StreamHandler())


class NotifierError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# RapidAPI client (Instagram Looter2, host: instagram-looter2.p.rapidapi.com)
#
# Endpoints + response shapes below were confirmed live on 2026-08-17
# against real accounts:
#
#   GET /profile?username=<username>
#     -> top-level dict (NOT nested under "user"). Relevant fields:
#        id (numeric IG user id, needed for /reels below), username,
#        edge_followed_by.count (followers), edge_follow.count (following),
#        edge_owner_to_timeline_media.count (media_count).
#
#   GET /reels?id=<numeric_user_id>&count=<n>
#     -> {"items": [{"media": {...}}], "paging_info": {...}, "status": true}
#        Each item's "media" dict has: play_count, like_count,
#        comment_count, code, pk, taken_at.
# ---------------------------------------------------------------------------


def rapidapi_get(path, params, retries=2):
    if not RAPIDAPI_KEY:
        raise NotifierError("RAPIDAPI_KEY is not set. Add it to your .env file.")

    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key": RAPIDAPI_KEY,
    }
    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(
                API_BASE + path, headers=headers, params=params, timeout=30
            )
            if resp.status_code != 200:
                raise NotifierError(
                    f"RapidAPI request to {path} failed "
                    f"({resp.status_code}): {resp.text[:300]}"
                )
            return resp.json()
        except (requests.RequestException, NotifierError) as exc:
            last_exc = exc
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise last_exc


def fetch_profile(username):
    raw = rapidapi_get("/profile", {"username": username})
    followers = (raw.get("edge_followed_by") or {}).get("count")
    following = (raw.get("edge_follow") or {}).get("count")
    media_count = (raw.get("edge_owner_to_timeline_media") or {}).get("count")
    user_id = raw.get("id")

    if followers is None or user_id is None:
        raise NotifierError(
            f"Unexpected /profile response for {username}: {str(raw)[:500]}"
        )

    return {
        "user_id": str(user_id),
        "followers": int(followers),
        "following": int(following) if following is not None else None,
        "media_count": int(media_count) if media_count is not None else None,
    }


def fetch_recent_reel_views(user_id):
    raw = rapidapi_get("/reels", {"id": user_id, "count": RECENT_REELS_COUNT})
    items = raw.get("items") or []
    views = []
    for item in items[:RECENT_REELS_COUNT]:
        media = item.get("media") or {}
        play_count = media.get("play_count")
        if play_count is not None:
            views.append(int(play_count))
    return views


# ---------------------------------------------------------------------------
# State (previous run snapshot, for deltas)
# ---------------------------------------------------------------------------


def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def fmt_delta(delta):
    if delta > 0:
        return f" (+{delta:,})"
    if delta < 0:
        return f" ({delta:,})"
    return ""


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise NotifierError(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID is not set. Add them to your .env file."
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=30
    )
    if resp.status_code != 200:
        raise NotifierError(
            f"Telegram sendMessage failed ({resp.status_code}): {resp.text[:300]}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    if not IG_USERNAMES:
        raise NotifierError("IG_USERNAMES is empty. Add at least one username.")

    now = datetime.now(timezone.utc)
    check_followers_today = now.strftime("%A") == WEEKLY_FOLLOWER_CHECK_DAY

    state = load_state()
    lines = [f"\U0001F4CA IG Stats — {now.strftime('%d %b')}", ""]
    any_success = False

    for username in IG_USERNAMES:
        account = state.get(username, {})
        account_lines = [f"@{username}"]

        try:
            # Bootstrap: we always need the numeric user_id for /reels.
            # Fetch it (and followers, opportunistically) if we don't have
            # it cached yet, or if today is the weekly follower-check day.
            if check_followers_today or "user_id" not in account:
                profile = fetch_profile(username)
                prev_followers = account.get("followers", profile["followers"])
                followers_delta = profile["followers"] - prev_followers
                account.update(profile)
                account["followers_checked_at"] = now.isoformat()
                account_lines.append(
                    f"\U0001F465 {profile['followers']:,} followers"
                    f"{fmt_delta(followers_delta)}"
                )

            recent_views = fetch_recent_reel_views(account["user_id"])
            views_total = sum(recent_views)
            prev_views_total = account.get("recent_views_total", views_total)
            views_delta = views_total - prev_views_total
            account["recent_views_total"] = views_total
            account["recent_views_count"] = len(recent_views)
            account["recent_views_checked_at"] = now.isoformat()

            if recent_views:
                account_lines.append(
                    f"\U0001F441 {views_total:,} views στα τελευταία "
                    f"{len(recent_views)} reels{fmt_delta(views_delta)}"
                )

            any_success = True
            state[username] = account
        except NotifierError as exc:
            logger.error("Failed to fetch stats for %s: %s", username, exc)
            account_lines.append(f"⚠️ could not fetch stats ({exc})")
            state[username] = account

        lines.extend(account_lines)
        lines.append("")

    save_state(state)

    message = "\n".join(lines).strip()
    logger.info("Sending Telegram message:\n%s", message)
    send_telegram_message(message)

    if not any_success:
        raise NotifierError("All accounts failed to fetch stats; see log above.")


if __name__ == "__main__":
    try:
        main()
    except NotifierError as exc:
        logger.error("Run failed: %s", exc)
        raise SystemExit(1)
