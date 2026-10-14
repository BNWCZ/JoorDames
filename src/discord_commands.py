import os

import requests
from dotenv import load_dotenv

load_dotenv()

from logger import get_logger

log = get_logger("discord_commands")

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_COMMAND_CHANNEL_ID = os.getenv("DISCORD_COMMAND_CHANNEL_ID", "")

_API = "https://discord.com/api/v10"

SKIP = "skip"
_COMMANDS = {SKIP}


def _headers() -> dict:
    return {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}


def check_skip_commands() -> set[str]:
    """
    Read recent messages from the command channel and return the set of active
    skip commands (any of: "skip checkin", "skip delete").
    Matched messages are deleted from the channel.
    Returns an empty set if Discord is not configured or the request fails.
    """
    if not DISCORD_BOT_TOKEN or not DISCORD_COMMAND_CHANNEL_ID:
        log.debug("Discord bot not configured — no skip commands checked")
        return set()

    try:
        resp = requests.get(
            f"{_API}/channels/{DISCORD_COMMAND_CHANNEL_ID}/messages",
            headers=_headers(),
            params={"limit": 50},
            timeout=10,
        )
        resp.raise_for_status()
        messages = resp.json()
    except Exception as e:
        log.error("failed to fetch command messages: %s", e)
        return set()

    found: set[str] = set()
    for msg in messages:
        content = msg.get("content", "").strip().lower()
        if content in _COMMANDS:
            found.add(content)
            log.info("command '%s' picked up from the Discord channel", content)
            try:
                requests.delete(
                    f"{_API}/channels/{DISCORD_COMMAND_CHANNEL_ID}/messages/{msg['id']}",
                    headers=_headers(),
                    timeout=10,
                )
            except Exception as e:
                log.warning("failed to delete command message %s: %s", msg["id"], e)

    log.debug("skip commands found: %s", sorted(found) or "none")
    return found
