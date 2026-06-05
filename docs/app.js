/* Token Burn dashboard — client-side render from data/stats.json.
   Tabs Claude<->Codex, window All/30d/7d, Overview/Models, subagent toggle.
   All windowed metrics recompute from daily[] (Σdaily == overview, verified). */
'use strict';

const GATSBY = 62000;
const state = { tool: 'claude', window: 'all', view: 'overview', subagents: false };
let DATA = null;

const $ = (s, r = document) => r.querySelector(s);
const el = (tag, cls, html) => { const n = document.createElement(tag); if (cls) n.className = cls; if (html != null) n.innerHTML = html; return n; };
// model names come from local log content — escape them before they hit innerHTML
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ---- formatting -------------------------------------------------------- */
function humanTokens(n) {
  n = +n;
  for (const [d, s] of [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']]) if (Math.abs(n) >= d) return (n / d).toFixed(1) + s;
  return String(Math.round(n));
}
const intc = n => (+n).toLocaleString('en-US');
function prettyModel(name) {
  if (!name) return '—';
  if (name.startsWith('claude-')) {
    const p = name.slice(7).split('-');
    const fam = p[0][0].toUpperCase() + p[0].slice(1);
    const nums = p.slice(1).filter(x => /^\d+$/.test(x)).slice(0, 2).join('.');
    return (fam + ' ' + nums).trim();
  }
  if (name.startsWith('gpt-')) return 'GPT-' + name.slice(4);
  return name;
}
const hourLabel = h => h == null ? '—' : String(h).padStart(2, '0') + ':00';

/* ---- date helpers (treat YYYY-MM-DD as UTC calendar days) -------------- */
const parseDay = s => new Date(s + 'T00:00:00Z');
const addDays = (d, n) => new Date(d.getTime() + n * 86400000);
const dayDiff = (a, b) => Math.round((parseDay(a) - parseDay(b)) / 86400000);
const iso = d => d.toISOString().slice(0, 10);
function fmtDate(s, withDow) {
  const d = parseDay(s);
  const mon = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getUTCMonth()];
  const dow = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][d.getUTCDay()];
  return (withDow ? dow + ' ' : '') + mon + ' ' + d.getUTCDate();
}

/* ---- windowing --------------------------------------------------------- */
function windowedDaily(tool) {
  const daily = DATA[tool].daily;
  if (!daily.length || state.window === 'all') return daily;
  const anchor = daily[daily.length - 1].date;
  const span = state.window === '7d' ? 7 : 30;
  const cutoff = addDays(parseDay(anchor), -(span - 1));
  return daily.filter(d => parseDay(d.date) >= cutoff);
}

function computeStreaks(dates, anchor) {
  if (!dates.length) return { cur: 0, longest: 0 };
  const set = new Set(dates);
  const sorted = [...dates].sort();
  let longest = 1, run = 1;
  for (let i = 1; i < sorted.length; i++) {
    run = dayDiff(sorted[i], sorted[i - 1]) === 1 ? run + 1 : 1;
    longest = Math.max(longest, run);
  }
  let cur = 0, d = parseDay(anchor);
  while (set.has(iso(d))) { cur++; d = addDays(d, -1); }
  return { cur, longest };
}

function computeMetrics(tool) {
  const wd = windowedDaily(tool), ov = DATA[tool].overview;
  const m = { tokens: 0, msgs: 0, sess: 0, subTok: 0, subMsg: 0, subSess: 0, byModel: {} };
  for (const d of wd) {
    m.tokens += d.tokens; m.msgs += d.messages; m.sess += d.sessions;
    m.subTok += d.subTokens || 0; m.subMsg += d.subMessages || 0; m.subSess += d.subSessions || 0;
    for (const k in d.byModel) m.byModel[k] = (m.byModel[k] || 0) + d.byModel[k];
  }
  let fav = null, favV = -1;
  for (const k in m.byModel) if (m.byModel[k] > favV) { favV = m.byModel[k]; fav = k; }
  const allWindow = state.window === 'all';
  const streaks = allWindow
    ? { cur: ov.currentStreak, longest: ov.longestStreak }
    : computeStreaks(wd.map(d => d.date), wd.length ? wd[wd.length - 1].date : iso(new Date()));
  const hasSub = tool === 'claude' && !!DATA.claude.subagents;
  const showSub = hasSub && state.subagents;
  return {
    wd, ov, hasSub, showSub,
    tokens: m.tokens,
    sessions: m.sess + (showSub ? m.subSess : 0),
    messages: m.msgs + (showSub ? m.subMsg : 0),
    activeDays: wd.length,
    cur: streaks.cur, longest: streaks.longest,
    peakHour: ov.peakHour,
    favorite: fav,
    subTok: m.subTok, subSess: m.subSess, subMsg: m.subMsg,
    first: wd.length ? wd[0].date : ov.firstSessionDate.slice(0, 10),
    last: wd.length ? wd[wd.length - 1].date : ov.lastSessionDate.slice(0, 10),
  };
}

/* ---- tiles ------------------------------------------------------------- */
function renderTiles(M) {
  const gatsby = (M.tokens / GATSBY).toLocaleString('en-US', { maximumFractionDigits: 0 });
  const subCap = M.hasSub && M.subTok
    ? `incl. ${humanTokens(M.subTok)} subagent (${(100 * M.subTok / M.tokens).toFixed(0)}%)` : '';
  const tiles = [
    { k: 'Total tokens', v: humanTokens(M.tokens), accent: true, x: `≈ ${gatsby} × The Great Gatsby`, x2: subCap },
    { k: 'Sessions', v: intc(M.sessions), x: M.showSub ? 'main + subagents' : '' },
    { k: 'Messages', v: intc(M.messages), x: M.showSub ? 'main + subagents' : '' },
    { k: 'Active days', v: intc(M.activeDays) },
    { k: 'Current streak', v: M.cur + ' <small>days</small>' },
    { k: 'Longest streak', v: M.longest + ' <small>days</small>' },
    { k: 'Peak hour', v: hourLabel(M.peakHour), x: 'all-time' },
    { k: 'Top model', v: esc(prettyModel(M.favorite)), x: esc(M.favorite || '') },
  ];
  const root = $('#tiles'); root.innerHTML = '';
  for (const t of tiles) {
    const n = el('div', 'tile' + (t.accent ? ' accent' : ''));
    n.appendChild(el('div', 'v', t.v));
    n.appendChild(el('div', 'k', t.k));
    if (t.x) n.appendChild(el('div', 'x', t.x));
    if (t.x2) n.appendChild(el('div', 'x', t.x2));
    root.appendChild(n);
  }
}

/* ---- heatmap ----------------------------------------------------------- */
function quartiles(values) {
  const nz = values.filter(v => v > 0).sort((a, b) => a - b);
  if (!nz.length) return () => 0;
  const q = [0.25, 0.5, 0.75].map(p => nz[Math.min(nz.length - 1, Math.floor(nz.length * p))]);
  return v => v <= 0 ? 0 : v <= q[0] ? 1 : v <= q[1] ? 2 : v <= q[2] ? 3 : 4;
}

function renderHeatmap(M) {
  const root = $('#heatmap'); root.innerHTML = '';
  const wd = M.wd;
  if (!wd.length) return;
  const byDate = {}; for (const d of wd) byDate[d.date] = d;
  const first = wd[0].date, last = wd[wd.length - 1].date;
  const firstSun = addDays(parseDay(first), -parseDay(first).getUTCDay());
  const nWeeks = Math.floor(dayDiff(last, iso(firstSun)) / 7) + 1;
  const level = quartiles(wd.map(d => d.tokens));
  $('#heatmap-sub').textContent = `${humanTokens(M.tokens)} tokens · ${M.activeDays} active days`;

  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  // Month labels: one per month present, at that month's first column. Drop a
  // partial leading month only if it would crowd the next label; keep a 2-column
  // min gap so labels never overlap. (Handles short ranges like the 6-week Claude
  // span, where the old "column starts in days 1-7" rule labelled only May.)
  const monthStarts = [];
  for (let w = 0, seen = -1; w < nWeeks; w++) {
    const m = addDays(firstSun, w * 7).getUTCMonth();
    if (m !== seen) { monthStarts.push([w, m]); seen = m; }
  }
  const labelAt = {};
  for (let i = 0, lastPlaced = -99; i < monthStarts.length; i++) {
    const [w, m] = monthStarts[i];
    const nxt = i + 1 < monthStarts.length ? monthStarts[i + 1][0] : nWeeks;
    if (w === 0 && nxt < 2) continue;     // partial leading month crowds the next
    if (w - lastPlaced < 2) continue;     // too close to the previous label
    labelAt[w] = MONTHS[m];
    lastPlaced = w;
  }
  for (let w = 0; w < nWeeks; w++) {
    root.appendChild(el('div', 'mlabel', labelAt[w] || ''));
    for (let row = 0; row < 7; row++) {
      const day = addDays(firstSun, w * 7 + row), ds = iso(day);
      const cell = el('div', 'cell');
      if (dayDiff(ds, first) < 0 || dayDiff(ds, last) > 0) { cell.style.background = 'transparent'; root.appendChild(cell); continue; }
      const d = byDate[ds];
      const tok = d ? d.tokens : 0;
      cell.classList.add('lvl-' + level(tok));
      if (M.showSub && d && d.subTokens) cell.classList.add('sub');
      cell.dataset.tip = d
        ? `<b>${fmtDate(ds, true)}</b><br>${intc(tok)} tokens · ${intc(d.sessions)} sess · ${intc(d.messages)} msg`
          + (d.subTokens ? `<br>${humanTokens(d.subTokens)} from subagents` : '')
        : `<b>${fmtDate(ds, true)}</b><br>no activity`;
      root.appendChild(cell);
    }
  }
  // legend
  const lg = $('#legend'); lg.innerHTML = 'Less';
  for (let i = 0; i <= 4; i++) lg.appendChild(el('span', 'cell' + (i ? ' lvl-' + i : '')));
  lg.appendChild(document.createTextNode('More'));
}

/* ---- active hours ------------------------------------------------------ */
function renderHours(tool) {
  const root = $('#hours'); root.innerHTML = '';
  const hc = DATA[tool].hourCounts || {};
  const counts = Array.from({ length: 24 }, (_, h) => hc[h] || 0);
  const max = Math.max(1, ...counts);
  const peak = DATA[tool].overview.peakHour;
  counts.forEach((c, h) => {
    const b = el('div', 'hb' + (h === peak ? ' peak' : ''));
    b.style.height = Math.max(2, (c / max) * 100) + '%';
    b.dataset.tip = `<b>${hourLabel(h)}</b><br>${intc(c)} sessions started`;
    root.appendChild(b);
  });
}

/* ---- tokens per day ---------------------------------------------------- */
function renderBars(M) {
  const root = $('#barchart'); root.innerHTML = '';
  const wd = M.wd;
  if (!wd.length) { $('#bars-sub').textContent = ''; return; }
  const max = Math.max(...wd.map(d => d.tokens));
  const peak = wd.reduce((a, d) => d.tokens > a.tokens ? d : a, wd[0]);
  $('#bars-sub').textContent = `${wd.length} days · peak ${humanTokens(peak.tokens)} (${fmtDate(peak.date)})`;
  const scale = t => max > 0 ? Math.sqrt(t) / Math.sqrt(max) * 100 : 0;
  for (const d of wd) {
    const bar = el('div', 'bar');
    bar.style.height = Math.max(1, scale(d.tokens)) + '%';
    if (M.showSub && d.subTokens) {
      const seg = el('span', 'subseg');
      seg.style.height = (100 * d.subTokens / d.tokens) + '%';
      bar.appendChild(seg);
    }
    bar.dataset.tip = `<b>${fmtDate(d.date, true)}</b><br>${intc(d.tokens)} tokens`
      + (d.subTokens ? `<br>${humanTokens(d.subTokens)} subagents` : '');
    root.appendChild(bar);
  }
}

/* ---- models ------------------------------------------------------------ */
function modelRow(name, v, maxV, total, detail) {
  const row = el('div', 'model-row');
  row.appendChild(el('div', 'name', `${esc(prettyModel(name))}<small>${esc(name)}</small>`));
  const track = el('div', 'track');
  if (detail) {
    const io = detail.in + detail.out || 1;
    const segIn = el('div', 'seg-in'); segIn.style.width = (100 * detail.in / io) + '%';
    const segOut = el('div', 'seg-out'); segOut.style.width = (100 * detail.out / io) + '%';
    track.style.width = Math.max(6, 100 * v / maxV) + '%';
    track.append(segIn, segOut);
    track.dataset.tip = `<b>${esc(prettyModel(name))}</b><br>↓ in ${humanTokens(detail.in)} · ↑ out ${humanTokens(detail.out)}<br>cache read ${humanTokens(detail.cacheRead)}`;
  } else {
    const bar = el('div', 'seg-bar'); bar.style.width = '100%';
    track.style.width = Math.max(6, 100 * v / maxV) + '%';
    track.appendChild(bar);
  }
  row.appendChild(track);
  const pct = total > 0 ? (100 * v / total).toFixed(1) : '0';
  row.appendChild(el('div', 'vals', `${humanTokens(v)}<small>${pct}% of tokens</small>`));
  return row;
}

function renderModels(tool, M) {
  const root = $('#model-list'); root.innerHTML = '';
  const allWindow = state.window === 'all';
  const detailByModel = {};
  for (const m of DATA[tool].models) detailByModel[m.model] = m;
  const entries = Object.entries(M.wd.reduce((acc, d) => {
    for (const k in d.byModel) acc[k] = (acc[k] || 0) + d.byModel[k];
    return acc;
  }, {})).sort((a, b) => b[1] - a[1]);
  const sub = $('#models-sub');
  if (allWindow) // static content (no user data) -> innerHTML is safe here
    sub.innerHTML = 'by tokens (input+output) · all-time · '
      + '<span class="io-key"><i class="sw-in"></i>in<i class="sw-out"></i>out</span>';
  else sub.textContent = `by tokens (input+output) · ${windowLabel()}`;
  if (!entries.length) { root.appendChild(el('p', 'panel-sub', 'No model usage in this window.')); return; }
  const total = entries.reduce((s, [, v]) => s + v, 0);
  const maxV = entries[0][1];
  for (const [name, v] of entries) {
    root.appendChild(modelRow(name, v, maxV, total, allWindow ? detailByModel[name] : null));
  }
  // subagent models (Claude, all-time only — no per-day subagent byModel)
  if (M.showSub && allWindow && DATA[tool].subagents) {
    const sub = DATA[tool].subagents;
    root.appendChild(el('div', 'model-group-label', `Subagents · ${humanTokens(sub.totalTokens)} tokens`));
    const sTotal = sub.models.reduce((s, m) => s + m.total, 0);
    const sMax = Math.max(...sub.models.map(m => m.total));
    for (const m of [...sub.models].sort((a, b) => b.total - a.total)) {
      root.appendChild(modelRow(m.model, m.total, sMax, sTotal, m));
    }
  }
}

const windowLabel = () => ({ all: 'all-time', '30d': 'last 30 days', '7d': 'last 7 days' }[state.window]);

/* ---- top-level render -------------------------------------------------- */
function render() {
  const tool = state.tool;
  // subagent toggle only applies to Claude
  const toggle = $('#sub-toggle');
  if (tool === 'codex') { toggle.hidden = true; state.subagents = false; $('#sub-check').checked = false; }
  else toggle.hidden = false;

  const M = computeMetrics(tool);
  $('#view-overview').hidden = state.view !== 'overview';
  $('#view-models').hidden = state.view !== 'models';

  if (state.view === 'overview') {
    renderTiles(M);
    renderHeatmap(M);
    renderHours(tool);
    renderBars(M);
  } else {
    renderModels(tool, M);
  }
  $('#foot-range').textContent =
    `${prettyTool(tool)}: ${fmtDate(DATA[tool].overview.firstSessionDate.slice(0,10))} `
    + `${parseDay(DATA[tool].overview.firstSessionDate.slice(0,10)).getUTCFullYear()} → `
    + `${fmtDate(DATA[tool].overview.lastSessionDate.slice(0,10))} · ${windowLabel()}`;
}
const prettyTool = t => t === 'claude' ? 'Claude Code' : 'Codex';

/* ---- controls ---------------------------------------------------------- */
function wireSegments() {
  document.querySelectorAll('.seg').forEach(seg => {
    seg.addEventListener('click', e => {
      const btn = e.target.closest('button'); if (!btn) return;
      state[seg.dataset.state] = btn.dataset.value;
      seg.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === btn));
      render();
    });
  });
  $('#sub-check').addEventListener('change', e => { state.subagents = e.target.checked; render(); });
}

/* ---- tooltip ----------------------------------------------------------- */
function wireTooltip() {
  const tip = $('#tooltip');
  document.addEventListener('mousemove', e => {
    const t = e.target.closest('[data-tip]');
    if (!t) { tip.hidden = true; return; }
    tip.innerHTML = t.dataset.tip;
    tip.hidden = false;
    tip.style.left = e.clientX + 'px';
    tip.style.top = e.clientY + 'px';
  });
  document.addEventListener('mouseleave', () => { tip.hidden = true; }, true);
}

/* ---- boot -------------------------------------------------------------- */
async function boot() {
  try {
    const res = await fetch('data/stats.json', { cache: 'no-cache' });
    DATA = await res.json();
  } catch (err) {
    $('#combined-total').textContent = 'failed to load stats.json';
    console.error(err); return;
  }
  const combined = DATA.claude.overview.totalTokens + DATA.codex.overview.totalTokens;
  $('#combined-total').textContent = `${humanTokens(combined)} tokens burned`;
  const g = DATA.generatedAt ? DATA.generatedAt.slice(0, 10) : '';
  $('#generated').textContent = g ? `updated ${fmtDate(g)} ${parseDay(g).getUTCFullYear()}` : '';
  wireSegments();
  wireTooltip();
  render();
}
boot();
