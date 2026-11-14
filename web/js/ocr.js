// 持仓截图识别：浏览器端 Tesseract.js OCR（免费、图片不上传服务器）+ 基金名称模糊匹配。
// 识别结果只作为草稿，必须由用户逐条核对后保存。后续可替换为多模态大模型（引擎 llm.py 已预留 ocr_parse）。
const TESSERACT_URL = 'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js';
const TESSERACT_SRI = 'sha384-GJqSu7vueQ9qN0E9yLPb3Wtpd7OrgK8KmYzC8T1IysG1bcvxvIO4qtYR/D3A991F';
let fundIndex = null;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src; s.integrity = TESSERACT_SRI; s.crossOrigin = 'anonymous'; s.onload = resolve; s.onerror = () => reject(new Error('OCR 组件加载失败，请检查网络'));
    document.head.appendChild(s);
  });
}

export async function getFundIndex() {
  if (!fundIndex) {
    const r = await fetch('data/funds_index.json');
    if (!r.ok) return [];  // 失败不缓存，下次重试
    fundIndex = await r.json();
  }
  return fundIndex;
}

/** 多张图片共用一个识别 worker，结束后释放（iOS 内存有限） */
export async function recognizeAll(files, onProgress) {
  if (!window.Tesseract) await loadScript(TESSERACT_URL);
  let idx = 0;
  const worker = await window.Tesseract.createWorker('chi_sim+eng', 1, {
    logger: (m) => onProgress && m.status === 'recognizing text' && onProgress(idx, Math.round(m.progress * 100)),
  });
  const texts = [];
  try {
    for (idx = 0; idx < files.length; idx++) texts.push((await worker.recognize(files[idx])).data.text || '');
  } finally {
    await worker.terminate();
  }
  return texts;
}

const norm = (s) => s.replace(/[\s（）()·\-—_]/g, '').replace(/[ＡＣ]/g, (c) => ({ 'Ａ': 'A', 'Ｃ': 'C' }[c]));
function bigrams(s) {
  const out = new Set();
  for (let i = 0; i < s.length - 1; i++) out.add(s.slice(i, i + 2));
  return out;
}
function dice(a, b) {
  if (!a.size || !b.size) return 0;
  let n = 0;
  a.forEach((g) => { if (b.has(g)) n++; });
  return (2 * n) / (a.size + b.size);
}

/** 在基金列表中找最相似的名称，返回前 3 个候选 */
export function matchFund(text, index) {
  const t = norm(text);
  const code = (t.match(/(?:^|\D)(\d{6})(?:\D|$)/) || [])[1];
  if (code) {
    const hit = index.find((f) => f[0] === code);
    if (hit) return [{ code: hit[0], name: hit[1], score: 1 }];
  }
  const tg = bigrams(t);
  const scored = [];
  for (const f of index) {
    const s = dice(tg, bigrams(norm(f[1])));
    if (s >= 0.5) scored.push({ code: f[0], name: f[1], score: s });
  }
  return scored.sort((a, b) => b.score - a.score).slice(0, 3);
}

const NUM = /[-+]?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|[-+]?\d+\.\d{1,2}/g;
const toNum = (s) => parseFloat(s.replace(/,/g, ''));

/** 把 OCR 文本解析为持仓草稿：基金名称行 + 其后数字（金额、收益） */
export function parseHoldings(text, index) {
  const lines = text.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  const out = [];
  let cur = null;
  for (const line of lines) {
    const chinese = (line.match(/[\u4e00-\u9fa5]/g) || []).length;
    const isLabel = /金额|收益|收益率|昨日|持有|市值|份额|净值/.test(line) && chinese <= 8;
    if (chinese >= 4 && !isLabel) {
      const cands = matchFund(line, index);
      if (cands.length) {
        cur = { raw: line, candidates: cands, code: cands[0].code, name: cands[0].name, amount: null, profit: null, nums: [] };
        out.push(cur);
        continue;
      }
    }
    if (!cur) continue;
    const nums = (line.match(NUM) || []).map(toNum);
    if (/持有收益|累计收益/.test(line) && nums.length) cur.profit = nums[nums.length - 1];
    else if (/金额|市值|资产/.test(line) && nums.length) cur.amount = nums[0];
    cur.nums.push(...nums);
  }
  for (const f of out) {
    if (f.amount == null && f.nums.length) f.amount = Math.max(...f.nums.map(Math.abs));
    if (f.profit == null && f.nums.length > 1) {
      const rest = f.nums.filter((n) => Math.abs(n) !== f.amount && Math.abs(n) < f.amount);
      f.profit = rest.length ? rest[rest.length - 1] : null;
    }
    delete f.nums;
  }
  return out;
}
