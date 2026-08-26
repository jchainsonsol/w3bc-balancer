"""
W3BC Balancer V2 - autonomous Solana volatility worker.

Purpose
-------
This replaces the old fixed 50/50 JCHAINS rebalance strategy with a dynamic
volatility loop:

  discover -> route check -> enter -> monitor -> exit -> return to USDC

The worker is intentionally DRY RUN by default. It is designed to run as a
long-lived Python process, while the Vercel app remains the dashboard/API.

Environment
-----------
SOLANA_PRIVATE_KEY       base58 private key for the dedicated trading wallet
TELEGRAM_BOT_TOKEN       optional Telegram bot token
TELEGRAM_CHAT_ID         optional chat id for alerts
SOLANA_RPC_URL           optional RPC override
BALANCER_API_URL         default https://w3bc-balancer.vercel.app
JUPITER_API_KEY          optional Jupiter API key
DRY_RUN                  true/false, defaults true

This is experimental trading software. Keep position sizes small while testing.
"""

import asyncio
import base64
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from dotenv import load_dotenv
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solana.rpc.api import Client
from solana.rpc.types import TokenAccountOpts, TxOpts

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
except Exception:
    Update = None
    Application = CommandHandler = ContextTypes = None

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("balancer-v2")

# ---------------------------- CONFIG ----------------------------
API_URL = os.getenv("BALANCER_API_URL", "https://w3bc-balancer.vercel.app").rstrip("/")
RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
JUPITER_QUOTE_URL = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_SWAP_URL = "https://lite-api.jup.ag/swap/v1/swap"
JUPITER_API_KEY = os.getenv("JUPITER_API_KEY", "")
JUPITER_HEADERS = {"x-api-key": JUPITER_API_KEY} if JUPITER_API_KEY else {}

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS = 6

DRY_RUN = os.getenv("DRY_RUN", "true").lower() not in {"0", "false", "no"}
SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "30"))
POSITION_USD = float(os.getenv("POSITION_USD", "10"))
MAX_POSITION_USD = float(os.getenv("MAX_POSITION_USD", "15"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "55"))
MAX_ROUND_TRIP_PCT = float(os.getenv("MAX_ROUND_TRIP_PCT", "2.5"))
MAX_PRICE_IMPACT_PCT = float(os.getenv("MAX_PRICE_IMPACT_PCT", "1.5"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "5.0"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "3.0"))
MAX_HOLD_MINUTES = int(os.getenv("MAX_HOLD_MINUTES", "15"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "120"))
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "20"))
SLIPPAGE_BPS = int(os.getenv("SLIPPAGE_BPS", "100"))
MIN_USDC_RESERVE = float(os.getenv("MIN_USDC_RESERVE", "10"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# ---------------------------------------------------------------


def utcnow():
    return datetime.now(timezone.utc)


def load_keypair() -> Keypair:
    raw = os.getenv("SOLANA_PRIVATE_KEY")
    if not raw:
        raise RuntimeError("SOLANA_PRIVATE_KEY is required for the dedicated bot wallet")
    return Keypair.from_base58_string(raw)


client = Client(RPC_URL)
keypair = load_keypair()
owner = keypair.pubkey()


@dataclass
class Position:
    symbol: str
    mint: str
    entry_usd: float
    token_raw: int
    entry_time: datetime
    entry_tx: Optional[str] = None
    peak_value_usd: float = 0.0


@dataclass
class State:
    paused: bool = False
    dry_run: bool = DRY_RUN
    position: Optional[Position] = None
    last_trade_time: Optional[datetime] = None
    trades_today: int = 0
    day_marker: str = utcnow().strftime("%Y-%m-%d")
    chat_id: Optional[int] = int(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None
    last_scan: str = "Never"
    last_decision: str = "Starting"


state = State()


def reset_daily_counter():
    today = utcnow().strftime("%Y-%m-%d")
    if today != state.day_marker:
        state.day_marker = today
        state.trades_today = 0


def token_raw_balance(mint: str) -> int:
    resp = client.get_token_accounts_by_owner_json_parsed(
        owner, TokenAccountOpts(mint=Pubkey.from_string(mint))
    )
    total = 0
    for acc in resp.value:
        info = acc.account.data.parsed["info"]["tokenAmount"]
        total += int(info.get("amount") or 0)
    return total


def usdc_balance() -> float:
    return token_raw_balance(USDC) / 10**USDC_DECIMALS


def quote(input_mint: str, output_mint: str, amount_raw: int) -> dict:
    r = requests.get(
        JUPITER_QUOTE_URL,
        params={
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(int(amount_raw)),
            "slippageBps": str(SLIPPAGE_BPS),
            "restrictIntermediateTokens": "true",
        },
        headers=JUPITER_HEADERS,
        timeout=12,
    )
    r.raise_for_status()
    d = r.json()
    if not d.get("outAmount"):
        raise RuntimeError(d.get("error") or d.get("errorMessage") or "No Jupiter route")
    return d


def execute_quote(q: dict) -> str:
    r = requests.post(
        JUPITER_SWAP_URL,
        headers=JUPITER_HEADERS,
        json={
            "quoteResponse": q,
            "userPublicKey": str(owner),
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto",
        },
        timeout=20,
    )
    r.raise_for_status()
    d = r.json()
    if not d.get("swapTransaction"):
        raise RuntimeError(d.get("error") or "Jupiter did not return a transaction")
    raw_tx = VersionedTransaction.from_bytes(base64.b64decode(d["swapTransaction"]))
    signed = VersionedTransaction(raw_tx.message, [keypair])
    resp = client.send_raw_transaction(
        bytes(signed), opts=TxOpts(skip_preflight=False, preflight_commitment="confirmed")
    )
    if hasattr(resp, "value"):
        return str(resp.value)
    raise RuntimeError(f"Transaction submission failed: {resp}")


def discovery() -> list[dict]:
    r = requests.get(f"{API_URL}/api/discover", timeout=20, headers={"accept": "application/json"})
    r.raise_for_status()
    d = r.json()
    if not d.get("ok"):
        raise RuntimeError(d.get("error") or "Discovery failed")
    return d.get("opportunities") or []


def route_check(candidate: dict, usd: float) -> dict:
    buy = quote(USDC, candidate["mint"], int(usd * 10**USDC_DECIMALS))
    token_raw = int(buy["outAmount"])
    sell = quote(candidate["mint"], USDC, token_raw)
    round_trip_usd = int(sell["outAmount"]) / 10**USDC_DECIMALS
    cost_pct = max(0.0, (1 - round_trip_usd / usd) * 100)
    impact = max(abs(float(buy.get("priceImpactPct") or 0)), abs(float(sell.get("priceImpactPct") or 0))) * 100
    return {
        "buy_quote": buy,
        "token_raw": token_raw,
        "round_trip_usd": round_trip_usd,
        "round_trip_pct": cost_pct,
        "impact_pct": impact,
        "ok": cost_pct <= MAX_ROUND_TRIP_PCT and impact <= MAX_PRICE_IMPACT_PCT,
    }


def current_position_value(pos: Position) -> float:
    raw = pos.token_raw if state.dry_run else token_raw_balance(pos.mint)
    if raw <= 0:
        return 0.0
    q = quote(pos.mint, USDC, raw)
    return int(q["outAmount"]) / 10**USDC_DECIMALS


async def send_message(text: str, context=None):
    log.info(text.replace("\n", " | "))
    if context is not None and state.chat_id:
        try:
            await context.bot.send_message(chat_id=state.chat_id, text=text)
        except Exception as e:
            log.warning("Telegram notification failed: %s", e)


async def enter(candidate: dict, route: dict, context=None):
    usd = min(POSITION_USD, MAX_POSITION_USD)
    if not state.dry_run:
        bal = usdc_balance()
        if bal - usd < MIN_USDC_RESERVE:
            state.last_decision = f"Skip {candidate['symbol']}: USDC reserve"
            return
        sig = execute_quote(route["buy_quote"])
        await asyncio.sleep(3)
        token_raw = token_raw_balance(candidate["mint"])
    else:
        sig = None
        token_raw = route["token_raw"]

    state.position = Position(
        symbol=candidate["symbol"],
        mint=candidate["mint"],
        entry_usd=usd,
        token_raw=token_raw,
        entry_time=utcnow(),
        entry_tx=sig,
        peak_value_usd=usd,
    )
    state.last_trade_time = utcnow()
    state.trades_today += 1
    state.last_decision = f"ENTER {candidate['symbol']} score={candidate.get('score')}"
    prefix = "🧪 DRY RUN" if state.dry_run else "✅ BOUGHT"
    msg = (
        f"{prefix} {candidate['symbol']}\n"
        f"Size: ${usd:.2f}\n"
        f"Score: {candidate.get('score', 0)}/100\n"
        f"5m: {candidate.get('m5', 0):+.2f}% · 1h: {candidate.get('h1', 0):+.2f}%\n"
        f"Round trip est: {route['round_trip_pct']:.2f}%"
    )
    if sig:
        msg += f"\nTx: https://solscan.io/tx/{sig}"
    await send_message(msg, context)


async def exit_position(reason: str, value_usd: float, context=None):
    pos = state.position
    if not pos:
        return
    pnl = value_usd - pos.entry_usd
    pnl_pct = (pnl / pos.entry_usd * 100) if pos.entry_usd else 0
    sig = None
    if not state.dry_run:
        raw = token_raw_balance(pos.mint)
        if raw > 0:
            sig = execute_quote(quote(pos.mint, USDC, raw))

    prefix = "🧪 DRY EXIT" if state.dry_run else "💰 SOLD"
    msg = (
        f"{prefix} {pos.symbol}\n"
        f"Reason: {reason}\n"
        f"Estimated value: ${value_usd:.2f}\n"
        f"P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%)"
    )
    if sig:
        msg += f"\nTx: https://solscan.io/tx/{sig}"
    state.position = None
    state.last_trade_time = utcnow()
    state.last_decision = f"EXIT {pos.symbol}: {reason} {pnl_pct:+.1f}%"
    await send_message(msg, context)


async def manage_position(context=None):
    pos = state.position
    if not pos:
        return
    value = current_position_value(pos)
    pos.peak_value_usd = max(pos.peak_value_usd, value)
    pnl_pct = ((value - pos.entry_usd) / pos.entry_usd * 100) if pos.entry_usd else 0
    age = utcnow() - pos.entry_time

    if pnl_pct >= TAKE_PROFIT_PCT:
        await exit_position("TAKE_PROFIT", value, context)
    elif pnl_pct <= -STOP_LOSS_PCT:
        await exit_position("STOP_LOSS", value, context)
    elif age >= timedelta(minutes=MAX_HOLD_MINUTES):
        await exit_position("TIMEOUT", value, context)
    elif pos.peak_value_usd > pos.entry_usd * 1.03 and value <= pos.peak_value_usd * 0.975:
        await exit_position("MOMENTUM_FADE", value, context)
    else:
        state.last_decision = f"HOLD {pos.symbol} {pnl_pct:+.2f}%"


async def engine_tick(context=None):
    try:
        reset_daily_counter()
        state.last_scan = utcnow().isoformat()
        if state.position:
            await manage_position(context)
            return
        if state.paused:
            state.last_decision = "Paused"
            return
        if state.trades_today >= MAX_TRADES_PER_DAY:
            state.last_decision = "Daily trade cap reached"
            return
        if state.last_trade_time and (utcnow() - state.last_trade_time).total_seconds() < COOLDOWN_SECONDS:
            state.last_decision = "Cooldown"
            return

        candidates = discovery()
        if not candidates:
            state.last_decision = "No volatility candidates"
            return

        for c in candidates[:5]:
            if int(c.get("score") or 0) < MIN_SCORE:
                continue
            try:
                route = route_check(c, min(POSITION_USD, MAX_POSITION_USD))
            except Exception as e:
                log.info("Route rejected %s: %s", c.get("symbol"), e)
                continue
            if route["ok"]:
                await enter(c, route, context)
                return
        state.last_decision = "Candidates found, no clean route"
    except Exception as e:
        log.exception("Engine tick failed")
        state.last_decision = f"ERROR {e}"
        await send_message(f"⚠️ Balancer V2 error: {e}", context)


# -------------------------- TELEGRAM ---------------------------
HELP = (
    "W3BC Balancer V2\n\n"
    "/status - engine + position status\n"
    "/pause - stop new entries\n"
    "/resume - resume entries\n"
    "/dryrun - toggle dry-run/live mode\n"
    "/scan - run one scan now\n"
    "/exit - exit current position\n"
    "/help - commands"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state.chat_id = update.effective_chat.id
    await update.message.reply_text(f"Connected to Balancer V2.\n\n{HELP}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pos = state.position
    ptxt = "None"
    if pos:
        try:
            value = current_position_value(pos)
            pnl = (value / pos.entry_usd - 1) * 100 if pos.entry_usd else 0
            ptxt = f"{pos.symbol} · ${value:.2f} · {pnl:+.2f}%"
        except Exception:
            ptxt = pos.symbol
    await update.message.reply_text(
        f"Wallet: {owner}\n"
        f"Dry run: {state.dry_run}\n"
        f"Paused: {state.paused}\n"
        f"Position: {ptxt}\n"
        f"Trades today: {state.trades_today}/{MAX_TRADES_PER_DAY}\n"
        f"Last decision: {state.last_decision}\n"
        f"Last scan: {state.last_scan}"
    )


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state.paused = True
    await update.message.reply_text("Paused. Existing position will still be managed/exited.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state.paused = False
    await update.message.reply_text("Resumed.")


async def cmd_dryrun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state.dry_run = not state.dry_run
    await update.message.reply_text(f"Dry run is now {'ON' if state.dry_run else 'OFF — LIVE EXECUTION'}")


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await engine_tick(context)
    await update.message.reply_text(f"Scan complete: {state.last_decision}")


async def cmd_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.position:
        await update.message.reply_text("No open position.")
        return
    value = current_position_value(state.position)
    await exit_position("MANUAL_TELEGRAM", value, context)


async def scheduler(context: ContextTypes.DEFAULT_TYPE):
    await engine_tick(context)


def main():
    log.info("Balancer V2 wallet: %s", owner)
    log.info("Dry run: %s | size=$%.2f | scan=%ss", state.dry_run, POSITION_USD, SCAN_SECONDS)
    if TELEGRAM_TOKEN and Application:
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("help", lambda u, c: u.message.reply_text(HELP)))
        app.add_handler(CommandHandler("status", cmd_status))
        app.add_handler(CommandHandler("pause", cmd_pause))
        app.add_handler(CommandHandler("resume", cmd_resume))
        app.add_handler(CommandHandler("dryrun", cmd_dryrun))
        app.add_handler(CommandHandler("scan", cmd_scan))
        app.add_handler(CommandHandler("exit", cmd_exit))
        app.job_queue.run_repeating(scheduler, interval=SCAN_SECONDS, first=3)
        app.run_polling()
    else:
        log.warning("Telegram not configured; running console worker only")
        while True:
            asyncio.run(engine_tick())
            import time
            time.sleep(SCAN_SECONDS)


if __name__ == "__main__":
    main()
