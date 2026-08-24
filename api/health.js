export default function handler(req, res) {
  res.status(200).json({ ok: true, service: 'w3bc-balancer', mode: 'live-pilot-read-only' });
}
