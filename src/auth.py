import os
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Playwright, TimeoutError as PlaywrightTimeout

from logger import dump_page_state, get_logger
from notifier import notify

log = get_logger("auth")

STATE_PATH = Path(os.getenv("SESSION_STATE_PATH", "session/state.json"))
APP_DOMAIN = "spa.doorjames.app"
MS_DOMAIN = "login.microsoftonline.com"
APP_URL = os.getenv("APP_URL", "https://spa.doorjames.app")

# "Logged-in" DOM signal. The June 2026 redesign (error log #9) removed the
# app-wide FAB (button.mdc-fab) in favour of button.new-booking-btn; keep the
# FAB as a fallback for older UI states.
APP_READY = "button.new-booking-btn, button.mdc-fab"


def get_browser_context(playwright: Playwright, headless: bool = True) -> tuple[Browser, BrowserContext]:
    log.debug("launching chromium (headless=%s)", headless)
    browser = playwright.chromium.launch(
        headless=headless,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    context_kwargs = {
        "timezone_id": "Europe/Paris",
        "locale": "fr-FR",
    }
    if STATE_PATH.exists():
        age_h = (datetime.now().timestamp() - STATE_PATH.stat().st_mtime) / 3600
        log.info("reusing saved session %s (%.1f h old)", STATE_PATH, age_h)
        context = browser.new_context(storage_state=str(STATE_PATH), **context_kwargs)
    else:
        log.warning("no saved session at %s — a full login will be required", STATE_PATH)
        context = browser.new_context(**context_kwargs)
    return browser, context


def _is_on_app(page) -> bool:
    """True when the page is on the app domain AND past the login screen."""
    return APP_DOMAIN in page.url and "/login" not in page.url


def _wait_for_page_ready(page, timeout: int = 30_000) -> None:
    """Wait until the SPA dashboard or a login form is visible."""
    selector = (
        "button.new-booking-btn, button.mdc-fab, "
        "input[name='email']:not([disabled]), "
        "input[name='loginfmt'], #tilesHolder, input#i0118, "
        "#idDiv_SAOTCAS_Title, #idRichContext_DisplaySign"
    )
    try:
        page.wait_for_selector(selector, timeout=timeout)
    except PlaywrightTimeout:
        log.warning("page not ready after %sms (url=%s) — reloading and retrying once", timeout, page.url)
        dump_page_state(page, "wait_for_page_ready_retry")
        page.reload(wait_until="load")
        try:
            page.wait_for_selector(selector, timeout=timeout)
        except PlaywrightTimeout:
            log.error("page still not ready after reload (url=%s)", page.url)
            dump_page_state(page, "wait_for_page_ready_failed")
            raise


def is_session_expired(page) -> bool:
    _wait_for_page_ready(page)
    if _is_on_app(page):
        log.info("session valid (url=%s)", page.url)
        return False
    log.warning("session expired — landed on %s", page.url)
    return True


def save_session(context: BrowserContext) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(STATE_PATH))
    log.info("session saved to %s", STATE_PATH)


def refresh_session(page, context: BrowserContext) -> None:
    """
    Persist the rolling session after a run that reached the app.

    ``save_session`` used to be called only from the manual login and from a
    successful headless re-auth, so ``state.json`` stayed frozen at whatever
    the last manual login produced and aged out on a fixed clock (error log
    #22). Writing it back on every run that ended up logged in keeps the
    refresh token current and makes expiry a non-event.

    Called from a ``finally`` block — it must never raise.
    """
    try:
        if _is_on_app(page):
            save_session(context)
        else:
            log.debug("not on the app (url=%s) — keeping the previous session", page.url)
    except Exception as exc:  # pragma: no cover - best effort
        log.warning("could not refresh the saved session: %s", exc)


def ensure_authenticated(page, context: BrowserContext) -> bool:
    """
    Returns False if the session is still valid (no-op).
    Returns True after a successful headless re-authentication.
    Raises RuntimeError if re-authentication fails.
    """
    if not is_session_expired(page):
        return False

    username = os.getenv("DOORJAMES_USERNAME", "")
    password = os.getenv("DOORJAMES_PASSWORD", "")
    ms_email = os.getenv("MICROSOFT_EMAIL", username)
    if not username or not password:
        raise RuntimeError(
            "Session expirée — DOORJAMES_USERNAME ou DOORJAMES_PASSWORD "
            "non configuré dans .env"
        )

    # Step 1 — Door James login page
    # The SPA may auto-redirect to Microsoft SSO (disabled email field), and
    # that redirect can fire *while* we are filling the form (error log #21).
    # Once it does, the Door James submit button no longer exists — Microsoft
    # uses #idSIButton9 — so never let this step fail the run: step 2 below
    # already knows how to drive the account picker / email form.
    log.info("re-authenticating headlessly as %s", username)
    dj_email = page.locator("input[name='email']:not([disabled])")
    if dj_email.count() > 0:
        log.info("step 1: Door James login form — submitting username")
        try:
            dj_email.fill(username)
            page.wait_for_timeout(500)
            if MS_DOMAIN in page.url:
                log.info("step 1: auto-redirected to Microsoft SSO — skipping submit")
            else:
                page.locator("button[type='submit']:not([disabled])").click(timeout=10_000)
        except Exception as exc:
            # Includes PlaywrightTimeout and the "execution context destroyed"
            # family raised when the redirect lands mid-fill.
            log.warning(
                "step 1: Door James form went away mid-submit (%s: %s, url=%s) — "
                "continuing with the Microsoft flow",
                type(exc).__name__,
                str(exc).splitlines()[0][:120],
                page.url,
            )

    ms_or_app = f"#tilesHolder, input[name='loginfmt'], input#i0118, {APP_READY}"
    if not _is_on_app(page):
        log.debug("waiting for Microsoft SSO or app (url=%s)", page.url)
        page.wait_for_selector(ms_or_app, timeout=30_000)
        page.wait_for_timeout(2000)

    # Step 2 — Microsoft: account picker OR email input
    if not _is_on_app(page):
        tile = page.locator("#tilesHolder > div").first
        ms_loginfmt = page.locator("input[name='loginfmt']")

        if tile.count() > 0:
            log.info("step 2: Microsoft account picker — selecting first tile")
            tile.click()
            page.wait_for_selector(
                f"input#i0118, {APP_READY}, #idBtn_Back",
                timeout=30_000,
            )
            page.wait_for_timeout(2000)
        elif ms_loginfmt.is_visible():
            log.info("step 2: Microsoft email form — submitting %s", ms_email)
            ms_loginfmt.fill(ms_email)
            page.wait_for_timeout(300)
            page.click("#idSIButton9")
            page.wait_for_selector(
                f"input#i0118, {APP_READY}, #idBtn_Back",
                timeout=30_000,
            )
            page.wait_for_timeout(2000)

    # Step 3 — Microsoft password page (may be skipped if MS session is valid)
    if not _is_on_app(page):
        try:
            page.wait_for_selector(
                "input[name='loginfmt']", state="hidden", timeout=10_000
            )
        except Exception:
            pass
        page.wait_for_timeout(1000)
        log.info("step 3: Microsoft password form")
        page.fill("input#i0118", password)
        page.wait_for_timeout(500)
        page.click("#idSIButton9")
        page.wait_for_selector(
            f"{APP_READY}, #idBtn_Back, #idDiv_SAOTCAS_Title, "
            "#idRichContext_DisplaySign, #passwordError",
            timeout=30_000,
        )
        if page.locator("#passwordError").count() > 0 and page.locator("#passwordError").is_visible():
            log.error("Microsoft rejected the password")
            dump_page_state(page, "password_error")
            raise RuntimeError(
                "Mot de passe incorrect — mettez à jour DOORJAMES_PASSWORD dans .env"
            )
        page.wait_for_timeout(2000)

    # Step 3b — Microsoft MFA approval (Authenticator push or number matching)
    if not _is_on_app(page):
        mfa_prompt = page.locator("#idDiv_SAOTCAS_Title, #idRichContext_DisplaySign")
        if mfa_prompt.count() > 0:
            number_el = page.locator("#idRichContext_DisplaySign")
            if number_el.count() > 0:
                code = number_el.inner_text().strip()
                notify("MFA requise 🔐", f"Approuvez la connexion sur votre téléphone (code : {code})")
            else:
                notify("MFA requise 🔐", "Approuvez la notification Microsoft Authenticator sur votre téléphone")
            log.warning("step 3b: MFA approval required — waiting up to 120s")
            dump_page_state(page, "mfa_waiting")
            page.wait_for_selector(
                f"{APP_READY}, #idBtn_Back", timeout=120_000,
            )
            page.wait_for_timeout(2000)

    # Step 4 — "Stay signed in?" interstitial (click No)
    if not _is_on_app(page):
        stay_btn = page.locator("#idBtn_Back")
        if stay_btn.count() > 0:
            log.info("step 4: dismissing the 'Stay signed in?' interstitial")
            stay_btn.click()
            page.wait_for_selector(APP_READY, timeout=30_000)
            page.wait_for_timeout(2000)

    if not _is_on_app(page):
        log.error("re-authentication failed — still not on the app (url=%s)", page.url)
        dump_page_state(page, "reauth_failed")
        raise RuntimeError(
            "Session expirée — réauthentification échouée "
            f"(MFA ou erreur de mot de passe). URL: {page.url}\n"
            f"Connectez-vous manuellement : {APP_URL}"
        )

    log.info("re-authentication succeeded (url=%s)", page.url)
    save_session(context)
    return True
