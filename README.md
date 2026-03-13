# Personal Kanban Board

A lightweight, Trello‑style kanban board for your own tasks. Everything runs client‑side in the browser and is saved to `localStorage` so you can use it offline without any account.

## Features

- **Trello‑like columns**: Default `To Do`, `Doing`, and `Done` columns, with the ability to add, rename, reorder, and delete columns.
- **Tasks / cards**: Title, optional description, due date, and priority (low, medium, high).
- **Drag and drop**: Reorder tasks within a column or move them between columns with native drag‑and‑drop.
- **Search**: Instant filtering of tasks across all columns by title or description.
- **Theme toggle**: Dark and light modes, persisted per browser.
- **Backup and restore**: Export your board to JSON and import it later.
- **Local persistence**: Board, columns, and tasks are saved automatically in your browser’s `localStorage`.

## Getting started

### Option 1: Open directly

1. Open `index.html` in any modern browser.
2. Start adding columns and tasks — your data is saved automatically.

### Option 2: Run a tiny dev server

If you prefer using a local HTTP server:

1. Start the server:

   ```bash
   cd "New project"
   npm start
   ```

2. Open `http://localhost:4173` in your browser.

## How it works

- The UI is built with plain HTML, CSS, and JavaScript — no framework or build step required.
- Board state (columns and tasks) is stored under the key `personal-kanban-board-v1` in `localStorage`.
- Theme preference is stored under `personal-kanban-theme`.

## Notes

- This is intended for **personal use**; there is no backend, authentication, or syncing between devices.
- If you clear your browser storage or use a different browser/machine, your board will not carry over.
- Use **Export board** before browser cleanup or machine migration, then use **Import board** to restore your tasks.
