const clamp = (n, min, max) => Math.min(max, Math.max(min, n));

export class BalancerStrategy {
  constructor(config) {
    this.config = {
      symbol: config.symbol,
      mint: config.mint ?? null,
      bankrollUsd: config.bankrollUsd ?? 1000,
      targetAssetPct: clamp(config.targetAssetPct ?? 50, 0, 100),
      rebalanceBandPct: Math.max(config.rebalanceBandPct ?? 4, 0.1),
      tradeFractionPct: clamp(config.tradeFractionPct ?? 20, 1, 100),
      feePct: Math.max(config.feePct ?? 0.25, 0),
      slippagePct: Math.max(config.slippagePct ?? 0.25, 0),
      maxTradeUsd: Math.max(config.maxTradeUsd ?? 250, 1),
      minTradeUsd: Math.max(config.minTradeUsd ?? 5, 0),
      maxDailyLossPct: Math.max(config.maxDailyLossPct ?? 5, 0),
    };
    this.reset();
  }

  reset() {
    this.assetUnits = 0;
    this.cashUsd = this.config.bankrollUsd;
    this.startPrice = null;
    this.lastRebalancePrice = null;
    this.realizedPnl = 0;
    this.feesPaid = 0;
    this.trades = [];
    this.paused = false;
  }

  initialize(price) {
    if (!(price > 0)) throw new Error('Price must be positive');
    this.startPrice = price;
    this.lastRebalancePrice = price;
    const assetUsd = this.config.bankrollUsd * (this.config.targetAssetPct / 100);
    this.assetUnits = assetUsd / price;
    this.cashUsd = this.config.bankrollUsd - assetUsd;
    return this.snapshot(price);
  }

  value(price) {
    return this.cashUsd + this.assetUnits * price;
  }

  holdBenchmark(price) {
    if (!this.startPrice) return this.config.bankrollUsd;
    const startAssetUsd = this.config.bankrollUsd * (this.config.targetAssetPct / 100);
    const startCash = this.config.bankrollUsd - startAssetUsd;
    return startCash + (startAssetUsd / this.startPrice) * price;
  }

  snapshot(price) {
    const portfolio = this.value(price);
    const assetValue = this.assetUnits * price;
    const hold = this.holdBenchmark(price);
    return {
      symbol: this.config.symbol,
      price,
      portfolioValue: portfolio,
      pnl: portfolio - this.config.bankrollUsd,
      pnlPct: ((portfolio / this.config.bankrollUsd) - 1) * 100,
      realizedPnl: this.realizedPnl,
      feesPaid: this.feesPaid,
      assetUnits: this.assetUnits,
      cashUsd: this.cashUsd,
      assetPct: portfolio ? (assetValue / portfolio) * 100 : 0,
      holdBenchmark: hold,
      alphaVsHold: portfolio - hold,
      trades: this.trades.length,
      paused: this.paused,
    };
  }

  onPrice(price) {
    if (!this.startPrice) this.initialize(price);
    if (this.paused) return { action: 'PAUSED', snapshot: this.snapshot(price) };

    const movePct = ((price / this.lastRebalancePrice) - 1) * 100;
    if (Math.abs(movePct) < this.config.rebalanceBandPct) {
      return { action: 'HOLD', movePct, snapshot: this.snapshot(price) };
    }

    const portfolio = this.value(price);
    const currentAssetUsd = this.assetUnits * price;
    const targetAssetUsd = portfolio * (this.config.targetAssetPct / 100);
    const deviationUsd = currentAssetUsd - targetAssetUsd;
    const desiredUsd = Math.abs(deviationUsd) * (this.config.tradeFractionPct / 100);
    const tradeUsd = Math.min(desiredUsd, this.config.maxTradeUsd);

    if (tradeUsd < this.config.minTradeUsd) {
      return { action: 'HOLD', reason: 'MIN_TRADE', movePct, snapshot: this.snapshot(price) };
    }

    const side = deviationUsd > 0 ? 'SELL' : 'BUY';
    const costPct = (this.config.feePct + this.config.slippagePct) / 100;
    const cost = tradeUsd * costPct;

    if (side === 'SELL') {
      const units = Math.min(tradeUsd / price, this.assetUnits);
      const gross = units * price;
      const actualCost = gross * costPct;
      this.assetUnits -= units;
      this.cashUsd += gross - actualCost;
      this.realizedPnl += gross - actualCost - (units * this.startPrice);
      this.feesPaid += actualCost;
    } else {
      const spend = Math.min(tradeUsd, this.cashUsd / (1 + costPct));
      const actualCost = spend * costPct;
      this.cashUsd -= spend + actualCost;
      this.assetUnits += spend / price;
      this.feesPaid += actualCost;
    }

    this.lastRebalancePrice = price;
    const trade = { side, price, tradeUsd, cost, movePct, at: new Date().toISOString() };
    this.trades.push(trade);

    const snap = this.snapshot(price);
    if (snap.pnlPct <= -this.config.maxDailyLossPct) this.paused = true;
    return { action: side, trade, snapshot: snap };
  }
}

export class MultiAssetBalancer {
  constructor() { this.strategies = new Map(); }
  add(config) {
    if (!config.symbol) throw new Error('symbol is required');
    const strategy = new BalancerStrategy(config);
    this.strategies.set(config.symbol.toUpperCase(), strategy);
    return strategy;
  }
  get(symbol) { return this.strategies.get(symbol.toUpperCase()); }
  dashboard(prices) {
    return [...this.strategies.entries()].map(([symbol, strategy]) => {
      const price = prices[symbol];
      return price ? strategy.snapshot(price) : { symbol, error: 'NO_PRICE' };
    });
  }
}
