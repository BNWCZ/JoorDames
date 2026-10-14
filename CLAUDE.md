# JoorDames — Maintainer Notes

> Context for anyone (human or Claude Code) maintaining this project.
> Read this before changing anything — especially the error log at the bottom.

---

## What this is

A Python + Playwright script that manages desk reservations on [Door James](https://spa.doorjames.app), a desk-booking PWA behind Microsoft SSO. It runs from host cron, reads Google Calendar to know when the user is out of office, books / checks in / cancels accordingly, and sends a Discord notification for every significant event.

It is a single-user personal tool: one install = one person, one desk. Keep it simple.

---

## Tech stack

| Component | Choice | Reason |
|---|---|---|
| Automation | Python + Playwright (Chromium) | Robust against a modern Angular PWA |
| Base image | `mcr.microsoft.com/playwright/python` | Chromium bundled, maintained |
| Scheduling | Host cron → `docker compose run --rm joordames python src/main.py <mode>` | No in-container scheduler |
| Notifications | Discord webhook (+ optional bot for the `skip` command) | Free, one HTTP call |
| Calendar | Google Calendar API (service account) | Fully automatable, no OAuth dance |
| State | `bookings.csv` (one status per day) | Human-readable, easy to fix by hand |
| Secrets | `.env` file (never committed) | Credentials stay local |

---

## Behaviour

| Mode | What it does |
|---|---|
| `sync` | Reads 90 days of Google Calendar; writes `out of office - remote / holidays / public holiday` statuses to `bookings.csv`, clears stale ones |
| `book` | Books `BOOKING_DESK` in `BOOKING_AREA` for today + 41 days, `BOOKING_START`–`BOOKING_END` (default 09:00–17:00); skips weekends and out-of-office days; verifies the booking in the agenda before reporting success |
| `checkin` | Checks in today's booking — or cancels it if today is out of office. Honours the Discord `skip` command |
| `cancel` | Cancels today's booking |
| `reminder` | Weekend alert if next week has no remote-working event in the calendar |
| `auth` | Manual login in a visible browser (needs a display — run outside Docker) |

Check-in opens 30 minutes before the booking start; once checked in, a booking can no longer be cancelled (only checked out). Both actions are reached from the homepage "Réservations du jour" card.

---

## Authentication

- Credentials (`DOORJAMES_USERNAME`, `DOORJAMES_PASSWORD`, optional `MICROSOFT_EMAIL`) live in `.env`.
- The Playwright `storageState` is saved to `session/state.json` and refreshed at the end of every run that reached the app (error log #22).
- When the session has expired, `ensure_authenticated()` re-logs in headlessly through Microsoft SSO. In practice no MFA is requested; if it is, the user gets the number-matching code on Discord and 120 s to approve.
- An expired session must never fail silently: success sends "Réauthentification réussie", failure raises with a Discord error.

---

## Project structure

```
JoorDames/
├── CLAUDE.md               # This file
├── README.md               # User documentation (FR)
├── LICENSE                 # MIT
├── docs/                   # User guides (FR)
│   ├── installation-docker.md    # Docker install, first run, cron
│   ├── installation-standard.md  # Python install (no Docker), manual `auth`
│   ├── setup-google-calendar.md  # Service account, sharing, OOO patterns
│   └── setup-discord.md          # Webhook notifications + `skip` bot
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .env                    # Never committed
├── bookings.csv            # Never committed — per-day status
├── service_account.json    # Never committed — Google credentials
├── session/state.json      # Never committed — Playwright session
├── logs/                   # Rotating application log
├── debug_out/              # Screenshot + HTML dump on every failure
└── src/
    ├── main.py              # Modes, bookings.csv, notifications
    ├── spa_booker.py        # Door James book / cancel / check-in
    ├── auth.py              # Session reuse + headless SSO re-auth
    ├── calendar_client.py   # Google Calendar logic
    ├── discord_commands.py  # Discord `skip` command (bot)
    ├── notifier.py          # Discord webhook
    └── logger.py            # File + stdout logging, page dumps
```

---

## Working on it

- Never commit `.env`, `bookings.csv`, `service_account.json`, `session/`, `logs/` or `debug_out/` — all are in `.gitignore`.
- `src/` is baked into the image: `docker compose build` after every change (error log #19).
- Run `docker compose run` in the foreground with a generous timeout — Chromium takes ~30 s to start (error log #4).
- When a selector breaks: read the latest `debug_out/*.html`, fix the selector, grep **all** modules for the old one (error log #14), rebuild, re-run.
- A failed verification is not proof the action failed — check the agenda before writing an `error` status (error log #23).
- A behaviour or config change (new `.env` variable, mode, schedule) must be reflected in `README.md` and the matching `docs/` guide — they are what users install from.
- Every failure you fix goes into the error log below.

---

## Error log — learn from each mistake, never repeat it

Each error encountered during this project is logged here. Claude must not make the same mistake twice.

| # | Error | Rule |
|---|-------|------|
| 1 | `Write` tool called without reading the file first → `File has not been read yet` | Always `Read` before `Write` on existing files |
| 2 | Used `glob` pattern in a `Write` file path | `Write` requires an exact absolute path — no wildcards, no patterns |
| 3 | Refactored `run()` to accept `None` defaults but left `__main__` passing hardcoded values — dynamic logic silently ignored | When adding dynamic defaults to a function, update the call site too |
| 4 | Ran `docker compose run` in background, saw "Created" and assumed stuck, killed it — container was just slow to start (Playwright/Chrome init ~30s) | Always run `docker compose run` in foreground with sufficient timeout; never background it |
| 5 | Card filter used an exclude-list (`has_not: cancelled, expired, checkedOut`) — new `ai-recommendation` card type not excluded, silently selected instead of real booking | Use an allow-list (`has: confirmed, checkInOpen, …`) so unknown card types are automatically excluded |
| 6 | Clicked `.mat-mdc-form-field-infix input` to open time picker — a `time-separator` sibling div overlaps the element center and intercepts the click | Click `.mat-mdc-form-field-icon-suffix` (chevron icon, right of separator) which is the real visual affordance and has no overlap |
| 7 | Desk detail panel opens with "Ma réservation" tab active by default; saw "Annuler la réservation" there and assumed booking already existed — it did not | "Ma réservation" is always the default tab; "Sélectionner" lives under the "Actions" tab (lazy-loaded, not in DOM until clicked) |
| 8 | Booking wizard changed to a 6-step flow (Bureau → Type → Participants → Heure → Ressource → Confirmer); old code used selectors from the previous UI that no longer matched | Office selection uses `.widget-item` with `.widget-label` text, desk search uses `input[placeholder*='Rechercher par nom']` (not the generic `Rechercher`), and FAB menu may or may not appear — handle both paths |
| 9 | **June 2026 redesign** removed the `button.mdc-fab` FAB app-wide and replaced the 6-step wizard with a single-card form. Old code failed at auth (FAB was the logged-in signal) and at every booking step | Logged-in/booking entry is `button.new-booking-btn` (fallback to FAB). A delayed **"Quoi de neuf ?"** modal (`mat-dialog-container`, close via Escape + force-click `button.close-button`) blocks clicks — dismiss in a loop. Booking form has 3 rows `div.djs-list-item[role='button']`: **type de ressource** (→ `.widget-item[aria-label='Bureau']`), **Date et heure** (calendar day by `button.mat-calendar-body-cell[aria-label^='<day> ']`, De/À times via `.mat-mdc-form-field-icon-suffix` + `input.time-input-box[aria-label='Heure'/'Minute']`, then **Confirmer** in the `.sub-page-dialog`), **Ressource** (map: `.area-selector-button` → `.widget-item` area, search, `djs-teak-entity-item`, then **Sélectionner**). Final **Confirmer** FAB. Do **not** use the `.rec-chip` recommendation (unstable). |
| 10 | Matched calendar day by cell text `^13$` / French aria-label `"13 juillet"` — cell text carries hidden a11y content and aria-labels use **abbreviated** months (`"4 juil. 2026"`, not `"juillet"`) | Match the day by aria-label **prefix** on the number: `button.mat-calendar-body-cell[aria-label^='<day> ']` — locale-independent and unique within the displayed month |
| 11 | Booking `_verify_booking` matched *any* agenda item with the desk → false positives | Verify the **specific target date**: the agenda lists every booking from the current day forward (weekends and current week included), each under a date header (`<h2>` like `"13 août"` / `"5 juil."`). Find that header and require the desk with an active status in its date-group. This gates the success notification. |
| 12 | `cancel()`/`checkin()` inner flow still used pre-redesign selectors: cancel/check-in actions as `.mdc-list-item__primary-text` nav items and cancel-confirm `button.confirmation-button-danger` | In the redesigned card detail panel the actions are **buttons**: `button:has-text('Annuler la réservation')`, `button:has-text('Check-in')`; the cancel confirmation dialog is `mat-dialog-actions button:has-text('Confirmer')` ("Conserver" keeps). Click with `force=True` (touch-target overlay). |
| 13 | Verified cancel/check-in on the same homepage without reloading — the "Réservations du jour" card's status lags after the action (still shows the old tag for several seconds) → false "could not be verified" | After the action, `page.reload()` + re-dismiss overlays, then check status. Verify cancel as "no active-status card (`confirmed/checkInOpen/checkedIn/checkOutForgotten`) remains for the desk" (card may flip to `cancelled` or drop off). NB: the homepage card's *displayed time* is an intermittent ±2h timezone display bug (same booking shows different times across loads) — cosmetic only; the agenda is authoritative and stored times are correct. |
| 14 | The #9 redesign fix updated booking/cancel/checkin but missed `auth.py`'s six post-login "logged-in" waits, which still watched only `button.mdc-fab` — after a successful re-auth the app loads `button.new-booking-btn` instead, so every wait timed out and raised a false "réauthentification échouée" | Auth's logged-in DOM signal is the `APP_READY` constant (`button.new-booking-btn, button.mdc-fab`). When a UI-wide selector changes, grep **all** modules for the old selector, not just the flow you're editing. |
| 15 | Attached the `mode` `logging.Filter` to the parent `joordames` logger — records from child loggers (`joordames.auth`, …) reach the parent's **handlers** by propagation but never run the parent **logger's** filters → every log call raised `ValueError: Formatting field not found in record: 'mode'` | A filter that injects a field used by the format string belongs on the **handler**, not the logger |
| 16 | `TZ=Europe/Paris` in `docker-compose.yml` is a silent no-op: the Playwright image ships **no** `/usr/share/zoneinfo`, so glibc falls back to UTC and every naive `datetime.now()` in the container is 2h off | Business logic is safe because it uses `pytz` explicitly — but any **displayed** timestamp (log lines, `debug_out/` filenames) must be built from `PARIS_TZ`, never from a naive `datetime.now()` |
| 17 | **Sept 2026**: choosing `Bureau` in the *type de ressource* step stopped returning to the booking form and instead auto-advances into the **"Sélectionner une ressource"** map. That map's full-viewport `<canvas>` sits in the browser **top layer** (a `popover="manual"` CDK overlay), so every click on the form rows below it was swallowed — Playwright reported the row "visible, enabled and stable" and then timed out retrying | After selecting the resource type, close the auto-opened nested sub-page with `button.close-button[aria-label='Retour']`. **Both** topbars expose `button.close-button` — only the aria-label separates them (`Retour` = nested sub-page, `Fermer` = the booking form itself), so closing the wrong one abandons the booking. `_dismiss_overlays()` cannot help: it only knows `mat-dialog-container` and `.cdk-overlay-backdrop`, and this is a legitimately-open sub-page. Date/heure **must** be set before the desk is picked, or availability is computed against the form's default (today) |
| 18 | The De/À time picker was replaced by an Angular Material `<mat-timepicker>`: a listbox of 15-minute slots, not the old keyboard/clock picker — `input.time-input-box[aria-label='Heure'/'Minute']` no longer exists | Open the panel via `.mat-mdc-form-field-icon-suffix` (still true, error #6), then click the slot in `div.mat-timepicker-panel[aria-label='De'/'À']` — the panel carries its field's label, which is what keeps the two apart. **`De` options read `"09:00"` but `À` options append the duration (`"17:00 (8 h)"`)**, so anchor the match as `^HH:MM(\s\|$)`, never `^HH:MM$`; the duration text is built with non-breaking spaces (`\xa0`, `\u202f`) |
| 19 | Edited `src/`, re-ran `docker compose run`, and got the byte-identical error — briefly reading it as "the fix does not work". The Dockerfile does `COPY src/ ./src/` and `docker-compose.yml` mounts only `session/`, `bookings.csv`, `service_account.json`, `debug/`, `debug_out/`, `logs/` | `src/` is **baked into the image**, not mounted. Run `docker compose build` after every source change before testing, or the container silently runs the previous code |
| 20 | The booking form grew a `div.rec-strip` recommendation carousel whose cards are also `djs-teak-entity-item` and also match the desk name. `.first` picked the **recommendation** (earlier in the DOM than the map's CDK overlay), which is visible but sits *below* the full-viewport `popover="manual"` overlay, so every click was swallowed for 30 s | Never locate the desk with a bare `djs-teak-entity-item`. Scope to the map's result list: `ul.assets-in-group li.teak-entity-container djs-teak-entity-item`. The recommendation entity is `.rec-card__entity` and its card is `.not-selectable` with no `role`; a real result card is `[role='button']` — three independent discriminators, all in `_find_desk_in_results()` |
| 21 | The Door James login page **auto-redirects to Microsoft SSO**, and the redirect fired during the 500 ms sleep between `fill()` and the submit click. Step 1 then waited 30 s for `button[type='submit']` on a Microsoft page (which uses `#idSIButton9`) and aborted the run — while the account picker it needed was already rendered and step 2 knew how to drive it | Step 1 of the re-auth must **never** fail the run: check for `login.microsoftonline.com` in `page.url` after the fill, give the click a short timeout, and catch broadly (`PlaywrightTimeout` *and* the "execution context destroyed" family) so the flow falls through to step 2 |
| 22 | `save_session()` was only called from the manual login and after a successful headless re-auth, so `session/state.json` stayed frozen at the last manual login and aged out on a fixed clock (~14 days). The first real re-auth then exposed #21 — two latent bugs surfacing as one failure | Call `refresh_session(page, context)` in the `finally` block of **every** run mode that reaches the app, so rolling tokens are persisted and expiry becomes a non-event. It guards on `_is_on_app()` (never overwrite a good session with a logged-out one) and must never raise — it runs in a `finally` |
| 23 | Agenda date headers gained a **weekday prefix** — `mardi 3 nov.`, not the `13 août` of #11 — so `_verify_booking`'s anchored `^\s*3 nov` matched nothing. The booking had actually **succeeded**: the run wrote `error` to `bookings.csv` and fired a red ❌ for a live reservation | Match the header as `^\s*(?:\w+\s+)?<day> <abbr>\b` — the optional weekday word keeps the anchor (so `3 nov` still can't match inside `13 nov`) and the trailing `\b` stops a short month abbreviation matching a longer token. A verification failure is **not** proof the action failed: check the agenda dump before writing an error status |
| 24 | "Fixed" one line of `bookings.csv` with `read_text()`/`write_text()` — Python's universal newlines silently converted the file's **CRLF** endings (written by `csv.writer`) to LF, so the diff showed all 366 lines changed | Edit data files the app writes with `read_bytes()`/`write_bytes()` and an exact byte-level replace, then `diff` against a backup to prove exactly one line moved |
