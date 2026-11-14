import { esc, money, toast } from './ui.js';
import { loadHoldings, saveHoldings, isDemo, ghReady, getPw, verifyPw } from './store.js';
import { getFundIndex, recognizeAll, parseHoldings } from './ocr.js';

const RISK_FIELDS = [
  ['max_drawdown', '组合最大回撤上限', 0.2], ['fund_stop_loss', '基金止损线(持有收益)', -0.12],
  ['fund_take_profit', '基金止盈观察线', 0.25], ['single_stock_cap', '单只股票仓位上限', 0.1],
  ['single_fund_cap', '单只基金仓位上限', 0.25],
];

export async function ensureLoaded(st) {
  if (!st.h) {
    const { holdings, sha, source } = await loadHoldings();
    st.h = holdings; st.sha = sha; st.hSource = source;
    st.h.funds ||= []; st.h.stocks ||= []; st.h.settings ||= {};
  }
}

export function render(st) {
  const h = st.h;
  const src = { demo: '演示数据（保存在本机浏览器）', github: 'GitHub 仓库（加密）', site: '站点副本（只读，配置 GitHub 后可保存）', empty: '暂无持仓' }[st.hSource];
  const fundRows = h.funds.map((f, i) => `<tr><td>${esc(f.name || f.code)}<div class="muted small">${esc(f.code)}</div></td>
    <td>${f.amount != null ? money(f.amount) + '元' : esc(f.shares) + '份'}</td>
    <td>${f.profit != null ? money(f.profit) : f.cost_nav != null ? '成本' + esc(f.cost_nav) : '-'}</td>
    <td>${esc(f.buy_date || (f.lots && f.lots[0] && f.lots[0].date) || '-')}</td>
    <td><button class="ghost" data-del-fund="${i}">删</button></td></tr>`).join('');
  const stockRows = h.stocks.map((s, i) => `<tr><td>${esc(s.name || s.code)}<div class="muted small">${esc(s.code)}</div></td>
    <td>${esc(s.shares)}股</td><td>${esc(s.cost)}</td><td>${esc(s.buy_date || '-')}</td>
    <td><button class="ghost" data-del-stock="${i}">删</button></td></tr>`).join('');
  const draft = (st.draft || []).map((d, i) => `<tr>
    <td><select data-draft-code="${i}">${d.candidates.map((c) => `<option value="${esc(c.code)}" ${c.code === d.code ? 'selected' : ''}>${esc(c.name)} ${esc(c.code)}</option>`).join('')}</select>
      <div class="muted small">识别原文：${esc(d.raw)}</div></td>
    <td><input data-draft-amount="${i}" inputmode="decimal" value="${esc(d.amount ?? '')}"></td>
    <td><input data-draft-profit="${i}" inputmode="decimal" value="${esc(d.profit ?? '')}"></td></tr>`).join('');
  return `
  <div class="card"><h3>持仓管理</h3><div class="muted small">数据来源：${esc(src)}</div></div>
  <div class="card"><h3>截图导入</h3>
    <div class="small muted">支持支付宝、天天基金、银行 App 的基金持仓截图。识别在手机本地完成，图片不会上传。识别后请逐条核对。</div>
    <input type="file" id="ocrFile" accept="image/*" multiple style="margin-top:8px">
    <div id="ocrStatus" class="small muted"></div>
    ${draft ? `<table style="margin-top:8px"><tr><th>基金</th><th>持有金额</th><th>持有收益</th></tr>${draft}</table>
      <div class="row" style="margin-top:8px"><button id="draftAdd">核对无误，全部加入</button><button class="ghost" id="draftClear">清空</button></div>` : ''}
  </div>
  <div class="card"><h3>基金</h3>
    <table><tr><th>名称</th><th>金额/份额</th><th>收益/成本</th><th>买入日</th><th></th></tr>${fundRows}</table>
    <h4>手动添加</h4>
    <label>基金代码</label><input id="fCode" inputmode="numeric" maxlength="6" placeholder="如 005827"><div id="fName" class="small muted"></div>
    <div class="grid"><div><label>持有金额(元)</label><input id="fAmount" inputmode="decimal"></div>
      <div><label>持有收益(元)</label><input id="fProfit" inputmode="decimal"></div>
      <div><label>买入日期</label><input id="fDate" type="date"></div></div>
    <div class="small muted">知道份额和成本净值也可以填：</div>
    <div class="grid"><div><label>份额</label><input id="fShares" inputmode="decimal"></div>
      <div><label>成本净值</label><input id="fCost" inputmode="decimal"></div><div></div></div>
    <div style="margin-top:8px"><button id="addFund">添加基金</button></div>
  </div>
  <div class="card"><h3>股票</h3>
    <table><tr><th>名称</th><th>数量</th><th>成本</th><th>买入日</th><th></th></tr>${stockRows}</table>
    <div class="grid"><div><label>代码</label><input id="sCode" inputmode="numeric" maxlength="6"></div>
      <div><label>名称</label><input id="sName"></div><div><label>买入日期</label><input id="sDate" type="date"></div>
      <div><label>股数</label><input id="sShares" inputmode="numeric"></div><div><label>成本价</label><input id="sCost" inputmode="decimal"></div><div></div></div>
    <div style="margin-top:8px"><button id="addStock">添加股票</button></div>
  </div>
  <div class="card"><h3>现金与风险参数</h3>
    <label>可用现金(元)</label><input id="cash" inputmode="decimal" value="${esc(h.cash || 0)}">
    <div class="grid">${RISK_FIELDS.map(([k, n, d]) => `<div><label>${n}</label><input data-risk="${k}" inputmode="decimal" value="${esc(h.settings[k] ?? d)}"></div>`).join('')}</div>
    <div class="muted small">比例用小数，如 0.2 表示 20%。</div>
  </div>
  <div class="card"><button id="saveH" style="width:100%">保存持仓${isDemo() ? '（演示模式仅保存在本机）' : ghReady() ? '并重新分析' : ''}</button>
    <div class="muted small" style="margin-top:6px">保存后 GitHub 会自动重新分析，几分钟后刷新页面即可看到新建议。</div></div>`;
}

const num = (v) => (v === '' || v == null ? null : Number(v));

export function bind(root, st, rerender0) {
  const $ = (id) => root.querySelector(`#${id}`);
  // 重新渲染前先把现金和风险参数输入框的值写回，避免未保存的输入丢失
  const syncInputs = () => {
    if ($('cash')) st.h.cash = num($('cash').value) || 0;
    root.querySelectorAll('[data-risk]').forEach((i) => { if (i.value !== '') st.h.settings[i.dataset.risk] = num(i.value); });
  };
  const rerender = () => { syncInputs(); rerender0(); };
  $('fCode')?.addEventListener('input', async (e) => {
    const code = e.target.value.trim();
    if (code.length !== 6) { $('fName').textContent = ''; return; }
    const f = (await getFundIndex()).find((x) => x[0] === code);
    $('fName').textContent = f ? `${f[1]} · ${f[2]}` : '未找到该基金代码';
  });
  $('addFund')?.addEventListener('click', async () => {
    const code = $('fCode').value.trim();
    const f = (await getFundIndex()).find((x) => x[0] === code);
    if (!/^\d{6}$/.test(code)) return toast('请输入 6 位基金代码');
    const item = { code, name: f ? f[1] : code, buy_date: $('fDate').value || null };
    if ($('fShares').value) { item.shares = num($('fShares').value); item.cost_nav = num($('fCost').value); }
    else { item.amount = num($('fAmount').value); item.profit = num($('fProfit').value) ?? 0; }
    if (!item.shares && !item.amount) return toast('请填写持有金额或份额');
    st.h.funds.push(item); rerender();
  });
  $('addStock')?.addEventListener('click', () => {
    const code = $('sCode').value.trim();
    if (!/^\d{6}$/.test(code) || !$('sShares').value) return toast('请填写股票代码和股数');
    st.h.stocks.push({ code, name: $('sName').value.trim() || code, shares: num($('sShares').value),
      cost: num($('sCost').value), buy_date: $('sDate').value || null });
    rerender();
  });
  root.querySelectorAll('[data-del-fund]').forEach((b) => b.addEventListener('click', () => { st.h.funds.splice(+b.dataset.delFund, 1); rerender(); }));
  root.querySelectorAll('[data-del-stock]').forEach((b) => b.addEventListener('click', () => { st.h.stocks.splice(+b.dataset.delStock, 1); rerender(); }));
  $('ocrFile')?.addEventListener('change', async (e) => {
    const files = [...e.target.files];
    if (!files.length) return;
    const index = await getFundIndex();
    if (!index.length) return toast('基金列表加载失败，请稍后重试');
    st.draft = st.draft || [];
    $('ocrStatus').textContent = '正在加载识别组件（首次约 20MB，之后会缓存）…';
    try {
      const texts = await recognizeAll(files, (i, p) => { $('ocrStatus').textContent = `识别第 ${i + 1}/${files.length} 张：${p}%`; });
      texts.forEach((t) => st.draft.push(...parseHoldings(t, index)));
    } catch (err) { toast(err.message || '识别失败', 4000); }
    if (!st.draft.length) toast('没有识别到基金，请换一张更清晰的截图或手动添加');
    rerender();
  });
  root.querySelectorAll('[data-draft-code]').forEach((s) => s.addEventListener('change', () => {
    const d = st.draft[+s.dataset.draftCode]; d.code = s.value; d.name = d.candidates.find((c) => c.code === s.value)?.name || d.name;
  }));
  root.querySelectorAll('[data-draft-amount]').forEach((s) => s.addEventListener('input', () => { st.draft[+s.dataset.draftAmount].amount = num(s.value); }));
  root.querySelectorAll('[data-draft-profit]').forEach((s) => s.addEventListener('input', () => { st.draft[+s.dataset.draftProfit].profit = num(s.value); }));
  $('draftAdd')?.addEventListener('click', () => {
    const ok = st.draft.filter((d) => d.amount > 0);
    ok.forEach((d) => st.h.funds.push({ code: d.code, name: d.name, amount: d.amount, profit: d.profit ?? 0, buy_date: null }));
    toast(`已加入 ${ok.length} 只基金，买入日期未知的按持有满一年估算赎回费`);
    st.draft = null; rerender();
  });
  $('draftClear')?.addEventListener('click', () => { st.draft = null; rerender(); });
  $('saveH')?.addEventListener('click', async () => {
    syncInputs();
    if (!isDemo()) {
      // 保存前确认口令与 GitHub Secret 一致，否则云端无法解密持仓
      const ok = await verifyPw(getPw());
      if (ok === false) return toast('口令与 GitHub Secret ADVISOR_PASSPHRASE 不一致，未保存。请在「我的」退出后重新输入', 4500);
      if (ok === null) return toast('站点还没有生成口令校验文件，请先在 GitHub 运行一次 advisor 任务后再保存', 4500);
    }
    try {
      $('saveH').disabled = true;
      const res = await saveHoldings(st.h, st.sha);
      if (res.sha) st.sha = res.sha;
      toast(res.demo ? '已保存到本机（演示模式）' : '已加密保存，正在自动重新分析');
    } catch (err) { toast(err.message, 4000); } finally { $('saveH').disabled = false; }
  });
}
