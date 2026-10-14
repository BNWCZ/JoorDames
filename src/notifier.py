import os

import requests

from logger import get_logger

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

log = get_logger("notifier")

_SUPPRESS_NOTIFICATIONS = 1 << 12


def notify(event: str, detail: str = "", silent: bool = False) -> None:
    # Mirror every Discord notification into the log file so the server keeps a
    # full record even when the webhook is down or the message is silent.
    log.info("notify: %s%s%s", event, f" — {detail}" if detail else "", " (silent)" if silent else "")

    msg = f"**[JoorDames]** {event}"
    if detail:
        msg += f"\n{detail}"

    if not WEBHOOK_URL:
        log.warning("DISCORD_WEBHOOK_URL not set — notification not sent")
        return

    payload = {"content": msg}
    if silent:
        payload["flags"] = _SUPPRESS_NOTIFICATIONS

    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code >= 400:
            log.error("Discord returned %s: %s", resp.status_code, resp.text[:200])
        else:
            log.debug("Discord accepted the notification (%s)", resp.status_code)
    except Exception as e:
        log.error("Discord send failed: %s", e)
