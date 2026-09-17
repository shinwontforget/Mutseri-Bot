"""
config_manager.py - Persistent Configuration Manager for Territory Wars

Manages per-server settings:
- Custom command prefix (default: '!')
- Allowed channel restrictions (blocks usage in non-allocated channels)
"""

import os
import json

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "server_config.json")

def load_config() -> dict:
    """Loads server configuration from disk."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_config(data: dict):
    """Atomically saves server configuration."""
    tmp_path = f"{CONFIG_PATH}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, CONFIG_PATH)
    except Exception:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

def get_prefix(guild_id: int | None) -> str:
    """Returns the custom prefix for the given guild, defaulting to '!'."""
    if not guild_id:
        return "!"
    cfg = load_config()
    return cfg.get(str(guild_id), {}).get("prefix", "!")

def set_prefix(guild_id: int, prefix: str):
    """Updates the custom prefix for a guild."""
    cfg = load_config()
    gid = str(guild_id)
    if gid not in cfg:
        cfg[gid] = {}
    cfg[gid]["prefix"] = prefix.strip()
    save_config(cfg)

def get_allowed_channels(guild_id: int | None) -> list[int]:
    """Returns list of allowed channel IDs for the guild. Empty means all channels allowed."""
    if not guild_id:
        return []
    cfg = load_config()
    return cfg.get(str(guild_id), {}).get("allowed_channels", [])

def set_allowed_channels(guild_id: int, channel_ids: list[int]):
    """Sets the allowed channel IDs for the guild."""
    cfg = load_config()
    gid = str(guild_id)
    if gid not in cfg:
        cfg[gid] = {}
    cfg[gid]["allowed_channels"] = channel_ids
    save_config(cfg)

def is_channel_allowed(guild_id: int | None, channel_id: int) -> bool:
    """Checks if command execution is permitted in the given channel."""
    if not guild_id:
        return True
    allowed = get_allowed_channels(guild_id)
    if not allowed:
        return True  # No restriction configured
    return channel_id in allowed
