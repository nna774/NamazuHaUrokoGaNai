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
      series[a] = { v, dc };
      for (const x of v) { if (x < lo) lo = x; if (x > hi) hi = x; }
    } else {
      const dc = mean(wf[a + '_max'].concat(wf[a + '_min']));
      const mn = wf[a + '_min'].map(x => x - dc);
      const mx = wf[a + '_max'].map(x => x - dc);
      series[a] = { min: mn, max: mx, dc };
      for (const x of mn) if (x < lo) lo = x;
      for (const x of mx) if (x > hi) hi = x;
    }
  }
  // クリップされたかどうかを後で知らせるため、実データの振れ幅を控えておく。
  const dataPeak = Math.max(Math.abs(lo), Math.abs(hi));
  let clipped = 0;
  if (fixedRange > 0) {
    // 固定レンジ（0中心対称）。安定した縦軸で「直線からの逸脱=異常」を読みやすくする。
    // レンジ外はクリップして描く（エンベロープ表示では上下端に張り付く）。
    if (dataPeak > fixedRange) clipped = dataPeak;
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

  // レンジ外は上下端に張り付き、波形が方形波のように見える。実際の振れ幅を出して
  // 縦軸を上げれば済むと分かるようにする。凡例が右上 pad+12 に出るので1行下げる。
  if (clipped) {
    ctx.fillStyle = '#e67e22';
    ctx.textAlign = 'right';
    ctx.fillText(`レンジ外 実測±${clipped.toFixed(0)} gal`, w - pad, pad + 28);
    ctx.textAlign = 'left';
  }

  for (const a of axes) {
    ctx.strokeStyle = COLORS[a];
    if (wf.mode === 'raw') {
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      series[a].v.forEach((v, i) => { const x = X(i), y = Y(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
    } else {
      // エンベロープ: min/max を半透明で塗り、輪郭を不透明の実線でなぞる。
      // ズーム等で帯が細くなっても輪郭だけは濃く残り、薄く見えない。
      const path = () => {
        ctx.beginPath();
        series[a].max.forEach((v, i) => { const x = X(i), y = Y(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
        for (let i = n - 1; i >= 0; i--) { ctx.lineTo(X(i), Y(series[a].min[i])); }
        ctx.closePath();
      };
      path();
      ctx.globalAlpha = 0.65;
      ctx.fillStyle = COLORS[a];
      ctx.fill();
      ctx.globalAlpha = 1;
      path();
      ctx.lineWidth = 1;
      ctx.stroke();  // strokeStyle はループ先頭で COLORS[a] 設定済み
    }
  }

  // 軸の凡例。DC(≈重力980gal)が700gal超の軸を上下(UD)と注記する。
  // DCの二乗和は重力の二乗で一定なので、700gal超(>980/√2≈693)は高々1軸。
  // 斜め設置でどの軸も超えない時は無印に戻るだけ（上下軸が存在しないので正しい）。
  ctx.font = '12px system-ui';
  const legend = axes.map(a => ({
    a,
    text: Math.abs(series[a].dc) > 700 ? `${a.toUpperCase()}(UD)` : a.toUpperCase(),
  }));
  let lx = w - pad - legend.reduce((s, l) => s + ctx.measureText(l.text).width + 8, -8);
  for (const l of legend) {
    ctx.fillStyle = COLORS[l.a];
    ctx.fillText(l.text, lx, pad + 12);
    lx += ctx.measureText(l.text).width + 8;
  }

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
  // Pointer Events でマウスとタッチを統一的に扱う。タッチはCSSの touch-action: pan-y と
  // 組で、縦はページスクロールのまま・横ドラッグだけを区間選択として受ける。
  let selStartPx = null;  // ドラッグ選択の始点x [CSS px]。null = 選択中でない
  cv.addEventListener('pointerdown', e => {
    const wf = getWf();
    if (!wf || !wf.n || wf.n <= 1) return;
    if (!e.isPrimary || selStartPx !== null) return;  // 2本目の指は無視
    selStartPx = e.offsetX;
    cv.setPointerCapture(e.pointerId);  // canvas外へ出てもmove/upを受ける
    e.preventDefault();                 // テキスト選択等の互換マウス動作を抑止
  });
  cv.addEventListener('pointermove', e => {
    if (selStartPx === null) return;
    redraw();
    const ctx = cv.getContext('2d');
    ctx.fillStyle = 'rgba(192,57,43,.15)';
    ctx.fillRect(Math.min(selStartPx, e.offsetX), 0,
                 Math.abs(e.offsetX - selStartPx), cv.clientHeight);
  });
  cv.addEventListener('pointerup', e => {
    if (selStartPx === null) return;
    const endPx = e.offsetX;  // capture中なのでcanvas基準の座標で来る（範囲外もあり得るが後段でクランプ）
    const x0 = selStartPx;
    selStartPx = null;
    if (Math.abs(endPx - x0) < 8) { redraw(); return; }  // タップ・クリック相当は無視
    apply({ fromUs: Math.min(pxToUs(x0), pxToUs(endPx)),
            toUs: Math.max(pxToUs(x0), pxToUs(endPx)) });
  });
  // スクロールに奪われた等で中断されたら選択を破棄して描き直す
  cv.addEventListener('pointercancel', () => {
    if (selStartPx === null) return;
    selStartPx = null;
    redraw();
  });
  cv.addEventListener('dblclick', () => apply(null));  // ダブルタップでも発火する
}

// --- クライアント側 概算震度計算（ライブ1分窓・生波形限定） ---
// tools/jismo/fir.py --fs 100 --numtaps 511 で設計したFIR係数（firmware/lib/Shindo/JmaFirTaps.h
// と同一）。tools/jismo/realtime.py のオフライン一括計算(filtered_composite)と同じ手順を
// JSに移植し、サーバへ問い合わせず「ガル表示のためにもう取得済みの」1分窓の生波形だけで
// 震度を概算する。fs/numtapsを変えたらこの配列も再生成すること
// （python -c "from jismo.fir import design_fir; ..." で作れる。tools/gen_fir_header.py 参照）。
const JMA_FIR_TAPS = [
  -5.958238504e-4, -5.959681457e-4, -5.961305200e-4, -5.963158097e-4, -5.965197882e-4, -5.967473698e-4,
  -5.969942425e-4, -5.972654152e-4, -5.975564711e-4, -5.978725321e-4, -5.982090567e-4, -5.985712980e-4,
  -5.989545694e-4, -5.993642751e-4, -5.997955623e-4, -6.002540068e-4, -6.007345683e-4, -6.012430157e-4,
  -6.017740993e-4, -6.023338041e-4, -6.029166488e-4, -6.035288586e-4, -6.041646980e-4, -6.048306582e-4,
  -6.055207269e-4, -6.062416883e-4, -6.069872304e-4, -6.077644597e-4, -6.085667413e-4, -6.094015347e-4,
  -6.102618596e-4, -6.111555613e-4, -6.120752910e-4, -6.130293153e-4, -6.140098941e-4, -6.150257527e-4,
  -6.160687374e-4, -6.171480724e-4, -6.182551683e-4, -6.193997908e-4, -6.205728931e-4, -6.217848282e-4,
  -6.230260707e-4, -6.243076096e-4, -6.256194200e-4, -6.269731787e-4, -6.283583412e-4, -6.297873275e-4,
  -6.312490535e-4, -6.327567410e-4, -6.342987471e-4, -6.358891576e-4, -6.375157523e-4, -6.391935467e-4,
  -6.409097248e-4, -6.426803014e-4, -6.444918466e-4, -6.463614480e-4, -6.482750439e-4, -6.502508716e-4,
  -6.522742197e-4, -6.543645563e-4, -6.565065020e-4, -6.587208402e-4, -6.609915053e-4, -6.633406838e-4,
  -6.657516045e-4, -6.682479490e-4, -6.708122201e-4, -6.734696892e-4, -6.762021113e-4, -6.790364462e-4,
  -6.819536766e-4, -6.849825519e-4, -6.881032565e-4, -6.913464331e-4, -6.946914381e-4, -6.981709139e-4,
  -7.017633556e-4, -7.055035135e-4, -7.093689842e-4, -7.133967358e-4, -7.175634232e-4, -7.219083440e-4,
  -7.264071628e-4, -7.311016186e-4, -7.359663304e-4, -7.410455910e-4, -7.463129110e-4, -7.518152493e-4,
  -7.575249363e-4, -7.634917090e-4, -7.696866364e-4, -7.761623442e-4, -7.828885484e-4, -7.899208725e-4,
  -7.972275761e-4, -8.048673877e-4, -8.128069939e-4, -8.211083332e-4, -8.297363892e-4, -8.387564119e-4,
  -8.481315370e-4, -8.579304241e-4, -8.681141999e-4, -8.787550283e-4, -8.898118487e-4, -9.013604199e-4,
  -9.133572969e-4, -9.258819201e-4, -9.388882435e-4, -9.524594714e-4, -9.665467198e-4, -9.812370346e-4,
  -9.964784346e-4, -1.012361881e-3, -1.028832014e-3, -1.045983780e-3, -1.063758133e-3, -1.082254072e-3,
  -1.101408535e-3, -1.121324632e-3, -1.141934932e-3, -1.163346718e-3, -1.185487802e-3, -1.208469700e-3,
  -1.232215055e-3, -1.256839674e-3, -1.282260592e-3, -1.308597963e-3, -1.335762745e-3, -1.363879502e-3,
  -1.392852609e-3, -1.422811106e-3, -1.453652256e-3, -1.485509642e-3, -1.518272846e-3, -1.552080079e-3,
  -1.586812642e-3, -1.622613458e-3, -1.659354916e-3, -1.697184752e-3, -1.735965774e-3, -1.775850650e-3,
  -1.816691895e-3, -1.858647251e-3, -1.901558195e-3, -1.945587698e-3, -1.990565414e-3, -2.036659734e-3,
  -2.083687658e-3, -2.131823214e-3, -2.180869872e-3, -2.231007557e-3, -2.282025281e-3, -2.334109161e-3,
  -2.387032782e-3, -2.440988791e-3, -2.495734314e-3, -2.551468926e-3, -2.607932198e-3, -2.665331089e-3,
  -2.723386456e-3, -2.782313158e-3, -2.841812104e-3, -2.902106647e-3, -2.962876432e-3, -3.024353974e-3,
  -3.086196249e-3, -3.148645690e-3, -3.211335094e-3, -3.274517670e-3, -3.337800402e-3, -3.401448243e-3,
  -3.465040595e-3, -3.528855239e-3, -3.592442076e-3, -3.656092924e-3, -3.719326087e-3, -3.782448773e-3,
  -3.844945382e-3, -3.907140029e-3, -3.968480660e-3, -4.029309980e-3, -4.089036657e-3, -4.148023861e-3,
  -4.205637826e-3, -4.262264270e-3, -4.317223453e-3, -4.370925957e-3, -4.422642067e-3, -4.472809800e-3,
  -4.520644930e-3, -4.566615760e-3, -4.609878374e-3, -4.650934521e-3, -4.688874649e-3, -4.724237462e-3,
  -4.756040899e-3, -4.784864513e-3, -4.809645745e-3, -4.831009311e-3, -4.847802817e-3, -4.860700924e-3,
  -4.868450404e-3, -4.871781164e-3, -4.869326104e-3, -4.861876243e-3, -4.847935033e-3, -4.828361084e-3,
  -4.801509654e-3, -4.768314073e-3, -4.726958643e-3, -4.678459216e-3, -4.620801243e-3, -4.555091559e-3,
  -4.479082231e-3, -4.393980107e-3, -4.297260633e-3, -4.190240071e-3, -4.070062428e-3, -3.938162719e-3,
  -3.791283036e-3, -3.630985608e-3, -3.453518558e-3, -3.260577409e-3, -3.047793883e-3, -2.816997726e-3,
  -2.563038050e-3, -2.287869509e-3, -1.985327525e-3, -1.657462598e-3, -1.296766145e-3, -9.053175663e-4,
  -4.737763615e-4, -4.110013663e-6, 5.156035203e-4, 1.083796708e-3, 1.716179120e-3, 2.412179694e-3,
  3.193370502e-3, 4.061492513e-3, 5.047794678e-3, 6.159099856e-3, 7.443690623e-3, 8.921260531e-3,
  1.067862505e-2, 1.277532723e-2, 1.537975303e-2, 1.864195380e-2, 2.312040933e-2, 3.030638585e-2,
  4.430245987e-2, 7.048877873e-2, 1.069516257e-1, 1.273922218e-1, 1.069516257e-1, 7.048877873e-2,
  4.430245987e-2, 3.030638585e-2, 2.312040933e-2, 1.864195380e-2, 1.537975303e-2, 1.277532723e-2,
  1.067862505e-2, 8.921260531e-3, 7.443690623e-3, 6.159099856e-3, 5.047794678e-3, 4.061492513e-3,
  3.193370502e-3, 2.412179694e-3, 1.716179120e-3, 1.083796708e-3, 5.156035203e-4, -4.110013663e-6,
  -4.737763615e-4, -9.053175663e-4, -1.296766145e-3, -1.657462598e-3, -1.985327525e-3, -2.287869509e-3,
  -2.563038050e-3, -2.816997726e-3, -3.047793883e-3, -3.260577409e-3, -3.453518558e-3, -3.630985608e-3,
  -3.791283036e-3, -3.938162719e-3, -4.070062428e-3, -4.190240071e-3, -4.297260633e-3, -4.393980107e-3,
  -4.479082231e-3, -4.555091559e-3, -4.620801243e-3, -4.678459216e-3, -4.726958643e-3, -4.768314073e-3,
  -4.801509654e-3, -4.828361084e-3, -4.847935033e-3, -4.861876243e-3, -4.869326104e-3, -4.871781164e-3,
  -4.868450404e-3, -4.860700924e-3, -4.847802817e-3, -4.831009311e-3, -4.809645745e-3, -4.784864513e-3,
  -4.756040899e-3, -4.724237462e-3, -4.688874649e-3, -4.650934521e-3, -4.609878374e-3, -4.566615760e-3,
  -4.520644930e-3, -4.472809800e-3, -4.422642067e-3, -4.370925957e-3, -4.317223453e-3, -4.262264270e-3,
  -4.205637826e-3, -4.148023861e-3, -4.089036657e-3, -4.029309980e-3, -3.968480660e-3, -3.907140029e-3,
  -3.844945382e-3, -3.782448773e-3, -3.719326087e-3, -3.656092924e-3, -3.592442076e-3, -3.528855239e-3,
  -3.465040595e-3, -3.401448243e-3, -3.337800402e-3, -3.274517670e-3, -3.211335094e-3, -3.148645690e-3,
  -3.086196249e-3, -3.024353974e-3, -2.962876432e-3, -2.902106647e-3, -2.841812104e-3, -2.782313158e-3,
  -2.723386456e-3, -2.665331089e-3, -2.607932198e-3, -2.551468926e-3, -2.495734314e-3, -2.440988791e-3,
  -2.387032782e-3, -2.334109161e-3, -2.282025281e-3, -2.231007557e-3, -2.180869872e-3, -2.131823214e-3,
  -2.083687658e-3, -2.036659734e-3, -1.990565414e-3, -1.945587698e-3, -1.901558195e-3, -1.858647251e-3,
  -1.816691895e-3, -1.775850650e-3, -1.735965774e-3, -1.697184752e-3, -1.659354916e-3, -1.622613458e-3,
  -1.586812642e-3, -1.552080079e-3, -1.518272846e-3, -1.485509642e-3, -1.453652256e-3, -1.422811106e-3,
  -1.392852609e-3, -1.363879502e-3, -1.335762745e-3, -1.308597963e-3, -1.282260592e-3, -1.256839674e-3,
  -1.232215055e-3, -1.208469700e-3, -1.185487802e-3, -1.163346718e-3, -1.141934932e-3, -1.121324632e-3,
  -1.101408535e-3, -1.082254072e-3, -1.063758133e-3, -1.045983780e-3, -1.028832014e-3, -1.012361881e-3,
  -9.964784346e-4, -9.812370346e-4, -9.665467198e-4, -9.524594714e-4, -9.388882435e-4, -9.258819201e-4,
  -9.133572969e-4, -9.013604199e-4, -8.898118487e-4, -8.787550283e-4, -8.681141999e-4, -8.579304241e-4,
  -8.481315370e-4, -8.387564119e-4, -8.297363892e-4, -8.211083332e-4, -8.128069939e-4, -8.048673877e-4,
  -7.972275761e-4, -7.899208725e-4, -7.828885484e-4, -7.761623442e-4, -7.696866364e-4, -7.634917090e-4,
  -7.575249363e-4, -7.518152493e-4, -7.463129110e-4, -7.410455910e-4, -7.359663304e-4, -7.311016186e-4,
  -7.264071628e-4, -7.219083440e-4, -7.175634232e-4, -7.133967358e-4, -7.093689842e-4, -7.055035135e-4,
  -7.017633556e-4, -6.981709139e-4, -6.946914381e-4, -6.913464331e-4, -6.881032565e-4, -6.849825519e-4,
  -6.819536766e-4, -6.790364462e-4, -6.762021113e-4, -6.734696892e-4, -6.708122201e-4, -6.682479490e-4,
  -6.657516045e-4, -6.633406838e-4, -6.609915053e-4, -6.587208402e-4, -6.565065020e-4, -6.543645563e-4,
  -6.522742197e-4, -6.502508716e-4, -6.482750439e-4, -6.463614480e-4, -6.444918466e-4, -6.426803014e-4,
  -6.409097248e-4, -6.391935467e-4, -6.375157523e-4, -6.358891576e-4, -6.342987471e-4, -6.327567410e-4,
  -6.312490535e-4, -6.297873275e-4, -6.283583412e-4, -6.269731787e-4, -6.256194200e-4, -6.243076096e-4,
  -6.230260707e-4, -6.217848282e-4, -6.205728931e-4, -6.193997908e-4, -6.182551683e-4, -6.171480724e-4,
  -6.160687374e-4, -6.150257527e-4, -6.140098941e-4, -6.130293153e-4, -6.120752910e-4, -6.111555613e-4,
  -6.102618596e-4, -6.094015347e-4, -6.085667413e-4, -6.077644597e-4, -6.069872304e-4, -6.062416883e-4,
  -6.055207269e-4, -6.048306582e-4, -6.041646980e-4, -6.035288586e-4, -6.029166488e-4, -6.023338041e-4,
  -6.017740993e-4, -6.012430157e-4, -6.007345683e-4, -6.002540068e-4, -5.997955623e-4, -5.993642751e-4,
  -5.989545694e-4, -5.985712980e-4, -5.982090567e-4, -5.978725321e-4, -5.975564711e-4, -5.972654152e-4,
  -5.969942425e-4, -5.967473698e-4, -5.965197882e-4, -5.963158097e-4, -5.961305200e-4, -5.959681457e-4,
  -5.958238504e-4,
];
// ゼロ履歴で始まる畳み込みの立ち上がり(=フィルタの整定時間)ぶんは震度計算から除く。
// tools/jismo/realtime.py の _warmup と同じ考え方（numtaps + fs秒ぶん）。
const JMA_FIR_WARMUP = JMA_FIR_TAPS.length + 100;
const JMA_EXCEEDANCE_SAMPLES = 30;  // 0.3秒 @ 100Hz（気象庁定義の超過時間）

// 1軸ぶんの因果FIR畳み込み。x[負の添字]=0として扱う（deque初期値ゼロのstreaming版と同値）。
function jmaFirFilter(x, taps) {
  const n = x.length, m = taps.length;
  const y = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let s = 0;
    const kmax = Math.min(i, m - 1);
    for (let k = 0; k <= kmax; k++) s += taps[k] * x[i - k];
    y[i] = s;
  }
  return y;
}

// 気象庁の丸め規則（tools/jismo/rounding.py jma_round と同一）:
// 小数第3位を四捨五入(ゼロから遠い方へ)し、小数第2位を切り捨てる。
function jmaRound(x) {
  const sign = x < 0 ? -1 : 1;
  const two = sign * Math.round(Math.abs(x) * 100) / 100;
  return Math.floor(two * 10) / 10;
}

// 3軸加速度[gal]から計測震度を概算する。100Hz・6000点(=1分)前後の生波形を想定。
// 短すぎる(整定時間+超過時間ぶんに満たない)・fsが100Hz以外なら null を返す。
function computeIntensity(x, y, z, fs) {
  const n = x && x.length || 0;
  if (Math.round(fs) !== 100 || n - JMA_FIR_WARMUP < JMA_EXCEEDANCE_SAMPLES) return null;
  const fx = jmaFirFilter(x, JMA_FIR_TAPS);
  const fy = jmaFirFilter(y, JMA_FIR_TAPS);
  const fz = jmaFirFilter(z, JMA_FIR_TAPS);
  const comp = new Float64Array(n - JMA_FIR_WARMUP);
  for (let i = JMA_FIR_WARMUP; i < n; i++) {
    const cx = fx[i], cy = fy[i], cz = fz[i];
    comp[i - JMA_FIR_WARMUP] = Math.sqrt(cx * cx + cy * cy + cz * cz);
  }
  const sorted = Array.from(comp).sort((a, b) => a - b);
  const a0 = sorted[sorted.length - JMA_EXCEEDANCE_SAMPLES];
  if (!(a0 > 0)) return { intensity: 0, scale: intensityScale(0), a0: 0 };
  const intensity = jmaRound(2 * Math.log10(a0) + 0.94);
  return { intensity, scale: intensityScale(intensity), a0 };
}

// --- 重ね表示（「1分」ライブ限定。tools/calibrate_orientation.py --write が
// namazu-devices に書いた傾き(tilt_up)・相対方位(azimuth_deg)で複数機を回転し、
// UD(鉛直)・H1/H2(回転後の水平2軸)を重ねて描く。docs/device_overlay.md §3.b）。
const OVERLAY_DEVICE_COLORS = ['#3498db', '#e74c3c', '#2ecc71', '#9b59b6', '#e67e22'];
const OVERLAY_CHANNEL_DASH = { ud: [], h1: [6, 4], h2: [1, 3] };

function meanOf(arr) {
  return arr.reduce((s, v) => s + v, 0) / (arr.length || 1);
}

// up(重力方向の単位ベクトル、raw sensor frame)から (h1,h2,up) 基底を作る。
// tools/calibrate_orientation.py の frame_from_up と同一手順（同じ機体・据え付けなら
// 常に同じ基底になるので azimuth_deg の意味とズレない）。
function frameFromUp(up) {
  const ref = Math.abs(up[0]) > 0.9 ? [0, 1, 0] : [1, 0, 0];
  const d = ref[0] * up[0] + ref[1] * up[1] + ref[2] * up[2];
  let h1 = [ref[0] - d * up[0], ref[1] - d * up[1], ref[2] - d * up[2]];
  const n1 = Math.hypot(h1[0], h1[1], h1[2]);
  h1 = [h1[0] / n1, h1[1] / n1, h1[2] / n1];
  const h2 = [
    up[1] * h1[2] - up[2] * h1[1],
    up[2] * h1[0] - up[0] * h1[2],
    up[0] * h1[1] - up[1] * h1[0],
  ];
  return { h1, h2, up };
}

// 生の x/y/z[gal] を UD/h1/h2 へ回転する。窓内平均を重力DC近似として引く
// （drawWaveform の DC 除去と同じ近似）。cal.azimuthDeg ぶん水平2軸を回して
// calibration_ref_device の水平基底へ揃える（回転の向きは下のtheta参照）。
function rotateToChannels(x, y, z, cal) {
  const { h1, h2, up } = frameFromUp(cal.tiltUp);
  const n = x.length;
  const mx = meanOf(x), my = meanOf(y), mz = meanOf(z);
  const ud = new Float64Array(n), a1 = new Float64Array(n), a2 = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const dx = x[i] - mx, dy = y[i] - my, dz = z[i] - mz;
    a1[i] = dx * h1[0] + dy * h1[1] + dz * h1[2];
    a2[i] = dx * h2[0] + dy * h2[1] + dz * h2[2];
    ud[i] = dx * up[0] + dy * up[1] + dz * up[2];
  }
  // fit_relative_azimuth(tools/calibrate_orientation.py)の実際の向きを確認したところ
  // v_ref ≈ Rot(-azimuth_deg)・v_other だった（docstringの文言だけでは符号が確定しないため
  // 実装を合成データで検算して確かめた）。よって -azimuth_deg 分だけ回す。
  const theta = -(cal.azimuthDeg || 0) * Math.PI / 180;
  const c = Math.cos(theta), s = Math.sin(theta);
  const rh1 = new Float64Array(n), rh2 = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    rh1[i] = c * a1[i] - s * a2[i];
    rh2[i] = s * a1[i] + c * a2[i];
  }
  return { ud, h1: rh1, h2: rh2 };
}

// 複数機の実測時間範囲の共通部分を、代表機(id最小)のサンプル間隔で刻んだ時刻配列を作る。
// サンプルクロックは機ごとに独立（docs/device_overlay.md 実装メモ）なので、重ねるには
// 共通グリッドへのリサンプルが要る。重なる範囲が無ければ null。
function buildOverlayGrid(waveforms, ids) {
  const base = waveforms[ids[0]];
  const stepUs = 1e6 / base.fs;
  let lo = -Infinity, hi = Infinity;
  for (const id of ids) {
    const wf = waveforms[id];
    lo = Math.max(lo, wf.start_us);
    hi = Math.min(hi, wf.start_us + (wf.n - 1) * (1e6 / wf.fs));
  }
  if (!(hi > lo)) return null;
  const n = Math.max(2, Math.floor((hi - lo) / stepUs) + 1);
  const t = new Float64Array(n);
  for (let i = 0; i < n; i++) t[i] = lo + i * stepUs;
  return t;
}

// t[] の各時刻における値を、機自身のサンプル列(srcStartUs起点・srcFs間隔)から線形補間する。
function interpOnto(t, srcStartUs, srcFs, srcArr) {
  const n = t.length, m = srcArr.length;
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const pos = (t[i] - srcStartUs) / 1e6 * srcFs;
    const i0 = Math.max(0, Math.min(m - 2, Math.floor(pos)));
    const f = Math.max(0, Math.min(1, pos - i0));
    out[i] = srcArr[i0] * (1 - f) + srcArr[i0 + 1] * f;
  }
  return out;
}

// data = { ids, waveforms:{id:wf}, cals:{id:{tiltUp,azimuthDeg,refDevice}} }
function drawOverlay(cv, data, fixedRange) {
  const { ctx, w, h } = fitCanvas(cv);
  ctx.clearRect(0, 0, w, h);
  const pad = PAD;
  const plotW = w - pad * 2, plotH = h - pad * 2;

  const t = buildOverlayGrid(data.waveforms, data.ids);
  if (!t) {
    ctx.fillStyle = '#888';
    ctx.fillText('重なる時間範囲が無い', pad, h / 2);
    return;
  }
  const n = t.length;

  const series = {};
  let lo = Infinity, hi = -Infinity;
  for (const id of data.ids) {
    const wf = data.waveforms[id];
    const ch = rotateToChannels(wf.x, wf.y, wf.z, data.cals[id]);
    const s = {
      ud: interpOnto(t, wf.start_us, wf.fs, ch.ud),
      h1: interpOnto(t, wf.start_us, wf.fs, ch.h1),
      h2: interpOnto(t, wf.start_us, wf.fs, ch.h2),
    };
    series[id] = s;
    for (const k of ['ud', 'h1', 'h2']) {
      for (const v of s[k]) { if (v < lo) lo = v; if (v > hi) hi = v; }
    }
  }

  const dataPeak = Math.max(Math.abs(lo), Math.abs(hi));
  let clipped = 0;
  if (fixedRange > 0) {
    if (dataPeak > fixedRange) clipped = dataPeak;
    lo = -fixedRange; hi = fixedRange;
  } else {
    if (lo === hi) { lo -= 1; hi += 1; }
    const margin = (hi - lo) * 0.1 || 1;
    lo -= margin; hi += margin;
  }
  const yr = hi - lo;
  const X = i => pad + (n <= 1 ? 0 : (i / (n - 1)) * plotW);
  const Y = v => {
    const c = Math.max(lo, Math.min(hi, v));
    return pad + plotH - ((c - lo) / yr) * plotH;
  };

  ctx.strokeStyle = 'rgba(128,128,128,.35)';
  ctx.beginPath(); ctx.moveTo(pad, Y(0)); ctx.lineTo(w - pad, Y(0)); ctx.stroke();
  ctx.fillStyle = '#888'; ctx.font = '11px system-ui';
  ctx.fillText(hi.toFixed(2), 2, Y(hi) + 4);
  ctx.fillText(lo.toFixed(2), 2, Y(lo) + 4);

  if (clipped) {
    ctx.fillStyle = '#e67e22';
    ctx.textAlign = 'right';
    ctx.fillText(`レンジ外 実測±${clipped.toFixed(0)} gal`, w - pad, pad + 28);
    ctx.textAlign = 'left';
  }

  data.ids.forEach((id, idx) => {
    ctx.strokeStyle = OVERLAY_DEVICE_COLORS[idx % OVERLAY_DEVICE_COLORS.length];
    for (const k of ['ud', 'h1', 'h2']) {
      ctx.setLineDash(OVERLAY_CHANNEL_DASH[k]);
      ctx.lineWidth = k === 'ud' ? 1.6 : 1;
      ctx.beginPath();
      series[id][k].forEach((v, i) => { const x = X(i), y = Y(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
    }
  });
  ctx.setLineDash([]);

  // 凡例は機の色のみ（UD実線/H1破線/H2点線の意味は下の説明文に出す。線6本ぶんの
  // テキストを並べると凡例だけで幅を食うため）。
  ctx.font = '12px system-ui';
  let lx = w - pad - data.ids.reduce((s, id) => s + ctx.measureText(String(id).padStart(4, '0')).width + 8, -8);
  data.ids.forEach((id, idx) => {
    const text = String(id).padStart(4, '0');
    ctx.fillStyle = OVERLAY_DEVICE_COLORS[idx % OVERLAY_DEVICE_COLORS.length];
    ctx.fillText(text, lx, pad + 12);
    lx += ctx.measureText(text).width + 8;
  });

  // 横軸（時刻目盛り + 薄いグリッド線）。drawWaveform と同じ間引き方。
  if (n > 1) {
    const startUs = t[0], endUs = t[n - 1];
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
    ctx.textAlign = 'left';
  }
}

// --- ライブ / 指定時刻 ---
let liveTimer = null;
let lastLiveWaveform = null;  // 縦軸切替時の再描画用（再フェッチしない）
let liveZoom = null;          // ドラッグ拡大 {fromUs, toUs}。固定窓になり自動更新は止まる

// いま画面に出ている（ズーム適用後の）波形。ドラッグ座標→時刻の変換にも使う。
// ズーム時は区間を /recent で取り直すが、取得窓はAPIの最小幅(0.1分)等で指定より
// 広いことがあるので、表示は常に指定区間へ切り出す。
function displayedLiveWf() {
  if (overlayActive()) return null;  // 重ね表示中はドラッグ拡大非対応（getWfがnullなら発火しない）
  const wf = lastLiveWaveform;
  if (!wf || !wf.n || wf.n <= 1 || !liveZoom) return wf;
  return sliceWaveform(wf, liveZoom.fromUs, liveZoom.toUs);
}

// 「1分」表示かつ2機以上が重ね表示チェック済みなら重ね表示モード。
function overlayActive() {
  const sel = document.getElementById('minutes');
  return !!sel && sel.value === '1' && liveOverlayIds.length >= 2;
}

// 通常表示⇄重ね表示の切り替えでUIの出し分けを揃える（軸チェック・デバイス選択は
// 重ね表示では使わないので隠し、説明文も対応するほうだけ出す）。
function updateLiveModeUi() {
  const active = overlayActive();
  const axHelp = document.getElementById('live-axes-help');
  const ovHelp = document.getElementById('live-overlay-help');
  if (axHelp) axHelp.style.display = active ? 'none' : '';
  if (ovHelp) ovHelp.style.display = active ? '' : 'none';
  const devLabel = document.getElementById('live-device-label');
  const axLabel = document.getElementById('live-axes-label');
  if (devLabel) devLabel.style.display = active ? 'none' : '';
  if (axLabel) axLabel.style.display = active ? 'none' : '';
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
  if (overlayActive()) { redrawLiveOverlay(); return; }
  if (!lastLiveWaveform) return;
  const yrange = Number(document.getElementById('yrange').value) || 0;
  drawWaveform(document.getElementById('live-canvas'), displayedLiveWf(), yrange, visibleAxes('live'));
}

// ライブの概算震度バッジを更新する。rawの生波形が手元にある時だけ計算する
// （envelope=間引き済みでは計算不能。「3分」以上の窓や拡大表示中は出さない）。
function updateLiveIntensity(wf) {
  const el = document.getElementById('live-intensity');
  if (!el) return;
  if (!wf || !wf.n) { el.innerHTML = ''; return; }
  if (wf.mode !== 'raw') {
    el.innerHTML = '<span class="muted">概算震度: 表示範囲が広いため計算できません（「1分」表示でのみ計算）</span>';
    return;
  }
  const r = computeIntensity(wf.x, wf.y, wf.z, wf.fs);
  if (!r) { el.innerHTML = '<span class="muted">概算震度: データが少なく計算できません</span>'; return; }
  el.innerHTML = `概算震度 ${scaleBadge(r.scale, false)}`
    + `<span class="muted"> 計測震度 ${r.intensity.toFixed(1)}・クライアント側の参考値（気象庁確定値ではない）</span>`;
}

// 重ね表示版の概算震度。計測震度は回転・符号反転に不変(design.md「向きは自由」)なので、
// 較正の有無に関わらず機ごとの生のx/y/zからそのまま計算できる。
function updateLiveIntensityMulti(waveforms) {
  const el = document.getElementById('live-intensity');
  if (!el) return;
  if (!waveforms) { el.innerHTML = ''; return; }
  const parts = Object.keys(waveforms).map(Number).sort((a, b) => a - b).map(id => {
    const wf = waveforms[id];
    const label = String(id).padStart(4, '0');
    if (!wf || wf.mode !== 'raw') return `<span class="muted">[${label}] 概算震度: 計算できません</span>`;
    const r = computeIntensity(wf.x, wf.y, wf.z, wf.fs);
    if (!r) return `<span class="muted">[${label}] 概算震度: データが少なく計算できません</span>`;
    return `[${label}] 概算震度 ${scaleBadge(r.scale, false)}`
      + `<span class="muted"> 計測震度 ${r.intensity.toFixed(1)}</span>`;
  });
  el.innerHTML = parts.join('　');
}

// 波形は1デバイスぶんだけ引く。混ぜると継ぎ目の段差が揺れに見える（api側も絞る）。
// 選択の真実は liveDeviceId 側に置く。<select> の選択肢は /devices を引くまで
// 空なので、DOM を真実にすると URL 復元と埋め込みの順序に依存してしまう。
let liveDeviceId = null;
let liveDevices = [];

// 重ね表示。真実は liveOverlayIds（チェック済みdevice_id、2件以上で有効）に置く。
// liveDeviceCal は /devices から拾った較正済み機の { tiltUp, azimuthDeg, refDevice }。
let liveOverlayIds = [];
let liveDeviceCal = {};
let lastLiveOverlay = null;  // 縦軸切替時の再描画用（再フェッチしない）

function liveDeviceParam() {
  return liveDeviceId ? '&device=' + encodeURIComponent(liveDeviceId) : '';
}

async function fillLiveDevices() {
  const sel = document.getElementById('live-device');
  if (!sel) return;
  try {
    const data = await apiGet('/devices');
    const all = data.devices || [];
    const ids = all.map(d => Number(d.device_id)).sort((a, b) => a - b);
    if (ids.join() !== liveDevices.join()) {
      liveDevices = ids;
      sel.innerHTML = ids.map(id =>
        `<option value="${id}">${String(id).padStart(4, '0')}</option>`).join('');
    }
    // URL 由来の選択が実在しなければ最若番へ倒す（デバイスを外した後のURL対策）。
    if (!ids.map(String).includes(String(liveDeviceId))) {
      liveDeviceId = ids.length ? String(ids[0]) : null;
    }
    if (liveDeviceId) sel.value = liveDeviceId;

    // 重ね表示の対象は較正済み(tilt_up書き込み済み)の機だけ。
    liveDeviceCal = {};
    for (const d of all) {
      if (d.tilt_up) {
        liveDeviceCal[Number(d.device_id)] = {
          tiltUp: d.tilt_up, azimuthDeg: d.azimuth_deg || 0, refDevice: d.calibration_ref_device,
        };
      }
    }
    renderOverlayChecks();
  } catch (e) {
    // デバイス一覧が引けなくても波形表示は続ける（api 側が最若番を選ぶ）。
  }
}

// 重ね表示のチェックボックス群を較正済みの機で作り直す。選択の真実は liveOverlayIds
// （他の live* 状態と同じ設計）。「1分」以外では触れないよう disabled にする。
function renderOverlayChecks() {
  const wrap = document.getElementById('live-overlay-checks');
  if (!wrap) return;
  const calIds = Object.keys(liveDeviceCal).map(Number).sort((a, b) => a - b);
  if (calIds.length < 2) {
    wrap.className = 'muted';
    wrap.textContent = '（較正済みの機が2台に満たない）';
    updateLiveModeUi();
    return;
  }
  const oneMin = document.getElementById('minutes').value === '1';
  wrap.className = oneMin ? '' : 'muted';
  const dis = oneMin ? '' : 'disabled';
  wrap.innerHTML = calIds.map(id => {
    const checked = liveOverlayIds.includes(id) ? 'checked' : '';
    return `<label style="margin-right:8px"><input type="checkbox" class="live-overlay-check" `
      + `data-id="${id}" ${checked} ${dis}> ${String(id).padStart(4, '0')}</label>`;
  }).join('') + (oneMin ? '' : ' 「1分」表示でのみ有効');
  wrap.querySelectorAll('.live-overlay-check').forEach(cb => {
    cb.onchange = () => {
      liveOverlayIds = Array.from(wrap.querySelectorAll('.live-overlay-check:checked'))
        .map(el => Number(el.dataset.id)).sort((a, b) => a - b);
      liveZoom = null;  // 重ね表示はドラッグ拡大非対応。切り替え時に解除しておく
      location.hash = liveHash();
    };
  });
  updateLiveModeUi();
}

// 重ね表示モードの再取得・再描画。ドラッグ拡大は非対応(displayedLiveWfがnullを返す)。
async function refreshLiveOverlay() {
  const status = document.getElementById('live-status');
  const minutes = document.getElementById('minutes').value;
  const sec = startSec();
  const ids = liveOverlayIds.slice().sort((a, b) => a - b);
  try {
    status.textContent = '取得中…';
    const cals = ids.map(id => liveDeviceCal[id]);
    if (cals.some(c => !c)) throw new Error('選択した機に較正値が無い');
    if (new Set(cals.map(c => c.refDevice)).size > 1) {
      throw new Error('選択した機の較正基準がバラバラ（重ねられない）');
    }
    const waveforms = {};
    await Promise.all(ids.map(async id => {
      waveforms[id] = await apiGet('/recent?minutes=' + minutes
        + (sec ? '&start=' + sec * 1e6 : '') + '&device=' + id);
    }));
    if (ids.some(id => waveforms[id].mode !== 'raw')) {
      throw new Error('データが多く生波形が取れない（対象範囲を確認しろ）');
    }
    lastLiveOverlay = { ids, waveforms, cals: Object.fromEntries(ids.map((id, i) => [id, cals[i]])) };
    redrawLiveOverlay();
    updateLiveIntensityMulti(waveforms);
    const dev = ids.map(id => String(id).padStart(4, '0')).join('+');
    if (sec) {
      const from = new Date(sec * 1000).toLocaleString('ja-JP');
      status.textContent = `重ね表示[${dev}]: ${from} から ${minutes}分`;
    } else {
      status.textContent = `重ね表示[${dev}] 更新: ` + new Date().toLocaleTimeString('ja-JP');
    }
  } catch (e) {
    lastLiveOverlay = null;
    redrawLiveOverlay();
    updateLiveIntensityMulti(null);
    status.textContent = 'エラー: ' + e.message;
  }
}

function redrawLiveOverlay() {
  const cv = document.getElementById('live-canvas');
  if (!lastLiveOverlay) {
    const { ctx, w, h } = fitCanvas(cv);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#888';
    ctx.fillText('データなし', PAD, h / 2);
    return;
  }
  const yrange = Number(document.getElementById('yrange').value) || 0;
  drawOverlay(cv, lastLiveOverlay, yrange);
}

async function refreshLive() {
  const status = document.getElementById('live-status');
  const minutes = document.getElementById('minutes').value;
  const sec = startSec();
  await fillLiveDevices();
  updateLiveModeUi();
  if (overlayActive()) { await refreshLiveOverlay(); return; }
  try {
    status.textContent = '取得中…';
    if (liveZoom) {
      // ドラッグ拡大: その区間だけ取り直す。窓が狭いほど間引きが細かくなる。
      // APIの minutes は0.1分が下限なので、指定区間へは displayedLiveWf が切り出す。
      const spanMin = Math.max(0.1, (liveZoom.toUs - liveZoom.fromUs) / 60e6);
      lastLiveWaveform = await apiGet('/recent?minutes=' + spanMin.toFixed(4)
        + '&start=' + Math.round(liveZoom.fromUs) + liveDeviceParam());
      redrawLive();
      // 拡大表示は窓の長さが不定（60秒の想定と噛み合わない）なので震度は出さない。
      updateLiveIntensity(null);
      const wf = displayedLiveWf();
      const from = new Date(liveZoom.fromUs / 1000).toLocaleTimeString('ja-JP');
      status.textContent = `拡大表示: ${from} から ${((liveZoom.toUs - liveZoom.fromUs) / 1e6).toFixed(1)}秒`
        + (wf.n ? (wf.mode === 'envelope' ? '（エンベロープ）' : '') : '・データなし');
      return;
    }
    const wf = await apiGet('/recent?minutes=' + minutes
      + (sec ? '&start=' + sec * 1e6 : '') + liveDeviceParam());
    lastLiveWaveform = wf;
    redrawLive();
    updateLiveIntensity(wf);
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
      // どのデバイスを見ているかは常に出す。多点では「静かだ」の意味が変わる。
      const dev = wf.device_id != null ? `[${String(wf.device_id).padStart(4, '0')}] ` : '';
      status.textContent = dev + '更新: ' + new Date().toLocaleTimeString('ja-JP')
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
// イベントのデバイス絞り込み。'all' は全機（既定）。ライブと同じく選択の真実は
// この変数に置く（<select> の選択肢は /devices を引くまで空なので DOM は真実にできない）。
let eventsDeviceId = 'all';

function eventsDeviceParam() {
  return eventsDeviceId !== 'all' ? '&device=' + encodeURIComponent(eventsDeviceId) : '';
}

// イベント絞り込みの選択肢を埋める。「全機」は常に残す。
async function fillEventsDevices() {
  const sel = document.getElementById('events-device');
  if (!sel) return;
  try {
    const data = await apiGet('/devices');
    const ids = (data.devices || []).map(d => Number(d.device_id)).sort((a, b) => a - b);
    const want = ['all'].concat(ids.map(String));
    const have = Array.from(sel.options).map(o => o.value);
    if (want.join() !== have.join()) {
      sel.innerHTML = '<option value="all">全機</option>'
        + ids.map(id => `<option value="${id}">${String(id).padStart(4, '0')}</option>`).join('');
    }
    // URL 由来の選択が実在しなければ全機へ倒す（デバイスを外した後のURL対策）。
    if (!want.includes(String(eventsDeviceId))) eventsDeviceId = 'all';
    sel.value = eventsDeviceId;
  } catch (e) {
    // デバイス一覧が引けなくても一覧表示は続ける（絞り込みは効いたまま）。
  }
}

async function reloadEvents(pageNum = 1) {
  eventsPageNum = pageNum;
  const status = document.getElementById('events-status');
  const tbody = document.querySelector('#events-table tbody');
  const page0 = Math.max(0, pageNum - 1);
  const all = document.getElementById('events-all').checked ? '&all=1' : '';
  await fillEventsDevices();
  try {
    status.textContent = '取得中…';
    const data = await apiGet(`/events?page=${page0}&size=${EVENTS_PAGE_SIZE}${all}`
      + eventsDeviceParam());
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
      const manualTag = ev.manual ? ' <span class="badge badge-manual">手動</span>' : '';
      // どの機のイベントかは常に出す。多点では震度の意味が機ごとに違う。
      const dev = ev.device_id != null ? String(ev.device_id).padStart(4, '0') : '—';
      tr.innerHTML = `<td>${t}</td><td>${dev}</td><td>${scaleBadge(scale, ev.artificial)}${artTag}${manualTag}</td>`
        + `<td>${i}</td><td>${Number(ev.peak_gal || 0).toFixed(2)}</td><td>${dur}</td>`
        + `<td>${ev.device_prompt ? '✓' : ''}</td><td>${ev.cloud_confirmed ? '✓' : ''}</td>`;
      // 非該当（評価済みだが未確定）・人工地震は薄く表示して区別する（全件表示でのみ出る）。
      // 手動保存(manual)は意図して残したものなので薄くしない。
      if (ev.artificial || (ev.checked && !ev.cloud_confirmed && !ev.manual)) tr.style.opacity = '0.45';
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
  if (m.manual) return '手動保存';
  if (m.cloud_confirmed) return '確定';
  if (m.checked) return '非該当（評価済み・未確定）';
  return '速報のみ（評価待ち）';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// メモをエスケープしつつ http(s) URL をリンク化する（ユーザー入力なので必ずエスケープ）。
function noteHtml(note) {
  return escapeHtml(note).replace(/(https?:\/\/[^\s]+)/g,
    '<a href="$1" target="_blank" rel="noopener">$1</a>');
}

function renderEventInfo(m) {
  const tbody = document.getElementById('event-info');
  const rows = [];
  const onset = Number(m.onset_us || 0);
  const last = Number(m.last_us || onset);
  const dur = onset ? Math.max(0, (last - onset) / 1e6) : 0;
  if (onset) rows.push(['発生時刻', new Date(onset / 1000).toLocaleString('ja-JP')]);
  if (m.device_id != null) rows.push(['デバイス', String(m.device_id).padStart(4, '0')]);
  rows.push(['継続時間', `${dur.toFixed(0)} 秒`]);
  rows.push(['計測震度', Number(m.max_intensity || 0).toFixed(1)]);
  rows.push(['震度', scaleBadge(m.scale || intensityScale(Number(m.max_intensity || 0)), m.artificial)]);
  rows.push(['ピーク加速度', `${Number(m.peak_gal || 0).toFixed(2)} gal`]);
  if (m.a0_gal != null) rows.push(['基準加速度 a0', `${Number(m.a0_gal).toFixed(2)} gal`]);
  rows.push(['状態', eventStateLabel(m)]);
  rows.push(['検知経路', `${m.device_prompt ? '速報✓ ' : ''}${m.cloud_confirmed ? '確定✓' : ''}`.trim() || '—']);
  rows.push(['イベントID', m.event_id || '']);
  if (m.note) rows.push(['メモ', noteHtml(m.note)]);
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
const EVENT_RAW_MAX_POINTS = 6000;

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

// デバイス詳細画面用。一覧は列幅が厳しく丸め表記(fmtAgo)のままだが、詳細画面は
// 実際に何秒遅れている/稼働しているかを丸めずに確認したい場面がある（例:
// 「2時間」表記だと1時間59分59秒との区別がつかない）ため秒数を併記する。
function fmtAgoExact(sec) {
  if (sec == null) return '—';
  const s = Math.max(0, Math.round(sec));
  const label = fmtAgo(sec);
  return s < 90 ? label : `${label}(${s}秒)`;
}

// 経過秒を警告値と比べて td の class 属性を返す。半分超で黄(warn-lo)・超過で赤(warn-hi)。
function warnBg(sec, warnAt) {
  if (sec == null || !warnAt) return '';
  if (sec >= warnAt) return ' class="warn-hi"';       // 超過 → 赤
  if (sec >= warnAt / 2) return ' class="warn-lo"';   // 半分超 → 黄
  return '';
}

// 一覧テーブルは列数がぎりぎりなので、日付と時刻を明示的に改行して1セルの
// 最大幅を縮める（ブラウザの自動折り返しに任せると崩れ位置が揃わない）。
function fmtLastIngestCell(us, ageS) {
  if (!us) return '—';
  const dt = new Date(us / 1000);
  return `${dt.toLocaleDateString('ja-JP')}<br>${dt.toLocaleTimeString('ja-JP')}（${fmtAgo(ageS)}前）`;
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
      tr.dataset.id = d.device_id;
      tr.onclick = () => { location.hash = deviceHash(d.device_id); };
      const id = String(d.device_id).padStart(4, '0');
      const restartBadge = d.pending_restart_requested_at_us
        ? ' <span class="badge badge-restart">再起動要求</span>'
        : '';
      const st = (d.online
        ? '<span class="status-ok">● オンライン</span>'
        : '<span class="status-ng">● 欠測</span>') + restartBadge;
      const last = fmtLastIngestCell(d.last_ingest_at_us, d.age_s);
      const fwVersion = d.fw_version || '—';
      let ota = '—';
      if (d.pending_ota_version) {
        ota = (d.fw_version && d.fw_version === d.pending_ota_version)
          ? `<span class="status-ok">適用済み (${d.pending_ota_version})</span>`
          : `<span class="warn-hi">→ ${d.pending_ota_version}</span>`;
      }
      tr.innerHTML = `<td>${id}</td><td>${st}</td>`
        + `<td${warnBg(d.age_s, offlineAt)}>${last}</td>`
        + `<td${warnBg(d.lag_s, lagAt)}>${fmtAgo(d.lag_s)}遅れ</td>`
        + `<td class="col-batches">${d.batches_total ?? 0}</td>`
        + `<td class="col-fw">${fwVersion}</td>`
        + `<td>${d.uptime_s != null ? fmtAgo(d.uptime_s) : '—'}</td>`
        + `<td>${ota}</td>`;
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

// --- デバイス詳細（温度トレンド） ---
let currentDeviceId = null;  // device-temp-hours 変更時にハッシュを組み直すため

function showDevicesMode(detail) {
  // 一覧モードと詳細モードは排他表示（イベントと同じ考え方）
  document.getElementById('devices-list').style.display = detail ? 'none' : 'block';
  document.getElementById('device-detail').style.display = detail ? 'block' : 'none';
}

// バージョン文字列はビルド時のgit短縮hash(firmware/get_fw_version.py)なので、
// GitHubのコミットへのリンクにできる。ただし作業ツリーが汚れていた場合は
// 末尾に"-dirty"が付き、それを含めたままリンクを組むとハッシュとして存在せず404になる
// ので、リンク先はそこを削った短縮hashにする（表示文字列自体は"-dirty"付きのまま）。
const GITHUB_REPO_URL = 'https://github.com/nna774/NamazuHaUrokoGaNai';

function fwVersionHtml(v) {
  if (!v) return '—';
  const safe = escapeHtml(v);
  const commit = escapeHtml(v.replace(/-dirty$/, ''));
  return `<a href="${GITHUB_REPO_URL}/commit/${commit}" target="_blank" rel="noopener">${safe}</a>`;
}

// このプロジェクトはリージョン固定(ap-northeast-1、CLAUDE.md)。ヒープテレメトリの
// トレンドはCloudWatch側に任せ、ここはコンソールへの深リンクだけを組む
// （軽く見る用途は最新値のテキスト表示のみ、docs/design.md「送信の信頼性」未定事項4）。
const CLOUDWATCH_REGION = 'ap-northeast-1';

function cloudwatchHeapUrl(deviceId) {
  const id = String(deviceId);
  return `https://${CLOUDWATCH_REGION}.console.aws.amazon.com/cloudwatch/home?region=${CLOUDWATCH_REGION}`
    + `#metricsV2:graph=~(metrics~(~(~'Namazu~'HeapFreeBytes~'DeviceId~'${id})`
    + `~(~'Namazu~'HeapMaxAllocBytes~'DeviceId~'${id}))~view~'timeSeries~stacked~false`
    + `~region~'${CLOUDWATCH_REGION}~start~'-PT24H~end~'P0D)`;
}

function cloudwatchBacklogUrl(deviceId) {
  const id = String(deviceId);
  return `https://${CLOUDWATCH_REGION}.console.aws.amazon.com/cloudwatch/home?region=${CLOUDWATCH_REGION}`
    + `#metricsV2:graph=~(metrics~(~(~'Namazu~'SpillCount~'DeviceId~'${id})`
    + `~(~'Namazu~'RamQueued~'DeviceId~'${id}))~view~'timeSeries~stacked~false`
    + `~region~'${CLOUDWATCH_REGION}~start~'-PT24H~end~'P0D)`;
}

function renderDeviceInfo(d) {
  const tbody = document.getElementById('device-info');
  const st = d.online
    ? '<span class="status-ok">● オンライン</span>'
    : '<span class="status-ng">● 欠測</span>';
  const last = d.last_ingest_at_us
    ? `${new Date(d.last_ingest_at_us / 1000).toLocaleString('ja-JP')}（${fmtAgo(d.age_s)}前）`
    : '—';
  const rows = [
    ['状態', st],
    ['最終受信', last],
    ['データ鮮度', `${fmtAgoExact(d.lag_s)}遅れ`],
    ['累計バッチ', String(d.batches_total ?? 0)],
    ['版数', fwVersionHtml(d.fw_version)],
    ['センサ', d.sensor || '不明'],
    ['稼働時間', d.uptime_s != null ? fmtAgoExact(d.uptime_s) : '不明'],
    ['前回の再起動理由', d.reset_reason ? escapeHtml(d.reset_reason) : '不明'],
  ];
  const heapText = d.heap_free_bytes != null
    ? `空き${(d.heap_free_bytes / 1024).toFixed(0)}KB / 最大連続${(d.heap_maxblock_bytes / 1024).toFixed(0)}KB　`
    : '直近データなし　';
  rows.push(['ヒープ', heapText
    + `<a href="${cloudwatchHeapUrl(d.device_id)}" target="_blank" rel="noopener">CloudWatchで見る →</a>`]);
  const backlogText = d.spill_count != null
    ? `退避${d.spill_count}件 / RAM${d.ram_queued}件　`
    : '直近データなし　';
  rows.push(['未送信バックログ', backlogText
    + `<a href="${cloudwatchBacklogUrl(d.device_id)}" target="_blank" rel="noopener">CloudWatchで見る →</a>`]);
  if (d.pending_ota_version) {
    rows.push(['OTA', (d.fw_version && d.fw_version === d.pending_ota_version)
      ? `適用済み (${d.pending_ota_version})` : `→ ${d.pending_ota_version}`]);
  }
  if (d.pending_restart_requested_at_us) rows.push(['再起動要求', '立っている（次回受信で反映）']);
  // events?p=1&all=0&d=<id> を直接組む。eventsHash()は現在のイベント一覧の
  // グローバル状態(eventsDeviceId等)に依存するので、ここでは使えない。
  rows.push(['イベント', `<a href="#events?p=1&all=0&d=${encodeURIComponent(d.device_id)}">このデバイスの一覧を見る →</a>`]);
  tbody.innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
}

// 温度トレンドの折れ線を描く。drawWaveform と同じ pad/fitCanvas を使い回すが、
// 1系列・実時間軸なので専用に書く（波形の3軸描画ロジックを流用すると複雑さが増す）。
function drawTempChart(cv, points) {
  const { ctx, w, h } = fitCanvas(cv);
  ctx.clearRect(0, 0, w, h);
  const pad = PAD;
  const plotW = w - pad * 2, plotH = h - pad * 2;

  if (!points.length) {
    ctx.fillStyle = '#888';
    ctx.fillText('データなし', pad, h / 2);
    return;
  }

  // c（換算℃）があればそちらを、無ければ生値をそのまま描く。
  const val = p => p.c != null ? p.c : p.raw;
  const vals = points.map(val);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (lo === hi) { lo -= 1; hi += 1; }
  const margin = (hi - lo) * 0.1 || 1;
  lo -= margin; hi += margin;
  const t0 = points[0].t, t1 = points[points.length - 1].t;
  const tr = Math.max(1, t1 - t0);
  const X = t => pad + ((t - t0) / tr) * plotW;
  const Y = v => pad + plotH - ((v - lo) / (hi - lo)) * plotH;

  ctx.fillStyle = '#888'; ctx.font = '11px system-ui';
  ctx.fillText(hi.toFixed(1), 2, Y(hi) + 4);
  ctx.fillText(lo.toFixed(1), 2, Y(lo) + 4);

  ctx.strokeStyle = '#e67e22';
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = X(p.t), y = Y(val(p));
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();

  // 横軸の時刻目盛り（drawWaveform と同じ間引き方）
  const nticks = Math.max(2, Math.min(6, Math.floor(plotW / 80)));
  ctx.font = '11px system-ui';
  for (let k = 0; k < nticks; k++) {
    const f = k / (nticks - 1);
    const x = pad + f * plotW;
    ctx.strokeStyle = 'rgba(128,128,128,.18)';
    ctx.beginPath(); ctx.moveTo(x, pad); ctx.lineTo(x, pad + plotH); ctx.stroke();
    ctx.fillStyle = '#888';
    ctx.textAlign = k === 0 ? 'left' : k === nticks - 1 ? 'right' : 'center';
    const d = new Date((t0 + f * (t1 - t0)) / 1000);
    ctx.fillText(d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }), x, h - 8);
  }
  ctx.textAlign = 'left';
}

async function refreshDeviceTemp(id) {
  const status = document.getElementById('device-temp-status');
  const hours = document.getElementById('device-temp-hours').value;
  try {
    status.textContent = '取得中…';
    const data = await apiGet(`/devices/${encodeURIComponent(id)}/temp?hours=${hours}`);
    const points = data.points || [];
    drawTempChart(document.getElementById('device-temp-canvas'), points);
    status.textContent = points.length
      ? `${points.length} 点（直近${hours}時間）`
      : 'データなし（このセンサは温度非対応、または直近データなし）';
  } catch (e) {
    status.textContent = 'エラー: ' + e.message;
  }
}

async function showDevice(id) {
  currentDeviceId = id;
  const title = document.getElementById('device-title');
  const padded = String(id).padStart(4, '0');
  title.textContent = '読み込み中… ' + padded;
  document.getElementById('device-info').innerHTML = '';
  let hasTemp = true;  // センサ種別が分からない間・取得失敗時は出しておく（隠れて気付けないよりまし）
  try {
    const data = await apiGet('/devices/' + encodeURIComponent(id));
    const d = data.device || {};
    title.textContent = `デバイス ${String(d.device_id ?? id).padStart(4, '0')}`;
    renderDeviceInfo(d);
    hasTemp = d.sensor === 'ADXL355' || d.sensor === 'IIS3DHHC';  // 両方内蔵温度センサ対応済み
  } catch (e) {
    title.textContent = `デバイス ${padded}`;
    document.getElementById('device-info').innerHTML =
      `<tr><td colspan="2">エラー: ${escapeHtml(e.message)}</td></tr>`;
  }
  document.getElementById('device-temp-section').style.display = hasTemp ? '' : 'none';
  document.getElementById('device-temp-hours-label').style.display = hasTemp ? '' : 'none';
  if (hasTemp) refreshDeviceTemp(id);
}

// --- ハッシュルーティング ---
// #live?m=<分>&auto=<0|1>&r=<レンジ>&ax=<表示軸> / #events?p=<頁>&all=<0|1>&d=<デバイス>
// / #event/<id>?p=&all=&d=&r=&ax=&t=<fromUs>-<toUs> を location.hash に持たせ、リロードや共有URLで
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
  const d = liveDeviceId ? `&d=${liveDeviceId}` : '';
  const overlay = liveOverlayIds.length ? `&overlay=${liveOverlayIds.join(',')}` : '';
  return `live?m=${m}&auto=${auto}&r=${r}&ax=${axesStr('live')}${sec ? `&s=${sec}` : ''}${t}${d}${overlay}`;
}

// イベント一覧のデバイス絞り込みのハッシュ表現（全機は既定なので省く）
function eventsDeviceHash() {
  return eventsDeviceId !== 'all' ? `&d=${encodeURIComponent(eventsDeviceId)}` : '';
}

// 現在のイベント一覧操作状態（ページ・全件フィルタ・デバイス絞り込み）を表すハッシュ
function eventsHash(pageNum) {
  const all = document.getElementById('events-all').checked ? 1 : 0;
  return `events?p=${pageNum || 1}&all=${all}${eventsDeviceHash()}`;
}

// イベント詳細ハッシュ。戻り先の一覧状態(p/all/d)・縦軸レンジ(r)・時間ズーム(t)を持たせ、
// リロード・共有URLでフィルタや表示範囲が復元されるようにする。
function eventHash(id) {
  const all = document.getElementById('events-all').checked ? 1 : 0;
  const r = document.getElementById('event-yrange').value;
  const t = eventZoom ? `&t=${Math.round(eventZoom.fromUs)}-${Math.round(eventZoom.toUs)}` : '';
  return `event/${encodeURIComponent(id)}?p=${eventsPageNum}&all=${all}`
    + `${eventsDeviceHash()}&r=${r}&ax=${axesStr('event')}${t}`;
}

// デバイス詳細ハッシュ。温度の表示期間(h)を持たせ、リロード・共有URLで復元される。
function deviceHash(id) {
  const h = document.getElementById('device-temp-hours').value;
  return `device/${encodeURIComponent(id)}?h=${h}`;
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
    eventsDeviceId = params.d ? decodeURIComponent(params.d) : 'all';  // 戻り先の絞り込み
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
    eventsDeviceId = params.d ? decodeURIComponent(params.d) : 'all';
    reloadEvents(params.p ? parseInt(params.p, 10) : 1);
  } else if (path.startsWith('device/')) {
    showView('devices');
    showDevicesMode(true);
    if (params.h) document.getElementById('device-temp-hours').value = params.h;
    showDevice(decodeURIComponent(path.slice('device/'.length)));
  } else if (path === 'devices') {
    showView('devices');
    showDevicesMode(false);
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
    if (params.d) liveDeviceId = params.d;
    liveOverlayIds = params.overlay
      ? params.overlay.split(',').map(Number).filter(Number.isFinite)
      : [];
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
    if (overlayActive() ? lastLiveOverlay : lastLiveWaveform) redrawLive(); else refreshLive();
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
  // デバイス絞り込みを変えたら1ページ目から。件数が変わるのでページ番号は保てない。
  document.getElementById('events-device').onchange = (e) => {
    eventsDeviceId = e.target.value;
    location.hash = eventsHash(1);
  };
  document.getElementById('event-back').onclick = () => { location.hash = eventsHash(eventsPageNum); };
  // デバイスを変えても時間窓（拡大・指定時刻）は保つ。同じ揺れを別の機体で見比べるのが
  // 多点化の主目的で、解除すると比較のたびに時刻を探し直すことになる。
  // URL に載せるので「この時刻のこの機体」をそのまま共有できる。
  document.getElementById('live-device').onchange = (e) => {
    liveDeviceId = e.target.value;
    location.hash = liveHash();
  };
  document.getElementById('reload-devices').onclick = () => refreshDevices();
  document.getElementById('devices-auto').onchange = () => scheduleDevices();
  document.getElementById('device-back').onclick = () => { location.hash = 'devices'; };
  document.getElementById('reload-device').onclick = () => { if (currentDeviceId != null) showDevice(currentDeviceId); };
  // 期間の変更は取り直しが要るので再フェッチする（縦軸レンジ等の再描画のみとは違う）。
  document.getElementById('device-temp-hours').onchange = () => {
    if (currentDeviceId == null) return;
    history.replaceState(null, '', '#' + deviceHash(currentDeviceId));
    refreshDeviceTemp(currentDeviceId);
  };
  // タイトルクリックで全操作状態を既定に戻す（ライブ・1分窓・自動更新・±100gal・全軸）。
  // イベント側のフィルタ・ページも既定へ。既に既定ならハッシュが変わらないので直接 route する。
  document.getElementById('home').onclick = () => {
    document.getElementById('minutes').value = '1';
    document.getElementById('autorefresh').checked = true;
    document.getElementById('yrange').value = '100';
    for (const a of AXES) document.getElementById(`live-ax-${a}`).checked = true;
    startInput.value = '';
    liveZoom = null;
    liveOverlayIds = [];
    document.getElementById('events-all').checked = false;
    eventsDeviceId = 'all';
    eventsPageNum = 1;
    const h = liveHash();
    if (location.hash === '#' + h) route(); else location.hash = h;
  };
  document.getElementById('tab-live').onclick = () => { location.hash = liveHash(); };
  document.getElementById('tab-events').onclick = () => { location.hash = eventsHash(eventsPageNum); };
  document.getElementById('tab-devices').onclick = () => { location.hash = 'devices'; };
  route();
});
