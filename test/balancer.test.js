import test from 'node:test';
import assert from 'node:assert/strict';
import { BalancerStrategy, MultiAssetBalancer } from '../src/core/balancer.js';

test('initializes at target allocation', () => {
  const s = new BalancerStrategy({ symbol: 'SOL', bankrollUsd: 1000, targetAssetPct: 50 });
  const snap = s.initialize(100);
  assert.equal(snap.assetUnits, 5);
  assert.equal(snap.cashUsd, 500);
  assert.equal(Math.round(snap.assetPct), 50);
});

test('does not trade inside band', () => {
  const s = new BalancerStrategy({ symbol: 'SOL', rebalanceBandPct: 4 });
  s.initialize(100);
  assert.equal(s.onPrice(103).action, 'HOLD');
});

test('supports independent assets', () => {
  const bot = new MultiAssetBalancer();
  bot.add({ symbol: 'SOL' });
  bot.add({ symbol: 'JCHAINS' });
  assert.notEqual(bot.get('SOL'), bot.get('JCHAINS'));
});
