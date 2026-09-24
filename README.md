# Parish — The Local Odds Desk

A live GenLayer Studionet prediction-market dApp. Market data, pools, evidence, resolution status, and user actions are read from or written to the deployed `ParishMarkets` contract—there is no mock market data.

## Run locally

```bash
npm --prefix frontend install
npm run dev
```

Open the Vite URL shown in the terminal (normally `http://localhost:5173`).

## Deploy to Vercel

Set this Vercel environment variable for Production, Preview, and Development:

```bash
VITE_CONTRACT_ADDRESS=0xYourDeployedParishMarketsAddress
```

The deployment uses `frontend/` as its Vite source.

```bash
npm run build
```

## Live interactions

- Read final market count and every market from the configured contract.
- Connect an EIP-1193 wallet to Studionet (chain ID `61999`).
- Create a market, stake GEN, submit evidence, close, resolve, and claim payouts.
- Refresh from finalized contract state after a completed transaction.

Contract source: `contracts/parish_markets.py`.
