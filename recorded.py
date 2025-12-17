import re
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import Playwright, sync_playwright


DEBUG_DIR = Path("debug_artifacts")
DEBUG_DIR.mkdir(exist_ok=True)


# ---------------------------
# Major step pause (2s)
# ---------------------------

def major_pause(page, ms: int = 2000):
    """Pause only at major page transitions / wizard steps."""
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
            locator.page.wait_for_timeout(250)
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
# Main scraper
# ---------------------------

def get_available_slots_for_court(
    playwright: Playwright,
    court_no: int,
    date_str: str,
    max_attempts: int = 2,
):
    complex_label = "Shahaji Raje Bhosle Kreeda Sankul, Andheri"
    last_error = None

    for attempt in range(1, max_attempts + 1):
        browser = context = page = None
        try:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()

            # STEP 0: Landing
            page.goto(
                "https://reczone.mcgm.gov.in/sports-complex/book-your-sport",
                wait_until="domcontentloaded",
            )
            wait_visible(page, "button:has-text('Next')", label="Step0 Next")

            # STEP 1: Next (moves to complex step)
            safe_click(page.get_by_role("button", name="Next"), label="Step1 Next")
            major_pause(page)  # major transition

            # STEP 2: Sports complex (major)
            wait_visible(page, "#select2-reczone-dropdown-container-container", label="Sports complex container")
            major_pause(page)  # before interacting with the dropdown

            open_select2_by_container_id(page, "#select2-reczone-dropdown-container-container")
            wait_visible(page, "input.select2-search__field", label="complex search field")
            page.locator("input.select2-search__field").first.fill(complex_label)
            select2_choose_option(page, complex_label)

            safe_click(page.get_by_role("button", name="Next"), label="After complex Next")
            major_pause(page)  # major transition to booking type step

            # STEP 3: Booking type (major)
            wait_visible(page, "text=General Slot Booking", label="General Slot Booking visible")
            major_pause(page)  # allow cards/overlay to settle

            safe_click(page.get_by_text("General Slot Booking"), label="Click General Slot Booking")
            safe_click(page.get_by_role("button", name="Next"), label="Next after booking type")
            major_pause(page)  # major transition to facility step

            # STEP 4: Sports Facility (major)
            wait_visible(
                page,
                "span.select2-selection__placeholder:has-text('Select your Sports Facility')",
                label="Facility placeholder",
            )
            major_pause(page)  # before opening facility dropdown

            open_select2_by_placeholder_text(page, "Select your Sports Facility")
            select2_choose_option(page, "Badminton")
            major_pause(page)  # after selecting badminton (sub-facility list often hydrates)

            # STEP 5: Court
            wait_visible(
                page,
                "span.select2-selection__placeholder:has-text('Select your Sports Sub-Facility')",
                label="Sub-facility placeholder",
            )
            open_select2_by_placeholder_text(page, "Select your Sports Sub-Facility")

            court_label = f"Wooden Court {court_no} | 968 Sq ft"
            opts = page.locator("li.select2-results__option").filter(has_text=court_label)

            # One retry if option list is late (NO 2s pause, just quick recovery)
            if opts.count() == 0:
                page.keyboard.press("Escape")
                page.wait_for_timeout(250)
                open_select2_by_placeholder_text(page, "Select your Sports Sub-Facility")
                opts = page.locator("li.select2-results__option").filter(has_text=court_label)

            if opts.count() == 0:
                raise RuntimeError(f"Court option not found: {court_label}")

            safe_click(opts.first, label=f"Select court {court_no}")

            safe_click(page.get_by_role("button", name="Next"), label="Next to slots")
            major_pause(page)  # major transition to slots page

            # STEP 6: Slots + date (major)
            wait_visible(page, "div.date-button", label="Slots date buttons")
            target_selector = f"div.date-button[data-active-date='{date_str}']"
            day_btn = page.locator(target_selector).first
            if day_btn.count() == 0:
                raise RuntimeError(f"Date button not found for {date_str}")

            safe_click(day_btn, label=f"Click date {date_str}")
            major_pause(page)  # allow grid to fully refresh after date click

            wait_visible(page, "div.timeslot-btn", label="Timeslot grid")
            page.wait_for_timeout(300)  # small buffer only (not 2s)

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

            context.close()
            browser.close()
            return available

        except Exception as e:
            last_error = e
            if page:
                dump_debug(page, f"attempt{attempt}_court{court_no}_{date_str}")

            if attempt < max_attempts:
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
                continue

            print(f"[FINAL FAIL] court={court_no} date={date_str} -> {type(e).__name__}: {e}")
            print(f"Saved debug artifacts in: {DEBUG_DIR.resolve()}")
            raise

    raise last_error


# ---------------------------
# Manual runner
# ---------------------------

if __name__ == "__main__":
    START_DATE = "2025-12-18"
    END_DATE = "2025-12-18"

    with sync_playwright() as p:
        for date_str in daterange(START_DATE, END_DATE):
            print(f"\n==================== {date_str} ====================")
            for court in range(1, 8):
                label = f"Wooden Court {court}"
                try:
                    slots = get_available_slots_for_court(p, court, date_str)
                    if slots:
                        print(f"{label}:")
                        for s in slots:
                            print(" ✔", s)
                    else:
                        print(f"{label}: ✖ No available slots")
                except Exception as e:
                    print(f"{label}: ERROR while checking ({type(e).__name__}: {e})")
