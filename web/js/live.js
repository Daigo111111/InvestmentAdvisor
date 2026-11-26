// 网页端实时估值：直接从腾讯行情接口（支持跨域）拉取重仓股最新涨跌，在手机上随时重新估算基金当日涨跌。
// 盘中是实时估算；15:00 收盘后到当晚净值公布前，是按收盘价算出的「收盘估算」；净值公布后以实际净值为准。

const QUOTE_URL = 'https://qt.gtimg.cn/q=';
const prefix = (c) => (/^[69]/.test(c) || /^(50|51|56|58|11)/.test(c) ? 'sh' : /^[48]/.test(c) ? 'bj' : 'sz');

async function fetchBatch(codes) {
  const r = await fetch(QUOTE_URL + codes.map((c) => prefix(c) + c).join(','), { cache: 'no-store' });
  if (!r.ok) throw new Error(`行情接口 HTTP ${r.status}`);
  const text = new TextDecoder('gbk').decode(await r.arrayBuffer());
  const out = {};
  for (const line of text.split(';')) {
    const i = line.indexOf('="');
    if (i < 0) continue;
    const f = line.slice(i + 2).split('~');
    if (f.length < 33) continue;
    const pct = parseFloat(f[32]);
    if (!Number.isNaN(pct)) out[f[2]] = { pct, price: parseFloat(f[3]), time: f[30] || '' };
  }
  return out;
}

export async function fetchQuotes(codes) {
  const uniq = [...new Set(codes)];
  const parts = [];
  for (let i = 0; i < uniq.length; i += 60) parts.push(fetchBatch(uniq.slice(i, i + 60)));
  return Object.assign({}, ...(await Promise.all(parts)));
}

const fmtDate = (t) => `${t.slice(0, 4)}-${t.slice(4, 6)}-${t.slice(6, 8)}`;

/** 计算每只基金的实时估值，返回 {byCode, tradeDate, updatedAt, phase} */
export async function computeLive(rep) {
  const funds = (rep.funds || []).filter((f) => f.live && f.live.holdings && f.live.holdings.length);
  if (!funds.length) return null;
  const quotes = await fetchQuotes(funds.flatMap((f) => f.live.holdings.map((h) => h.code)));
  // 行情所属交易日 = 所有报价里最新的日期（停牌股的旧报价不参与）
  const latest = Object.values(quotes).map((q) => q.time.slice(0, 8)).filter(Boolean).sort().pop();
  if (!latest) return null;
  const tradeDate = fmtDate(latest);
  const byCode = {};
  for (const f of funds) {
    let wsum = 0, acc = 0;
    for (const h of f.live.holdings) {
      const q = quotes[h.code];
      if (!q || !q.time.startsWith(latest)) continue;
      wsum += h.weight; acc += h.weight * q.pct;
    }
    if (!wsum) continue;
    const est = (acc / wsum) * f.live.pos * (f.live.beta || 1);
    const m = f.metrics || {};
    const published = m.nav_date && m.nav_date >= tradeDate;  // 报告里已有当日真实净值
    // 报告里的市值可能已含 14:10 的估算，先还原成「最新已公布净值 × 份额」再套用实时估算，避免重复计算
    const base = m.value != null ? m.value / (1 + (m.est_pct || 0) / 100) : null;
    const pct = published ? m.last_pct : Math.round(est * 100) / 100;
    byCode[f.code] = {
      est: Math.round(est * 100) / 100,
      coverage: Math.min(1, wsum / 100 / f.live.pos),
      actual: published ? m.last_pct : null,
      value: published ? m.value : base != null ? base * (1 + est / 100) : null,
      pnl: base != null && pct != null ? (published ? m.value - m.value / (1 + pct / 100) : base * est / 100) : null,
    };
  }
  const now = new Date();
  const hhmm = now.getHours() * 100 + now.getMinutes();
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  let phase = '收盘估算';
  if (tradeDate === todayStr && hhmm >= 930 && hhmm < 1500) phase = '盘中实时';
  else if (tradeDate === todayStr && hhmm < 930) phase = '未开盘';
  return { byCode, tradeDate, phase, updatedAt: now.toTimeString().slice(0, 8) };
}

/** 盘中（交易日 9:30–15:00）才需要自动刷新 */
export function isMarketOpen() {
  const d = new Date();
  const day = d.getDay(), hhmm = d.getHours() * 100 + d.getMinutes();
  return day >= 1 && day <= 5 && ((hhmm >= 930 && hhmm <= 1130) || (hhmm >= 1300 && hhmm <= 1500));
}
