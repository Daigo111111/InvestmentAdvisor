import { loadReport, getPw, setPw, clearPw, getCfg, setCfg, isDemo, ghReady, triggerJob, verifyPw } from './store.js';
import { esc, toast } from './ui.js';
import * as V from './views.js';
import * as V2 from './views2.js';
import * as H from './holdings.js';
import { computeLive, isMarketOpen } from './live.js';

const st = { report: null, demo: false, zone: null, h: null, sha: null, draft: null, hSource: null,
  live: null, liveAt: 0, liveLoading: false, liveErr: '' };
let liveTimer = null;

async function refreshLive(force = false) {
  if (!st.report || st.liveLoading) return;
  if (!force && st.live && Date.now() - st.liveAt < 30000) return;
  st.liveLoading = true; st.liveErr = '';
  paint();
  try {
    st.live = await computeLive(st.report);
    st.liveAt = Date.now();
  } catch (e) {
    st.liveErr = e.message || '网络错误';
  } finally {
    st.liveLoading = false;
    paint();
  }
}
const view = document.getElementById('view');

function lockScreen(msg) {
  return `<div class="card"><h3>输入口令解锁</h3>
    <div class="small muted">你的持仓和报告在仓库中加密存储，口令只保存在你的设备上。${esc(msg || '')}</div>
    <label>口令</label><input id="pw" type="password" autocomplete="current-password">
    <label style="display:flex;align-items:center;gap:6px"><input id="remember" type="checkbox" style="width:auto"> 在本设备记住口令</label>
    <div class="row" style="margin-top:10px"><button id="unlock">解锁</button><button class="ghost" id="toDemo">查看演示</button></div></div>`;
}

function mePage() {
  const c = getCfg();
  return `<div class="card"><h3>使用方式</h3><div class="small">
      iPhone：Safari 打开本页 → 底部「分享」→「添加到主屏幕」。Android/电脑：浏览器菜单 →「安装应用」。<br>
      推送：每个交易日 09:00 早报、14:10 尾盘决策、20:30 晚间复盘，周六周报（飞书 / 微信 WxPusher）。</div></div>
    <div class="card"><h3>口令</h3>
      <div class="small muted">${getPw() ? '已解锁' : '未解锁'}${isDemo() ? ' · 当前为演示模式' : ''}${st.demo && !isDemo() ? ' · 还没有你的持仓报告，页面显示的是演示数据' : ''}</div>
      <div class="row" style="margin-top:8px"><button class="ghost" id="logout">退出并清除本机口令</button>
        <button class="ghost" id="demoToggle">${isDemo() ? '退出演示模式' : '切换到演示模式'}</button></div></div>
    <div class="card"><h3>GitHub 仓库（用于保存持仓、手动触发分析）</h3>
      <div class="small muted">令牌请使用 Fine-grained token，只授权本仓库的 Contents 读写和 Actions 读写，保存在本机浏览器中。</div>
      <label>用户名 / 组织</label><input id="ghOwner" value="${esc(c.ghOwner || '')}">
      <label>仓库名</label><input id="ghRepo" value="${esc(c.ghRepo || '')}">
      <label>分支</label><input id="ghBranch" value="${esc(c.ghBranch || 'main')}">
      <label>令牌</label><input id="ghToken" type="password" value="${esc(c.ghToken || '')}">
      <div class="row" style="margin-top:8px"><button id="saveGh">保存配置</button>
        <button class="ghost" id="runNow" ${ghReady() ? '' : 'disabled'}>立即重新分析</button></div></div>
    <div id="hBox"><div class="card">加载持仓…</div></div>`;
}

async function renderHoldings() {
  const box = document.getElementById('hBox');
  if (!box) return;
  try {
    await H.ensureLoaded(st);
    box.innerHTML = H.render(st);
    H.bind(box, st, renderHoldings);
  } catch (e) {
    if (e.message === 'NEED_PW' || e.message === 'BAD_PW') {
      box.innerHTML = lockScreen(e.message === 'BAD_PW' ? '口令与已保存的持仓不匹配。' : '首次使用请设置口令，并在 GitHub Secret ADVISOR_PASSPHRASE 中填入同一个口令。');
      bindLock();
    } else {
      box.innerHTML = `<div class="card">持仓读取失败：${esc(e.message)}</div>`;
    }
  }
}

function bindMe() {
  const $ = (id) => document.getElementById(id);
  $('logout').onclick = () => { clearPw(); st.report = null; st.h = null; toast('已退出'); route(); };
  $('demoToggle').onclick = () => {
    setCfg({ demo: !isDemo() });
    if (new URLSearchParams(location.search).has('demo')) history.replaceState(null, '', location.pathname + location.hash);
    st.report = null; st.h = null; route();
  };
  $('saveGh').onclick = () => {
    setCfg({ ghOwner: $('ghOwner').value.trim(), ghRepo: $('ghRepo').value.trim(), ghBranch: $('ghBranch').value.trim() || 'main', ghToken: $('ghToken').value.trim() });
    st.h = null; toast('已保存'); route();
  };
  $('runNow').onclick = async () => {
    try { await triggerJob('refresh'); toast('已触发分析，几分钟后刷新页面'); } catch (e) { toast(e.message, 4000); }
  };
  renderHoldings();
}

function bindLock() {
  const $ = (id) => document.getElementById(id);
  $('unlock').onclick = async () => {
    const pw = $('pw').value;
    if (!pw) return toast('请输入口令');
    const ok = await verifyPw(pw);
    if (ok === false) return toast('口令错误：与 GitHub Secret ADVISOR_PASSPHRASE 不一致', 3500);
    if (ok === null) toast('暂时无法校验口令（站点尚未生成校验文件），请确认与 GitHub Secret 一致', 3500);
    setPw(pw, $('remember').checked); st.report = null; st.h = null; route();
  };
  $('pw').onkeydown = (e) => { if (e.key === 'Enter') $('unlock').click(); };
  $('toDemo').onclick = () => { setCfg({ demo: true }); st.report = null; route(); };
}

async function ensureReport() {
  if (st.report) return true;
  if (!st.pwChecked && getPw() && !isDemo()) {
    st.pwChecked = true;
    if ((await verifyPw(getPw())) === false) { clearPw(); toast('已保存的口令不正确，请重新输入', 3000); }
  }
  try {
    const { report, demo } = await loadReport();
    st.report = report; st.demo = demo; st.live = null; st.liveAt = 0;
    return true;
  } catch (e) {
    if (e.message === 'NEED_PW' || e.message === 'BAD_PW') {
      view.innerHTML = lockScreen(e.message === 'BAD_PW' ? '口令错误，请重试。' : '');
      bindLock();
    } else {
      view.innerHTML = `<div class="card">报告加载失败：${esc(e.message)}。首次部署需要等待第一次定时任务运行完成。</div>`;
    }
    return false;
  }
}

let seq = 0;
async function route() {
  const my = ++seq;
  const tab = (location.hash.replace('#/', '') || 'home').split('?')[0];
  document.querySelectorAll('.tabs a').forEach((a) => a.classList.toggle('on', a.dataset.tab === tab));
  if (tab === 'me') {
    clearInterval(liveTimer);
    view.innerHTML = mePage();
    bindMe();
    return;
  }
  const ok = await ensureReport();
  if (my !== seq || !ok) return;  // 等待解密期间用户已切换页面
  const meta = st.report.meta || {};
  document.getElementById('badge').textContent = st.demo ? '演示数据' : '';
  document.getElementById('updated').textContent = `报告更新于 ${meta.generated_at || '-'}（${{ morning: '早报', close: '尾盘', evening: '复盘', weekly: '周报', refresh: '手动' }[meta.job] || ''}）`;
  paint();
  window.scrollTo(0, 0);
  clearInterval(liveTimer);
  if (tab === 'home' || tab === 'funds') {
    refreshLive();
    liveTimer = setInterval(() => { if (isMarketOpen() && !document.hidden) refreshLive(true); }, 60000);
  }
}

function currentTab() { return (location.hash.replace('#/', '') || 'home').split('?')[0]; }

/** 只重绘当前页面（不重新解密报告），实时估值更新时调用 */
function paint() {
  const tab = currentTab();
  if (tab === 'me' || !st.report) return;
  const rep = st.report;
  const ls = { loading: st.liveLoading, err: st.liveErr };
  const pages = { home: (r) => V.home(r, st.live, ls), funds: (r) => V.funds(r, st.live, ls), stocks: V.stocks,
    zones: (r) => V2.zones(r, st), plan: V2.plan };
  const y = window.scrollY;
  try {
    view.innerHTML = (pages[tab] || pages.home)(rep) + `<div class="disclaimer">${esc((rep.meta || {}).disclaimer || '')}</div>`;
  } catch (e) {
    view.innerHTML = `<div class="card">该页面数据不完整，等待下一次分析任务后再试。（${esc(e.message)}）</div>`;
  }
  window.scrollTo(0, y);
  view.querySelectorAll('[data-zone]').forEach((b) => b.addEventListener('click', () => { st.zone = b.dataset.zone; paint(); }));
  const rb = document.getElementById('liveRefresh');
  if (rb) rb.onclick = () => refreshLive(true);
}

// 从后台切回应用时，如果估值超过 1 分钟没更新就自动刷新
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && ['home', 'funds'].includes(currentTab())) refreshLive();
});

window.addEventListener('hashchange', route);
route();

if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
