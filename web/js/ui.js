// 通用工具：HTML 转义（所有外部数据必须经过 esc 再渲染）、格式化、简易 SVG 折线图
export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? esc(u) : '#');

export const pct = (v, n = 1) => (v == null || Number.isNaN(v) ? '-' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(n)}%`);
export const pp = (v, n = 2) => (v == null || Number.isNaN(v) ? '-' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(n)}%`);
export const money = (v) => (v == null ? '-' : Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 }));
export const cls = (v) => (v == null ? '' : v > 0 ? 'up' : v < 0 ? 'down' : '');
export const trendTxt = (t) => ({ 1: '多头', 0: '震荡', '-1': '空头' }[t] ?? '-');

export function toast(msg, ms = 2200) {
  const d = document.createElement('div');
  d.className = 'toast';
  d.textContent = msg;
  document.body.appendChild(d);
  setTimeout(() => d.remove(), ms);
}

/** series: [{name, color, points:[number|null]}]，labels: x 轴日期 */
export function lineChart(series, labels = []) {
  const W = 600, H = 160, P = 4;
  const all = series.flatMap((s) => s.points).filter((v) => v != null && !Number.isNaN(v));
  if (!all.length) return '<div class="muted small">暂无数据</div>';
  const min = Math.min(...all), max = Math.max(...all), span = max - min || 1;
  const n = Math.max(...series.map((s) => s.points.length));
  const x = (i) => P + (i / Math.max(1, n - 1)) * (W - 2 * P);
  const y = (v) => H - P - ((v - min) / span) * (H - 2 * P);
  const paths = series.map((s) => {
    let d = '';
    s.points.forEach((v, i) => { if (v != null && !Number.isNaN(v)) d += `${d ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`; });
    return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2"/>`;
  }).join('');
  const legend = series.map((s) => `<span class="tag" style="color:${s.color}">— ${esc(s.name)}</span>`).join('');
  const range = labels.length ? `<span class="muted small">${esc(labels[0])} ~ ${esc(labels[labels.length - 1])}</span>` : '';
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${paths}</svg><div class="row">${legend}${range}</div>`;
}

export function reasonsList(rs) {
  return `<ul class="reasons">${(rs || []).map((r) => `<li>${esc(r)}</li>`).join('')}</ul>`;
}
