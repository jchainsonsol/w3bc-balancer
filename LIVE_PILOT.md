# $100 Live Pilot

## Status

**NOT ENABLED YET.** The current GitHub Pages dashboard is a static client and must not hold wallet secrets or autonomous signing keys.

## Pilot target

- Pair: SOL / USDC
- Capital at risk: $100 total
- Wallet: dedicated Phantom wallet only
- Starting target: 50% SOL / 50% USDC
- Rebalance band: 4%
- Maximum proposed trade: $10
- Minimum proposed trade: $3
- Daily loss cutoff: $10
- Execution: user-approved only
- Benchmark: buy-and-hold from pilot start

## Required launch gates

1. Dedicated wallet is connected by public address only.
2. Application reads real SOL and USDC balances.
3. Jupiter quote adapter returns a valid route and price impact.
4. Proposed trade is displayed before signing.
5. Phantom signs the transaction on the user's device.
6. Transaction signature and resulting balances are reconciled on-chain.
7. P&L includes execution costs and is compared with buy-and-hold.
8. Pause/kill state blocks creation of new trade proposals.
9. No seed phrase or private key is stored in GitHub, Telegram, localStorage, or the static dashboard.
10. AUTO mode remains disabled.

## Launch rule

Do not fund or execute from a primary wallet. The first real-money pilot is limited to a dedicated wallet containing only the pilot capital plus a small SOL fee reserve.
