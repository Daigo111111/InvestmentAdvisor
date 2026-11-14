import { esc, safeUrl, pct, pp, money, cls, trendTxt, lineChart, reasonsList } from './ui.js';

const act = (a) => `<span class="tag act-${esc(a)}">${esc(a)}</span>`;

export function home(rep) {
  const pf = rep.portfolio || {}, m = rep.market || {}, news = rep.news || {};
  const hist = pf.history || [];
  const funds = rep.funds || [], stocks = rep.stocks || [];
  const todo = [...funds.filter((f) => f.action !== '不动'), ...stocks.filter((s) => s.action !== '持有')];
  const curve = lineChart([{ name: '组合收益率', color: '#1f6feb', points: hist.map((p) => (p.cost ? p.value / p.cost - 1 : null)) }],
    hist.map((p) => p.date));
  return `
  <div class="card">
    <div class="row"><h3>组合总览</h3><span class="tag">市场：${esc(m.regime || '-')}</span></div>
    <div class="grid">
      <div class="kv"><span class="muted small">总资产</span><b>${money(pf.total)}</b></div>
      <div class="kv"><span class="muted small">累计收益</span><b class="${cls(pf.ret)}">${pct(pf.ret)}</b></div>
      <div class="kv"><span class="muted small">当前回撤</span><b class="${cls(pf.drawdown)}">${pct(pf.drawdown)}</b></div>
    </div>
    ${pf.realized ? `<div class="small" style="margin-top:6px">已实现收益 <b class="${cls(pf.realized)}">${money(pf.realized)}</b> 元 · 浮动盈亏 <b class="${cls(pf.pnl)}">${money(pf.pnl)}</b> 元 · 合计 <b class="${cls(pf.total_pnl)}">${money(pf.total_pnl)}</b> 元</div>` : ''}
    <div class="muted small" style="margin-top:6px">基金 ${money(pf.funds)} · 股票 ${money(pf.stocks)} · 现金 ${money(pf.cash)} ·
      回撤上限 ${pct(-(rep.meta?.risk?.max_drawdown ?? 0.2), 0)}</div>
    ${hist.length > 1 ? curve : ''}
  </div>
  <div class="card">
    <h3>今日待办 <span class="muted small">${todo.length ? '' : '（暂无需要操作的持仓）'}</span></h3>
    ${todo.map((t) => `<div class="item"><div class="row"><b>${esc(t.name)}</b>${act(t.action)}</div>
      <div class="small">${t.ratio ? `比例 ${Math.round(t.ratio * 100)}% · ` : ''}约 ${money(t.amount)} 元 · ${esc(t.reasons?.[0])}</div></div>`).join('')}
  </div>
  <div class="card news">
    <h3>要闻与情绪</h3>
    ${(news.hot_boards || []).length ? `<div class="small" style="margin-bottom:6px">热度板块：${news.hot_boards.slice(0, 8).map((b) => `<span class="tag">${esc(b.board)} ${b.score > 0 ? '+' : ''}${Number(b.score).toFixed(0)}</span>`).join('')}</div>` : ''}
    ${(news.watch || []).map((w) => `<div class="small">【持仓相关】${esc(w.name)}：${esc(w.title)}</div>`).join('')}
    ${(news.items || []).slice(0, 15).map((n) => `<div class="item small"><a href="${safeUrl(n.url)}" target="_blank" rel="noopener">
      <span class="${cls(n.score)}">${n.score > 0 ? '利好' : n.score < 0 ? '利空' : '中性'}</span> ${esc(n.title)}</a>
      <div class="muted">${esc(n.source)} ${esc(n.time)} ${(n.boards || []).map((b) => `<span class="tag">${esc(b)}</span>`).join('')}</div></div>`).join('')}
  </div>`;
}

export function funds(rep) {
  const list = rep.funds || [];
  if (!list.length) return '<div class="card">还没有基金持仓，去「我的 → 持仓管理」添加。</div>';
  return `<div class="card small muted">交易规则：交易日 15:00 前申购/赎回按当日净值确认，15:00 后按下一交易日净值；一般 T+1 确认份额，
    QDII 多为 T+2。持有不满 7 天赎回通常收取 1.5% 惩罚性费用。</div>` + list.map((f) => {
    const m = f.metrics || {}, bt = f.backtest;
    return `<div class="card">
      <div class="row"><div><b>${esc(f.name)}</b> <span class="muted small">${esc(f.code)} · ${esc(f.type)}</span></div>${act(f.action)}</div>
      <div class="grid" style="margin-top:8px">
        <div class="kv"><span class="muted small">今日估算</span><b class="${cls(m.est_pct)}">${pp(m.est_pct)}</b></div>
        <div class="kv"><span class="muted small">持有收益</span><b class="${cls(m.ret_hold)}">${pct(m.ret_hold)}</b></div>
        <div class="kv"><span class="muted small">持有市值</span><b>${money(m.value)}</b></div>
      </div>
      ${f.action !== '不动' ? `<div style="margin-top:6px"><b>建议：${esc(f.action)} ${Math.round((f.ratio || 0) * 100)}%</b>（约 ${money(f.amount)} 元${f.fee ? `，赎回费约 ${money(f.fee.fee)} 元` : ''}）</div>` : ''}
      ${reasonsList(f.reasons)}
      ${m.n_trades ? `<div class="small muted">已记录 ${esc(m.n_trades)} 笔交易${m.realized ? ` · 已实现收益 ${money(m.realized)} 元` : ''}${m.pending ? ' · 有买入尚未按净值确认，份额暂按最新净值估算' : ''}</div>` : ''}
      <div class="small muted" style="margin-top:6px">估值来源：${esc(m.est_source || '无')}${m.coverage ? `（重仓覆盖 ${Math.round(m.coverage * 100)}%）` : ''}${m.est_note ? `，${esc(m.est_note)}` : ''}
        ${m.est_own != null && m.est_source === '东财估值' ? ` · 重仓股估算 ${pp(m.est_own)}` : ''}
        ${m.est_pct_em != null ? ` · 东财估值 ${pp(m.est_pct_em)}` : ''} · 最新净值 ${esc(m.last_nav)}（${esc(m.nav_date)}）
        · 趋势 ${trendTxt(m.trend)} · RSI ${esc(m.rsi ?? '-')} · 板块 ${esc(m.sector || '-')} 强度 ${m.sector_pct != null ? Math.round(m.sector_pct * 100) + '%' : '-'}
        · 同类近3月排名 ${m.rank_pct != null ? '前' + Math.round((1 - m.rank_pct) * 100) + '%' : '-'}</div>
      <details><summary>净值走势与重仓股（${esc(m.quarter || '')}）</summary>
        ${lineChart([{ name: '累计净值', color: '#1f6feb', points: (f.nav_curve || []).map((p) => p.v) }], (f.nav_curve || []).map((p) => p.d))}
        <table><tr><th>重仓股</th><th>占比</th><th>今日</th><th>贡献</th></tr>
        ${(f.top_holdings || []).map((h) => `<tr><td>${esc(h.name)}</td><td>${esc(h.weight)}%</td><td class="${cls(h.pct)}">${pp(h.pct)}</td><td>${esc(h.contrib)}</td></tr>`).join('')}</table>
      </details>
      ${bt && bt.strategy && bt.hold ? `<details><summary>规则回测（近3年）</summary><table>
        <tr><th></th><th>年化</th><th>最大回撤</th><th>夏普</th></tr>
        <tr><td>按建议规则操作</td><td>${pct(bt.strategy.cagr)}</td><td>${pct(bt.strategy.mdd)}</td><td>${esc(bt.strategy.sharpe)}</td></tr>
        <tr><td>一直持有</td><td>${pct(bt.hold.cagr)}</td><td>${pct(bt.hold.mdd)}</td><td>${esc(bt.hold.sharpe)}</td></tr></table>
        <div class="muted small">交易 ${esc(bt.trades)} 次，自 ${esc(bt.start)}，未计申赎费</div></details>` : ''}
    </div>`;
  }).join('') + switchCard(rep);
}

export function switchCard(rep) {
  const plans = rep.switch || [];
  if (!plans.length) return '';
  return `<div class="card"><h3>换基建议（强势板块候选）</h3>
    <div class="muted small">只在持有基金趋势转弱、同类排名靠后时建议换；换基前请计算赎回费和申购费。</div>
    ${plans.map((p) => `<div class="item"><b>${esc(p.board)}</b> <span class="muted small">${esc(p.why)}</span>
      <table><tr><th>基金</th><th>近3月</th><th>近1年</th><th>近1年回撤</th></tr>
      ${(p.funds || []).map((f) => `<tr><td>${esc(f.name)}<div class="muted small">${esc(f.code)}</div></td><td class="${cls(f.r3m)}">${pp(f.r3m)}</td>
        <td class="${cls(f.r1y)}">${pp(f.r1y)}</td><td>${pct(f.mdd_1y)}</td></tr>`).join('')}</table></div>`).join('')}</div>`;
}

function closedCard(rep) {
  const c = rep.closed || [];
  if (!c.length) return '';
  return `<div class="card"><h3>已清仓</h3><table><tr><th>名称</th><th>类型</th><th>已实现收益</th></tr>
    ${c.map((x) => `<tr><td>${esc(x.name)}<div class="muted small">${esc(x.code)}</div></td><td>${x.asset === 'fund' ? '基金' : '股票'}</td>
      <td class="${cls(x.realized)}">${money(x.realized)} 元</td></tr>`).join('')}</table></div>`;
}

export function stocks(rep) {
  const list = rep.stocks || [];
  if (!list.length) return '<div class="card">还没有股票持仓，去「我的 → 持仓管理」添加。专区推荐见「专区」页。</div>' + closedCard(rep);
  return closedCardAfter(list, rep);
}

function closedCardAfter(list, rep) {
  return list.map((s) => {
    const m = s.metrics || {};
    return `<div class="card">
      <div class="row"><div><b>${esc(s.name)}</b> <span class="muted small">${esc(s.code)} · ${esc(m.board || '')}</span></div>${act(s.action)}</div>
      <div class="grid" style="margin-top:8px">
        <div class="kv"><span class="muted small">现价</span><b>${esc(m.price)}</b></div>
        <div class="kv"><span class="muted small">浮盈</span><b class="${cls(m.ret_hold)}">${pct(m.ret_hold)}</b></div>
        <div class="kv"><span class="muted small">止损位</span><b>${esc(m.stop)}</b></div>
      </div>
      ${s.shares ? `<div style="margin-top:6px"><b>建议：${esc(s.action)} ${esc(s.shares)} 股</b>（约 ${money(s.amount)} 元）</div>` : ''}
      ${reasonsList(s.reasons)}
      ${m.n_trades ? `<div class="small muted">已记录 ${esc(m.n_trades)} 笔交易${m.realized ? ` · 已实现收益 ${money(m.realized)} 元` : ''}</div>` : ''}
      <div class="small muted">仓位 ${pct(m.weight)} · 趋势 ${trendTxt(m.trend)} · RSI ${esc(m.rsi ?? '-')} · ATR ${esc(m.atr)} · 新闻情绪 ${esc(m.news_score)}</div>
      ${(s.news || []).length ? `<details><summary>相关新闻</summary>${s.news.map((n) => `<div class="small item"><a href="${safeUrl(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a>
        <span class="${cls(n.score)}">${n.score > 0 ? '+' : ''}${esc(n.score)}</span></div>`).join('')}</details>` : ''}
    </div>`;
  }).join('') + closedCard(rep);
}
