const USDC='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const WSOL='So11111111111111111111111111111111111111112';
const TARGET=0.50;
const BAND=0.025;
const MAX_TRADE_USD=15;
const MIN_TRADE_USD=5;

async function pilot(req){
  const proto=req.headers['x-forwarded-proto']||'https';
  const host=req.headers.host;
  const r=await fetch(`${proto}://${host}/api/pilot`,{headers:{accept:'application/json'},cache:'no-store'});
  const d=await r.json();
  if(!r.ok||!d.ok)throw new Error(d.error||`Pilot ${r.status}`);
  return d;
}

async function quote(inputMint,outputMint,rawAmount){
  const u=new URL('https://lite-api.jup.ag/swap/v1/quote');
  u.searchParams.set('inputMint',inputMint);u.searchParams.set('outputMint',outputMint);u.searchParams.set('amount',String(rawAmount));u.searchParams.set('slippageBps','50');u.searchParams.set('restrictIntermediateTokens','true');
  const r=await fetch(u,{headers:{accept:'application/json'}});if(!r.ok)throw new Error(`Jupiter ${r.status}`);const q=await r.json();if(!q.outAmount)throw new Error(q.error||'No route');return q;
}

export default async function handler(req,res){
  res.setHeader('Cache-Control','no-store');
  if(req.method!=='GET')return res.status(405).json({ok:false,error:'Method not allowed'});
  try{
    const d=await pilot(req),solPct=d.allocation.solPct/100,deviation=solPct-TARGET;
    if(Math.abs(deviation)<BAND)return res.status(200).json({ok:true,action:'HOLD',reason:`SOL allocation ${d.allocation.solPct.toFixed(1)}% is inside the ${(BAND*100).toFixed(1)}% rebalance band`,targetPct:50,bandPct:BAND*100,tradeUsd:0,portfolio:d});
    const desiredSolValue=d.portfolioValue*TARGET;
    let tradeUsd=Math.min(MAX_TRADE_USD,Math.abs(d.solValue-desiredSolValue));
    if(tradeUsd<MIN_TRADE_USD)return res.status(200).json({ok:true,action:'HOLD',reason:`Drift exists but calculated trade is below $${MIN_TRADE_USD}`,targetPct:50,bandPct:BAND*100,tradeUsd:0,portfolio:d});
    const action=deviation>0?'SELL_SOL':'BUY_SOL';
    const inputMint=action==='SELL_SOL'?WSOL:USDC,outputMint=action==='SELL_SOL'?USDC:WSOL;
    const rawAmount=action==='SELL_SOL'?Math.floor((tradeUsd/d.solPrice)*1e9):Math.floor(tradeUsd*1e6);
    const q=await quote(inputMint,outputMint,rawAmount);
    const expectedOut=action==='SELL_SOL'?Number(q.outAmount)/1e6:Number(q.outAmount)/1e9;
    return res.status(200).json({ok:true,action,reason:`SOL is ${d.allocation.solPct.toFixed(1)}% of portfolio vs 50% target`,targetPct:50,bandPct:BAND*100,tradeUsd:Number(tradeUsd.toFixed(2)),inputMint,outputMint,rawAmount:String(rawAmount),expectedOut,expectedOutSymbol:action==='SELL_SOL'?'USDC':'SOL',slippageBps:50,priceImpactPct:Number(q.priceImpactPct||0),quote:q,portfolio:d,executionEnabled:false});
  }catch(e){return res.status(502).json({ok:false,error:e.message||'Proposal failed'});}
}
