import re
from datetime import datetime, timedelta

from playwright.sync_api import Playwright, sync_playwright


# ---------------------------
# Select2 helpers (ROBUST)
# ---------------------------

def open_select2_by_container_id(page, id_prefix: str, timeout: int = 15000) -> None:
    """
    Opens a Select2 dropdown using its container ID prefix.
    Example: id_prefix="select2-facility_id-"
    """
    for _ in range(4):
        container = page.locator(f"span[id^='{id_prefix}'][id$='-container']").first
        selection = container.locator(
            "xpath=ancestor::span[contains(@class,'select2-selection')]"
        ).first

        try:
            selection.click(timeout=timeout)
        except Exception:
            try:
                selection.click(force=True, timeout=timeout)
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

    # Final fallback: JS click on a fresh handle
    container = page.locator(f"span[id^='{id_prefix}'][id$='-container']").first
    selection = container.locator(
        "xpath=ancestor::span[contains(@class,'select2-selection')]"
    ).first
    selection.evaluate("el => el.click()")
    page.wait_for_selector(
        "ul.select2-results__options li.select2-results__option",
        timeout=timeout,
        state="visible",
    )



def open_select2_by_placeholder_text(page, placeholder_text: str, timeout: int = 15000) -> None:
    """
    Opens a Select2 dropdown using its visible placeholder text, e.g.
    "Select your Sports Facility" or "Select your Sports Sub-Facility".
    Clicks the outer .select2-selection combobox, with retries.
    """
    for _ in range(4):
        # Always re-locate to avoid stale handles
        placeholder = page.locator("span.select2-selection__placeholder").filter(
            has_text=placeholder_text
        ).first
        selection = placeholder.locator(
            "xpath=ancestor::span[contains(@class,'select2-selection')]"
        ).first

        # Click -> check if dropdown opened
        try:
            selection.click(timeout=timeout)
        except Exception:
            try:
                selection.click(force=True, timeout=timeout)
            except Exception:
                page.wait_for_timeout(200)
                continue

        try:
            page.wait_for_selector(
                "ul.select2-results__options li.select2-results__option",
                timeout=1500,
                state="visible",
            )
            return  # success
        except Exception:
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)

    # Final fallback: JS click on a fresh handle
    placeholder = page.locator("span.select2-selection__placeholder").filter(
        has_text=placeholder_text
    ).first
    selection = placeholder.locator(
        "xpath=ancestor::span[contains(@class,'select2-selection')]"
    ).first
    selection.evaluate("el => el.click()")
    page.wait_for_selector(
        "ul.select2-results__options li.select2-results__option",
        timeout=timeout,
        state="visible",
    )


def daterange(start_date: str, end_date: str):
    """Yield date strings YYYY-MM-DD from start_date to end_date inclusive."""
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
    """
    For a given court and date (YYYY-MM-DD), return a list of available slot strings.
    Retries the whole flow up to `max_attempts` times to handle slow loads/timeouts.
    If all attempts fail, raises the last error.
    """
    target_date = datetime.strptime(date_str, "%Y-%m-%d")
    last_error = None

    for attempt in range(1, max_attempts + 1):
        browser = None
        context = None

        try:
            # For backend usage keep headless=True. For debugging set False.
            # browser = playwright.chromium.launch(headless=True)
            browser = playwright.chromium.launch(headless=False)

            context = browser.new_context()
            page = context.new_page()

            # Start page
            page.goto("https://reczone.mcgm.gov.in/sports-complex/book-your-sport")
            page.wait_for_load_state("networkidle")

            # Step 1: Next
            page.get_by_role("button", name="Next").click()
            page.wait_for_load_state("networkidle")

            # Step 2: Select sports complex
            page.get_by_text("Select your Sports complex").click()
            page.get_by_role("searchbox", name="Search").fill("shah")
            page.locator("span").filter(
                has_text="Shahaji Raje Bhosle Kreeda"
            ).nth(3).click()
            page.get_by_role("button", name="Next").click()
            page.wait_for_load_state("networkidle")

            # Step 3: General Slot Booking
            page.get_by_text("General Slot Booking").click()
            page.get_by_role("button", name="Next").click()
            page.wait_for_load_state("networkidle")

            # Step 4: Sports Facility (Badminton)
            open_select2_by_placeholder_text(page, "Select your Sports Facility")
            page.locator("li.select2-results__option").filter(
                has_text="Badminton"
            ).first.click()
            page.wait_for_timeout(200)

            # Step 5: Sports Sub-Facility (Court)
            open_select2_by_placeholder_text(page, "Select your Sports Sub-Facility")
            court_label = f"Wooden Court {court_no} | 968 Sq ft"
            page.wait_for_selector("li.select2-results__option", timeout=15000)

            court_options = page.locator("li.select2-results__option").filter(
                has_text=court_label
            )

            # Retry ONCE if list is empty
            if court_options.count() == 0:
                page.keyboard.press("Escape")
                page.wait_for_timeout(200)
                open_select2_by_placeholder_text(page, "Select your Sports Sub-Facility")
                page.wait_for_selector("li.select2-results__option", timeout=15000)
                court_options = page.locator("li.select2-results__option").filter(
                    has_text=court_label
                )

            if court_options.count() == 0:
                raise RuntimeError(f"Court option not found: {court_label}")

            court_options.first.click()

            # Step 6: Next to time slots page
            page.get_by_role("button", name="Next").click()
            page.wait_for_load_state("networkidle")

            # Step 7: Click correct day tab on slots page
            page.wait_for_selector("div.date-button", timeout=20000)

            target_selector = f"div.date-button[data-active-date='{date_str}']"
            day_button = page.locator(target_selector).first

            if not day_button.is_visible():
                day_button.scroll_into_view_if_needed()

            try:
                day_button.click()
            except Exception:
                page.wait_for_timeout(3000)
                try:
                    day_button.click()
                except Exception:
                    day_button.evaluate("el => el.click()")

            # Wait for slots grid
            page.wait_for_selector("div.timeslot-btn", timeout=25000)
            page.wait_for_timeout(1200)

            # Collect slot cards
            slot_cards = page.locator("div.timeslot-btn")
            count = slot_cards.count()
            available = []

            for i in range(count):
                card = slot_cards.nth(i)
                text = card.inner_text().strip()

                # Skip non-time cells
                if not re.search(r"(am|pm)", text):
                    continue

                opacity = card.evaluate(
                    "el => window.getComputedStyle(el).opacity"
                )
                pointer_events = card.evaluate(
                    "el => window.getComputedStyle(el).pointerEvents"
                )

                # Only keep fully active slots
                if opacity != "1" or pointer_events == "none":
                    continue

                available.append(text)

            return available

        except Exception as e:
            last_error = e

            if attempt < max_attempts:
                # retry from scratch
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

            # Out of attempts -> re-raise
            raise

        finally:
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

    if last_error:
        raise last_error

    return []


# ---------------------------
# Manual runner
# ---------------------------

if __name__ == "__main__":
    START_DATE = "2025-12-16"
    END_DATE = "2025-12-16"

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
                    print(
                        f"{label}: ERROR while checking ({type(e).__name__}: {e})"
                    )
