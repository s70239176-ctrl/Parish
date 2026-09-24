# Parish — The Local Odds Desk

A pixel-focused recreation of the supplied Parish editorial prediction-market reference, built with Next.js App Router, TypeScript, CSS, Lucide icons, and local mock state.

## Run locally

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

## Deploy to Vercel

Vercel detects the Next.js application from the repository root. No environment variables are required for this mock interface.

```bash
npm run build
```

## Included interactions

- Search questions, categories, and locations; press `Cmd/Ctrl + K` to focus it.
- Filter market cards by category and sort by activity, probability, or traders.
- Complete and submit the **Post a notice** form for its local success state.
- Responsive 3-column / 2-column / 1-column editorial layout.

The earlier GenLayer contract remains in `contracts/parish_markets.py`, deliberately separate from this standalone, mock-data UI recreation.
