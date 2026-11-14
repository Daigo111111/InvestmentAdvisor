import { decryptObj, encryptObj } from './crypto.js';

const CFG_KEY = 'advisor_cfg';
const PW_KEY = 'advisor_pw';

export function getCfg() {
  try { return JSON.parse(localStorage.getItem(CFG_KEY)) || {}; } catch { return {}; }
}
export function setCfg(patch) {
  const c = { ...getCfg(), ...patch };
  localStorage.setItem(CFG_KEY, JSON.stringify(c));
  return c;
}
export function getPw() {
  return sessionStorage.getItem(PW_KEY) || localStorage.getItem(PW_KEY) || '';
}
export function setPw(pw, remember) {
  sessionStorage.setItem(PW_KEY, pw);
  if (remember) localStorage.setItem(PW_KEY, pw); else localStorage.removeItem(PW_KEY);
}
export function clearPw() { sessionStorage.removeItem(PW_KEY); localStorage.removeItem(PW_KEY); }

export const isDemo = () => new URLSearchParams(location.search).has('demo') || getCfg().demo === true;

async function fetchJson(url) {
  const r = await fetch(`${url}?t=${Date.now()}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

/** 用站点上的口令校验文件确认口令与 GitHub Secret 一致。返回 true/false；校验文件不存在时返回 null。 */
export async function verifyPw(pw) {
  let env = null;
  try { env = await fetchJson('data/key_check.enc.json'); } catch { return null; }
  try { return (await decryptObj(env, pw)).ok === true; } catch { return false; }
}

/** 返回 {report, demo}；正式数据需要口令，口令错误抛出 'BAD_PW'，无数据时回退演示数据。 */
export async function loadReport() {
  if (!isDemo()) {
    let env = null;
    try { env = await fetchJson('data/report.enc.json'); } catch { env = null; }
    if (env) {
      const pw = getPw();
      if (!pw) throw new Error('NEED_PW');
      try { return { report: await decryptObj(env, pw), demo: false }; } catch { throw new Error('BAD_PW'); }
    }
  }
  return { report: await fetchJson('data/demo_report.json'), demo: true };
}

// ---------- GitHub 仓库读写（持仓文件 + 手动触发分析） ----------
function gh() {
  const c = getCfg();
  if (!c.ghOwner || !c.ghRepo || !c.ghToken) return null;
  return { ...c, ghBranch: c.ghBranch || 'main' };
}
async function ghFetch(path, opt = {}, allow404 = false) {
  const c = gh();
  const r = await fetch(`https://api.github.com/repos/${encodeURIComponent(c.ghOwner)}/${encodeURIComponent(c.ghRepo)}/${path}`, {
    ...opt,
    cache: 'no-store',
    headers: { Authorization: `Bearer ${c.ghToken}`, Accept: 'application/vnd.github+json', ...(opt.headers || {}) },
  });
  if (r.ok || (allow404 && r.status === 404)) return r;
  const hint = { 401: '令牌无效或已过期', 403: '令牌权限不足', 404: '找不到仓库/分支，或令牌无权访问', 409: '文件已在别处被修改，请刷新后重试', 422: '参数错误（分支或工作流不存在）' }[r.status] || '';
  throw new Error(`GitHub ${r.status} ${hint}`);
}
const utf8b64 = (s) => {
  const bytes = new TextEncoder().encode(s);
  let out = '';
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(out);
};
const b64utf8 = (s) => new TextDecoder().decode(Uint8Array.from(atob(s.replace(/\n/g, '')), (c) => c.charCodeAt(0)));

export const ghReady = () => !!gh();

export async function loadHoldings() {
  if (isDemo()) {
    const local = localStorage.getItem('demo_holdings');
    return { holdings: local ? JSON.parse(local) : await fetchJson('data/demo_holdings.json'), sha: null, source: 'demo' };
  }
  const pw = getPw();
  if (!pw) throw new Error('NEED_PW');
  if (gh()) {
    const c = gh();
    const r = await ghFetch(`contents/data/holdings.enc.json?ref=${encodeURIComponent(c.ghBranch)}`, {}, true);
    if (r.status === 404) return { holdings: { funds: [], stocks: [], cash: 0, settings: {} }, sha: null, source: 'github' };
    const j = await r.json();
    try {
      return { holdings: await decryptObj(JSON.parse(b64utf8(j.content)), pw), sha: j.sha, source: 'github' };
    } catch { throw new Error('BAD_PW'); }
  }
  let env = null;
  try { env = await fetchJson('data/holdings.enc.json'); } catch { env = null; }
  if (!env) return { holdings: { funds: [], stocks: [], cash: 0, settings: {} }, sha: null, source: 'empty' };
  try { return { holdings: await decryptObj(env, pw), sha: null, source: 'site' }; } catch { throw new Error('BAD_PW'); }
}

export async function saveHoldings(holdings, sha) {
  if (isDemo()) {
    localStorage.setItem('demo_holdings', JSON.stringify(holdings));
    return { ok: true, demo: true };
  }
  if (!gh()) throw new Error('请先在「我的」里配置 GitHub 仓库和令牌');
  const c = gh();
  const env = await encryptObj(holdings, getPw());
  const body = { message: 'update holdings (encrypted)', content: utf8b64(JSON.stringify(env)), branch: c.ghBranch };
  if (sha) body.sha = sha;
  const r = await ghFetch('contents/data/holdings.enc.json', { method: 'PUT', body: JSON.stringify(body) });
  const j = await r.json();
  return { ok: true, sha: j.content && j.content.sha };
}

export async function triggerJob(job) {
  if (!gh()) throw new Error('请先配置 GitHub');
  const c = gh();
  await ghFetch('actions/workflows/advisor.yml/dispatches', {
    method: 'POST', body: JSON.stringify({ ref: c.ghBranch, inputs: { job } }),
  });
}
