const WALLET = '7mVEbMXAzmK8Gwe8vkHDEn6YfxPEPJMF269EnFnQb8Su';
const USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const WSOL = 'So11111111111111111111111111111111111111112';

async function rpc(method, params) {
  const endpoint = process.env.SOLANA_RPC_URL || 'https://api.mainnet-beta.solana.com';
  const r = await fetch(endpoint, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params })
  });
  if (!r.ok) throw new Error(`RPC ${r.status}`);
  const j = await r.json();
  if (j.error) throw new Error(j.error.message || 'RPC error');
  return j.result;
}

async function getQuote() {
  const u = `https://lite-api.jup.ag/swap/v1/quote?inputMint=${WSOL}&outputMint=${USDC}&amount=1000000000&slippageBps=50&restrictIntermediateTokens=true`;
  const r = await fetch(u, { headers: { accept: 'application/json' } });
  if (!r.ok) throw new Error(`Jupiter ${r.status}`);
  const q = await r.json();
  if (!q.outAmount) throw new Error(q.error || 'No Jupiter route');
  return { price: Number(q.outAmount) / 1e6, priceImpactPct: Number(q.priceImpactPct || 0) };
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 'no-store');
  if (req.method === 'OPTIONS') return res.status(204).end();
  if (req.method !== 'GET') return res.status(405).json({ ok: false, error: 'Method not allowed' });
  try {
    const [sol, tokens, quote] = await Promise.all([
      rpc('getBalance', [WALLET, { commitment: 'confirmed' }]),
      rpc('getTokenAccountsByOwner', [WALLET, { mint: USDC }, { commitment: 'confirmed', encoding: 'jsonParsed' }]),
      getQuote()
    ]);
    const solAmount = sol.value / 1e9;
    const usdcAmount = tokens.value.reduce((sum, a) => sum + Number(a.account.data.parsed.info.tokenAmount.uiAmountString || 0), 0);
    const solValue = solAmount * quote.price;
    const portfolioValue = solValue + usdcAmount;
    return res.status(200).json({ ok: true, wallet: WALLET, solAmount, usdcAmount, solPrice: quote.price, priceImpactPct: quote.priceImpactPct, solValue, portfolioValue, allocation: { solPct: portfolioValue ? 100 * solValue / portfolioValue : 0, usdcPct: portfolioValue ? 100 * usdcAmount / portfolioValue : 0 }, updatedAt: new Date().toISOString(), executionEnabled: false });
  } catch (e) {
    return res.status(502).json({ ok: false, error: e.message || 'Pilot feed failed' });
  }
}
