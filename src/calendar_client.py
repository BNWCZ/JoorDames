import os
from datetime import date, datetime, timedelta

import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build

from logger import get_logger

log = get_logger("calendar")

PARIS_TZ = pytz.timezone("Europe/Paris")
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
SERVICE_ACCOUNT_PATH = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "service_account.json")

_REMOTE_PATTERNS = [p.strip().upper() for p in os.getenv("REMOTE_WORKING_PATTERNS", "").split(",") if p.strip()]
_OOO_PATTERNS = [p.strip().upper() for p in os.getenv("OUT_OF_OFFICE_PATTERNS", "").split(",") if p.strip()]


def is_configured() -> bool:
    """The calendar integration is optional. A missing service account file
    can also show up as an empty *directory*: Docker creates one when the
    ./service_account.json bind-mount source does not exist."""
    return os.path.isfile(SERVICE_ACCOUNT_PATH)


def _service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_PATH, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _events_for_range(start: date, end: date) -> list:
    time_min = PARIS_TZ.localize(datetime(start.year, start.month, start.day, 0, 0, 0)).isoformat()
    time_max = PARIS_TZ.localize(datetime(end.year, end.month, end.day, 23, 59, 59)).isoformat()

    log.debug("fetching calendar %s from %s to %s", CALENDAR_ID, start, end)
    result = _service().events().list(
        calendarId=CALENDAR_ID,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        timeZone="Europe/Paris",
    ).execute()

    items = result.get("items", [])
    log.info("calendar: %s event(s) between %s and %s", len(items), start, end)
    return items


def _is_remote(event: dict) -> bool:
    summary = event.get("summary", "").upper()
    return any(p in summary for p in _REMOTE_PATTERNS)


def _is_holidays(event: dict) -> bool:
    summary = event.get("summary", "").upper()
    return any(p in summary for p in _OOO_PATTERNS)


def _event_dates(event: dict) -> list[date]:
    """Returns all calendar dates covered by an event."""
    start = event.get("start", {})
    end_data = event.get("end", {})

    if "date" in start:
        # All-day event; end date is exclusive in the Google Calendar API
        start_d = date.fromisoformat(start["date"])
        end_d = date.fromisoformat(end_data["date"])
        dates = []
        d = start_d
        while d < end_d:
            dates.append(d)
            d += timedelta(days=1)
        return dates
    else:
        dt_str = start.get("dateTime", "")
        if not dt_str:
            return []
        dt_start = datetime.fromisoformat(dt_str)
        if dt_start.tzinfo:
            dt_start = dt_start.astimezone(PARIS_TZ)
        dt_end_str = end_data.get("dateTime", "")
        if dt_end_str:
            dt_end = datetime.fromisoformat(dt_end_str)
            if dt_end.tzinfo:
                dt_end = dt_end.astimezone(PARIS_TZ)
            end_d = dt_end.date()
        else:
            end_d = dt_start.date()
        dates = []
        d = dt_start.date()
        while d <= end_d:
            dates.append(d)
            d += timedelta(days=1)
        return dates


def get_ooo_calendar_days(start: date, end: date) -> dict[date, str]:
    """
    Returns a dict mapping dates to 'remote' or 'holidays' based on Google Calendar events.
    Uses a single API call for the full range.
    Priority: 'holidays' wins over 'remote' on the same day.
    Returns an empty dict when Google Calendar is not configured.
    """
    if not is_configured():
        log.warning("Google Calendar not configured (%s not found) — skipping calendar", SERVICE_ACCOUNT_PATH)
        return {}
    events = _events_for_range(start, end)
    result: dict[date, str] = {}
    for event in events:
        for d in _event_dates(event):
            if not (start <= d <= end):
                continue
            if _is_holidays(event):
                result[d] = "holidays"
            elif _is_remote(event) and result.get(d) != "holidays":
                result[d] = "remote"
    log.info(
        "calendar: %s out-of-office day(s) matched (%s remote, %s holidays)",
        len(result),
        sum(1 for v in result.values() if v == "remote"),
        sum(1 for v in result.values() if v == "holidays"),
    )
    return result


def has_remote_events_next_week(today: date) -> bool:
    """Returns True if next Mon–Fri has at least one remote working event.
    today should be Saturday or Sunday.
    """
    days_to_monday = 7 - today.weekday()  # Sat→2, Sun→1
    monday = today + timedelta(days=days_to_monday)
    friday = monday + timedelta(days=4)

    events = _events_for_range(monday, friday)
    remote = [e for e in events if _is_remote(e)]
    log.info(
        "calendar: %s remote event(s) for next week (%s to %s)",
        len(remote), monday, friday,
    )
    return bool(remote)
