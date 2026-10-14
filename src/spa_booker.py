"""
JoorDames SPA — booking / cancel / check-in primitives.

Each function takes an already-authenticated Playwright ``Page`` and returns a
details dict on success so ``main.py`` can feed rich Discord notifications.
Browser/context lifecycle is owned by the caller.
"""

import os
import re
from datetime import date, datetime
from typing import Optional

import pytz
from playwright.sync_api import Page

from logger import get_logger

log = get_logger("spa_booker")

PARIS_TZ = pytz.timezone("Europe/Paris")

BOOKING_AREA = os.getenv("BOOKING_AREA", "")
BOOKING_DESK = os.getenv("BOOKING_DESK", "")


def _parse_slot(var: str, default: str) -> tuple[int, int]:
    """Read an "HH:MM" time from the environment. The Door James time picker
    only offers 15-minute slots, so anything else is rejected up front."""
    raw = os.getenv(var, "").strip() or default
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if not m or int(m[1]) > 23 or int(m[2]) % 15:
        raise ValueError(f"{var}={raw!r} — expected HH:MM on a 15-minute slot (e.g. 09:00, 17:30)")
    return int(m[1]), int(m[2])


_START_HOUR, _START_MINUTE = _parse_slot("BOOKING_START", "09:00")
_END_HOUR, _END_MINUTE = _parse_slot("BOOKING_END", "17:00")
if (_END_HOUR, _END_MINUTE) <= (_START_HOUR, _START_MINUTE):
    raise ValueError("BOOKING_END must be later than BOOKING_START")


def _require_desk() -> None:
    if not BOOKING_DESK or not BOOKING_AREA:
        raise RuntimeError("BOOKING_DESK et BOOKING_AREA doivent être renseignés dans .env")

STATUS_CLASSES = [
    "confirmed",
    "checkInOpen",
    "checkedIn",
    "cancelled",
    "declined",
    "checkedOut",
    "expired",
    "checkOutForgotten",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _dismiss_overlays(page: Page) -> None:
    """Close any modal dialog (e.g. the "Quoi de neuf ?" what's-new popup) whose
    backdrop would otherwise intercept clicks on the homepage."""
    for attempt in range(4):
        dialog = page.locator("mat-dialog-container")
        if dialog.count() == 0 or not dialog.first.is_visible():
            log.debug("no modal dialog to dismiss")
            return
        log.info("dismissing modal dialog (attempt %s/4)", attempt + 1)
        # Escape closes most mat-dialogs. force-click bypasses the backdrop,
        # which otherwise intercepts pointer events on the dialog's own buttons.
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        if dialog.count() == 0 or not dialog.first.is_visible():
            log.debug("dialog closed by Escape")
            return
        for sel in ("mat-dialog-container button.close-button",
                    "mat-dialog-container button[aria-label='Fermer']",
                    "mat-dialog-container button[class*='close']",
                    "mat-dialog-container button.continue",
                    "mat-dialog-container .fab-button-context"):
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                try:
                    btn.click(force=True)
                except Exception as exc:
                    log.debug("close button %r did not take: %s", sel, exc)
                    continue
                log.debug("dialog closed via %r", sel)
                break
        page.wait_for_timeout(600)
    # Wait for the darkening backdrop to go away.
    backdrop = page.locator(".cdk-overlay-backdrop.cdk-overlay-backdrop-showing")
    if backdrop.count() > 0:
        try:
            backdrop.first.wait_for(state="detached", timeout=4000)
        except Exception:
            log.warning("overlay backdrop still present — clicks may be intercepted")


def book(page: Page, target_date: date) -> dict:
    _require_desk()
    today = datetime.now(PARIS_TZ).date()
    month_offset = (target_date.year - today.year) * 12 + (target_date.month - today.month)
    log.info(
        "booking %s (%s, area %s), month offset +%s",
        target_date.isoformat(), BOOKING_DESK, BOOKING_AREA, month_offset,
    )

    # The June 2026 redesign replaced the 6-step wizard with a single-card form
    # (Type de ressource / Date et heure / Ressource) opened from the homepage
    # "Nouvelle réservation" button.
    _open_booking_form(page)

    # --- Type de ressource -> Bureau (desk) ---
    _click_form_row(page, r"type de ressource")
    page.wait_for_timeout(1500)
    page.locator(".widget-item[aria-label='Bureau']").first.click()
    page.wait_for_timeout(2000)
    log.info("row 'type de ressource' -> Bureau")

    # Picking the type auto-opens the resource map, whose canvas covers the
    # form. Close it: the date/time must be set *before* a desk is chosen, or
    # availability is computed against the form's default (today) instead of
    # the target date.
    _close_nested_subpage(page)

    # --- Date et heure ---
    _click_form_row(page, r"Date et heure")
    page.wait_for_timeout(2000)
    page.locator(".mat-calendar-body-cell-content").first.wait_for(
        state="visible", timeout=15_000,
    )
    log.debug("calendar visible")
    _navigate_to_month(page, month_offset)
    page.wait_for_timeout(500)
    # Match the day by its aria-label prefix ("4 juil. 2026", "13 août 2026", …).
    # Using the number prefix avoids depending on locale month abbreviations, and
    # is unique within the single displayed month.
    day_cell = page.locator(
        f"button.mat-calendar-body-cell[aria-label^='{target_date.day} ']"
    ).first
    day_cell.wait_for(state="visible", timeout=8000)
    day_cell.click()
    page.wait_for_timeout(500)
    log.info("row 'Date et heure' -> day %s selected", target_date.day)
    _set_time_field(page, "De", _START_HOUR, _START_MINUTE)
    _set_time_field(page, "À", _END_HOUR, _END_MINUTE)
    log.info("time set to %02d:%02d-%02d:%02d", _START_HOUR, _START_MINUTE, _END_HOUR, _END_MINUTE)
    _apply_subpage(page)  # "Confirmer" on the date/heure sub-page

    # --- Ressource (desk selection on the floor map) ---
    _click_form_row(page, r"Ressource \*")
    page.wait_for_timeout(2500)
    _select_desk_on_map(page)

    # --- Final confirm on the main booking form ---
    confirmer = page.locator(
        "button.mdc-fab:has-text('Confirmer'), "
        ".fab-button-context:has-text('Confirmer'), "
        "button:has-text('Confirmer')"
    ).first
    confirmer.wait_for(state="visible", timeout=8000)
    confirmer.click(force=True)
    page.wait_for_timeout(3000)
    log.info("booking form confirmed — verifying in the agenda")

    if not _verify_booking(page, target_date):
        log.error("booking not found in the agenda for %s", target_date.isoformat())
        raise RuntimeError("Booking verification failed")
    log.info("booking verified for %s", target_date.isoformat())

    return {
        "desk": BOOKING_DESK,
        "area": BOOKING_AREA,
        "date": target_date.strftime("%d/%m/%Y"),
        "start": f"{_START_HOUR:02d}:{_START_MINUTE:02d}",
        "end": f"{_END_HOUR:02d}:{_END_MINUTE:02d}",
    }


def cancel(page: Page, target_date: Optional[date] = None) -> dict:
    """Cancel today's active booking for BOOKING_DESK.

    The SPA homepage exposes today's booking card; ``target_date`` is accepted
    for API compatibility with the old booker but not used for selection.
    """
    _require_desk()
    today = (target_date or datetime.now(PARIS_TZ).date()).strftime("%d/%m/%Y")
    log.info("cancelling %s for %s", BOOKING_DESK, today)

    page.wait_for_selector("button.new-booking-btn, button.mdc-fab", timeout=30_000)
    page.wait_for_timeout(2000)
    _dismiss_overlays(page)

    card = page.locator(
        "djs-dashboard-item",
        has=page.locator("h2", has_text=BOOKING_DESK),
    ).filter(
        has=page.locator(
            ".djs-status-tag.confirmed, "
            ".djs-status-tag.checkInOpen, "
            ".djs-status-tag.checkedIn, "
            ".djs-status-tag.declined, "
            ".djs-status-tag.checkOutForgotten"
        )
    ).first
    try:
        card.wait_for(state="visible", timeout=15_000)
    except Exception:
        log.warning("no active booking card found for %s", BOOKING_DESK)
        raise RuntimeError("No booking found to cancel")

    start, end = _card_time_range(card)

    tag = card.locator(".djs-status-tag").first
    tag_cls = (tag.get_attribute("class") or "") if tag.count() > 0 else ""
    log.info("card found: status=%s, time=%s-%s", _card_status(card) or "unknown", start, end)
    if "checkedIn" in tag_cls.split():
        log.error("refusing to cancel: booking is already checked in")
        raise RuntimeError(
            "Cannot cancel a checked-in booking — only check-out is available "
            "once the user has checked in."
        )

    card.click()
    page.wait_for_timeout(1500)

    # The redesigned detail panel exposes actions as buttons (not nav-list items).
    annuler = page.locator("button:has-text('Annuler la réservation')").first
    annuler.wait_for(state="visible", timeout=8000)
    annuler.click(force=True)
    page.wait_for_timeout(1000)
    log.debug("clicked 'Annuler la réservation'")

    # Confirmation dialog: "Conserver" (keep) / "Confirmer" (confirm cancellation).
    confirm_btn = page.locator("mat-dialog-actions button:has-text('Confirmer')").first
    confirm_btn.wait_for(state="visible", timeout=5000)
    confirm_btn.click(force=True)
    page.wait_for_timeout(2000)
    log.info("cancellation confirmed — reloading to verify")

    # Success = no active booking remains for the desk today — works whether the
    # card flips to a "cancelled" tag or drops off the homepage entirely.
    def _active_cards() -> int:
        return page.locator(
            "djs-dashboard-item",
            has=page.locator("h2", has_text=BOOKING_DESK),
        ).filter(
            has=page.locator(
                ".djs-status-tag.confirmed, .djs-status-tag.checkInOpen, "
                ".djs-status-tag.checkedIn, .djs-status-tag.checkOutForgotten"
            )
        ).count()

    # The homepage card lags after cancelling; reload for the authoritative status.
    page.wait_for_timeout(1500)
    page.reload(wait_until="load")
    page.wait_for_timeout(3000)
    _dismiss_overlays(page)
    for attempt in range(12):
        remaining = _active_cards()
        if remaining == 0:
            log.info("cancellation verified — no active card remains (after %s check(s))", attempt + 1)
            break
        log.debug("verify cancel: %s active card(s) still shown", remaining)
        page.wait_for_timeout(600)
    else:
        log.error("cancellation could not be verified — an active card is still displayed")
        raise RuntimeError("Cancellation could not be verified")

    return {
        "desk": BOOKING_DESK,
        "area": BOOKING_AREA,
        "date": today,
        "start": start,
        "end": end,
    }


def checkin(page: Page) -> dict:
    """Check in today's active booking for BOOKING_DESK."""
    _require_desk()
    today = datetime.now(PARIS_TZ).date().strftime("%d/%m/%Y")
    log.info("checking in %s for %s", BOOKING_DESK, today)

    page.wait_for_selector("button.new-booking-btn, button.mdc-fab", timeout=30_000)
    page.wait_for_timeout(2000)
    _dismiss_overlays(page)

    card = page.locator(
        "djs-dashboard-item",
        has=page.locator("h2", has_text=BOOKING_DESK),
    ).filter(
        has=page.locator(
            ".djs-status-tag.confirmed, "
            ".djs-status-tag.checkInOpen, "
            ".djs-status-tag.checkedIn, "
            ".djs-status-tag.declined, "
            ".djs-status-tag.checkOutForgotten"
        )
    ).first
    try:
        card.wait_for(state="visible", timeout=15_000)
    except Exception:
        log.warning("no active booking card found for %s", BOOKING_DESK)
        raise RuntimeError("No booking found to check in")

    start, end = _card_time_range(card)
    state = _card_status(card)
    log.info("card found: status=%s, time=%s-%s", state or "unknown", start, end)
    if state == "checkedIn":
        log.info("already checked in — nothing to do")
        raise RuntimeError("Booking is already checked in — nothing to do.")
    if state != "checkInOpen":
        log.error("check-in unavailable — card state is '%s'", state or "unknown")
        raise RuntimeError(
            f"Check-in not available — card state is '{state or 'unknown'}', "
            "expected 'checkInOpen'. Check-in opens 30 minutes before the "
            "booking start time."
        )

    card.click()
    page.wait_for_timeout(1500)

    # The redesigned detail panel exposes actions as buttons (not nav-list items).
    checkin_item = page.locator("button:has-text('Check-in')").first
    checkin_item.wait_for(state="visible", timeout=8000)
    checkin_item.click(force=True)
    page.wait_for_timeout(2000)
    log.info("clicked 'Check-in' — reloading to verify")

    # The homepage card lags after check-in; reload for the authoritative status.
    page.wait_for_timeout(1500)
    page.reload(wait_until="load")
    page.wait_for_timeout(3000)
    _dismiss_overlays(page)
    checked_chip = page.locator(
        "djs-dashboard-item",
        has=page.locator("h2", has_text=BOOKING_DESK),
    ).locator(".djs-status-tag.checkedIn").first
    try:
        checked_chip.wait_for(state="visible", timeout=8000)
        log.info("check-in verified — card shows 'checkedIn'")
    except Exception:
        log.error("check-in could not be verified — card status is '%s'", _card_status(card) or "unknown")
        raise RuntimeError("Check-in could not be verified")

    return {
        "desk": BOOKING_DESK,
        "area": BOOKING_AREA,
        "date": today,
        "start": start,
        "end": end,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_booking_form(page: Page) -> None:
    """Dismiss the delayed what's-new modal and open the booking form."""
    # The "Quoi de neuf ?" dialog can appear a few seconds after load; dismiss
    # in a loop until its backdrop is gone.
    for _ in range(6):
        _dismiss_overlays(page)
        if page.locator(".cdk-overlay-backdrop.cdk-overlay-backdrop-showing").count() == 0:
            page.wait_for_timeout(1200)
            if page.locator(".cdk-overlay-backdrop.cdk-overlay-backdrop-showing").count() == 0:
                break

    new_booking = page.locator("button.new-booking-btn").first
    try:
        new_booking.wait_for(state="visible", timeout=15_000)
        new_booking.click()
        log.info("booking form opened via button.new-booking-btn")
    except Exception:  # fall back to the pre-redesign FAB
        log.warning("button.new-booking-btn not found — falling back to the FAB")
        fab = page.locator("button.mdc-fab.mat-mdc-fab").first
        fab.wait_for(state="visible", timeout=10_000)
        fab.click()
        log.info("booking form opened via button.mdc-fab (fallback)")
    page.wait_for_timeout(3000)


def _close_nested_subpage(page: Page) -> bool:
    """Close the nested sub-page stacked on top of the booking form.

    Since September 2026 (error log #17) choosing the resource type
    auto-advances into the "Sélectionner une ressource" map instead of
    returning to the form. That map's full-viewport <canvas> lives in the
    browser top layer (a ``popover="manual"`` CDK overlay), so it swallows
    every click aimed at the form rows underneath.

    Both topbars expose a ``button.close-button``; only the aria-label tells
    them apart — "Retour" on the nested sub-page, "Fermer" on the booking form
    itself. Closing the wrong one would abandon the booking.
    """
    back = page.locator("button.close-button[aria-label='Retour']")
    if back.count() == 0:
        log.debug("no nested sub-page open")
        return False
    back.last.click(force=True)
    try:
        page.locator(".sub-page-dialog-nested").last.wait_for(
            state="detached", timeout=8000,
        )
    except Exception:
        log.warning("nested sub-page still attached after 'Retour'")
    page.wait_for_timeout(800)
    log.info("closed the auto-opened nested sub-page")
    return True


def _click_form_row(page: Page, title_rx: str) -> None:
    """Click one of the booking-form rows by (regex) text."""
    rows = page.locator("div.djs-list-item[role='button']", has_text=re.compile(title_rx))
    log.debug("form row %r: %s match(es)", title_rx, rows.count())
    rows.first.click(timeout=10_000)


def _apply_subpage(page: Page) -> None:
    """Click 'Confirmer' inside the currently-open sub-page dialog (date/heure)."""
    pane = page.locator(".cdk-overlay-pane.sub-page-dialog")
    scope = pane.last if pane.count() > 0 else page
    confirm = scope.locator(
        "button:has-text('Confirmer'), .fab-button-context:has-text('Confirmer')"
    ).first
    if confirm.count() > 0 and confirm.is_visible():
        confirm.click(force=True)  # force past the button's own touch-target overlay
        page.wait_for_timeout(1800)
        log.debug("sub-page confirmed")
    else:
        log.warning("no 'Confirmer' button found on the sub-page dialog")


def _find_desk_in_results(page: Page):
    """
    Locate the desk inside the map's search-result list.

    The booking form underneath the map carries a ``div.rec-strip``
    recommendation carousel whose cards are also ``djs-teak-entity-item`` and
    also match the desk name (error log #20).  Those cards live *earlier* in
    the DOM than the map's CDK overlay, so a bare ``.first`` picks the
    recommendation — which is visible but sits below the full-viewport
    ``popover="manual"`` overlay, so every click is swallowed until timeout.

    Anchor on the result list container, and keep two independent fallbacks:
    the recommendation entity is marked ``.rec-card__entity`` and its card is
    ``.not-selectable`` with no ``role``, whereas a real result card is
    ``[role='button']``.
    """
    named = page.locator("h2.truncate-text", has_text=BOOKING_DESK)
    candidates = [
        # 1. scoped to the map's result list (survives a rec-strip restyle)
        page.locator(
            "ul.assets-in-group li.teak-entity-container djs-teak-entity-item",
            has=named,
        ),
        # 2. any entity that is not a recommendation card
        page.locator("djs-teak-entity-item:not(.rec-card__entity)", has=named),
        # 3. any entity whose card is actually selectable
        page.locator(
            "djs-teak-entity-item",
            has=named,
        ).filter(has=page.locator(".teak-entity-card[role='button']")),
    ]
    for i, loc in enumerate(candidates, 1):
        if loc.count() > 0:
            if i > 1:
                log.warning("map: desk found via fallback #%s — check the result list markup", i)
            return loc.first
    raise RuntimeError(
        f"desk {BOOKING_DESK!r} not found in the map search results "
        "(only recommendation cards matched, if any)"
    )


def _select_desk_on_map(page: Page) -> None:
    """On the Ressource map: switch to BOOKING_AREA, search and select the desk."""
    area_btn = page.locator(".area-selector-button, djs-area-selector button").first
    area_btn.wait_for(state="visible", timeout=10_000)
    area_btn.click()
    page.wait_for_timeout(1000)

    area_opt = page.locator(
        ".widget-item", has=page.locator(".widget-label", has_text=BOOKING_AREA)
    ).first
    if area_opt.count() == 0 or not area_opt.is_visible():
        area_opt = page.locator(".widget-item", has_text=BOOKING_AREA).first
    area_opt.click()
    page.wait_for_timeout(1500)
    log.info("map: area %s selected", BOOKING_AREA)

    search = page.locator("input[placeholder*='Rechercher par nom']").first
    search.wait_for(state="visible", timeout=8000)
    search.fill(BOOKING_DESK)
    page.wait_for_timeout(2500)
    log.debug("map: searched for %r", BOOKING_DESK)

    zone_header = page.locator("djs-list-item.zone-header .djs-list-item").first
    if zone_header.count() > 0 and zone_header.is_visible():
        zone_header.click()
        page.wait_for_timeout(800)

    desk_item = _find_desk_in_results(page)
    desk_item.wait_for(state="visible", timeout=8000)
    desk_item.click()
    page.wait_for_timeout(1000)
    log.debug("map: desk item %r opened", BOOKING_DESK)

    # The desk detail panel opens on the "Actions" tab; click "Sélectionner".
    selectionner = page.locator("button:has-text('Sélectionner')").first
    selectionner.wait_for(state="visible", timeout=8000)
    selectionner.click(force=True)
    page.wait_for_timeout(2500)
    log.info("map: desk %s selected", BOOKING_DESK)


def _navigate_to_month(page: Page, offset: int) -> None:
    next_btn = page.locator("button.mat-calendar-next-button")
    for _ in range(offset):
        next_btn.click()
        page.wait_for_timeout(400)
    if offset:
        label = page.locator("button.mat-calendar-period-button").first
        try:
            log.debug("calendar advanced %s month(s) to %r", offset, label.inner_text().strip())
        except Exception:
            log.debug("calendar advanced %s month(s)", offset)


def _set_time_field(page: Page, label: str, hour: int, minute: int) -> None:
    """Set the 'De' (start) or 'À' (end) time in the date/heure sub-page."""
    value = f"{hour:02d}:{minute:02d}"
    field = page.locator(
        "mat-form-field",
        has=page.locator("mat-label", has_text=re.compile(rf"^{re.escape(label)}$")),
    ).first
    # Error log #6: click the icon suffix, never the input — a time-separator
    # sibling overlaps the input's centre and swallows the click.
    field.locator(".mat-mdc-form-field-icon-suffix").click()
    page.wait_for_timeout(600)

    # Error log #18: this is now an Angular Material <mat-timepicker> — a
    # listbox of 15-minute slots, not the old keyboard/clock picker with
    # separate Heure/Minute inputs. Each panel is tagged with its field's
    # label, which is what keeps 'De' and 'À' apart.
    panel = page.locator(
        f"div.mat-timepicker-panel[aria-label='{label}']"
    ).first
    panel.wait_for(state="visible", timeout=8000)

    # 'De' options are a bare "09:00"; 'À' options append the resulting
    # duration ("17:00 (8 h)"), so anchor on the time and let the rest vary.
    # \s covers the non-breaking spaces the duration text is built with.
    option = panel.locator("mat-option").filter(
        has=page.locator(
            "span.mdc-list-item__primary-text",
            has_text=re.compile(rf"^{re.escape(value)}(\s|$)"),
        )
    ).first
    try:
        option.wait_for(state="visible", timeout=8000)
    except Exception:
        offered = panel.locator("span.mdc-list-item__primary-text").all_inner_texts()
        log.error("slot %s not offered for %r — available: %s", value, label, offered[:12])
        raise RuntimeError(f"Time slot {value} not offered for field '{label}'")
    option.click()
    page.wait_for_timeout(500)
    log.debug("field %r set to %s", label, value)


# Agenda date headers use abbreviated French months (e.g. "13 août", "6 juil.").
# Matched without the trailing dot so both "juil." and a full form would hit.
_FR_MONTH_ABBR = {
    1: "janv", 2: "févr", 3: "mars", 4: "avr", 5: "mai", 6: "juin",
    7: "juil", 8: "août", 9: "sept", 10: "oct", 11: "nov", 12: "déc",
}


def _verify_booking(page: Page, target_date: date) -> bool:
    """Confirm the booking landed by finding the target date's section in the
    agenda and checking the desk is reserved there.

    The agenda lists a date header only for days that actually have a booking,
    so the presence of the target date's header with our desk under it is a
    reliable success signal. This is the gate for the success notification.
    """
    app_url = os.getenv("APP_URL", "https://spa.doorjames.app")
    try:
        page.goto(f"{app_url}/agenda")
        page.wait_for_load_state("load")
        page.wait_for_timeout(4000)
        _dismiss_overlays(page)
    except Exception as exc:
        log.error("could not open the agenda: %s", exc)
        return False

    # Agenda date headers read "mardi 3 nov." / "vendredi 30 oct." — the
    # weekday prefix is newer than error log #11's "13 août" format, and an
    # anchored "^3 nov" silently fails against it (error log #23). Keep the
    # anchor and allow one optional leading weekday word: that still stops
    # "3 nov" from matching inside "13 nov", and the trailing \b stops the
    # month abbreviation from matching a longer token.
    header_rx = re.compile(
        rf"^\s*(?:\w+\s+)?{target_date.day} {_FR_MONTH_ABBR[target_date.month]}\b"
    )
    header = page.locator("h2", has_text=header_rx).first
    try:
        header.wait_for(state="visible", timeout=15_000)
        log.debug("agenda: date header %r found", header.inner_text().strip())
    except Exception:
        log.error(
            "agenda: no date header for %s %s",
            target_date.day, _FR_MONTH_ABBR[target_date.month],
        )
        return False

    # Scope to the date-group container (nearest ancestor holding the item),
    # then require our desk with an active (non-cancelled) status in that day.
    group = header.locator("xpath=ancestor::div[.//djs-dashboard-item][1]")
    desk_item = group.locator(
        "djs-dashboard-item", has_text=BOOKING_DESK
    ).filter(
        has=page.locator(
            ".djs-status-tag.confirmed, "
            ".djs-status-tag.checkInOpen, "
            ".djs-status-tag.checkedIn, "
            ".djs-status-tag.checkOutForgotten"
        )
    ).first
    try:
        desk_item.wait_for(state="visible", timeout=8000)
        return True
    except Exception:
        log.error(
            "agenda: %s has a date group but no active booking for %s",
            target_date.isoformat(), BOOKING_DESK,
        )
        return False


def _card_time_range(card_locator) -> tuple[str, str]:
    span = card_locator.locator(".time-range").first
    if span.count() == 0:
        return "", ""
    txt = (span.inner_text() or "").strip()
    parts = [p.strip() for p in txt.split("-")]
    if len(parts) == 2 and all(":" in p for p in parts):
        return parts[0], parts[1]
    return "", ""


def _card_status(card_locator) -> str:
    tag = card_locator.locator(".djs-status-tag").first
    if tag.count() == 0:
        return ""
    cls = tag.get_attribute("class") or ""
    for s in STATUS_CLASSES:
        if s in cls.split():
            return s
    return ""
