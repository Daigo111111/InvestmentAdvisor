// 网页端实时估值：从腾讯行情接口（支持跨域）拉取最新行情，套用服务器每天回测选出的估值模型，随时重新估算基金涨跌。
// 模型由若干成分组成（重仓股组合 / 跟踪指数），每个成分有回归系数；QDII 还叠加美元兑人民币汇率变化。
// 算法与引擎 analysis/estimator.py 的 live_estimate 保持一致。

const QUOTE_URL = 'https://qt.gtimg.cn/q=';
const FX = 'whUSDCNY';
const digits = (s) => (s || '').replace(/\D/g, '').slice(0, 8);

async function fetchBatch(syms) {
  const r = await fetch(QUOTE_URL + syms.join(','), { cache: 'no-store' });
  if (!r.ok) throw new Error(`行情接口 HTTP ${r.status}`);
  const text = new TextDecoder('gbk').decode(await r.arrayBuffer());
  const out = {};
  for (const line of text.split(';')) {
    const i = line.indexOf('="');
    if (i < 0) continue;
    const key = line.slice(0, i).trim().replace(/^v_/, '');
    const f = line.slice(i + 2).split('~');
    let pct, t;
    if (key.startsWith('wh')) {  // 汇率：f[3] 最新价，f[6] 昨收
      const p = parseFloat(f[3]), prev = parseFloat(f[6]);
      pct = p && prev ? (p / prev - 1) * 100 : NaN; t = f[5];
    } else {
      if (f.length < 33) continue;
      pct = parseFloat(f[32]); t = f[30];
    }
    if (!Number.isNaN(pct)) out[key] = { pct, date: digits(t) };
  }
  return out;
}

export async function fetchQuotes(syms) {
  const uniq = [...new Set(syms)];
  const parts = [];
  for (let i = 0; i < uniq.length; i += 60) parts.push(fetchBatch(uniq.slice(i, i + 60)));
  return Object.assign({}, ...(await Promise.all(parts)));
}

function symbolsOf(model) {
  const s = model.components.flatMap((c) => (c.kind === 'basket' ? c.holdings.map((h) => h.symbol) : [c.symbol]));
  return model.fx ? [...s, FX] : s;
}

function compLive(c, q) {
  if (c.kind === 'basket') {
    const rows = c.holdings.map((h) => [h.weight, q[h.symbol]]);
    const dates = rows.map(([, x]) => x && x.date).filter(Boolean).sort();
    if (!dates.length) return null;
    const latest = dates[dates.length - 1];
    const ok = rows.filter(([, x]) => x && x.date === latest);
    const w = ok.reduce((a, [wt]) => a + wt, 0);
    if (!w) return null;
    return { x: ok.reduce((a, [wt, x]) => a + wt * x.pct, 0) / w, date: latest,
      cov: w / c.holdings.reduce((a, h) => a + h.weight, 0) };
  }
  const x = q[c.symbol];
  return x ? { x: x.pct, date: x.date, cov: 1 } : null;
}

export function applyModel(model, q) {
  const fx = model.fx && q[FX] ? q[FX].pct : null;
  let total = 0; const dates = []; let cov = 1;
  for (const c of model.components) {
    const v = compLive(c, q);
    if (!v) return null;
    const x = fx != null ? ((1 + v.x / 100) * (1 + fx / 100) - 1) * 100 : v.x;
    total += c.beta * x; dates.push(v.date); cov = Math.min(cov, v.cov);
  }
  return { est: Math.round(total * 100) / 100, date: dates.sort().pop(), cov };
}

const fmtDate = (t) => `${t.slice(0, 4)}-${t.slice(4, 6)}-${t.slice(6, 8)}`;
const todayStr = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

/** 计算每只基金的实时估值，返回 {byCode, phase, updatedAt} */
export async function computeLive(rep) {
  const funds = (rep.funds || []).filter((f) => f.live && f.live.components && f.live.components.length);
  if (!funds.length) return null;
  const q = await fetchQuotes(funds.flatMap((f) => symbolsOf(f.live)));
  const byCode = {};
  let anyToday = false;
  const now = new Date(), hhmm = now.getHours() * 100 + now.getMinutes();
  for (const f of funds) {
    const v = applyModel(f.live, q);
    if (!v || !v.date) continue;
    const navDate = fmtDate(v.date);  // 这次估算对应的净值日期（美股基金白天是前一晚美股收盘对应的那天）
    const m = f.metrics || {};
    const published = m.nav_date && m.nav_date >= navDate;
    const base = m.value != null ? m.value / (1 + (m.est_pct || 0) / 100) : null;
    const pct = published ? m.last_pct : v.est;
    const isToday = navDate === todayStr();
    anyToday = anyToday || isToday;
    byCode[f.code] = {
      est: v.est, coverage: v.cov, navDate, actual: published ? m.last_pct : null,
      state: published ? '实际' : isToday && (hhmm < 1610 || (f.category === 'qdii' && hhmm >= 2130)) ? '实时' : '收盘',
      value: published ? m.value : base != null ? base * (1 + v.est / 100) : null,
      pnl: base != null && pct != null ? (published ? m.value - m.value / (1 + pct / 100) : base * v.est / 100) : null,
    };
  }
  const phase = anyToday && hhmm >= 930 && hhmm < 1500 ? '盘中实时' : '收盘估算';
  return { byCode, phase, updatedAt: now.toTimeString().slice(0, 8) };
}

/** 交易时段（A股/港股 9:30–16:10）才需要自动刷新 */
export function isMarketOpen() {
  const d = new Date();
  const day = d.getDay(), hhmm = d.getHours() * 100 + d.getMinutes();
  return day >= 1 && day <= 5 && hhmm >= 930 && hhmm <= 1610;
}
