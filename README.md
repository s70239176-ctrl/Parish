# Parish

Parish is a Studionet prediction-market dApp for specific, local YES/NO questions. The contract settles outcomes through GenLayer validator consensus and sends real native GEN payouts only after finalization.

## Run it on Studionet

1. Get Studionet GEN from the [Studio faucet droplet](https://studio.genlayer.com).
2. Deploy `contracts/parish_markets.py` on Studionet in Studio or run:

   ```sh
   genlayer network set studionet
   genlayer deploy --contract contracts/parish_markets.py --args "10000000000000000"
   ```

3. Copy the deployed address.
4. Set `frontend/.env`:

   ```sh
   VITE_CONTRACT_ADDRESS=0x...
   ```

5. Run `npm install && npm run dev` from `frontend`.
6. In MetaMask, add Studionet RPC `https://studio.genlayer.com/api`, chain ID `61999`, symbol `GEN`.
7. Create a market that closes in at least five minutes, stake YES and NO from two funded accounts with real GEN, submit evidence, wait for the deadline, resolve, then claim.

The app refuses to render a functional board without a configured address, refuses signing on any chain other than 61999, shows the real wallet GEN balance, and estimates fees per submitted contract write.
