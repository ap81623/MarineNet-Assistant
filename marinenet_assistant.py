#!/usr/bin/env python3
"""
MarineNet Course Assistant
Handles tedious navigation so you can focus on the content.
You log in with your CAC, the assistant handles clicking through slides,
pauses on questions, and gives you a recommended answer + brief explanation
via Claude so you can learn from it before selecting your own answer.
"""

import asyncio
import os
import re
import sys
from datetime import datetime

import anthropic
from playwright.async_api import async_playwright, Page, Frame

# ── Config ────────────────────────────────────────────────────────────────────
MARINENET_URL = "https://www.marinenet.usmc.mil"

# How long to wait (ms) after clicking Next before looking for new content
NAV_SETTLE_MS = 1500

# Claude model used for question analysis
CLAUDE_MODEL = "claude-opus-4-6"

# Selectors tuned for common MarineNet / SCORM patterns
NEXT_SELECTORS = [
    "button:has-text('Next')",
    "button:has-text('Continue')",
    "a:has-text('Next')",
    "input[value='Next']",
    "input[value='Continue']",
    "input[type='button'][value*='next' i]",
    "button[id*='next' i]",
    "button[class*='next' i]",
    "[aria-label*='next' i]",
    "[title*='next' i]",
]

QUESTION_SIGNALS = [
    "[class*='question' i]",
    "[class*='quiz' i]",
    "[class*='assessment' i]",
    "[id*='question' i]",
    "input[type='radio']",
    "input[type='checkbox']",
    "[class*='answer' i]",
    "[class*='choice' i]",
]

SUBMIT_SELECTORS = [
    "button:has-text('Submit')",
    "input[value='Submit']",
    "button:has-text('Check')",
    "button:has-text('OK')",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def banner(msg: str, char: str = "─") -> None:
    width = 70
    print(f"\n{char * width}")
    print(f"  {msg}")
    print(f"{char * width}")


def status(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}]  {msg}")


def prompt_user(question: str) -> str:
    print(f"\n{'▶' * 3}  {question}")
    return input("    Your input → ").strip()


async def find_in_frames(page: Page, selector: str) -> list:
    """Search for a selector across the main page and all nested iframes."""
    results = []
    frames: list[Frame] = [page.main_frame]
    seen_urls: set[str] = set()

    while frames:
        frame = frames.pop()
        if frame.url in seen_urls:
            continue
        seen_urls.add(frame.url)

        try:
            els = await frame.query_selector_all(selector)
            results.extend(els)
        except Exception:
            pass

        try:
            child_frames = frame.child_frames
            frames.extend(child_frames)
        except Exception:
            pass

    return results


async def click_first_visible(page: Page, selectors: list[str]) -> bool:
    """Try each selector; click the first visible, enabled match. Returns True if clicked."""
    for sel in selectors:
        try:
            elements = await find_in_frames(page, sel)
            for el in elements:
                try:
                    visible = await el.is_visible()
                    enabled = await el.is_enabled()
                    if visible and enabled:
                        await el.scroll_into_view_if_needed()
                        await el.click()
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


async def page_has_question(page: Page) -> bool:
    """Return True if the current view looks like it contains a question."""
    for sel in QUESTION_SIGNALS:
        elements = await find_in_frames(page, sel)
        for el in elements:
            try:
                if await el.is_visible():
                    return True
            except Exception:
                continue
    return False


async def get_visible_text(page: Page, max_chars: int = 2000) -> str:
    """Pull readable text from the page / active frame for display."""
    frames: list[Frame] = [page.main_frame]
    text_parts: list[str] = []
    seen: set[str] = set()

    while frames:
        frame = frames.pop()
        if frame.url in seen:
            continue
        seen.add(frame.url)
        try:
            t = await frame.inner_text("body")
            if t:
                text_parts.append(t.strip())
        except Exception:
            pass
        try:
            frames.extend(frame.child_frames)
        except Exception:
            pass

    combined = "\n\n".join(text_parts)
    combined = re.sub(r"\n{3,}", "\n\n", combined)
    combined = re.sub(r" {2,}", " ", combined)
    return combined[:max_chars]


# ── Claude question advisor ───────────────────────────────────────────────────

def get_claude_recommendation(client: anthropic.Anthropic, question_text: str) -> str:
    """
    Ask Claude to identify the best answer to a MarineNet question and
    briefly explain why — so the learner understands the reasoning.
    Streams the response and returns the full text.
    """
    system = (
        "You are a knowledgeable Marine Corps training advisor. "
        "When given the text of a MarineNet course question (including any answer choices), "
        "you will:\n"
        "1. State the recommended answer clearly (e.g. 'Recommended answer: B – <option text>').\n"
        "2. Give a concise 2-4 sentence explanation of WHY that answer is correct, "
        "referencing the relevant Marine Corps doctrine, regulation, or principle when applicable.\n"
        "3. If relevant, briefly note why the other choices are wrong.\n"
        "Keep your response under 150 words. Be direct and educational."
    )

    full_text = ""
    print("\n  ┌─ Claude's Recommendation ──────────────────────────────────────")
    print("  │")

    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        thinking={"type": "adaptive"},
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
            # Indent each streamed chunk under the box border
            print(f"\r  │  {full_text.splitlines()[-1] if full_text.splitlines() else ''}", end="", flush=True)

    # Reprint neatly with proper line wrapping
    print("\r" + " " * 78, end="\r")  # clear the streaming line
    for line in full_text.splitlines():
        print(f"  │  {line}")
    print("  └" + "─" * 65)

    return full_text


async def wait_for_user_navigation(page: Page) -> None:
    banner("Waiting for you to open a course…", "═")
    print("  1. Log in with your CAC in the browser window that just opened.")
    print("  2. Navigate to the course you want to take.")
    print("  3. Press  ENTER  here once you're on the course's first slide/page.\n")
    input("  → Press ENTER when ready: ")


# ── Core loop ─────────────────────────────────────────────────────────────────

async def run_course(page: Page, claude: anthropic.Anthropic) -> None:
    slide_number = 0
    completed = False

    while not completed:
        slide_number += 1
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(NAV_SETTLE_MS / 1000)

        # ── Detect question ────────────────────────────────────────────────
        if await page_has_question(page):
            banner(f"QUESTION DETECTED  (slide ~{slide_number})", "★")
            text = await get_visible_text(page, max_chars=3000)

            # Print the question text
            print("\n" + text + "\n")

            # Ask Claude for a recommendation (runs synchronously in a thread
            # so the async event loop isn't blocked)
            status("Asking Claude for a recommendation…")
            try:
                await asyncio.to_thread(get_claude_recommendation, claude, text)
            except Exception as exc:
                print(f"\n  [Claude unavailable: {exc}]")

            print()
            print("  Read the question and Claude's suggestion above.")
            print("  Make your own selection in the browser, then press ENTER.")

            input("\n  → Press ENTER when you've answered and are ready to move on: ")

            # Try to submit / confirm if a submit button is present
            clicked = await click_first_visible(page, SUBMIT_SELECTORS)
            if clicked:
                status("Clicked Submit / Check button for you.")
                await asyncio.sleep(NAV_SETTLE_MS / 1000)
            continue  # re-evaluate the page after answering

        # ── Regular content slide ──────────────────────────────────────────
        text = await get_visible_text(page, max_chars=1500)

        banner(f"Slide {slide_number}", "─")
        lines = [l for l in text.splitlines() if l.strip()]
        preview = "\n".join(lines[:20])
        if len(lines) > 20:
            preview += f"\n  … ({len(lines) - 20} more lines — see browser for full content)"
        print(preview)

        # ── Advance ───────────────────────────────────────────────────────
        clicked = await click_first_visible(page, NEXT_SELECTORS)

        if clicked:
            status("Clicked Next ↓")
        else:
            banner("No 'Next' button found", "!")
            print("  Possible reasons:")
            print("  • This is the last slide — course complete!")
            print("  • The button has an unusual label.")
            print("  • Content is still loading.\n")
            choice = prompt_user("Options:  [r] retry  |  [s] skip/manual  |  [q] quit")
            if choice.lower() == "q":
                break
            elif choice.lower() == "r":
                slide_number -= 1
                continue
            else:
                input("  → Advance the course manually, then press ENTER: ")

    banner("Session ended. Check the browser — you may be done!", "═")


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    banner("MarineNet Course Assistant", "═")
    print("  This tool handles navigation so you can focus on the content.")
    print("  For every question, Claude will suggest an answer and explain why.")
    print("  You still make the final selection yourself.\n")

    # Validate API key up front
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  ⚠  ANTHROPIC_API_KEY not set.")
        print("     Export it before running:  export ANTHROPIC_API_KEY=sk-ant-...")
        print("     Question hints will be skipped if unavailable.\n")

    claude = anthropic.Anthropic(api_key=api_key) if api_key else None

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(
                channel="chrome",
                headless=False,
                args=["--enable-features=SecurityKeyAPI", "--no-sandbox"],
            )
            status("Launched Google Chrome.")
        except Exception:
            status("Google Chrome not found, using bundled Chromium.")
            browser = await pw.chromium.launch(
                headless=False,
                args=["--no-sandbox"],
            )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=False,
        )
        page = await context.new_page()

        status(f"Opening {MARINENET_URL} …")
        try:
            await page.goto(MARINENET_URL, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            status(f"Could not reach {MARINENET_URL}: {exc}")
            status("The browser is open — navigate there manually.")

        await wait_for_user_navigation(page)

        try:
            await run_course(page, claude)
        except KeyboardInterrupt:
            print("\n\nInterrupted by user.")
        finally:
            input("\nPress ENTER to close the browser: ")
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
