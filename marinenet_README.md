# MarineNet Course Assistant

Handles tedious slide navigation so you can focus on reading content and answering questions yourself.

## What it does
- Opens Google Chrome and navigates to MarineNet
- Waits for you to log in with your CAC
- Auto-clicks **Next / Continue** through content slides
- **Pauses and alerts you** whenever it detects a question
- **Asks Claude for a recommended answer** and a brief explanation of why it's correct — streamed live to your terminal so you can learn from it
- You still make the final selection yourself in the browser, then press Enter
- Prints a condensed text preview of each slide in your terminal so you can skim fast

## Setup (one-time)

```bash
# 1. Install Python dependencies
pip install -r marinenet_requirements.txt

# 2. Install the Playwright browser binaries
python -m playwright install chromium

# 3. Set your Anthropic API key (get one at console.anthropic.com)
export ANTHROPIC_API_KEY=sk-ant-...
```

### CAC / smart card note
The script tries to launch **your installed Google Chrome** first because Chrome has better smart-card / PIV middleware support than the bundled Chromium. Make sure:
- ActivClient or equivalent CAC middleware is running
- You can log into CAC-gated sites in Chrome normally before running this

## Running

```bash
python marinenet_assistant.py
```

1. Chrome opens and goes to `marinenet.usmc.mil`
2. Log in with your CAC in the browser as usual
3. Navigate to the course you want to take and get to the first slide
4. Switch back to the terminal and press **Enter**
5. The assistant takes over navigation — read the terminal preview and watch the browser
6. When a question appears, the terminal will say **QUESTION DETECTED** and pause — answer it in the browser, then press **Enter** in the terminal

## Keyboard shortcuts (in the terminal)
| Prompt option | Action |
|---|---|
| `r` + Enter | Retry finding a Next button (if page was still loading) |
| `s` + Enter | Skip — advance manually in the browser, then Enter |
| `q` + Enter | Quit the assistant and close Chrome |
| `Ctrl-C` | Emergency stop |

## Troubleshooting

**"Google Chrome not found"** — Install Chrome, or edit the script and set `channel=None` to use bundled Chromium (CAC may not work without extra PKCS#11 config).

**Next button not found mid-course** — Some courses use non-standard labels. Choose `s` to advance manually once; the assistant picks back up on the next slide.

**Content inside iframes not showing in terminal** — The terminal preview is best-effort. The browser always shows the full content.
