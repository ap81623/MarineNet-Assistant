#!/usr/bin/env python3
"""
MarineNet Course Assistant
Handles tedious navigation so you can focus on reading the content.
You log in with your CAC, the assistant clicks through slides for you,
pauses on real questions, and gives you Claude's recommended answer
with a brief explanation so you can learn from it.
"""

import asyncio
import hashlib
import os
import re
import sys
from datetime import datetime

import anthropic
from playwright.async_api import async_playwright, Page, Frame, ElementHandle

# ── Config ────────────────────────────────────────────────────────────────────
MARINENET_URL = "https://www.marinenet.usmc.mil"

# Settle time after clicking (seconds)
NAV_SETTLE_SEC = 2.0

# Extra wait for slow SCORM loads
SCORM_LOAD_SEC = 3.0

# Claude model for question analysis
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# Max consecutive times we can see the same content before asking for help
MAX_STUCK_COUNT = 3

# ── Navigation selectors (ordered by likelihood) ─────────────────────────────
# These cover common SCORM player patterns, Articulate Storyline, Adobe Captivate, etc.
NEXT_SELECTORS = [
    # Standard SCORM player buttons
    "button[id*='next' i]",
    "button[id*='Next']",
    "a[id*='next' i]",
    "input[id*='next' i]",
    # Text-based
    "button:has-text('Next')",
    "button:has-text('NEXT')",
    "a:has-text('Next')",
    "a:has-text('NEXT')",
    "input[value='Next']",
    "input[value='NEXT']",
    "button:has-text('Continue')",
    "a:has-text('Continue')",
    "input[value='Continue']",
    # Aria / title
    "[aria-label*='next' i]",
    "[aria-label*='Next']",
    "[title*='Next']",
    "[title*='next page' i]",
    "[title*='forward' i]",
    # Class-based
    "button[class*='next' i]",
    "a[class*='next' i]",
    "[class*='nav-next' i]",
    "[class*='navNext' i]",
    "[class*='btn-next' i]",
    "[class*='btnNext' i]",
    # Arrow / icon buttons (Articulate, Captivate)
    "button[class*='right-arrow' i]",
    "button[class*='forward' i]",
    "[class*='arrow-right' i]",
    "[class*='slide-forward' i]",
    # Generic play/advance
    "button:has-text('Proceed')",
    "button:has-text('Advance')",
    "button:has-text('Start')",
    "a:has-text('Proceed')",
    # Articulate Storyline specific
    "[data-acc-text*='next' i]",
    "[data-ref='next']",
    # Common icon-only next buttons (right chevron, etc.)
    "button[class*='chevron-right' i]",
    "button[class*='fa-chevron-right']",
    "button[class*='fa-arrow-right']",
]

# Selectors that ONLY match actual interactive answer inputs
ANSWER_INPUT_SELECTORS = [
    "input[type='radio']",
    "input[type='checkbox']",
]

# Additional confirmation: elements that wrap quiz questions
QUIZ_CONTAINER_SELECTORS = [
    "[class*='quiz' i]",
    "[class*='assessment' i]",
    "[class*='exam' i]",
    "[class*='test' i][class*='question' i]",
    "[id*='quiz' i]",
    "[id*='assessment' i]",
]

SUBMIT_SELECTORS = [
    "button:has-text('Submit')",
    "input[value='Submit']",
    "button:has-text('Check Answer')",
    "button:has-text('Check')",
    "button:has-text('Confirm')",
    "input[value='Submit Answer']",
    "button[id*='submit' i]",
]

# Things to click away (popups, modals, confirmations)
DISMISS_SELECTORS = [
    "button:has-text('OK')",
    "button:has-text('Close')",
    "button:has-text('Got it')",
    "button:has-text('Dismiss')",
    "[class*='modal'] button[class*='close' i]",
    "[class*='dialog'] button[class*='close' i]",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def banner(msg: str, char: str = "─") -> None:
    width = 70
    print(f"\n{char * width}")
    print(f"  {msg}")
    print(f"{char * width}")


def status(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}]  {msg}")


def content_hash(text: str) -> str:
    """Hash page text to detect if we're stuck on the same slide."""
    cleaned = re.sub(r'\s+', ' ', text.strip().lower())
    return hashlib.md5(cleaned.encode()).hexdigest()[:12]


def get_all_frames(page: Page) -> list[Frame]:
    """Get all frames including nested iframes."""
    frames = []
    seen = set()

    def collect(frame: Frame):
        fid = id(frame)
        if fid in seen:
            return
        seen.add(fid)
        frames.append(frame)
        for child in frame.child_frames:
            collect(child)

    collect(page.main_frame)
    return frames


async def find_in_frames(page: Page, selector: str) -> list[tuple[Frame, ElementHandle]]:
    """Search for a selector across the main page and all nested iframes.
    Returns list of (frame, element) tuples."""
    results = []
    for frame in get_all_frames(page):
        try:
            els = await frame.query_selector_all(selector)
            for el in els:
                results.append((frame, el))
        except Exception:
            pass
    return results


async def count_visible(page: Page, selector: str) -> int:
    """Count visible elements matching selector across all frames."""
    count = 0
    for frame in get_all_frames(page):
        try:
            els = await frame.query_selector_all(selector)
            for el in els:
                try:
                    if await el.is_visible():
                        count += 1
                except Exception:
                    pass
        except Exception:
            pass
    return count


async def click_first_visible(page: Page, selectors: list[str]) -> bool:
    """Try each selector; click the first visible, enabled match."""
    for sel in selectors:
        try:
            results = await find_in_frames(page, sel)
            for frame, el in results:
                try:
                    visible = await el.is_visible()
                    enabled = await el.is_enabled()
                    if visible and enabled:
                        await el.scroll_into_view_if_needed()
                        await asyncio.sleep(0.2)
                        await el.click()
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


async def is_real_question(page: Page) -> bool:
    """
    Determine if the current page has an ACTUAL question with answer choices.

    The key insight: a real question page has VISIBLE radio buttons or checkboxes
    that the user needs to interact with. We require at least 2 visible radio/checkbox
    inputs — that's the universal signal for a multiple-choice question regardless
    of how the SCORM package styles things.
    """
    # Primary check: are there 2+ visible radio buttons or checkboxes?
    radio_count = await count_visible(page, "input[type='radio']")
    checkbox_count = await count_visible(page, "input[type='checkbox']")

    if radio_count >= 2 or checkbox_count >= 2:
        return True

    # Secondary check: clickable answer-choice elements (some SCORM packages
    # use styled divs/buttons instead of native inputs)
    # Look for multiple sibling elements that look like answer choices
    for frame in get_all_frames(page):
        try:
            # Articulate Storyline pattern: buttons with answer text
            choice_patterns = [
                "[class*='choice' i][role='button']",
                "[class*='answer' i][role='button']",
                "[class*='option' i][role='radio']",
                "[role='radio']",
                "[role='option']",
                "label[class*='choice' i]",
                "label[class*='answer' i]",
                "[class*='mcq'] [class*='option' i]",
            ]
            for pattern in choice_patterns:
                try:
                    els = await frame.query_selector_all(pattern)
                    visible_count = 0
                    for el in els:
                        try:
                            if await el.is_visible():
                                visible_count += 1
                        except Exception:
                            pass
                    if visible_count >= 2:
                        return True
                except Exception:
                    pass
        except Exception:
            pass

    # Check for quiz container + any interactive element
    for sel in QUIZ_CONTAINER_SELECTORS:
        containers = await find_in_frames(page, sel)
        for frame, container in containers:
            try:
                if await container.is_visible():
                    # There's a visible quiz container — check for any input inside
                    inner = await container.query_selector_all("input, select, [role='radio'], [role='checkbox']")
                    if len(inner) >= 2:
                        return True
            except Exception:
                pass

    return False


async def get_question_text(page: Page, max_chars: int = 3000) -> str:
    """Extract text specifically from question/answer areas if possible,
    falling back to full page text."""
    # Try to get text from quiz containers first
    for sel in QUIZ_CONTAINER_SELECTORS:
        results = await find_in_frames(page, sel)
        for frame, el in results:
            try:
                if await el.is_visible():
                    text = await el.inner_text()
                    if text and len(text.strip()) > 20:
                        return text.strip()[:max_chars]
            except Exception:
                pass

    # Fall back to getting all visible text
    return await get_visible_text(page, max_chars)


async def get_visible_text(page: Page, max_chars: int = 2000) -> str:
    """Pull readable text from the page / active frames."""
    text_parts = []

    for frame in get_all_frames(page):
        try:
            t = await frame.inner_text("body")
            if t and t.strip():
                text_parts.append(t.strip())
        except Exception:
            pass

    combined = "\n\n".join(text_parts)
    combined = re.sub(r"\n{3,}", "\n\n", combined)
    combined = re.sub(r" {2,}", " ", combined)
    return combined[:max_chars]


async def dismiss_popups(page: Page) -> None:
    """Try to close any modal/popup that might be blocking."""
    for sel in DISMISS_SELECTORS:
        try:
            results = await find_in_frames(page, sel)
            for frame, el in results:
                try:
                    if await el.is_visible():
                        await el.click()
                        await asyncio.sleep(0.5)
                except Exception:
                    pass
        except Exception:
            pass


async def try_advance(page: Page) -> bool:
    """Try all methods to advance to the next slide."""
    # First try standard next buttons
    if await click_first_visible(page, NEXT_SELECTORS):
        return True

    # Try dismissing a popup first, then retry
    await dismiss_popups(page)
    await asyncio.sleep(0.5)
    if await click_first_visible(page, NEXT_SELECTORS):
        return True

    # Try keyboard navigation (some SCORM players support this)
    try:
        for frame in get_all_frames(page):
            try:
                await frame.press("body", "ArrowRight")
                await asyncio.sleep(1.0)
                return True  # Can't be sure it worked, caller checks via hash
            except Exception:
                pass
    except Exception:
        pass

    return False


# ── Claude question advisor ──────────────────────────────────────────────────

def get_claude_recommendation(client: anthropic.Anthropic, question_text: str) -> str:
    """
    Ask Claude to identify the best answer and explain why.
    """
    system = (
        "You are a knowledgeable Marine Corps training advisor. "
        "When given the text of a MarineNet course question (including any answer choices), "
        "you will:\n"
        "1. State the recommended answer clearly (e.g. 'Recommended answer: B – <option text>').\n"
        "2. Give a concise 2-4 sentence explanation of WHY that answer is correct, "
        "referencing relevant Marine Corps doctrine, regulation, or principle when applicable.\n"
        "3. If relevant, briefly note why the other choices are wrong.\n"
        "Keep your response under 150 words. Be direct and educational."
    )

    full_text = ""
    print()
    print("  ┌─ Claude's Recommendation ──────────────────────────────────────")
    print("  │")

    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=system,
        messages=[
            {
                "role": "user",
                "content": (
                    "Here is the question from my MarineNet course:\n\n"
                    f"{question_text}\n\n"
                    "What is the recommended answer, and why?"
                ),
            }
        ],
    ) as stream:
        for text in stream.text_stream:
            full_text += text

    # Print neatly
    for line in full_text.splitlines():
        print(f"  │  {line}")
    print("  │")
    print("  └" + "─" * 65)

    return full_text


# ── Core loop ────────────────────────────────────────────────────────────────

async def wait_for_user_navigation(page: Page) -> None:
    banner("Waiting for you to open a course…", "═")
    print("  1. Log in with your CAC in the browser window.")
    print("  2. Navigate to the course and open the first lesson/slide.")
    print("  3. Come back here and press ENTER.\n")
    input("  → Press ENTER when you're on the first slide: ")


async def run_course(page: Page, claude: anthropic.Anthropic | None) -> None:
    slide_number = 0
    last_hash = ""
    stuck_count = 0

    banner("Course assistant is running", "═")
    print("  • Content slides: auto-advancing (you just read the browser)")
    print("  • Questions: will pause and show Claude's recommendation")
    print("  • Press Ctrl+C at any time to stop\n")

    while True:
        slide_number += 1
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(NAV_SETTLE_SEC)

        # Get current page text and check if we're stuck
        text = await get_visible_text(page, max_chars=2000)
        current_hash = content_hash(text)

        if current_hash == last_hash:
            stuck_count += 1
            if stuck_count >= MAX_STUCK_COUNT:
                banner(f"Stuck on the same content (tried {stuck_count} times)", "!")
                print("  The page isn't advancing. Possible reasons:")
                print("  • Course is complete")
                print("  • Navigation button has an unusual pattern")
                print("  • A popup or modal is blocking")
                print("  • Content requires interaction before advancing\n")
                choice = input("  [r] retry  |  [m] I'll advance manually  |  [q] quit → ").strip().lower()
                if choice == "q":
                    break
                elif choice == "m":
                    input("  → Advance the course manually, then press ENTER: ")
                    stuck_count = 0
                    last_hash = ""
                    continue
                else:
                    stuck_count = 0
                    await dismiss_popups(page)
                    continue
        else:
            stuck_count = 0
            last_hash = current_hash

        # ── Check for a REAL question ─────────────────────────────────────
        if await is_real_question(page):
            banner(f"✦ QUESTION  (slide ~{slide_number})", "★")

            question_text = await get_question_text(page)
            # Show the question text
            print()
            for line in question_text.splitlines()[:30]:
                if line.strip():
                    print(f"    {line.strip()}")
            print()

            # Get Claude's recommendation
            if claude:
                status("Asking Claude for a recommendation…")
                try:
                    await asyncio.to_thread(get_claude_recommendation, claude, question_text)
                except Exception as exc:
                    print(f"\n  [Claude error: {exc}]")
            else:
                print("  (No API key — Claude recommendations unavailable)")

            print()
            print("  ➤ Select your answer in the browser window.")
            input("  → Press ENTER when you've answered: ")

            # Try to submit
            clicked_submit = await click_first_visible(page, SUBMIT_SELECTORS)
            if clicked_submit:
                status("Clicked Submit for you.")
                await asyncio.sleep(NAV_SETTLE_SEC)
                # After submit, try to dismiss result popups and advance
                await dismiss_popups(page)
                await asyncio.sleep(1.0)

            # Try to advance past the question
            await try_advance(page)
            await asyncio.sleep(NAV_SETTLE_SEC)
            last_hash = ""  # Reset hash after question
            continue

        # ── Regular content slide — auto-advance ──────────────────────────
        # Show a brief preview in terminal so user knows what slide we're on
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        preview = lines[0] if lines else "(no text detected)"
        if len(preview) > 80:
            preview = preview[:77] + "…"
        status(f"Slide {slide_number}: {preview}")

        # Auto-advance
        advanced = await try_advance(page)
        if advanced:
            status("  → Advanced ✓")
        else:
            status("  → No next button found, waiting…")
            await asyncio.sleep(1.0)

        await asyncio.sleep(NAV_SETTLE_SEC)


# ── Entry point ──────────────────────────────────────────────────────────────

async def main() -> None:
    banner("MarineNet Course Assistant", "═")
    print("  Handles clicking through slides so you can focus on reading.")
    print("  Pauses on questions and shows Claude's recommended answer.\n")

    # Validate API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  ⚠  ANTHROPIC_API_KEY not set.")
        print("     export ANTHROPIC_API_KEY=sk-ant-...")
        print("     Questions will still pause but without recommendations.\n")

    claude = anthropic.Anthropic(api_key=api_key) if api_key else None

    async with async_playwright() as pw:
        # Launch browser
        try:
            browser = await pw.chromium.launch(
                channel="chrome",
                headless=False,
                args=["--no-sandbox"],
            )
            status("Launched Google Chrome.")
        except Exception:
            status("Chrome not found, using bundled Chromium.")
            browser = await pw.chromium.launch(
                headless=False,
                args=["--no-sandbox"],
            )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=False,
        )
        page = await context.new_page()

        status(f"Opening {MARINENET_URL}…")
        try:
            await page.goto(MARINENET_URL, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            status(f"Could not reach MarineNet: {exc}")
            status("Navigate there manually in the browser window.")

        await wait_for_user_navigation(page)

        try:
            await run_course(page, claude)
        except KeyboardInterrupt:
            print("\n\n  Stopped by user.")
        finally:
            banner("Session complete", "═")
            input("  Press ENTER to close the browser: ")
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
