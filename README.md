# Parish — The Local Odds Desk

## Project summary

Hyper-local predictions ("will the taco truck be on 5th by 12:30?", "will the library be open Saturday?") have no good place to live they're too small for mainstream prediction markets and too easy to fudge if one person is left to judge the outcome. Parish is a live GenLayer prediction-market dApp where anyone can post a local yes/no question, stake GEN on an outcome, and attach evidence, with **no off-chain backend and no mock data** every market, pool, and resolution is read from or written to the deployed `ParishMarkets` Intelligent Contract. The GenLayer advantage is the resolution step itself: instead of trusting a single admin or oracle, `resolve()` has the contract fetch the primary source and submitted evidence directly from the web inside a non-deterministic block, asks an LLM to judge the outcome from that material, and only finalizes the result once GenLayer's validators reach consensus via `eq_principle.strict_eq` bringing plain-language, web-sourced judgment on-chain without a centralized resolver.

## Live demo

`https://parish-markets.vercel.app`

## Contract details

| Field | Value |
|---|---|
| Network | GenLayer Studionet (testnet) |
| Chain ID | `61999` (`0xf22f`) |
| RPC URL | `https://studio.genlayer.com/api` |
| Block explorer | https://explorer-studio.genlayer.com |
| Contract | `ParishMarkets` — `0x99EA12811Da300414e5A963dE573F3699885b4F1` |
| Explorer link | `https://explorer-studio.genlayer.com/address/><0x99EA12811Da300414e5A963dE573F3699885b4F1` |

Get test GEN from the Studio faucet at https://studio.genlayer.com before staking or posting markets.

## Tech stack

- **Frontend** — React + TypeScript, built with Vite, styled with a single hand-rolled stylesheet (`frontend/src/styles/parish.css`). No UI framework or component library.
- **Chain access** — [`genlayer-js`](https://www.npmjs.com/package/genlayer-js) for reading and writing to the contract (`readContract` / `writeContract`), plus `viem` types; MetaMask (or any EIP-1193 wallet) is used to sign writes and switch/add the Studionet network.
- **GenLayer contract** — `contracts/parish_markets.py`, a Python Intelligent Contract on `py-genlayer`. Uses `gl.nondet.web.get` to fetch page content, `gl.nondet.exec_prompt` to have an LLM produce a structured YES/NO/UNRESOLVED/INVALID verdict, and `gl.eq_principle.strict_eq` so validators must agree on that verdict before it's committed.
- **Backend / database** — none. All state (markets, positions, evidence) lives in the contract's own storage (`TreeMap`s); the frontend is a static SPA that talks to the chain directly.

> Note: the repository also contains a separate Next.js UI mockup at the root (`app/`, `components/parish/`, `data/markets.ts`) that renders the same visual design against a hardcoded array of sample markets. It is **not** wired to the live contract and is not what's deployed — `frontend/` (Vite) is the real app, and it's what `vercel.json` builds.

## How it works

1. **Connect** — a user connects a MetaMask wallet; the app switches (or adds) the Studionet network automatically.
2. **Post a market** — "Post a notice" submits a question, resolution rules, category, place, an optional primary source URL, and a resolution mode (`WEB`, `EVIDENCE`, or `HYBRID`) to `create_market`, which must close at least 5 minutes in the future.
3. **Stake** — while a market is `OPEN`, users call `stake` with GEN (≥ the contract's `min_stake`) on `YES` or `NO`; stakes accumulate into that market's yes/no pool.
4. **Submit evidence** — anyone can call `submit_evidence` with a URL and note pointing validators at supporting material (the contract keeps the latest submission per market).
5. **Close** — once the deadline passes, `close_if_due` (or `resolve` itself) flips the market from `OPEN` to `CLOSED`.
6. **Resolve** — `resolve` runs a non-deterministic block that fetches the primary source and/or evidence URL (depending on resolution mode), prompts an LLM for a JSON verdict, and requires validator consensus (`strict_eq`) before writing the final `outcome` and moving the market to `RESOLVED` (YES/NO) or `VOID` (UNRESOLVED/INVALID).
7. **Claim** — once `RESOLVED` or `VOID`, each staker calls `claim`: winners split the losing pool pro-rata by stake, and `VOID` markets return each staker's original stake.

## How to run locally

```bash
# from the repo root
npm --prefix frontend install

# create frontend/.env with your deployed contract address
echo "VITE_CONTRACT_ADDRESS=0x99EA12811Da300414e5A963dE573F3699885b4F1" > frontend/.env

npm run dev
```

Open the Vite URL printed in the terminal (normally `http://localhost:5173`). MetaMask must be installed to stake, post markets, submit evidence, resolve, or claim — reads work without a wallet.

**Build:**

```bash
npm run build
```

**Deploy to Vercel** — the project builds `frontend/` as its Vite source (see `vercel.json`). Set this environment variable for Production, Preview, and Development:

```bash
VITE_CONTRACT_ADDRESS=0x99EA12811Da300414e5A963dE573F3699885b4F1
```

## Demo evidence

To see a full create → stake → resolve → claim cycle quickly, post a market with a short deadline and material that's easy for the resolver to read:

- **Question:** `Will this Parish demo market resolve YES within the hour?`
- **Rules:** `Resolves YES if the linked page is reachable and returns HTTP 200 at resolution time; otherwise resolves NO.`
- **Category:** `Civic`
- **Place:** `Parish demo`
- **Resolution mode:** `WEB`
- **Primary source URL:** `https://example.com`
- **Close time:** 5–10 minutes out (the minimum allowed)

After the deadline passes, call **Resolve with validators** — the contract fetches `https://example.com`, the LLM judges reachability from the fetched body, and validators reach consensus on `YES`. For `EVIDENCE` or `HYBRID` markets, submit any short evidence URL and a one-line note before resolving so the resolver has something to read.

## Known limitations

- **AI-sourced resolution** depends on what the LLM can extract from fetched page text — JavaScript-rendered pages, paywalls, or pages that block scrapers can leave it with little or nothing to reason over, which the contract treats as `UNRESOLVED` → `VOID`.
- **Latency** — a resolution involves a non-deterministic web fetch, an LLM call, and validator consensus, so `resolve()` is noticeably slower than a normal contract write.
- **Testnet state** — Studionet can reset, and GEN balances come from the faucet; don't treat deployed markets or balances as persistent.
- **Single evidence slot per market** — `submit_evidence` overwrites the previous submission rather than keeping a history, so only the latest note/URL is visible to the resolver.
- **No dispute or appeal path** — once `resolve()` finalizes an outcome via validator consensus, there's no on-chain mechanism to contest or re-resolve it.
- **Wallet requirement** — writes require an EIP-1193 browser wallet (MetaMask); there's no walletconnect or mobile-wallet fallback.
- **Unused mockup in-repo** — the root-level Next.js files are a static design reference only; don't confuse them with the deployed app.

## Future roadmap

- **Phase 2** — multiple evidence submissions with validator-visible history instead of a single overwritable slot; a lightweight dispute/re-resolution window before payouts unlock; richer categories and location-based discovery (map view, "near me" filtering).
- **Phase 3** — mainnet deployment with real GEN economics and a protocol fee, push notifications for markets a user has staked in, a public creator/resolver reputation or leaderboard system, and native mobile wallets support beyond MetaMask.
