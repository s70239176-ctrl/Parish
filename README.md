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
| Contract | `ParishMarkets` — `0x0b306f3DA1237d872594A6a5349FB4dEDbbb207F` |
| Explorer link | https://explorer-studio.genlayer.com/address/0x0b306f3DA1237d872594A6a5349FB4dEDbbb207F |

Get test GEN from the Studio faucet at https://studio.genlayer.com before staking or posting markets.

This deployment carries the multi-record-evidence and strict-HYBRID resolution fixes described below; its on-chain source was diffed against `contracts/parish_markets.py` (identical apart from blank-line whitespace introduced by the explorer's text rendering — no code differs) — see [Live verification](#live-verification) for the full transaction chain proving it.

## Tech stack

- **Frontend** — React + TypeScript, built with Vite, styled with a single hand-rolled stylesheet (`frontend/src/styles/parish.css`). No UI framework or component library.
- **Chain access** — [`genlayer-js`](https://www.npmjs.com/package/genlayer-js) for reading and writing to the contract (`readContract` / `writeContract`), plus `viem` types; MetaMask (or any EIP-1193 wallet) is used to sign writes and switch/add the Studionet network.
- **GenLayer contract** — `contracts/parish_markets.py`, a Python Intelligent Contract on `py-genlayer`. Uses `gl.nondet.web.get` to fetch page content, `gl.nondet.exec_prompt` to have an LLM produce a structured YES/NO/UNRESOLVED/INVALID verdict, and `gl.eq_principle.strict_eq` so validators must agree on that verdict before it's committed.
- **Backend / database** — none. All state (markets, positions, evidence) lives in the contract's own storage (`TreeMap`s); the frontend is a static SPA that talks to the chain directly.

> Note: the repository also contains a separate Next.js UI mockup at the root (`app/`, `components/parish/`, `data/markets.ts`) that renders the same visual design against a hardcoded array of sample markets. It is **not** wired to the live contract and is not what's deployed — `frontend/` (Vite) is the real app, and it's what `vercel.json` builds.

## How it works

1. **Connect** — a user connects a MetaMask wallet; the app switches (or adds) the Studionet network automatically.
2. **Post a market** — "Post a notice" submits a question, resolution rules, category, place, a resolution mode (`WEB`, `EVIDENCE`, or `HYBRID`), and a primary source URL, to `create_market`, which must close at least 5 minutes in the future. `WEB` and `HYBRID` markets must provide a primary source URL up front — `create_market` rejects the call otherwise, since there'd be nothing for `resolve()` to fetch.
3. **Stake** — while a market is `OPEN`, users call `stake` with GEN (≥ the contract's `min_stake`) on `YES` or `NO`; stakes accumulate into that market's yes/no pool.
4. **Submit evidence** — while a market is still `OPEN` and before its deadline, anyone can call `submit_evidence` with a URL and note pointing validators at supporting material (evidence submitted after the deadline, or once the market is `CLOSED`, is rejected — it can no longer influence a resolution that's already about to happen). Each submission is validated (must be an `http(s)` URL) and then snapshotted by validator consensus — the contract fetches the URL, records its HTTP status, whether it was HTTPS, and a sha256 hash of its body — and appended to that market's **evidence history**; earlier submissions are never overwritten (`get_evidence_history` returns the full list, `get_evidence` returns the latest). A fetch failure is recorded on the entry (`fetch_error`, `verified: false`) rather than reverting the submission.
5. **Close** — once the deadline passes, `close_if_due` (or `resolve` itself) flips the market from `OPEN` to `CLOSED`.
6. **Resolve** — `resolve` first checks, deterministically, that the resolution mode actually has the material it needs — if not, it settles `VOID` immediately without ever calling out to the web or an LLM. `WEB` requires the primary source (guaranteed present since creation requires it for `WEB`/`HYBRID`); `EVIDENCE` requires at least one *verified* evidence submission; **`HYBRID` requires both** the primary source *and* at least one verified evidence submission — it can never resolve off the primary source alone. For `EVIDENCE`/`HYBRID`, resolution considers a bounded window of the market's evidence history (the most recent `MAX_EVIDENCE_CONSIDERED` submissions, oldest-of-that-window first, so ordering is deterministic and an earlier valid record isn't dropped just because a later one also exists) — every verified candidate in that window is re-fetched and re-hashed at resolution time, and only those whose content still matches their submission-time hash are folded into the resolver's input; a record that drifted, disappeared, or was never verified in the first place is skipped, not silently trusted. If HYBRID's evidence side ends up with zero still-valid records after that re-check (even if it looked fine at submission time), resolution does not fall back to the primary source alone — it settles `VOID`. Assuming the required material checks out, `resolve` runs a non-deterministic block that fetches everything with bounded retries, prompts an LLM for a JSON verdict, and requires validator consensus (`strict_eq`, itself retried a bounded number of times) before writing the final outcome. A fetch failure, a malformed LLM response, or validators failing to reach consensus at all always degrades to a deterministic `UNRESOLVED`/`VOID` outcome rather than reverting, so a market can never get stuck mid-resolution. If validators pick a winning side that nobody actually staked on, the market settles `VOID` instead of `RESOLVED` so that pool isn't permanently trapped. Anyone can also call `expire_market` on a market that's sat `CLOSED` past a 7-day resolution grace period without ever being resolved, moving it to `EXPIRED` so stakers can recover funds from an abandoned market. A creator can `cancel_market` an `OPEN` market that has received no stakes yet.
7. **Claim** — once a market reaches a terminal status (`RESOLVED`, `VOID`, `EXPIRED`, or `CANCELLED`), each staker calls `claim`: `RESOLVED` winners split the losing pool using running-pool accounting (each claim reduces the market's own `winner_pool_remaining`/`loser_pool_remaining` counters), so every wei is eventually paid out with no rounding dust left stranded regardless of claim order; `VOID`/`EXPIRED`/`CANCELLED` markets return each staker's original stake. `claim` always settles the position (marks it claimed) whether the payout is positive or zero — a losing position is a legitimate terminal outcome, not an error — so it never needs retrying and can never move funds twice.

## How to run locally

```bash
# from the repo root
npm --prefix frontend install

# create frontend/.env with your deployed contract address
echo "VITE_CONTRACT_ADDRESS=0x0b306f3DA1237d872594A6a5349FB4dEDbbb207F" > frontend/.env

npm run dev
```

Open the Vite URL printed in the terminal (normally `http://localhost:5173`). MetaMask must be installed to stake, post markets, submit evidence, resolve, or claim — reads work without a wallet.

**Build:**

```bash
npm run build
```

**Deploy to Vercel** — the project builds `frontend/` as its Vite source (see `vercel.json`). Set this environment variable for Production, Preview, and Development:

```bash
VITE_CONTRACT_ADDRESS=0x0b306f3DA1237d872594A6a5349FB4dEDbbb207F
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

### Live verification

A full `create → stake → submit_evidence → close_if_due → resolve → claim` lifecycle was run on Studionet against **`0x0b306f3DA1237d872594A6a5349FB4dEDbbb207F`** (the deployment listed above), on a `HYBRID` market — the mode the enforcement fix specifically targets, so this run exercises both blocker fixes (bounded multi-record evidence consideration, and HYBRID requiring both a source and verified evidence) at once, not just a `WEB` market that wouldn't touch either:

| Step | Tx hash | Result |
|---|---|---|
| Deploy | [`0xa728c8f3…9bb784b3`](https://explorer-studio.genlayer.com/tx/0xa728c8f357e6007786bf8d9146e190b07ad2f432f019eb5b2d13b45b9bb784b3) | `FINALIZED` |
| `create_market(..., "HYBRID", "https://example.com", ...)` | [`0x2af56188…afc3b69d`](https://explorer-studio.genlayer.com/tx/0x2af56188923321c378d1f7c6ff4a3aea8d463ec680e794edb412d55aafc3b69d) | `FINALIZED` — returns `"m-2"` |
| `stake("m-2", "YES")`, 5 GEN | [`0x52af27c3…79dcda21b`](https://explorer-studio.genlayer.com/tx/0x52af27c37791069812c4d7c0f1224b3166c5215b5a35a5087d31d5279dcda21b) | `FINALIZED` |
| `submit_evidence("m-2", "https://httpstat.us/200", ...)` | [`0x57c30c75…65326055`](https://explorer-studio.genlayer.com/tx/0x57c30c75aba8f5217464167d0933ce25c2e83eff6c7a0b91a0477c4965326055) | `FINALIZED` — verified `true` |
| `close_if_due("m-2")` | [`0x054ea0f8…11d996bf8`](https://explorer-studio.genlayer.com/tx/0x054ea0f8c888e3dbd00eb2dfe9cf0e2839cb2e702f42e5f583f080c11d996bf8) | `FINALIZED` |
| `resolve("m-2")` | [`0x92ef9474…31f0f1f3a`](https://explorer-studio.genlayer.com/tx/0x92ef9474b92f4c355486dd34ed6a43bdbf7aa235ebb3a0f7fe0915c31f0f1f3a) | `FINALIZED` — `{"id":"m-2","outcome":"NO","status":"VOID"}`, Equivalence Principle output `{"outcome":"NO"}` |
| `claim("m-2")` | [`0x741dc08b…070da9038`](https://explorer-studio.genlayer.com/tx/0x741dc08b35c89ac54deb18d02abcc76cb878a70fc66e5e3106a2b44070da9038) | `FINALIZED` — `{"claimed":true,"market_id":"m-2","payout":"5000000000000000000"}` |

Canonical readback (`get_market`/`get_position`/`get_evidence_history`, read directly from the deployed contract after the claim landed):

```json
// get_market("m-2")
{"category":"Civic","closes_at_unix":"1790627760","created_at_unix":"1790627047",
 "creator":"0xD1F39bc446B4344366e314b206eea8417B12749A","id":"m-2",
 "loser_pool_remaining":"0","no_pool":"0","outcome":"NO","place":"Parish demo",
 "primary_source_url":"https://example.com",
 "question":"Will this Parish HYBRID demo resolve YES from source and evidence together?",
 "reasoning":"Validators found NO, but the winning side had no stakes; all stakes were refunded.",
 "resolution_mode":"HYBRID","resolved_at_unix":"1790629370",
 "rules":"Resolves YES if both the primary source and the submitted evidence page are reachable and return HTTP 200 at resolution time; otherwise NO.",
 "status":"VOID","winner_pool_remaining":"0","yes_pool":"5000000000000000000"}

// get_evidence_history("m-2")
[{"author":"0xD1F39bc446B4344366e314b206eea8417B12749A",
  "content_hash":"6807c84bf35d67496e020c1528303b87d4759933c09817e514a7159ac689d352",
  "fetch_error":"","https":true,"index":"0","market_id":"m-2",
  "note":"Confirms a second independent source also returns 200.",
  "status_code":"0","submitted_at_unix":"1790627247",
  "url":"https://httpstat.us/200","verified":true}]

// get_position("m-2", "0xD1F39bc446B4344366e314b206eea8417B12749A")
{"claimed":true,"market_id":"m-2","no_amount":"0",
 "owner":"0xD1F39bc446B4344366e314b206eea8417B12749A","yes_amount":"5000000000000000000"}
```

What this proves: the `reasoning` field ("Validators found NO...") shows `resolve()` actually reached the LLM/validator stage — meaning both the primary source *and* the submitted evidence passed their resolution-time checks, which is only possible under the fixed HYBRID logic. The validators' verdict itself came back `NO` on a market with only `YES` stakes, which correctly tripped the empty-winning-pool safety net into `VOID` rather than `RESOLVED`, and `claim` refunded the full 5 GEN stake — a second, independent live confirmation of that fix.

**One gap, stated plainly rather than papered over:** the spec calls for a canonical `get_market()` read showing `"status":"CLOSED"`, taken *between* `close_if_due` and `resolve`. Here those two transactions landed about two minutes apart, and the market has since moved on to `VOID` — GenLayer's read API only exposes latest-final state, not a historical read as of a given block/tx, so that specific readback cannot be reconstructed after the fact. Capturing it requires one more live run where `resolve()` is deliberately not called until the `CLOSED` state has been read back.

## Testing

`contracts/parish_markets.py` has a pure-Python unit test suite (47 cases) under `tests/` that runs against an in-process mock of the `genlayer` SDK (see `tests/mock_genlayer.py`), so the market lifecycle, evidence handling, and settlement accounting can be exercised without a live GenLayer node. Besides the general lifecycle/settlement coverage (malformed evidence URLs, failed/retried fetches, append-only evidence history, evidence rejected once past deadline/`CLOSED`, LLM failure and genuine validator-consensus disagreement with bounded retry, unresolved markets, zero-payout claims settling terminally, rounding-dust-free multi-winner payouts, trapped pool balances, abandoned-market expiry, and the full `stake → close → resolve → claim` flow), it specifically covers:

- **Multi-record evidence resolution** (`TestMultiRecordEvidenceResolution`) — two-or-more verified submissions jointly feeding the resolver input; an earlier valid record surviving even though a later verified record also exists; a later record's content-hash drift excluding only that record while an earlier still-valid one remains usable; unverified evidence being excluded even alongside verified evidence; deterministic (ascending, oldest-of-window-first) evidence ordering; and the evidence window staying bounded (fetch count capped) independent of how much evidence history a market actually has.
- **Strict HYBRID enforcement** (`TestHybridRequiresBothSourceAndEvidence`) — HYBRID voiding deterministically with a source but no evidence, with a source but only unverified evidence, and with a source but evidence that drifted and has no other valid record; HYBRID resolving normally once it has a source and one valid record; and HYBRID resolving using only the still-valid subset when some of its evidence records are invalid and at least one remains valid.

```bash
pip install -r tests/requirements-dev.txt
npm run test:contract
# or directly:
python -m pytest tests/ -q
```

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs this suite plus a frontend typecheck/build on every push and PR to `main`.

## Known limitations

- **AI-sourced resolution** depends on what the LLM can extract from fetched page text — JavaScript-rendered pages, paywalls, or pages that block scrapers can leave it with little or nothing to reason over, which the contract treats as `UNRESOLVED` → `VOID` rather than failing.
- **Latency** — a resolution involves a non-deterministic web fetch, an LLM call, and validator consensus, so `resolve()` is noticeably slower than a normal contract write.
- **Testnet state** — Studionet can reset, and GEN balances come from the faucet; don't treat deployed markets or balances as persistent.
- **No dispute or appeal path** — once `resolve()` finalizes an outcome via validator consensus, there's no on-chain mechanism to contest or re-resolve it; an abandoned or wrongly-void market can only be recovered via the `expire_market`/refund path, not re-judged.
- **Wallet requirement** — writes require an EIP-1193 browser wallet (MetaMask); there's no walletconnect or mobile-wallet fallback.
- **Unused mockup in-repo** — the root-level Next.js files are a static design reference only; don't confuse them with the deployed app.

## Future roadmap

- **Phase 2** — a lightweight dispute/re-resolution window before payouts unlock; richer categories and location-based discovery (map view, "near me" filtering); surface `get_evidence_history` in the UI instead of just the latest submission.
- **Phase 3** — mainnet deployment with real GEN economics and a protocol fee, push notifications for markets a user has staked in, a public creator/resolver reputation or leaderboard system, and native mobile wallet support beyond MetaMask.
