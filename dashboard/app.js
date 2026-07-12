'use strict';

// API URL の解決優先度: ?api= > localStorage > config.js(window.NAMZ_API_URL)
function apiBase() {
  const q = new URLSearchParams(location.search).get('api');
  if (q) localStorage.setItem('namz_api', q);
  return localStorage.getItem('namz_api') || window.NAMZ_API_URL || '';
}

function setApi(url) {
  localStorage.setItem('namz_api', url.trim().replace(/\/$/, ''));
}

async function apiGet(path) {
  const base = apiBase();
  if (!base) throw new Error('API URL 未設定');
  const res = await fetch(base.replace(/\/$/, '') + path);
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

// 計測震度 → 気象庁の震度階級（jismo/rounding.py と一致）
function intensityScale(i) {
  if (i < 0.5) return '0';
  if (i < 1.5) return '1';
  if (i < 2.5) return '2';
  if (i < 3.5) return '3';
  if (i < 4.5) return '4';
  if (i < 5.0) return '5弱';
  if (i < 5.5) return '5強';
  if (i < 6.0) return '6弱';
  if (i < 6.5) return '6強';
  return '7';
}

// --- Canvas 波形描画 ---
const COLORS = { x: '#e74c3c', y: '#2ecc71', z: '#3498db' };

function fitCanvas(cv) {
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth, h = cv.clientHeight;
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

function drawWaveform(cv, wf) {
  const { ctx, w, h } = fitCanvas(cv);
  ctx.clearRect(0, 0, w, h);
  const pad = 28;
  const plotW = w - pad * 2, plotH = h - pad * 2;

  if (!wf || !wf.n) {
    ctx.fillStyle = '#888';
    ctx.fillText('データなし', pad, h / 2);
    return;
  }

  // 全軸の値域。各軸の平均(=重力DC等)を引いて0中心で描く。
  // そうしないと z の重力(約983gal)に縦軸が引っ張られ、揺れ(±数gal)が潰れる。
  const mean = arr => arr.reduce((s, v) => s + v, 0) / (arr.length || 1);
  let lo = Infinity, hi = -Infinity;
  const axes = ['x', 'y', 'z'];
  const series = {};
  for (const a of axes) {
    if (wf.mode === 'raw') {
      const dc = mean(wf[a]);
      const v = wf[a].map(x => x - dc);
      series[a] = { v };
      for (const x of v) { if (x < lo) lo = x; if (x > hi) hi = x; }
    } else {
      const dc = mean(wf[a + '_max'].concat(wf[a + '_min']));
      const mn = wf[a + '_min'].map(x => x - dc);
      const mx = wf[a + '_max'].map(x => x - dc);
      series[a] = { min: mn, max: mx };
      for (const x of mn) if (x < lo) lo = x;
      for (const x of mx) if (x > hi) hi = x;
    }
  }
  if (lo === hi) { lo -= 1; hi += 1; }
  // 上下に少し余白
  const margin = (hi - lo) * 0.1 || 1;
  lo -= margin; hi += margin;
  const yr = hi - lo;
  const n = wf.n;
  const X = i => pad + (n <= 1 ? 0 : (i / (n - 1)) * plotW);
  const Y = v => pad + plotH - ((v - lo) / yr) * plotH;

  // 軸・0線
  ctx.strokeStyle = 'rgba(128,128,128,.35)';
  ctx.beginPath(); ctx.moveTo(pad, Y(0)); ctx.lineTo(w - pad, Y(0)); ctx.stroke();
  ctx.fillStyle = '#888'; ctx.font = '11px system-ui';
  ctx.fillText(hi.toFixed(2), 2, Y(hi) + 4);
  ctx.fillText(lo.toFixed(2), 2, Y(lo) + 4);

  for (const a of axes) {
    ctx.strokeStyle = COLORS[a];
    if (wf.mode === 'raw') {
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      series[a].v.forEach((v, i) => { const x = X(i), y = Y(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
    } else {
      // エンベロープ: min/max を塗り、輪郭線も引いて見やすくする
      ctx.globalAlpha = 0.65;
      ctx.beginPath();
      series[a].max.forEach((v, i) => { const x = X(i), y = Y(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      for (let i = n - 1; i >= 0; i--) { ctx.lineTo(X(i), Y(series[a].min[i])); }
      ctx.closePath();
      ctx.fillStyle = COLORS[a];
      ctx.fill();
      ctx.globalAlpha = 1;
    }
  }

  // 軸の凡例
  ctx.font = '12px system-ui';
  axes.forEach((a, i) => {
    ctx.fillStyle = COLORS[a];
    ctx.fillText(a.toUpperCase(), w - pad - 60 + i * 20, pad + 12);
  });

  // 時刻ラベル
  if (wf.start_us) {
    const start = new Date(wf.start_us / 1000);
    ctx.fillStyle = '#888';
    ctx.fillText(start.toLocaleTimeString('ja-JP'), pad, h - 8);
  }
}

// --- ライブ ---
let liveTimer = null;
async function refreshLive() {
  const status = document.getElementById('live-status');
  const minutes = document.getElementById('minutes').value;
  try {
    status.textContent = '取得中…';
    const wf = await apiGet('/recent?minutes=' + minutes);
    drawWaveform(document.getElementById('live-canvas'), wf);
    status.textContent = '更新: ' + new Date().toLocaleTimeString('ja-JP')
      + (wf.mode === 'envelope' ? '（エンベロープ）' : '');
  } catch (e) {
    status.textContent = 'エラー: ' + e.message;
  }
}

function scheduleLive() {
  if (liveTimer) clearInterval(liveTimer);
  if (document.getElementById('autorefresh').checked) {
    liveTimer = setInterval(refreshLive, 4000);
  }
}

// --- イベント ---
async function reloadEvents() {
  const status = document.getElementById('events-status');
  const tbody = document.querySelector('#events-table tbody');
  try {
    status.textContent = '取得中…';
    const data = await apiGet('/events');
    tbody.innerHTML = '';
    for (const ev of data.events) {
      const tr = document.createElement('tr');
      tr.dataset.id = ev.event_id;
      const t = new Date(Number(ev.onset_us) / 1000).toLocaleString('ja-JP');
      const iv = Number(ev.max_intensity || 0);
      const i = iv.toFixed(1);
      const scale = ev.scale || intensityScale(iv);
      const dur = ev.last_us ? ((Number(ev.last_us) - Number(ev.onset_us)) / 1e6).toFixed(0) + 's' : '—';
      tr.innerHTML = `<td>${t}</td><td><span class="badge">${scale}</span></td>`
        + `<td>${i}</td><td>${Number(ev.peak_gal || 0).toFixed(2)}</td><td>${dur}</td>`
        + `<td>${ev.device_prompt ? '✓' : ''}</td><td>${ev.cloud_confirmed ? '✓' : ''}</td>`;
      tr.onclick = () => { location.hash = 'event/' + ev.event_id; };
      tbody.appendChild(tr);
    }
    status.textContent = data.events.length + ' 件';
  } catch (e) {
    status.textContent = 'エラー: ' + e.message;
  }
}

async function showEvent(id) {
  const title = document.getElementById('event-title');
  const cv = document.getElementById('event-canvas');
  title.textContent = '読み込み中… ' + id;
  try {
    const data = await apiGet('/event?id=' + encodeURIComponent(id));
    const m = data.meta || {};
    title.textContent = `イベント ${id} — 震度${m.scale || ''}（計測震度 ${Number(m.max_intensity || 0).toFixed(1)}）`;
    drawWaveform(cv, data.waveform);
  } catch (e) {
    title.textContent = 'エラー: ' + e.message;
  }
}

// --- ハッシュルーティング ---
// #live?m=<分>&auto=<0|1> / #events / #event/<id> を location.hash に持たせ、
// リロードや共有URLで状態(タブ・表示範囲・自動更新)が復元されるようにする。
function showView(name) {
  const tabs = { live: 'tab-live', events: 'tab-events' };
  for (const k in tabs) {
    document.getElementById(tabs[k]).classList.toggle('active', k === name);
    document.getElementById(k).classList.toggle('active', k === name);
  }
  if (name !== 'live' && liveTimer) { clearInterval(liveTimer); liveTimer = null; }
}

function parseHash() {
  const raw = location.hash.replace(/^#/, '');
  const [path, query] = raw.split('?');
  const params = {};
  if (query) for (const kv of query.split('&')) { const [k, v] = kv.split('='); params[k] = v; }
  return { path, params };
}

// 現在のlive操作状態を表すハッシュ
function liveHash() {
  const m = document.getElementById('minutes').value;
  const auto = document.getElementById('autorefresh').checked ? 1 : 0;
  return `live?m=${m}&auto=${auto}`;
}

function showEventsMode(detail) {
  // 一覧モードと詳細モードは排他表示（同時に出さないのでテーブルがガタつかない）
  document.getElementById('events-list').style.display = detail ? 'none' : 'block';
  document.getElementById('event-detail').style.display = detail ? 'block' : 'none';
}

function route() {
  const { path, params } = parseHash();
  if (path.startsWith('event/')) {
    showView('events');
    showEventsMode(true);
    showEvent(decodeURIComponent(path.slice('event/'.length)));
  } else if (path === 'events') {
    showView('events');
    showEventsMode(false);
    reloadEvents();
  } else {
    // live（既定）。URLの表示範囲・自動更新を操作子へ反映してから描画。
    if (params.m) document.getElementById('minutes').value = params.m;
    if (params.auto !== undefined) {
      document.getElementById('autorefresh').checked = params.auto === '1';
    }
    showView('live');
    refreshLive();
    scheduleLive();
  }
}

window.addEventListener('hashchange', route);

window.addEventListener('load', () => {
  const apiInput = document.getElementById('api');
  apiInput.value = apiBase();
  document.getElementById('save-api').onclick = () => { setApi(apiInput.value); refreshLive(); };
  // 操作したらURLへ反映（hashchange→route が実際の描画を行う）
  document.getElementById('minutes').onchange = () => { location.hash = liveHash(); };
  document.getElementById('autorefresh').onchange = () => { location.hash = liveHash(); };
  document.getElementById('reload-events').onclick = reloadEvents;
  document.getElementById('event-back').onclick = () => { location.hash = 'events'; };
  document.getElementById('tab-live').onclick = () => { location.hash = liveHash(); };
  document.getElementById('tab-events').onclick = () => { location.hash = 'events'; };
  route();
});
