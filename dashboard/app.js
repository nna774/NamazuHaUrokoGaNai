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

// 気象庁の震度階級カラー（HPColorGuide 2020年7月版）。[背景, 文字]。
// 明色の低震度は濃い文字、濃色の高震度は白文字にして可読性を確保する。
const SCALE_STYLE = {
  '0':  ['#b0b0b0', '#333'],
  '1':  ['#f2f2ff', '#333'],
  '2':  ['#00aaff', '#333'],
  '3':  ['#0041ff', '#fff'],
  '4':  ['#fae696', '#333'],
  '5弱': ['#ffe600', '#333'],
  '5強': ['#ff9900', '#333'],
  '6弱': ['#ff2800', '#fff'],
  '6強': ['#a50021', '#fff'],
  '7':  ['#b40068', '#fff'],
};
const ART_STYLE = ['#888', '#fff'];  // 人工地震はグレー

// 震度バッジのHTML。階級で色分けし、人工地震はグレーにする。
function scaleBadge(scale, artificial) {
  const [bg, fg] = artificial ? ART_STYLE : (SCALE_STYLE[scale] || SCALE_STYLE['0']);
  return `<span class="badge" style="background:${bg};color:${fg}">${scale}</span>`;
}

// --- Canvas 波形描画 ---
const COLORS = { x: '#e74c3c', y: '#2ecc71', z: '#3498db' };
const AXES = ['x', 'y', 'z'];

// prefix('live'|'event') のチェックボックスから、表示中の軸の配列を返す。
function visibleAxes(prefix) {
  return AXES.filter(a => document.getElementById(`${prefix}-ax-${a}`).checked);
}
// URL用の軸文字列（例 'xy'）。全オンなら 'xyz'、全オフなら ''。
function axesStr(prefix) {
  return visibleAxes(prefix).join('');
}
// URLの軸文字列からチェック状態を復元。undefined（旧URL等）なら全オンのまま触らない。
function setAxes(prefix, s) {
  if (s === undefined) return;
  for (const a of AXES) {
    document.getElementById(`${prefix}-ax-${a}`).checked = s.includes(a);
  }
}

const PAD = 28;  // プロット領域の余白。描画とドラッグ座標変換で共有する。

function fitCanvas(cv) {
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth, h = cv.clientHeight;
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

// axes は描画する軸の配列（既定は全軸）。チェックで一部を隠せる。値域も表示軸だけで決める。
function drawWaveform(cv, wf, fixedRange, axes = ['x', 'y', 'z']) {
  const { ctx, w, h } = fitCanvas(cv);
  ctx.clearRect(0, 0, w, h);
  const pad = PAD;
  const plotW = w - pad * 2, plotH = h - pad * 2;

  if (!wf || !wf.n) {
    ctx.fillStyle = '#888';
    ctx.fillText('データなし', pad, h / 2);
    return;
  }
  if (!axes.length) {
    ctx.fillStyle = '#888';
    ctx.fillText('表示する軸が選択されていません', pad, h / 2);
    return;
  }

  // 表示軸の値域。各軸の平均(=重力DC等)を引いて0中心で描く。
  // そうしないと z の重力(約983gal)に縦軸が引っ張られ、揺れ(±数gal)が潰れる。
  const mean = arr => arr.reduce((s, v) => s + v, 0) / (arr.length || 1);
  let lo = Infinity, hi = -Infinity;
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
  if (fixedRange > 0) {
    // 固定レンジ（0中心対称）。安定した縦軸で「直線からの逸脱=異常」を読みやすくする。
    // レンジ外はクリップして描く（エンベロープ表示では上下端に張り付く）。
    lo = -fixedRange; hi = fixedRange;
  } else {
    if (lo === hi) { lo -= 1; hi += 1; }
    // 上下に少し余白
    const margin = (hi - lo) * 0.1 || 1;
    lo -= margin; hi += margin;
  }
  const yr = hi - lo;
  const n = wf.n;
  const X = i => pad + (n <= 1 ? 0 : (i / (n - 1)) * plotW);
  const Y = v => {
    const c = Math.max(lo, Math.min(hi, v));  // 固定レンジ外はクリップ
    return pad + plotH - ((c - lo) / yr) * plotH;
  };

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

  // 横軸（時刻目盛り + 薄いグリッド線）
  if (wf.start_us && n > 1) {
    const stepUs = ((wf.mode === 'raw' ? 1 : wf.bucket) / wf.fs) * 1e6;
    const startUs = wf.start_us;
    const endUs = startUs + (n - 1) * stepUs;
    const spanSec = (endUs - startUs) / 1e6;
    const fmt = us => {
      const d = new Date(us / 1000);
      return spanSec >= 600
        ? d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })
        : d.toLocaleTimeString('ja-JP');
    };
    const nticks = Math.max(2, Math.min(6, Math.floor(plotW / 80)));
    ctx.font = '11px system-ui';
    for (let k = 0; k < nticks; k++) {
      const f = k / (nticks - 1);
      const x = pad + f * plotW;
      ctx.strokeStyle = 'rgba(128,128,128,.18)';
      ctx.beginPath(); ctx.moveTo(x, pad); ctx.lineTo(x, pad + plotH); ctx.stroke();
      ctx.fillStyle = '#888';
      ctx.textAlign = k === 0 ? 'left' : k === nticks - 1 ? 'right' : 'center';
      ctx.fillText(fmt(startUs + f * (endUs - startUs)), x, h - 8);
    }
    ctx.textAlign = 'left';  // 既定に戻す
  }
}

// 波形の1点あたりの時間 [us]。エンベロープは bucket サンプルを1点に潰している。
function wfStepUs(wf) {
  return ((wf.mode === 'raw' ? 1 : wf.bucket) / wf.fs) * 1e6;
}

// [fromUs, toUs] に対応する区間を切り出した波形オブジェクトを返す。
// 手持ちデータの再描画だけで済ませるためのクライアント側ズーム（再フェッチしない）。
// 解像度(bucket)はそのままなので、拡大しても細部は増えない。
function sliceWaveform(wf, fromUs, toUs) {
  const step = wfStepUs(wf);
  let i0 = Math.floor((fromUs - wf.start_us) / step);
  let i1 = Math.ceil((toUs - wf.start_us) / step);
  i0 = Math.max(0, Math.min(wf.n - 2, i0));
  i1 = Math.max(i0 + 1, Math.min(wf.n - 1, i1));
  const out = { ...wf, n: i1 - i0 + 1, start_us: wf.start_us + i0 * step };
  const keys = wf.mode === 'raw' ? AXES : AXES.flatMap(a => [`${a}_min`, `${a}_max`]);
  for (const k of keys) out[k] = wf[k].slice(i0, i1 + 1);
  return out;
}

// canvas にドラッグでの時間区間選択を付ける。選択中は redraw() の上に半透明の矩形を
// 重ね、確定で apply({fromUs, toUs})、ダブルクリックで apply(null)（=全体に戻す）。
// getWf() は「いま表示中の」波形を返すこと（ズーム済みならその区間）。
function attachZoomDrag(cv, getWf, redraw, apply) {
  // canvas上のx座標 → 表示中波形上の時刻 [us]。プロット外は端にクランプ。
  const pxToUs = px => {
    const wf = getWf();
    const plotW = cv.clientWidth - PAD * 2;
    const f = Math.max(0, Math.min(1, (px - PAD) / plotW));
    return wf.start_us + f * (wf.n - 1) * wfStepUs(wf);
  };
  let selStartPx = null;  // ドラッグ選択の始点x [CSS px]。null = 選択中でない
  cv.addEventListener('mousedown', e => {
    const wf = getWf();
    if (!wf || !wf.n || wf.n <= 1) return;
    selStartPx = e.offsetX;
    e.preventDefault();
  });
  cv.addEventListener('mousemove', e => {
    if (selStartPx === null) return;
    redraw();
    const ctx = cv.getContext('2d');
    ctx.fillStyle = 'rgba(192,57,43,.15)';
    ctx.fillRect(Math.min(selStartPx, e.offsetX), 0,
                 Math.abs(e.offsetX - selStartPx), cv.clientHeight);
  });
  // mouseupはcanvas外で離した時も拾えるようwindowで受ける
  window.addEventListener('mouseup', e => {
    if (selStartPx === null) return;
    const endPx = e.clientX - cv.getBoundingClientRect().left;
    const x0 = selStartPx;
    selStartPx = null;
    if (Math.abs(endPx - x0) < 8) { redraw(); return; }  // クリック相当は無視
    apply({ fromUs: Math.min(pxToUs(x0), pxToUs(endPx)),
            toUs: Math.max(pxToUs(x0), pxToUs(endPx)) });
  });
  cv.addEventListener('dblclick', () => apply(null));
}

// --- ライブ / 指定時刻 ---
let liveTimer = null;
let lastLiveWaveform = null;  // 縦軸切替時の再描画用（再フェッチしない）
let liveZoom = null;          // ドラッグ拡大 {fromUs, toUs}。固定窓になり自動更新は止まる

// いま画面に出ている（ズーム適用後の）波形。ドラッグ座標→時刻の変換にも使う。
// ズーム時は区間を /recent で取り直すが、取得窓はAPIの最小幅(0.1分)等で指定より
// 広いことがあるので、表示は常に指定区間へ切り出す。
function displayedLiveWf() {
  const wf = lastLiveWaveform;
  if (!wf || !wf.n || wf.n <= 1 || !liveZoom) return wf;
  return sliceWaveform(wf, liveZoom.fromUs, liveZoom.toUs);
}

// raw/ の保持日数（terraform の raw_retention_days と一致させる）。開始時刻ピッカーの
// 選べる下限に使う。これより古い時刻を選んでもAPIは「データなし」を返すだけなので、
// 厳密一致は不要だが目安として制限しておく。
const RAW_RETENTION_DAYS = 90;

// Date → datetime-local の value 形式（ローカル時刻 'YYYY-MM-DDTHH:MM'）。
function localDatetimeValue(d) {
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

// 開始時刻ピッカーの現在値を epoch 秒で返す。未指定なら null（=ライブ）。
function startSec() {
  const v = document.getElementById('start-time').value;
  if (!v) return null;
  const t = new Date(v).getTime();
  return Number.isFinite(t) ? Math.floor(t / 1000) : null;
}
// epoch 秒 → ピッカーへ反映（ハッシュ復元用）。
function setStartSec(sec) {
  document.getElementById('start-time').value =
    sec ? localDatetimeValue(new Date(sec * 1000)) : '';
}

function redrawLive() {
  if (!lastLiveWaveform) return;
  const yrange = Number(document.getElementById('yrange').value) || 0;
  drawWaveform(document.getElementById('live-canvas'), displayedLiveWf(), yrange, visibleAxes('live'));
}

async function refreshLive() {
  const status = document.getElementById('live-status');
  const minutes = document.getElementById('minutes').value;
  const sec = startSec();
  try {
    status.textContent = '取得中…';
    if (liveZoom) {
      // ドラッグ拡大: その区間だけ取り直す。窓が狭いほど間引きが細かくなる。
      // APIの minutes は0.1分が下限なので、指定区間へは displayedLiveWf が切り出す。
      const spanMin = Math.max(0.1, (liveZoom.toUs - liveZoom.fromUs) / 60e6);
      lastLiveWaveform = await apiGet('/recent?minutes=' + spanMin.toFixed(4)
        + '&start=' + Math.round(liveZoom.fromUs));
      redrawLive();
      const wf = displayedLiveWf();
      const from = new Date(liveZoom.fromUs / 1000).toLocaleTimeString('ja-JP');
      status.textContent = `拡大表示: ${from} から ${((liveZoom.toUs - liveZoom.fromUs) / 1e6).toFixed(1)}秒`
        + (wf.n ? (wf.mode === 'envelope' ? '（エンベロープ）' : '') : '・データなし');
      return;
    }
    const wf = await apiGet('/recent?minutes=' + minutes
      + (sec ? '&start=' + sec * 1e6 : ''));
    lastLiveWaveform = wf;
    redrawLive();
    if (sec) {
      // 指定時刻表示は過去の固定窓なので鮮度は無意味。指定範囲を表示する。
      const from = new Date(sec * 1000).toLocaleString('ja-JP');
      status.textContent = `${from} から ${minutes}分`
        + (wf.n ? (wf.mode === 'envelope' ? '（エンベロープ）' : '') : '・データなし');
    } else {
      // データ鮮度: バッチは完成後に送られるため、右端は常に30〜40秒ほど過去になる
      let age = '';
      if (wf && wf.n) {
        const samples = wf.mode === 'envelope' ? wf.n * wf.bucket : wf.n;
        const endUs = wf.start_us + (samples / wf.fs) * 1e6;
        age = `・最新データ ${Math.max(0, Math.round(Date.now() / 1000 - endUs / 1e6))}秒前`;
      }
      status.textContent = '更新: ' + new Date().toLocaleTimeString('ja-JP')
        + (wf.mode === 'envelope' ? '（エンベロープ）' : '') + age;
    }
  } catch (e) {
    status.textContent = 'エラー: ' + e.message;
  }
}

function refreshIntervalMs() {
  // 窓が広いほど更新間隔を伸ばす。1回の更新コスト(S3 GET数)は窓幅に比例する上、
  // 新データは30秒に1回しか来ないので、広い窓の高頻度更新は無駄が大きい。
  const m = Number(document.getElementById('minutes').value) || 1;
  if (m <= 3) return 15000;
  if (m <= 10) return 30000;
  return 60000;
}

function scheduleLive() {
  if (liveTimer) clearInterval(liveTimer);
  // 指定時刻表示・ドラッグ拡大は過去の固定窓なので自動更新しない（新データは増えない）。
  if (document.getElementById('autorefresh').checked && !startSec() && !liveZoom) {
    liveTimer = setInterval(refreshLive, refreshIntervalMs());
  }
}

// --- イベント ---
const EVENTS_PAGE_SIZE = 20;
let eventsPageNum = 1;  // 詳細→戻る/行クリック時に一覧の現在ページを引き継ぐ
async function reloadEvents(pageNum = 1) {
  eventsPageNum = pageNum;
  const status = document.getElementById('events-status');
  const tbody = document.querySelector('#events-table tbody');
  const page0 = Math.max(0, pageNum - 1);
  const all = document.getElementById('events-all').checked ? '&all=1' : '';
  try {
    status.textContent = '取得中…';
    const data = await apiGet(`/events?page=${page0}&size=${EVENTS_PAGE_SIZE}${all}`);
    tbody.innerHTML = '';
    for (const ev of data.events) {
      const tr = document.createElement('tr');
      tr.dataset.id = ev.event_id;
      const t = new Date(Number(ev.onset_us) / 1000).toLocaleString('ja-JP');
      const iv = Number(ev.max_intensity || 0);
      const i = iv.toFixed(1);
      const scale = ev.scale || intensityScale(iv);
      const dur = ev.last_us ? ((Number(ev.last_us) - Number(ev.onset_us)) / 1e6).toFixed(0) + 's' : '—';
      // 震度バッジは階級で色分け（人工地震はグレー）。人工地震は種別を示すタグも震度セル内に
      // 添える。列を足すとチェック有無でレイアウトが変わるため、既存セル内で完結させる。
      // グレーは震度0とも紛らわしいので「人工」タグを併記して判別を確実にする（全件表示でのみ出る）。
      const artTag = ev.artificial ? ' <span class="badge badge-art">人工地震</span>' : '';
      tr.innerHTML = `<td>${t}</td><td>${scaleBadge(scale, ev.artificial)}${artTag}</td>`
        + `<td>${i}</td><td>${Number(ev.peak_gal || 0).toFixed(2)}</td><td>${dur}</td>`
        + `<td>${ev.device_prompt ? '✓' : ''}</td><td>${ev.cloud_confirmed ? '✓' : ''}</td>`;
      // 非該当（評価済みだが未確定）・人工地震は薄く表示して区別する（全件表示でのみ出る）
      if (ev.artificial || (ev.checked && !ev.cloud_confirmed)) tr.style.opacity = '0.45';
      tr.onclick = () => { location.hash = eventHash(ev.event_id); };
      tbody.appendChild(tr);
    }
    // ページャ
    const total = data.total || 0;
    const pages = Math.max(1, Math.ceil(total / EVENTS_PAGE_SIZE));
    document.getElementById('ev-pageinfo').textContent = `${pageNum} / ${pages} ページ（全${total}件）`;
    const prev = document.getElementById('ev-prev');
    const next = document.getElementById('ev-next');
    prev.disabled = pageNum <= 1;
    next.disabled = pageNum >= pages;
    prev.onclick = () => { location.hash = eventsHash(pageNum - 1); };
    next.onclick = () => { location.hash = eventsHash(pageNum + 1); };
    status.textContent = `${total} 件`;
  } catch (e) {
    status.textContent = 'エラー: ' + e.message;
  }
}

function eventStateLabel(m) {
  if (m.artificial) return '人工地震（テスト等）';
  if (m.cloud_confirmed) return '確定';
  if (m.checked) return '非該当（評価済み・未確定）';
  return '速報のみ（評価待ち）';
}

function renderEventInfo(m) {
  const tbody = document.getElementById('event-info');
  const rows = [];
  const onset = Number(m.onset_us || 0);
  const last = Number(m.last_us || onset);
  const dur = onset ? Math.max(0, (last - onset) / 1e6) : 0;
  if (onset) rows.push(['発生時刻', new Date(onset / 1000).toLocaleString('ja-JP')]);
  rows.push(['継続時間', `${dur.toFixed(0)} 秒`]);
  rows.push(['計測震度', Number(m.max_intensity || 0).toFixed(1)]);
  rows.push(['震度', scaleBadge(m.scale || intensityScale(Number(m.max_intensity || 0)), m.artificial)]);
  rows.push(['ピーク加速度', `${Number(m.peak_gal || 0).toFixed(2)} gal`]);
  if (m.a0_gal != null) rows.push(['基準加速度 a0', `${Number(m.a0_gal).toFixed(2)} gal`]);
  rows.push(['状態', eventStateLabel(m)]);
  rows.push(['検知経路', `${m.device_prompt ? '速報✓ ' : ''}${m.cloud_confirmed ? '確定✓' : ''}`.trim() || '—']);
  rows.push(['イベントID', m.event_id || '']);
  tbody.innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
}

let lastEventWaveform = null;  // 縦軸切替時の再描画用（再フェッチしない）
let currentEventId = null;     // event-yrange 変更時に詳細ハッシュを組み直すため
let eventZoom = null;          // 時間方向ズーム {fromUs, toUs}。null = 全体表示
// ズーム区間のraw再取得キャッシュ。全体波形はエンベロープ(間引き)で来るので、
// 十分狭く拡大したら /event?from=&to= でその区間だけ100Hz生波形を取り直す。
let eventRawWf = null;         // {fromUs, toUs, wf}
let eventRawSeq = 0;           // 遅れて届いた古い応答を捨てるためのトークン
// APIの MAX_POINTS と一致させる（この点数以下ならAPIはrawで返す）
const EVENT_RAW_MAX_POINTS = 3000;

// raw キャッシュが現在のズーム区間を覆っているか
function rawCovers(z) {
  return eventRawWf && eventRawWf.fromUs <= z.fromUs && z.toUs <= eventRawWf.toUs;
}

// いま画面に出ている（ズーム適用後の）波形。ドラッグ座標→時刻の変換にも使う。
// ズーム区間のrawを取得済みならそちらを使う（更に狭めた時もクライアント側で切るだけ）。
function displayedEventWf() {
  const wf = lastEventWaveform;
  if (!wf || !wf.n || wf.n <= 1 || !eventZoom) return wf;
  const src = rawCovers(eventZoom) ? eventRawWf.wf : wf;
  return sliceWaveform(src, eventZoom.fromUs, eventZoom.toUs);
}

// ズームが十分狭くなったら、その区間の生波形をAPIから取り直す。
// 取れるまではエンベロープの切り出しが表示されており、届いたら差し替える。
async function maybeFetchRawZoom() {
  const wf = lastEventWaveform;
  if (!wf || !wf.n || !eventZoom || wf.mode === 'raw') return;  // 全体がrawなら不要
  const spanS = (eventZoom.toUs - eventZoom.fromUs) / 1e6;
  if (spanS * wf.fs > EVENT_RAW_MAX_POINTS) return;  // まだ広い（エンベロープでしか返らない）
  if (rawCovers(eventZoom)) return;                  // キャッシュ済み
  const seq = ++eventRawSeq;
  const id = currentEventId;
  const { fromUs, toUs } = eventZoom;
  try {
    const data = await apiGet(`/event?id=${encodeURIComponent(id)}`
      + `&from=${Math.round(fromUs)}&to=${Math.round(toUs)}`);
    // 取得中にイベントやズームが変わっていたら捨てる
    if (seq !== eventRawSeq || id !== currentEventId) return;
    if (data.waveform && data.waveform.n && data.waveform.mode === 'raw') {
      eventRawWf = { fromUs, toUs, wf: data.waveform };
      drawEventWaveform();
    }
  } catch (e) {
    // raw が取れなくてもエンベロープ表示のままで実害なし。静かに諦める。
  }
}

function drawEventWaveform() {
  if (!lastEventWaveform) return;
  const r = Number(document.getElementById('event-yrange').value) || 0;
  drawWaveform(document.getElementById('event-canvas'), displayedEventWf(), r, visibleAxes('event'));
}

async function showEvent(id) {
  currentEventId = id;
  const title = document.getElementById('event-title');
  title.textContent = '読み込み中… ' + id;
  document.getElementById('event-info').innerHTML = '';
  lastEventWaveform = null;
  eventRawWf = null;  // 別イベントのrawを誤って使わないようキャッシュを破棄
  eventRawSeq++;      // 取得中の応答も無効化
  try {
    const data = await apiGet('/event?id=' + encodeURIComponent(id));
    const m = data.meta || {};
    title.textContent = `震度${m.scale || ''}（計測震度 ${Number(m.max_intensity || 0).toFixed(1)}）`;
    lastEventWaveform = data.waveform;
    drawEventWaveform();
    maybeFetchRawZoom();  // ハッシュ復元で狭いズームが指定済みならrawを取りにいく
    renderEventInfo(m);
  } catch (e) {
    title.textContent = 'エラー: ' + e.message;
  }
}

// --- デバイス（欠測監視） ---
let devicesTimer = null;

// 経過秒を日本語の粗い相対表記に。watchdog._humanize と同じ粒度。
function fmtAgo(sec) {
  if (sec == null) return '—';
  const s = Math.max(0, Math.round(sec));
  if (s < 90) return `${s}秒`;
  const m = Math.floor(s / 60);
  if (m < 90) return `${m}分`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}時間`;
  return `${Math.floor(h / 24)}日`;
}

// 経過秒を警告値と比べて td の class 属性を返す。半分超で黄(warn-lo)・超過で赤(warn-hi)。
function warnBg(sec, warnAt) {
  if (sec == null || !warnAt) return '';
  if (sec >= warnAt) return ' class="warn-hi"';       // 超過 → 赤
  if (sec >= warnAt / 2) return ' class="warn-lo"';   // 半分超 → 黄
  return '';
}

async function refreshDevices() {
  const status = document.getElementById('devices-status');
  const tbody = document.querySelector('#devices-table tbody');
  try {
    status.textContent = '取得中…';
    const data = await apiGet('/devices');
    const offlineAt = data.offline_after_s;  // 最終受信の警告値
    const lagAt = data.lag_after_s;          // データ鮮度の警告値
    tbody.innerHTML = '';
    for (const d of (data.devices || [])) {
      const tr = document.createElement('tr');
      const id = String(d.device_id).padStart(4, '0');
      const st = d.online
        ? '<span class="status-ok">● オンライン</span>'
        : '<span class="status-ng">● 欠測</span>';
      const last = d.last_ingest_at_us
        ? `${new Date(d.last_ingest_at_us / 1000).toLocaleString('ja-JP')}（${fmtAgo(d.age_s)}前）`
        : '—';
      tr.innerHTML = `<td>${id}</td><td>${st}</td>`
        + `<td${warnBg(d.age_s, offlineAt)}>${last}</td>`
        + `<td${warnBg(d.lag_s, lagAt)}>${fmtAgo(d.lag_s)}遅れ</td>`
        + `<td>${d.batches_total ?? 0}</td>`;
      tbody.appendChild(tr);
    }
    const n = (data.devices || []).length;
    const off = (data.devices || []).filter(d => !d.online).length;
    status.textContent = n
      ? `${n} 台` + (off ? `・欠測 ${off} 台` : '・全台オンライン')
      : 'まだ受信したデバイスがない';
  } catch (e) {
    status.textContent = 'エラー: ' + e.message;
  }
}

function scheduleDevices() {
  if (devicesTimer) { clearInterval(devicesTimer); devicesTimer = null; }
  if (document.getElementById('devices-auto').checked) {
    devicesTimer = setInterval(refreshDevices, 30000);
  }
}

// --- ハッシュルーティング ---
// #live?m=<分>&auto=<0|1>&r=<レンジ>&ax=<表示軸> / #events?p=<頁>&all=<0|1>
// / #event/<id>?p=&all=&r=&ax=&t=<fromUs>-<toUs> を location.hash に持たせ、リロードや共有URLで
// 状態(タブ・表示範囲・自動更新・表示軸・全件フィルタ・ページ)が復元されるようにする。
// ax は表示中の軸を連結した文字列（例 'xy'=z非表示 / ''=全非表示 / 省略=全表示）。
function showView(name) {
  const tabs = { live: 'tab-live', events: 'tab-events', devices: 'tab-devices' };
  for (const k in tabs) {
    document.getElementById(tabs[k]).classList.toggle('active', k === name);
    document.getElementById(k).classList.toggle('active', k === name);
  }
  // タブを離れたら各自の自動更新タイマーを止める
  if (name !== 'live' && liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  if (name !== 'devices' && devicesTimer) { clearInterval(devicesTimer); devicesTimer = null; }
}

// t=<fromUs>-<toUs> 形式のズームパラメータを {fromUs, toUs} | null に変換
function parseZoomParam(t) {
  if (!t || !/^\d+-\d+$/.test(t)) return null;
  const [f, to] = t.split('-').map(Number);
  return to > f ? { fromUs: f, toUs: to } : null;
}

function parseHash() {
  const raw = location.hash.replace(/^#/, '');
  const [path, query] = raw.split('?');
  const params = {};
  if (query) for (const kv of query.split('&')) { const [k, v] = kv.split('='); params[k] = v; }
  return { path, params };
}

// 現在のlive操作状態を表すハッシュ。s=<epoch秒> があれば指定時刻表示、
// t=<fromUs>-<toUs> があればドラッグ拡大の固定窓。
function liveHash() {
  const m = document.getElementById('minutes').value;
  const auto = document.getElementById('autorefresh').checked ? 1 : 0;
  const r = document.getElementById('yrange').value;
  const sec = startSec();
  const t = liveZoom ? `&t=${Math.round(liveZoom.fromUs)}-${Math.round(liveZoom.toUs)}` : '';
  return `live?m=${m}&auto=${auto}&r=${r}&ax=${axesStr('live')}${sec ? `&s=${sec}` : ''}${t}`;
}

// 現在のイベント一覧操作状態（ページ・全件フィルタ）を表すハッシュ
function eventsHash(pageNum) {
  const all = document.getElementById('events-all').checked ? 1 : 0;
  return `events?p=${pageNum || 1}&all=${all}`;
}

// イベント詳細ハッシュ。戻り先の一覧状態(p/all)・縦軸レンジ(r)・時間ズーム(t)を持たせ、
// リロード・共有URLでフィルタや表示範囲が復元されるようにする。
function eventHash(id) {
  const all = document.getElementById('events-all').checked ? 1 : 0;
  const r = document.getElementById('event-yrange').value;
  const t = eventZoom ? `&t=${Math.round(eventZoom.fromUs)}-${Math.round(eventZoom.toUs)}` : '';
  return `event/${encodeURIComponent(id)}?p=${eventsPageNum}&all=${all}&r=${r}&ax=${axesStr('event')}${t}`;
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
    // 戻り先の一覧状態と詳細の縦軸レンジを操作子へ復元してから描画
    document.getElementById('events-all').checked = params.all === '1';
    if (params.p) eventsPageNum = parseInt(params.p, 10);
    if (params.r !== undefined) document.getElementById('event-yrange').value = params.r;
    setAxes('event', params.ax);
    // 時間ズームの復元。t が無ければ全体表示（別イベントへ移った時のリセットも兼ねる）。
    eventZoom = parseZoomParam(params.t);
    showEvent(decodeURIComponent(path.slice('event/'.length)));
  } else if (path === 'events') {
    showView('events');
    showEventsMode(false);
    document.getElementById('events-all').checked = params.all === '1';
    reloadEvents(params.p ? parseInt(params.p, 10) : 1);
  } else if (path === 'devices') {
    showView('devices');
    refreshDevices();
    scheduleDevices();
  } else {
    // live（既定）。URLの表示範囲・自動更新を操作子へ反映してから描画。
    if (params.m) document.getElementById('minutes').value = params.m;
    if (params.auto !== undefined) {
      document.getElementById('autorefresh').checked = params.auto === '1';
    }
    if (params.r !== undefined) document.getElementById('yrange').value = params.r;
    setAxes('live', params.ax);
    setStartSec(params.s ? parseInt(params.s, 10) : null);
    liveZoom = parseZoomParam(params.t);  // t が無ければズーム解除
    showView('live');
    refreshLive();
    scheduleLive();
  }
}

window.addEventListener('hashchange', route);

window.addEventListener('load', () => {
  const apiInput = document.getElementById('api');
  apiInput.value = apiBase();
  // config.js / localStorage / ?api= のいずれかでURLが決まっていれば設定欄は隠す。
  // 未設定（自前ホスト等）の時だけ入力欄を出す。
  if (!apiBase()) document.getElementById('api-settings').style.display = '';
  document.getElementById('save-api').onclick = () => { setApi(apiInput.value); refreshLive(); };
  // 開始時刻ピッカーの選べる範囲を [now-保持日数, now] に制限（保存期間内のみ）。
  const startInput = document.getElementById('start-time');
  const now = new Date();
  startInput.max = localDatetimeValue(now);
  startInput.min = localDatetimeValue(new Date(now.getTime() - RAW_RETENTION_DAYS * 86400 * 1000));

  // 操作したらURLへ反映（hashchange→route が実際の描画を行う）
  // 表示範囲・開始時刻の変更は新しい窓の明示指定なので、ドラッグ拡大は解除する。
  document.getElementById('minutes').onchange = () => { liveZoom = null; location.hash = liveHash(); };
  document.getElementById('autorefresh').onchange = () => { location.hash = liveHash(); };
  // 開始時刻の指定は別の時間窓を取り直すので、再フェッチを伴う route を通す。
  startInput.onchange = () => { liveZoom = null; location.hash = liveHash(); };
  document.getElementById('start-clear').onclick = () => {
    startInput.value = '';
    liveZoom = null;
    location.hash = liveHash();  // s も t も無し = ライブ（最新）に戻る
  };
  // 縦軸レンジは取得済みデータの描画変換にすぎないので再フェッチしない。
  // URLは replaceState で更新して hashchange→route(=再取得) を発火させない。
  document.getElementById('yrange').onchange = () => {
    history.replaceState(null, '', '#' + liveHash());
    if (lastLiveWaveform) redrawLive(); else refreshLive();
  };
  // 詳細の縦軸レンジは取得済みデータの再描画にすぎないので再フェッチしない。
  // URLは replaceState で更新して hashchange→route(=再取得) を発火させない。
  document.getElementById('event-yrange').onchange = () => {
    if (currentEventId) history.replaceState(null, '', '#' + eventHash(currentEventId));
    drawEventWaveform();
  };
  // 軸のオンオフも表示変換にすぎない（縦軸レンジと同じ扱い）。再フェッチせず再描画のみ。
  for (const a of AXES) {
    document.getElementById(`live-ax-${a}`).onchange = () => {
      history.replaceState(null, '', '#' + liveHash());
      if (lastLiveWaveform) redrawLive(); else refreshLive();
    };
    document.getElementById(`event-ax-${a}`).onchange = () => {
      if (currentEventId) history.replaceState(null, '', '#' + eventHash(currentEventId));
      drawEventWaveform();
    };
  }
  // --- イベント詳細の時間ズーム（ドラッグで区間選択→拡大、ダブルクリックで全体） ---
  // ズームは手持ちデータの再描画で即反映し、十分狭ければその区間のrawを取り直す。
  const applyEventZoom = z => {
    eventZoom = z;
    if (currentEventId) history.replaceState(null, '', '#' + eventHash(currentEventId));
    drawEventWaveform();
    maybeFetchRawZoom();
  };
  attachZoomDrag(document.getElementById('event-canvas'),
                 displayedEventWf, drawEventWaveform, applyEventZoom);
  document.getElementById('event-zoom-reset').onclick = () => applyEventZoom(null);

  // --- ライブの時間ズーム。区間を /recent で取り直す（狭い窓ほど間引きが細かくなり、
  // 30秒以下ならraw）。指定時刻表示と同じく固定窓なので自動更新は止まる。 ---
  attachZoomDrag(document.getElementById('live-canvas'),
                 displayedLiveWf, redrawLive, z => {
    liveZoom = z;
    // 取り直しが要るので route を通す（scheduleLive も再評価され自動更新が止まる/戻る）
    location.hash = liveHash();
  });

  document.getElementById('reload-events').onclick = () => route();  // 現在ページを再読込
  // フィルタ切替はURLへ反映（hashchange→route が1ページ目から再取得する）
  document.getElementById('events-all').onchange = () => { location.hash = eventsHash(1); };
  document.getElementById('event-back').onclick = () => { location.hash = eventsHash(eventsPageNum); };
  document.getElementById('reload-devices').onclick = () => refreshDevices();
  document.getElementById('devices-auto').onchange = () => scheduleDevices();
  // タイトルクリックで全操作状態を既定に戻す（ライブ・1分窓・自動更新・±100gal・全軸）。
  // イベント側のフィルタ・ページも既定へ。既に既定ならハッシュが変わらないので直接 route する。
  document.getElementById('home').onclick = () => {
    document.getElementById('minutes').value = '1';
    document.getElementById('autorefresh').checked = true;
    document.getElementById('yrange').value = '100';
    for (const a of AXES) document.getElementById(`live-ax-${a}`).checked = true;
    startInput.value = '';
    liveZoom = null;
    document.getElementById('events-all').checked = false;
    eventsPageNum = 1;
    const h = liveHash();
    if (location.hash === '#' + h) route(); else location.hash = h;
  };
  document.getElementById('tab-live').onclick = () => { location.hash = liveHash(); };
  document.getElementById('tab-events').onclick = () => { location.hash = eventsHash(eventsPageNum); };
  document.getElementById('tab-devices').onclick = () => { location.hash = 'devices'; };
  route();
});
