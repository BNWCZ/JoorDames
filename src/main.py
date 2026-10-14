import csv
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

import logger
from logger import dump_page_state, get_logger
from auth import ensure_authenticated, get_browser_context, refresh_session, save_session
from spa_booker import book, cancel, checkin
from calendar_client import has_remote_events_next_week, get_ooo_calendar_days
from calendar_client import is_configured as calendar_configured
from discord_commands import SKIP, check_skip_commands
from notifier import notify

log = get_logger("main")

PARIS_TZ = pytz.timezone("Europe/Paris")
APP_URL = os.getenv("APP_URL", "https://spa.doorjames.app")
BOOKINGS_PATH = Path(os.getenv("BOOKINGS_PATH", "bookings.csv"))

DAYS_AHEAD = 41

_SILENT_OOO_STATUSES = ("out of office - holidays", "out of office - public holiday")


def _is_silent_day() -> bool:
    """Return True on days where notifications should be silent: weekends, public holidays, calendar holidays."""
    import holidays as holidays_lib
    today = datetime.now(PARIS_TZ).date()
    if today.weekday() >= 5:
        return True
    if today in holidays_lib.France():
        return True
    status = _load_bookings().get(today.isoformat(), "")
    return status in _SILENT_OOO_STATUSES


# ---------------------------------------------------------------------------
# bookings.csv helpers
# ---------------------------------------------------------------------------

def _load_bookings() -> dict[str, str]:
    if not BOOKINGS_PATH.exists():
        return {}
    with open(BOOKINGS_PATH, newline="") as f:
        return {row["date"]: row["status"] for row in csv.DictReader(f)}


def _save_bookings(bookings: dict[str, str]) -> None:
    with open(BOOKINGS_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "status"])
        for d in sorted(bookings):
            writer.writerow([d, bookings[d]])


def _update_status(date_str: str, status: str) -> None:
    bookings = _load_bookings()
    bookings[date_str] = status
    _save_bookings(bookings)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def run_book() -> None:
    now = datetime.now(PARIS_TZ)
    target = (now + timedelta(days=DAYS_AHEAD)).date()
    target_str = target.isoformat()

    log.info("target date is %s (%s days ahead)", target_str, DAYS_AHEAD)

    if target.weekday() >= 5:
        log.info("%s is a weekend — skipping", target_str)
        return

    existing = _load_bookings().get(target_str, "")
    if existing in ("booked", "checked_in") or existing.startswith("out of office"):
        log.info("%s already has status '%s' — skipping", target_str, existing)
        return

    with sync_playwright() as p:
        browser, context = get_browser_context(p, headless=True)
        page = context.new_page()
        try:
            page.goto(APP_URL)
            page.wait_for_load_state("load")

            if ensure_authenticated(page, context):
                notify("Réauthentification réussie ✅", "Session renouvelée automatiquement", silent=_is_silent_day())

            result = book(page, target)
            _update_status(target_str, "booked")
            notify(
                "Réservation réussie ✅",
                f"{result['desk']} ({result['area']}) réservé pour le "
                f"{result['date']} ({result['start']}–{result['end']})",
                silent=_is_silent_day(),
            )

        except Exception as e:
            log.error("booking failed for %s: %s", target_str, e)
            dump_page_state(page, "book_error")
            _update_status(target_str, "error")
            notify("Erreur réservation ❌", f"{target_str} — {e}")
            raise
        finally:
            refresh_session(page, context)
            context.close()
            browser.close()


def run_cancel(target_date=None) -> None:
    today = datetime.now(PARIS_TZ).date()
    target = target_date or today
    target_str = target.isoformat()

    with sync_playwright() as p:
        browser, context = get_browser_context(p, headless=True)
        page = context.new_page()
        try:
            page.goto(APP_URL)
            page.wait_for_load_state("load")

            if ensure_authenticated(page, context):
                notify("Réauthentification réussie ✅", "Session renouvelée automatiquement", silent=_is_silent_day())

            try:
                result = cancel(page, target)
            except RuntimeError as e:
                # Nothing booked that day is a non-event, not a failure — the
                # check-in path already treats it that way. Without this the
                # run raises and fires a red "Erreur annulation" for a no-op.
                if "No booking found" in str(e):
                    stored = _load_bookings().get(target_str, "") or "none"
                    log.info(
                        "no booking to cancel for %s (stored status '%s') — nothing to do",
                        target_str, stored,
                    )
                    return
                raise

            _update_status(target_str, "cancelled")
            notify(
                "Annulation réussie ✅",
                f"{result['desk']} ({result['area']}) annulé pour le "
                f"{result['date']} ({result['start']}–{result['end']})",
                silent=_is_silent_day(),
            )

        except Exception as e:
            log.error("cancellation failed for %s: %s", target_str, e)
            dump_page_state(page, "cancel_error")
            notify("Erreur annulation ❌", f"{target_str} — {e}")
            raise
        finally:
            refresh_session(page, context)
            context.close()
            browser.close()


def run_checkin() -> None:
    today = datetime.now(PARIS_TZ).date()
    today_str = today.isoformat()
    today_status = _load_bookings().get(today_str, "")
    is_ooo = today_status.startswith("out of office")
    log.info(
        "today is %s, stored status '%s' — will %s",
        today_str, today_status or "none", "cancel" if is_ooo else "check in",
    )

    skip = check_skip_commands()

    if SKIP in skip:
        silent = _is_silent_day()
        if is_ooo:
            notify("Action ignorée ⏭️", f"Annulation ignorée pour le {today_str} (skip)", silent=silent)
        else:
            notify("Action ignorée ⏭️", f"Check-in ignoré pour le {today_str} (skip)", silent=silent)
        return

    with sync_playwright() as p:
        browser, context = get_browser_context(p, headless=True)
        page = context.new_page()
        try:
            page.goto(APP_URL)
            page.wait_for_load_state("load")

            if ensure_authenticated(page, context):
                notify("Réauthentification réussie ✅", "Session renouvelée automatiquement", silent=_is_silent_day())

            if is_ooo:
                try:
                    result = cancel(page, today)
                    _update_status(today_str, "cancelled")
                    notify(
                        "Annulation réussie ✅",
                        f"{result['desk']} ({result['area']}) annulé pour le "
                        f"{result['date']} ({result['start']}–{result['end']}) "
                        f"— {today_status}",
                        silent=_is_silent_day(),
                    )
                except RuntimeError as e:
                    if "No booking found" in str(e):
                        log.info(
                            "no booking to cancel for %s (%s) — nothing to do",
                            today_str, today_status,
                        )
                    else:
                        raise
            else:
                result = checkin(page)
                _update_status(today_str, "checked_in")
                notify(
                    "Check-in réussi ✅",
                    f"{result['desk']} ({result['area']}) check-in effectué "
                    f"le {result['date']} ({result['start']}–{result['end']})",
                    silent=_is_silent_day(),
                )

        except Exception as e:
            log.error("check-in/cancellation failed for %s: %s", today_str, e)
            dump_page_state(page, "checkin_error")
            notify("Erreur check-in/annulation ❌", f"{today_str} — {e}")
            raise
        finally:
            refresh_session(page, context)
            context.close()
            browser.close()


def run_sync() -> None:
    import holidays as holidays_lib

    today = datetime.now(PARIS_TZ).date()
    end = today + timedelta(days=89)

    fr_holidays = holidays_lib.France()
    ooo_cal = get_ooo_calendar_days(today, end)
    bookings = _load_bookings()

    OOO_STATUSES = ("out of office - remote", "out of office - holidays", "out of office - public holiday")

    changed = 0
    for i in range(90):
        d = today + timedelta(days=i)
        if d.weekday() >= 5:
            continue

        d_str = d.isoformat()
        current = bookings.get(d_str, "")

        cal_reason = ooo_cal.get(d)  # 'remote', 'holidays', or None
        is_bank_holiday = d in fr_holidays

        # Priority: holidays > public holiday > remote
        if cal_reason == "holidays":
            new_ooo = "out of office - holidays"
        elif is_bank_holiday:
            new_ooo = "out of office - public holiday"
        elif cal_reason == "remote":
            new_ooo = "out of office - remote"
        else:
            new_ooo = None

        if new_ooo:
            if current != new_ooo:
                log.info("%s: '%s' -> '%s'", d_str, current or "none", new_ooo)
                bookings[d_str] = new_ooo
                changed += 1
        else:
            # Clear any stale OOO status (remote event removed, holiday period ended, etc.)
            if current in OOO_STATUSES:
                log.info("%s: clearing stale status '%s'", d_str, current)
                del bookings[d_str]
                changed += 1

    if changed:
        _save_bookings(bookings)
        log.info("%s day(s) updated in %s", changed, BOOKINGS_PATH)
        notify("Calendrier synchronisé 📅", f"{changed} jour(s) mis à jour", silent=True)
    else:
        log.info("no changes detected over the next 90 days")


def run_calendar_reminder() -> None:
    today = datetime.now(PARIS_TZ).date()
    if not calendar_configured():
        log.info("Google Calendar not configured — no reminder to send")
        return
    if not has_remote_events_next_week(today):
        notify("Alerte Calendrier ⚠️", "Events de télétravail non renseignés")
    else:
        log.info("next week has remote events — no reminder needed")


def run_auth() -> None:
    log.info("opening a browser for manual authentication")
    with sync_playwright() as p:
        browser, context = get_browser_context(p, headless=False)
        page = context.new_page()
        page.goto(APP_URL)
        print("Log in and approve the 2FA on your phone, then press Enter here...")
        input()
        save_session(context)
        context.close()
        browser.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

MODES = {
    "book": run_book,
    "cancel": run_cancel,
    "checkin": run_checkin,
    "sync": run_sync,
    "reminder": run_calendar_reminder,
    "auth": run_auth,
}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "book"

    logger.setup(mode)

    if mode not in MODES:
        log.error("unknown mode '%s' — usage: python src/main.py [%s]", mode, "|".join(MODES))
        sys.exit(1)

    logger.log_run_start(mode)
    try:
        MODES[mode]()
    except Exception:
        # The run_* handlers log the one-line context and notify Discord; the
        # single full traceback is emitted here rather than in each handler.
        log.exception("run aborted")
        logger.log_run_end(mode, ok=False)
        sys.exit(1)
    logger.log_run_end(mode, ok=True)
