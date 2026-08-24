import os
import json
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "stats.json")

DEFAULT_TOKENS = ["🔴", "🔵", "🟢", "🟡"]
ALL_UNLOCKED_TOKENS = ["🔴", "🔵", "🟢", "🟡", "🏎️", "🚀", "👑", "🐉", "💎", "🦁", "⚡", "🏆"]

def load_db() -> dict:
    if os.path.exists(DB_PATH):
        try:
            with open(DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_db(data: dict):
    """Atomically writes JSON to a temporary file then replaces target to avoid corruption on crashes."""
    tmp_path = f"{DB_PATH}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, DB_PATH)
    except Exception:
        # Fallback direct write if os.replace fails
        try:
            with open(DB_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

def get_player_stats(user_id: int, display_name: str) -> dict:
    db = load_db()
    uid_str = str(user_id)
    if uid_str not in db:
        db[uid_str] = {
            "display_name": display_name,
            "games_played": 0,
            "wins": 0,
            "properties_bought": 0,
            "bankruptcies_caused": 0,
            "last_daily": 0,
            "daily_streak": 0,
            "custom_token": None,
            "bonus_cash": 0
        }
        save_db(db)
    else:
        if db[uid_str].get("display_name") != display_name:
            db[uid_str]["display_name"] = display_name
            save_db(db)
    return db[uid_str]

def record_game_win(winner_id: int, all_player_ids: list[int]):
    db = load_db()
    for pid in all_player_ids:
        uid_str = str(pid)
        if uid_str not in db:
            db[uid_str] = {
                "display_name": f"Player {pid}",
                "games_played": 0,
                "wins": 0,
                "properties_bought": 0,
                "bankruptcies_caused": 0,
                "last_daily": 0,
                "daily_streak": 0,
                "custom_token": None,
                "bonus_cash": 0
            }
        db[uid_str]["games_played"] += 1
        if pid == winner_id:
            db[uid_str]["wins"] += 1
    save_db(db)

def claim_daily(user_id: int, display_name: str) -> tuple[bool, str, int]:
    db = load_db()
    uid_str = str(user_id)
    if uid_str not in db:
        db[uid_str] = {
            "display_name": display_name,
            "games_played": 0,
            "wins": 0,
            "properties_bought": 0,
            "bankruptcies_caused": 0,
            "last_daily": 0,
            "daily_streak": 0,
            "custom_token": None,
            "bonus_cash": 0
        }
    p_data = db[uid_str]
    p_data["display_name"] = display_name
    now = time.time()
    cooldown = 86400  # 24 hours

    elapsed = now - p_data.get("last_daily", 0)
    if elapsed < cooldown:
        remaining_secs = int(cooldown - elapsed)
        hours = remaining_secs // 3600
        mins = (remaining_secs % 3600) // 60
        return False, f"⏳ You have already claimed your daily bonus today! Please wait **{hours}h {mins}m**.", 0

    # Streak calculation: must have claimed before and within 60 hours (24h cooldown + 36h grace period)
    last_daily = p_data.get("last_daily", 0)
    if last_daily > 0 and elapsed <= (cooldown * 2.5):
        streak = p_data.get("daily_streak", 0) + 1
    else:
        streak = 1

    reward = 250 + (streak * 25)
    p_data["last_daily"] = now
    p_data["daily_streak"] = streak
    p_data["bonus_cash"] = p_data.get("bonus_cash", 0) + reward

    save_db(db)

    unlock_msg = ""
    if streak >= 7 and "👑" not in p_data.get("unlocked_tokens", []):
        unlock_msg = "\n🎉 **7-Day Streak Bonus!** Unlocked the Crown Token 👑!"

    return True, f"🎁 **Daily Bonus Claimed!** Received **+${reward}** (Streak: {streak} days)!{unlock_msg}", reward

def get_top_leaderboard(limit=10) -> list[dict]:
    db = load_db()
    players = list(db.values())
    sorted_players = sorted(players, key=lambda x: (x.get("wins", 0), x.get("games_played", 0)), reverse=True)
    return sorted_players[:limit]

def set_custom_token(user_id: int, display_name: str, token_emoji: str) -> tuple[bool, str]:
    if token_emoji not in ALL_UNLOCKED_TOKENS:
        return False, f"Invalid token emoji! Available tokens: {' '.join(ALL_UNLOCKED_TOKENS)}"

    db = load_db()
    uid_str = str(user_id)
    if uid_str not in db:
        get_player_stats(user_id, display_name)
        db = load_db()
    
    db[uid_str]["custom_token"] = token_emoji
    save_db(db)
    return True, f"✨ Custom player token set to {token_emoji}!"
