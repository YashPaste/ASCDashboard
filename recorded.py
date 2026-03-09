import re
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from playwright.sync_api import Playwright, sync_playwright
from logger import get_logger

logger = get_logger(__name__)

DEBUG_DIR = Path("debug_artifacts")
DEBUG_DIR.mkdir(exist_ok=True)


# ---------------------------
# Pause helpers (reduced)
# ---------------------------

def major_pause(page, ms: int = 2000):
    """Pause at major page transitions / wizard steps."""
    page.wait_for_timeout(ms)


def mini_pause(page, ms: int = 200):
    page.wait_for_timeout(ms)


# ---------------------------
# Small robustness helpers
# ---------------------------

def safe_click(locator, timeout=15000, retries=3, label=""):
    last = None
    for _ in range(retries):
        try:
            locator.click(timeout=timeout)
            return
        except Exception as e:
            last = e
            try:
                locator.click(timeout=timeout, force=True)
                return
            except Exception as e2:
                last = e2
            locator.page.wait_for_timeout(200)
    try:
        locator.evaluate("el => el.click()")
        return
    except Exception as e:
        last = e
    raise RuntimeError(f"safe_click failed {label}: {last}")


def wait_visible(page, selector, timeout=20000, label=""):
    try:
        page.wait_for_selector(selector, timeout=timeout, state="visible")
    except Exception as e:
        raise RuntimeError(f"wait_visible failed {label} for {selector}: {e}")


def dump_debug(page, tag: str):
    try:
        page.screenshot(path=str(DEBUG_DIR / f"{tag}.png"), full_page=True)
    except Exception:
        pass
    try:
        html = page.content()
        (DEBUG_DIR / f"{tag}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass


# ---------------------------
# Select2 helpers
# ---------------------------

def open_select2_by_container_id(page, container_css: str, timeout: int = 15000) -> None:
    for _ in range(4):
        container = page.locator(container_css).first
        selection = container.locator(
            "xpath=ancestor::span[contains(@class,'select2-selection')]"
        ).first

        try:
            selection.scroll_into_view_if_needed(timeout=timeout)
        except Exception:
            pass
        try:
            selection.focus()
        except Exception:
            pass

        try:
            safe_click(selection, timeout=timeout, retries=2, label="open_select2")
        except Exception:
            page.wait_for_timeout(200)
            continue

        try:
            page.wait_for_selector(
                "ul.select2-results__options li.select2-results__option",
                timeout=1500,
                state="visible",
            )
            return
        except Exception:
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)

    selection.evaluate("el => el.click()")
    page.wait_for_selector(
        "ul.select2-results__options li.select2-results__option",
        timeout=timeout,
        state="visible",
    )


def open_select2_by_placeholder_text(page, placeholder_text: str, timeout: int = 15000) -> None:
    for _ in range(4):
        placeholder = page.locator("span.select2-selection__placeholder").filter(
            has_text=placeholder_text
        ).first
        selection = placeholder.locator(
            "xpath=ancestor::span[contains(@class,'select2-selection')]"
        ).first

        try:
            selection.scroll_into_view_if_needed(timeout=timeout)
        except Exception:
            pass
        try:
            selection.focus()
        except Exception:
            pass

        try:
            safe_click(selection, timeout=timeout, retries=2, label=placeholder_text)
        except Exception:
            page.wait_for_timeout(200)
            continue

        try:
            page.wait_for_selector(
                "ul.select2-results__options li.select2-results__option",
                timeout=1500,
                state="visible",
            )
            return
        except Exception:
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)

    selection.evaluate("el => el.click()")
    page.wait_for_selector(
        "ul.select2-results__options li.select2-results__option",
        timeout=timeout,
        state="visible",
    )


def select2_choose_option(page, option_text: str, timeout: int = 15000) -> None:
    page.wait_for_selector(
        "ul.select2-results__options li.select2-results__option",
        timeout=timeout,
        state="visible",
    )
    opt = page.locator("li.select2-results__option").filter(has_text=option_text).first
    if opt.count() == 0:
        raise RuntimeError(f"Select2 option not found: {option_text}")
    safe_click(opt, timeout=timeout, retries=2, label=option_text)


# ---------------------------
# Dates
# ---------------------------

def daterange(start_date: str, end_date: str):
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    cur = start
    while cur <= end:
        yield cur.strftime("%Y-%m-%d")
        cur += timedelta(days=1)


# ---------------------------
# Resource blocking (safe — analytics/tracking only)
# CSS and JS are NOT blocked because the wizard relies on
# CSS to hide inactive steps (14 "Next" buttons exist, only
# the active step's button should be visible/clickable).
# ---------------------------

BLOCKED_URL_PATTERNS = [
    "google-analytics", "googletagmanager", "facebook",
    "doubleclick", "hotjar", "clarity.ms", "cdn.heapanalytics",
]


def block_unnecessary_resources(route, request):
    """Block only analytics/tracking scripts. CSS/JS/fonts stay intact."""
    url = request.url.lower()
    for pattern in BLOCKED_URL_PATTERNS:
        if pattern in url:
            route.abort()
            return
    # Block only images and media (safe — no layout impact)
    if request.resource_type in {"image", "media"}:
        route.abort()
        return
    route.continue_()


# ---------------------------
# Navigate to facility step (Steps 0-4)
# Shared across all courts — this is the common prefix
# ---------------------------

def navigate_to_facility_step(page):
    """Navigate from landing page through Step 4 (Badminton selected).
    After this, the page is ready for court selection (Step 5).
    """
    complex_label = "Shahaji Raje Bhosle Kreeda Sankul, Andheri"

    # STEP 0: Landing
    page.goto(
        "https://reczone.mcgm.gov.in/sports-complex/book-your-sport",
        wait_until="domcontentloaded",
    )
    wait_visible(page, "button:has-text('Next')", label="Step0 Next")

    # STEP 1: Next (use .first — page has 14 Next buttons, CSS hides inactive ones)
    safe_click(page.get_by_role("button", name="Next").first, label="Step1 Next")
    major_pause(page)

    # STEP 2: Sports complex
    wait_visible(page, "#select2-reczone-dropdown-container-container", label="Sports complex container")
    major_pause(page)

    open_select2_by_container_id(page, "#select2-reczone-dropdown-container-container")
    wait_visible(page, "input.select2-search__field", label="complex search field")
    page.locator("input.select2-search__field").first.fill(complex_label)
    select2_choose_option(page, complex_label)

    safe_click(page.get_by_role("button", name="Next").first, label="After complex Next")

    # STEP 3: Booking type
    wait_visible(page, "text=General Slot Booking", label="General Slot Booking visible")
    major_pause(page)

    safe_click(page.get_by_text("General Slot Booking").first, label="Click General Slot Booking")
    safe_click(page.get_by_role("button", name="Next").first, label="Next after booking type")

    # STEP 4: Sports Facility
    wait_visible(
        page,
        "span.select2-selection__placeholder:has-text('Select your Sports Facility')",
        label="Facility placeholder",
    )
    major_pause(page)

    open_select2_by_placeholder_text(page, "Select your Sports Facility")
    select2_choose_option(page, "Badminton")
    major_pause(page)


# ---------------------------
# From facility step, pick court + date and collect slots (Steps 5-6)
# ---------------------------

def get_slots_from_facility_step(page, court_no: int, date_str: str):
    """Starting from facility-selected state, pick court, date, and return slots."""
    court_label = f"Wooden Court {court_no} | 968 Sq ft"

    # STEP 5: Court
    wait_visible(
        page,
        "span.select2-selection__placeholder:has-text('Select your Sports Sub-Facility')",
        label="Sub-facility placeholder",
    )
    open_select2_by_placeholder_text(page, "Select your Sports Sub-Facility")

    opts = page.locator("li.select2-results__option").filter(has_text=court_label)

    if opts.count() == 0:
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        open_select2_by_placeholder_text(page, "Select your Sports Sub-Facility")
        opts = page.locator("li.select2-results__option").filter(has_text=court_label)

    if opts.count() == 0:
        raise RuntimeError(f"Court option not found: {court_label}")

    safe_click(opts.first, label=f"Select court {court_no}")
    safe_click(page.get_by_role("button", name="Next").first, label="Next to slots")
    major_pause(page)

    # STEP 6: Slots + date
    wait_visible(page, "div.date-button", label="Slots date buttons")
    target_selector = f"div.date-button[data-active-date='{date_str}']"
    day_btn = page.locator(target_selector).first
    if day_btn.count() == 0:
        raise RuntimeError(f"Date button not found for {date_str}")

    safe_click(day_btn, label=f"Click date {date_str}")
    major_pause(page)

    wait_visible(page, "div.timeslot-btn", label="Timeslot grid")
    mini_pause(page, 300)

    # Collect slots
    slot_cards = page.locator("div.timeslot-btn")
    available = []

    for i in range(slot_cards.count()):
        card = slot_cards.nth(i)
        text = card.inner_text().strip()
        if not re.search(r"(am|pm)", text):
            continue

        opacity = card.evaluate("el => window.getComputedStyle(el).opacity")
        pointer_events = card.evaluate("el => window.getComputedStyle(el).pointerEvents")

        if opacity != "1" or pointer_events == "none":
            continue

        available.append(text)

    return available


# ---------------------------
# Single court worker (for parallel execution)
# ---------------------------

def check_single_court(court_no: int, date_str: str, max_attempts: int = 2):
    """Self-contained: launches its own Playwright + browser, checks one court.
    Designed to run in a thread.
    """
    last_error = None

    for attempt in range(1, max_attempts + 1):
        browser = context = page = None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    java_script_enabled=True,
                )
                page = context.new_page()

                # Block heavy resources
                page.route("**/*", block_unnecessary_resources)

                # Navigate Steps 0-4 (common for all courts)
                navigate_to_facility_step(page)

                # Steps 5-6 (court-specific)
                slots = get_slots_from_facility_step(page, court_no, date_str)

                context.close()
                browser.close()
                return slots

        except Exception as e:
            last_error = e
            if page:
                dump_debug(page, f"attempt{attempt}_court{court_no}_{date_str}")
            logger.warning(
                f"[Attempt {attempt}] court={court_no} date={date_str} -> {type(e).__name__}: {e}"
            )
            try:
                if context:
                    context.close()
            except Exception:
                pass
            try:
                if browser:
                    browser.close()
            except Exception:
                pass

            if attempt >= max_attempts:
                logger.error(
                    f"[FINAL FAIL] court={court_no} date={date_str} -> {type(e).__name__}: {e}",
                    exc_info=True,
                )
                raise

    raise last_error


# ---------------------------
# Original function (kept for backward compat)
# ---------------------------

def get_available_slots_for_court(
    playwright: Playwright,
    court_no: int,
    date_str: str,
    max_attempts: int = 2,
):
    """Backward-compatible wrapper. Ignores the playwright arg and calls check_single_court."""
    return check_single_court(court_no, date_str, max_attempts)


# ---------------------------
# Parallel batch checker
# ---------------------------

def check_all_courts_parallel(
    date_str: str,
    courts: list = None,
    max_workers: int = 3,
    progress_callback=None,
):
    """Check multiple courts in parallel for a given date.

    Args:
        date_str: Date string YYYY-MM-DD
        courts: List of court numbers (default 1-7)
        max_workers: Max parallel browsers (3 is safe for Render Free 512MB)
        progress_callback: Optional fn(court_no, status, slots_or_error) called per court

    Returns:
        dict: {court_no_str: slots_list_or_"ERROR"}
    """
    if courts is None:
        courts = list(range(1, 8))

    results = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_court = {
            executor.submit(check_single_court, court, date_str): court
            for court in courts
        }

        for future in as_completed(future_to_court):
            court = future_to_court[future]
            try:
                slots = future.result()
                results[str(court)] = slots
                if progress_callback:
                    progress_callback(court, "ok", slots)
            except Exception as e:
                results[str(court)] = "ERROR"
                if progress_callback:
                    progress_callback(court, "error", str(e))

    return results


# ---------------------------
# Manual runner
# ---------------------------

if __name__ == "__main__":
    START_DATE = "2025-12-19"
    END_DATE = "2025-12-19"

    for date_str in daterange(START_DATE, END_DATE):
        logger.info("\n==================== %s ====================", date_str)

        def on_progress(court, status, data):
            label = f"Wooden Court {court}"
            if status == "ok":
                logger.info(f"{label}: {len(data)} slots found")
                for s in data:
                    logger.info(f"  ✔ {s}")
            else:
                logger.error(f"{label}: ERROR - {data}")

        results = check_all_courts_parallel(
            date_str,
            max_workers=3,
            progress_callback=on_progress,
        )