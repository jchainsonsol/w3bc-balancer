const USDC='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const UNIVERSE=[
 {symbol:'SOL',mint:'So11111111111111111111111111111111111111112',decimals:9},
 {symbol:'JUP',mint:'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',decimals:6},
 {symbol:'JTO',mint:'jtojtomepa8beP8AuQc6eXt5FriJwfFMwY4Qm6rASfR',decimals:9},
 {symbol:'BONK',mint:'DezXAZ8z7PnrnRJjz3wXBoRgixCa6fhXtKTq9vQ6WnC',decimals:5},
 {symbol:'WIF',mint:'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzL4jM4FqkPZ5',decimals:6}
];
async function quote(t,usd=10){const amount=Math.floor(usd*1e6),u=new URL('https://lite-api.jup.ag/swap/v1/quote');u.searchParams.set('inputMint',USDC);u.searchParams.set('outputMint',t.mint);u.searchParams.set('amount',String(amount));u.searchParams.set('slippageBps','50');u.searchParams.set('restrictIntermediateTokens','true');const r=await fetch(u,{headers:{accept:'application/json'}});if(!r.ok)throw new Error(`quote ${r.status}`);const q=await r.json();if(!q.outAmount)throw new Error('no route');const out=Number(q.outAmount)/10**t.decimals;return{priceUsd:usd/out,priceImpactPct:Number(q.priceImpactPct||0)}}
export default async function handler(req,res){res.setHeader('Cache-Control','no-store');try{const rows=await Promise.all(UNIVERSE.map(async t=>{try{const q=await quote(t);return{...t,...q,tradable:true}}catch(e){return{...t,tradable:false,error:e.message}}}));return res.status(200).json({ok:true,updatedAt:new Date().toISOString(),universe:rows,policy:{homeBase:'USDC',maxOpenPositions:2,maxPositionUsd:25,minPositionUsd:10,maxPriceImpactPct:0.5,executionEnabled:false}})}catch(e){return res.status(502).json({ok:false,error:e.message})}}
