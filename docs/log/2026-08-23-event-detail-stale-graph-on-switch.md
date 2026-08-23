# イベント詳細を切り替えた時、前のグラフが読み込み完了まで残る不具合を直した

## 何が起きていたか

イベント一覧 → `#event/<id>` を開く → 一覧に戻る → 別の `#event/<id2>` を開く、という
操作で、`<id2>` のデータ取得が終わるまで `<id>` のグラフがキャンバスに残ったまま表示され続けていた。
ユーザーがGyazoスクショ無しで口頭で報告。

## 原因

`showEvent()` は切り替え直後に `lastEventWaveform = null` へリセットするが、実際の
キャンバス再描画は `apiGet('/event?id=...')` の完了後に呼ぶ `drawEventWaveform()` 任せ
だった。`drawEventWaveform()` は `if (!lastEventWaveform) return;` で早期returnする実装
なので、リセット直後に呼んでもキャンバスはクリアされない。結果、fetch中は前フレームの
`drawWaveform()` 呼び出しでcanvasに焼かれた絵がそのまま残る。

## 直した内容

`showEvent()` 内でリセット直後に `drawWaveform(event-canvas, null, 0, visibleAxes('event'))`
を直接呼び、キャンバスを明示的にクリア（`drawWaveform`は`wf`がnullだと「データなし」を
描いて`clearRect`済みの状態で終わる）。`drawEventWaveform()`のガード自体は他の呼び出し元
（縦軸レンジ変更・軸トグル・ズーム操作。いずれも現在表示中のイベントに対する再描画で
`lastEventWaveform`が存在する前提）で必要なので変更していない。

## 次に可能になったこと

一覧⇔詳細を行き来する時に、常に「今見ているグラフは今開いているイベントのものである」
という不変が保てる。デプロイ（`dashboard/`のS3 sync + CloudFront invalidation）は未実施。
