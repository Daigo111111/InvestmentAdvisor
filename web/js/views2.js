import { esc, pct, pp, cls, trendTxt, lineChart } from './ui.js';

const ZONE_DESC = {
  dividend: '股息率 ≥3.5%、长期稳定分红、ROE ≥8%、波动低，适合做底仓',
  value: '大市值、ROE ≥12%、PE ≤25、经营现金流为正的龙头',
  tech: '科技板块中营收和利润双增长、估值与增速匹配（PEG）的公司',
  consumer: '消费医药中 ROE 高、毛利率高、估值合理的公司',
  cyclical: '周期资源中盈利改善、PB 偏低的公司，波动较大，仓位宜小',
  catalyst: '近期正面新闻集中且基本面不差的个股，偏短线，注意追高风险',
};

export function zones(rep, state) {
  const zs = rep.zones || {};
  const names = rep.zone_names || {};
  const keys = Object.keys(zs);
  if (!keys.length) return '<div class="card">专区数据将在晚间复盘任务后生成。</div>';
  const cur = state.zone && zs[state.zone] ? state.zone : keys[0];
  const alloc = rep.allocation?.target || {};
  const picks = zs[cur] || [];
  return `<div class="card"><div class="seg">${keys.map((k) => `<button data-zone="${esc(k)}" class="${k === cur ? 'on' : ''}">${esc(names[k] || k)}</button>`).join('')}</div>
    <div class="small muted">${esc(ZONE_DESC[cur] || '')}${alloc[cur] != null ? ` · 建议占总资产 <b>${pct(alloc[cur], 0)}</b>` : ''}
    · 财报期 ${esc(rep.universe_period || '-')}</div></div>
    ${picks.map((p, i) => `<div class="card">
      <div class="row"><div><b>${i + 1}. ${esc(p.name)}</b> <span class="muted small">${esc(p.code)} · ${esc(p.board)}</span></div><span class="tag">评分 ${esc(p.score)}</span></div>
      <div class="grid" style="margin-top:8px">
        <div class="kv"><span class="muted small">现价</span><b>${esc(p.price)}</b></div>
        <div class="kv"><span class="muted small">${cur === 'dividend' ? '股息率' : 'ROE(年化)'}</span><b>${cur === 'dividend' ? pct(p.div_yield) : esc(p.roe) + '%'}</b></div>
        <div class="kv"><span class="muted small">PE / PB</span><b>${esc(p.pe)} / ${esc(p.pb)}</b></div>
      </div>
      <ul class="reasons">${(p.reasons || []).map((r) => `<li>${esc(r)}</li>`).join('')}</ul>
      <div class="small"><b>操作</b>：${esc(p.entry)}，参考止损 ${esc(p.stop ?? '-')}（2.5×ATR），单只不超过总资产 10%</div>
      <div class="small muted">趋势 ${trendTxt(p.trend)} · 近60日 ${pct(p.r60)} · 年化波动 ${pct(p.vol, 0)} · 近1年最大回撤 ${pct(p.mdd_1y)} · 市值 ${esc(p.mv_yi)}亿</div>
    </div>`).join('')}`;
}

function bar(cur, target) {
  const c = Math.min(100, (cur || 0) * 100), t = Math.min(100, (target || 0) * 100);
  return `<div class="bar"><i style="left:0;width:${c.toFixed(1)}%"></i><em style="left:${t.toFixed(1)}%"></em></div>`;
}

export function plan(rep) {
  const a = rep.allocation || {}, bt = rep.backtest?.allocation, rot = rep.rotation || {};
  const risk = rep.meta?.risk || {};
  let html = `<div class="card"><h3>资产配置</h3>
    <div class="small">${esc(a.note || '')}。当前权益目标 <b>${pct(a.equity_target, 0)}</b>。</div>
    ${(a.rebalance || []).map((x) => `<div class="item"><div class="row"><span>${esc(x.name)}</span>
      <span class="small">${pct(x.current, 0)} → ${pct(x.target, 0)} <span class="tag act-${esc(x.action)}">${esc(x.action)}${x.action !== '保持' ? ' ' + Math.abs(x.amount).toLocaleString() + '元' : ''}</span></span></div>
      ${bar(x.current, x.target)}</div>`).join('')}
    <div class="muted small">蓝条为当前占比，橙线为目标占比；偏离超过 5% 才建议调整。</div></div>`;
  if (bt && bt.strategy && bt.hs300 && bt.mix6040) {
    const s = bt.strategy, h = bt.hs300, m = bt.mix6040;
    const row = (n, x) => `<tr><td>${n}</td><td class="${cls(x.cagr)}">${pct(x.cagr)}</td><td>${pct(x.mdd)}</td><td>${esc(x.sharpe)}</td>
      <td>${Math.round((x.hit_min || 0) * 100)}%</td><td>${Math.round((x.hit_target || 0) * 100)}%</td></tr>`;
    const years = Object.entries(s.years || {});
    html += `<div class="card"><h3>策略回测 <span class="muted small">${esc(bt.start)} ~ ${esc(bt.end)}</span></h3>
      <div class="small muted">${esc(bt.name)}</div>
      ${lineChart([{ name: '本策略', color: '#1f6feb', points: (bt.curve || []).map((p) => p.s) },
        { name: '沪深300全收益', color: '#e5383b', points: (bt.curve || []).map((p) => p.b) }], (bt.curve || []).map((p) => p.d))}
      <table><tr><th></th><th>年化</th><th>最大回撤</th><th>夏普</th><th>年收益≥${pct(risk.min_return, 0)}</th><th>≥${pct(risk.target_return, 0)}</th></tr>
      ${row('本策略', s)}${row('沪深300', h)}${row('60/40股债', m)}</table>
      <h4>逐年收益</h4><div class="small">${years.map(([y, v]) => `<span class="tag ${cls(v)}">${esc(y)} ${pct(v)}</span>`).join('')}</div>
      <div class="muted small" style="margin-top:6px">${esc(bt.note)}</div></div>`;
  }
  if ((rot.top || []).length) {
    const t = (list) => `<table><tr><th>板块</th><th>强度</th><th>近20日</th><th>近60日</th><th>趋势</th></tr>
      ${list.map((b) => `<tr><td>${esc(b.board)}${b.overheat ? ' <span class="tag act-减仓">过热</span>' : ''}</td><td>${esc(b.score)}</td>
        <td class="${cls(b.r20)}">${pct(b.r20)}</td><td class="${cls(b.r60)}">${pct(b.r60)}</td><td>${trendTxt(b.trend)}</td></tr>`).join('')}</table>`;
    html += `<div class="card"><h3>板块轮动</h3><div class="small muted">综合动量、趋势、资金流向和新闻热度打分（同花顺行业）</div>
      <h4>强势</h4>${t(rot.top)}<h4>弱势</h4>${t(rot.bottom)}</div>`;
  }
  const chk = rep.est_check || [];
  if (chk.length) {
    html += `<div class="card"><h3>估值误差检查</h3><table><tr><th>基金</th><th>14:10估算</th><th>实际</th><th>误差</th></tr>
      ${chk.map((c) => `<tr><td>${esc(c.name)}</td><td>${pp(c.est)}</td><td>${pp(c.actual)}</td><td>${pp(c.error)}</td></tr>`).join('')}</table></div>`;
  }
  return html;
}
