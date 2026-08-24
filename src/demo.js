import { MultiAssetBalancer } from './core/balancer.js';

const bot = new MultiAssetBalancer();

bot.add({ symbol: 'SOL', bankrollUsd: 1000, rebalanceBandPct: 4 });
bot.add({ symbol: 'JCHAINS', bankrollUsd: 1000, rebalanceBandPct: 5 });

const paths = {
  SOL: [180, 188, 176, 191, 183, 198, 187, 202],
  JCHAINS: [0.00060, 0.00064, 0.00059, 0.00067, 0.00062, 0.00070, 0.00065],
};

for (const [symbol, prices] of Object.entries(paths)) {
  const strategy = bot.get(symbol);
  console.log(`\n${symbol}`);
  for (const price of prices) {
    const event = strategy.onPrice(price);
    const s = event.snapshot;
    console.log(`${event.action.padEnd(4)} price=${price} value=$${s.portfolioValue.toFixed(2)} hold=$${s.holdBenchmark.toFixed(2)} alpha=$${s.alphaVsHold.toFixed(2)}`);
  }
}
