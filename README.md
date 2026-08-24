# W3BC Balancer

Phone-first, multi-asset Solana rebalancing platform.

## Goal

Build a measurable rebalancing engine that can manage multiple Solana assets against USDC, controlled from Telegram, with Phantom-based user approval before any live execution.

> V1 is simulation-only. No private keys, seed phrases, or autonomous live trading are included.

## V1

- Multi-asset strategy instances
- Independent bankrolls per asset
- Rebalancing simulator
- Realized and unrealized P&L
- Buy-and-hold benchmark
- Fee and slippage modeling
- Risk limits and kill switch state
- Telegram-ready control/API layer
- Jupiter quote/execution adapter boundary
- Phantom approval adapter boundary

## Modes

1. `SIMULATION` — no transactions
2. `APPROVAL` — proposed transaction requires wallet signature
3. `AUTO` — future isolated execution-wallet mode after testing and explicit enablement

## Core principle

Balancer must be judged against the alternative of simply holding the asset. A profitable strategy can still be a bad strategy if buy-and-hold would have performed better.

## Security

Never store a Phantom seed phrase or primary-wallet private key in the application, repository, Telegram bot, database, or environment configuration.
